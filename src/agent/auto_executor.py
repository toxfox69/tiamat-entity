#!/usr/bin/env python3
"""
TIAMAT Auto-Executor — Zero-latency extraction on scanner findings.
Called directly by continuous_scanner.py when a finding passes validation.
Simulates → checks profitability → executes → alerts.

Requires:
  TIAMAT_WALLET_KEY in env (hex private key)
  ETH balance > 0 for gas

If either is missing, silently returns False and the finding goes to the queue as usual.
"""

import os
import sys
import json
import time
import logging
import urllib.parse
import urllib.request
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account

log = logging.getLogger("vuln_scanner")

# ── Config ──
BASE_RPCS = [
    "https://mainnet.base.org",
    "https://base.meowrpc.com",
    "https://base.drpc.org",
]

WETH = "0x4200000000000000000000000000000000000006"

# Minimum profit in ETH after gas to bother executing
MIN_PROFIT_ETH = 0.002  # ~$5 at $2500/ETH

# Max gas willing to spend — safety caps
MAX_GAS_PRICE_GWEI = 100  # Hard cap: never pay more than 100 gwei
MAX_GAS_UNITS = 300_000
MAX_GAS_COST_RATIO = 0.10  # Don't execute if gas > 10% of prize

# Execution log
EXEC_LOG = "/root/.automaton/execution_log.json"

PAIR_ABI = json.loads("""[
{"constant":false,"inputs":[{"name":"to","type":"address"}],"name":"skim","outputs":[],"type":"function"},
{"constant":true,"inputs":[],"name":"getReserves","outputs":[{"name":"","type":"uint112"},{"name":"","type":"uint112"},{"name":"","type":"uint32"}],"type":"function"},
{"constant":true,"inputs":[],"name":"token0","outputs":[{"name":"","type":"address"}],"type":"function"},
{"constant":true,"inputs":[],"name":"token1","outputs":[{"name":"","type":"address"}],"type":"function"}
]""")

ERC20_ABI = json.loads(
    '[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],'
    '"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],'
    '"type":"function"}]'
)

# Dangerous function selectors for rescue
NO_ARG_SELECTORS = {"0x3ccfd60b", "0xe9fad8ee", "0x7b103999", "0x853828b6"}
ADDR_ARG_SELECTORS = {"0x51cff8d9", "0xf2fde38b", "0x01681a62"}
UINT_ARG_SELECTORS = {"0x2e1a7d4d"}


class AutoExecutor:
    def __init__(self):
        self.private_key = os.environ.get("TIAMAT_WALLET_KEY", "")
        self.enabled = False
        self.account = None
        self.w3 = None

        if not self.private_key:
            return

        try:
            self.account = Account.from_key(self.private_key)
        except Exception:
            return

        # Connect to RPC
        for rpc in BASE_RPCS:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
                w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
                if w3.is_connected():
                    self.w3 = w3
                    break
            except Exception:
                continue

        if not self.w3:
            return

        # Check we have gas money
        try:
            bal = self.w3.eth.get_balance(self.account.address)
            eth_bal = float(self.w3.from_wei(bal, "ether"))
            if eth_bal < 0.0005:  # Need at least ~$1.25 for gas
                log.info(f"[AUTO-EXEC] Disabled: only {eth_bal:.6f} ETH for gas")
                return
            self.enabled = True
            log.info(f"[AUTO-EXEC] Enabled: wallet {self.account.address[:12]}... ({eth_bal:.4f} ETH)")
        except Exception:
            return

    def _send_telegram(self, message):
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            }).encode("utf-8")
            urllib.request.urlopen(url, data=data, timeout=10)
        except Exception:
            pass

    def _log_exec(self, action, address, result, details=""):
        try:
            entry = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "action": action,
                "address": address,
                "result": result,
                "details": details,
            }
            with open(EXEC_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def _capped_gas_price(self):
        """Get current gas price, capped at MAX_GAS_PRICE_GWEI. Returns None if over cap."""
        try:
            gas_price = self.w3.eth.gas_price
            max_price = Web3.to_wei(MAX_GAS_PRICE_GWEI, "gwei")
            if gas_price > max_price:
                return None
            return gas_price
        except Exception:
            return None

    def _estimate_gas_cost_eth(self):
        """Estimate gas cost in ETH for a typical execution."""
        gas_price = self._capped_gas_price()
        if gas_price is None:
            return None  # Gas too expensive or RPC error
        return float(self.w3.from_wei(gas_price * MAX_GAS_UNITS, "ether"))

    def _simulate(self, to, calldata):
        """Simulate a call from our wallet. Returns True if it doesn't revert."""
        try:
            self.w3.eth.call({
                "from": self.account.address,
                "to": Web3.to_checksum_address(to),
                "data": calldata,
            })
            return True
        except Exception:
            return False

    def try_skim(self, pair_address, eth_value):
        """
        Attempt to skim a pair. Returns True if executed successfully.
        Returns False if skipped/failed (caller should queue instead).
        """
        if not self.enabled:
            return False

        addr = Web3.to_checksum_address(pair_address)
        gas_cost = self._estimate_gas_cost_eth()
        if gas_cost is None:
            log.info(f"[AUTO-EXEC] Skip skim {addr[:16]}: gas price over {MAX_GAS_PRICE_GWEI} gwei cap")
            self._log_exec("skim", addr, "SKIPPED", "gas price over cap")
            self._send_telegram(f"<b>AUTO-SKIM SKIPPED</b>\nPair: {addr}\nReason: gas price over {MAX_GAS_PRICE_GWEI} gwei cap")
            return False

        # Gas ratio check: don't execute if gas > 10% of prize
        if eth_value > 0 and gas_cost / eth_value > MAX_GAS_COST_RATIO:
            pct = gas_cost / eth_value * 100
            log.info(f"[AUTO-EXEC] Skip skim {addr[:16]}: gas is {pct:.1f}% of prize (max {MAX_GAS_COST_RATIO*100:.0f}%)")
            self._log_exec("skim", addr, "SKIPPED", f"gas {pct:.1f}% of prize exceeds {MAX_GAS_COST_RATIO*100:.0f}% cap")
            return False

        profit = eth_value - gas_cost
        if profit < MIN_PROFIT_ETH:
            log.info(f"[AUTO-EXEC] Skip skim {addr[:16]}: profit {profit:.4f} ETH below threshold")
            return False

        # Simulate skim(our_address)
        pair = self.w3.eth.contract(address=addr, abi=PAIR_ABI)
        try:
            calldata = pair.functions.skim(self.account.address)._encode_transaction_data()
        except Exception as e:
            log.error(f"[AUTO-EXEC] Skim encode failed: {e}")
            self._log_exec("skim", addr, "ERROR", f"encode failed: {e}")
            self._send_telegram(f"<b>AUTO-SKIM ERROR</b>\nPair: {addr}\nReason: encode failed")
            return False

        if not self._simulate(addr, calldata):
            log.info(f"[AUTO-EXEC] Skim simulation reverted for {addr[:16]}")
            self._log_exec("skim", addr, "SIM_REVERTED", f"value={eth_value}")
            self._send_telegram(f"<b>AUTO-SKIM SIM REVERTED</b>\nPair: {addr}\nValue: {eth_value:.4f} ETH")
            return False

        # Get capped gas price for the actual transaction
        capped_price = self._capped_gas_price()
        if capped_price is None:
            log.info(f"[AUTO-EXEC] Skip skim {addr[:16]}: gas spiked over cap before tx")
            self._log_exec("skim", addr, "SKIPPED", "gas spiked over cap before tx")
            return False

        # Execute
        try:
            tx = pair.functions.skim(self.account.address).build_transaction({
                "from": self.account.address,
                "gas": MAX_GAS_UNITS,
                "gasPrice": capped_price,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
            })
            signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            success = receipt["status"] == 1
            gas_used = receipt["gasUsed"]
            result = "SUCCESS" if success else "FAILED"

            log.info(f"[AUTO-EXEC] Skim {result}: {addr} | tx: {tx_hash.hex()} | gas: {gas_used}")
            self._log_exec("skim", addr, result, f"tx={tx_hash.hex()} gas={gas_used} value={eth_value}")

            msg = (
                f"<b>AUTO-SKIM {result}</b>\n"
                f"Pair: {addr}\n"
                f"Value: {eth_value:.4f} ETH\n"
                f"Gas: {gas_used}\n"
                f"Tx: {tx_hash.hex()}"
            )
            self._send_telegram(msg)
            return success

        except Exception as e:
            log.error(f"[AUTO-EXEC] Skim execution failed: {str(e)[:200]}")
            self._log_exec("skim", addr, "ERROR", str(e)[:200])
            self._send_telegram(f"<b>AUTO-SKIM ERROR</b>\nPair: {addr}\nValue: {eth_value:.4f} ETH\nError: {str(e)[:100]}")
            return False

    def try_rescue(self, contract_address, callable_functions, eth_value):
        """
        Attempt to rescue ETH via callable withdraw/sweep functions.
        Returns True if executed successfully.
        """
        if not self.enabled:
            return False

        addr = Web3.to_checksum_address(contract_address)
        gas_cost = self._estimate_gas_cost_eth()
        if gas_cost is None:
            log.info(f"[AUTO-EXEC] Skip rescue {addr[:16]}: gas price over {MAX_GAS_PRICE_GWEI} gwei cap")
            self._log_exec("rescue", addr, "SKIPPED", "gas price over cap")
            self._send_telegram(f"<b>AUTO-RESCUE SKIPPED</b>\nContract: {addr}\nReason: gas price over {MAX_GAS_PRICE_GWEI} gwei cap")
            return False

        # Gas ratio check: don't execute if gas > 10% of prize
        if eth_value > 0 and gas_cost / eth_value > MAX_GAS_COST_RATIO:
            pct = gas_cost / eth_value * 100
            log.info(f"[AUTO-EXEC] Skip rescue {addr[:16]}: gas is {pct:.1f}% of prize (max {MAX_GAS_COST_RATIO*100:.0f}%)")
            self._log_exec("rescue", addr, "SKIPPED", f"gas {pct:.1f}% of prize exceeds {MAX_GAS_COST_RATIO*100:.0f}% cap")
            return False

        profit = eth_value - gas_cost
        if profit < MIN_PROFIT_ETH:
            log.info(f"[AUTO-EXEC] Skip rescue {addr[:16]}: profit {profit:.4f} below threshold")
            return False

        # Try each callable function in order of preference
        preferred_order = [
            "0x3ccfd60b",  # withdraw()
            "0x853828b6",  # withdrawAll()
            "0x2e1a7d4d",  # withdraw(uint256)
            "0x51cff8d9",  # withdraw(address)
            "0xe9fad8ee",  # exit()
            "0x7b103999",  # claimReward()
            "0x01681a62",  # sweep(address)
        ]

        for selector in preferred_order:
            if selector not in callable_functions:
                continue

            calldata = self._build_calldata(selector, addr)
            fn_name = callable_functions.get(selector, selector)

            # Simulate from our wallet specifically
            if not self._simulate(addr, calldata):
                self._log_exec("rescue", addr, "SIM_REVERTED", f"fn={fn_name} value={eth_value}")
                continue

            # Get capped gas price for the actual transaction
            capped_price = self._capped_gas_price()
            if capped_price is None:
                log.info(f"[AUTO-EXEC] Skip rescue {addr[:16]}: gas spiked over cap before tx")
                self._log_exec("rescue", addr, "SKIPPED", "gas spiked over cap before tx")
                return False

            # Execute
            try:
                balance_before = self.w3.eth.get_balance(self.account.address)

                tx = {
                    "from": self.account.address,
                    "to": addr,
                    "data": calldata,
                    "gas": MAX_GAS_UNITS,
                    "gasPrice": capped_price,
                    "nonce": self.w3.eth.get_transaction_count(self.account.address),
                }
                signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
                tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

                success = receipt["status"] == 1
                balance_after = self.w3.eth.get_balance(self.account.address)
                gained = float(self.w3.from_wei(balance_after - balance_before, "ether"))
                result = "SUCCESS" if success else "FAILED"

                log.info(f"[AUTO-EXEC] Rescue {result}: {fn_name} on {addr} | gained: {gained:.4f} ETH | tx: {tx_hash.hex()}")
                self._log_exec("rescue", addr, result, f"fn={fn_name} tx={tx_hash.hex()} gained={gained}")

                msg = (
                    f"<b>AUTO-RESCUE {result}</b>\n"
                    f"Contract: {addr}\n"
                    f"Function: {fn_name}\n"
                    f"Gained: {gained:.4f} ETH\n"
                    f"Tx: {tx_hash.hex()}"
                )
                self._send_telegram(msg)
                return success

            except Exception as e:
                log.error(f"[AUTO-EXEC] Rescue {selector} failed: {str(e)[:200]}")
                self._log_exec("rescue", addr, "ERROR", f"fn={fn_name} error={str(e)[:150]}")
                self._send_telegram(f"<b>AUTO-RESCUE ERROR</b>\nContract: {addr}\nFunction: {fn_name}\nError: {str(e)[:100]}")
                continue

        return False

    def _build_calldata(self, selector, contract_addr):
        """Build calldata with proper ABI encoding."""
        sel = selector[2:]
        if selector in NO_ARG_SELECTORS:
            return "0x" + sel
        if selector in ADDR_ARG_SELECTORS:
            return "0x" + sel + self.account.address[2:].lower().zfill(64)
        if selector in UINT_ARG_SELECTORS:
            # withdraw(uint256) — try to withdraw everything
            try:
                bal = self.w3.eth.get_balance(Web3.to_checksum_address(contract_addr))
                return "0x" + sel + hex(bal)[2:].zfill(64)
            except Exception:
                return "0x" + sel + "f" * 64
        return "0x" + sel


# Singleton — initialized once when continuous_scanner imports this module
executor = AutoExecutor()
