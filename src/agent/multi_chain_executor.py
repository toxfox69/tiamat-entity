#!/usr/bin/env python3
"""
Multi-chain executor. Same wallet key works on all EVM chains.
Handles chain-specific gas params, chain IDs, and safety rules.
"""

import os
import sys
import json
import time
import fcntl
import logging
from web3 import Web3
from dotenv import load_dotenv

load_dotenv('/root/.env')

sys.path.insert(0, os.path.dirname(__file__))

LOG = logging.getLogger('multi_executor')
EXEC_LOG = "/root/.automaton/execution_log.json"

WALLET_KEY = os.environ.get("TIAMAT_WALLET_KEY")
WALLET_ADDR = "0xdc118c4e1284a61e4d5277936a64B9E08Ad9e7EE"

# Chain configs with gas strategies
CHAIN_CONFIG = {
    8453: {
        "name": "Base",
        "rpcs": ["https://mainnet.base.org", "https://base.meowrpc.com", "https://base.drpc.org"],
        "chain_id": 8453,
        "auto_execute": True,
        "max_gas_gwei": 100,
        "priority_fee_gwei": 0.1,
        "min_balance_eth": 0.001,  # Need at least this much to execute
        "gas_style": "eip1559",
    },
    42161: {
        "name": "Arbitrum",
        "rpcs": ["https://arb1.arbitrum.io/rpc", "https://arbitrum.drpc.org"],
        "chain_id": 42161,
        "auto_execute": True,
        "max_gas_gwei": 10,       # Arbitrum gas is very cheap
        "priority_fee_gwei": 0.01,
        "min_balance_eth": 0.0005,
        "gas_style": "eip1559",
    },
    10: {
        "name": "Optimism",
        "rpcs": ["https://mainnet.optimism.io", "https://optimism.drpc.org"],
        "chain_id": 10,
        "auto_execute": True,
        "max_gas_gwei": 100,
        "priority_fee_gwei": 0.1,
        "min_balance_eth": 0.001,
        "gas_style": "eip1559",
    },
    1: {
        "name": "Ethereum",
        "rpcs": ["https://eth.drpc.org", "https://rpc.ankr.com/eth"],
        "chain_id": 1,
        "auto_execute": False,     # NEVER auto-execute — gas expensive
        "max_gas_gwei": 50,        # Even 50 gwei can be $5-20 per tx
        "priority_fee_gwei": 2,
        "min_balance_eth": 0.01,   # Need more ETH for mainnet
        "gas_style": "eip1559",
    },
}

# Nonce cache per chain
_nonce_cache = {}
_nonce_time = {}


class MultiChainExecutor:
    def __init__(self):
        self.connections = {}
        self.account = None
        if WALLET_KEY:
            # Test with any chain's web3 — account is chain-independent
            w3 = Web3(Web3.HTTPProvider("https://mainnet.base.org"))
            self.account = w3.eth.account.from_key(WALLET_KEY)
            LOG.info(f"Wallet loaded: {self.account.address}")

    def get_w3(self, chain_id):
        """Get or create Web3 connection for a chain."""
        if chain_id not in self.connections:
            config = CHAIN_CONFIG.get(chain_id)
            if not config:
                raise ValueError(f"Unknown chain: {chain_id}")
            self.connections[chain_id] = {
                "w3": Web3(Web3.HTTPProvider(config["rpcs"][0])),
                "rpc_index": 0,
            }
        return self.connections[chain_id]["w3"]

    def rotate_rpc(self, chain_id):
        """Rotate to next RPC on failure."""
        config = CHAIN_CONFIG[chain_id]
        conn = self.connections.get(chain_id, {})
        idx = (conn.get("rpc_index", 0) + 1) % len(config["rpcs"])
        self.connections[chain_id] = {
            "w3": Web3(Web3.HTTPProvider(config["rpcs"][idx])),
            "rpc_index": idx,
        }
        return self.connections[chain_id]["w3"]

    def get_balance(self, chain_id):
        """Get TIAMAT's ETH balance on a specific chain."""
        w3 = self.get_w3(chain_id)
        addr = Web3.to_checksum_address(WALLET_ADDR)
        return w3.from_wei(w3.eth.get_balance(addr), 'ether')

    def can_execute(self, chain_id):
        """Check if execution is allowed on this chain."""
        config = CHAIN_CONFIG.get(chain_id)
        if not config:
            return False, "Unknown chain"
        if not config["auto_execute"]:
            return False, f"{config['name']} requires manual approval — gas expensive"
        if not self.account:
            return False, "No wallet key"
        try:
            bal = self.get_balance(chain_id)
            if float(bal) < config["min_balance_eth"]:
                return False, f"Insufficient balance on {config['name']}: {bal:.6f} ETH (need {config['min_balance_eth']})"
        except:
            return False, "Cannot check balance"
        return True, "OK"

    def get_gas_params(self, chain_id):
        """Get chain-specific EIP-1559 gas parameters."""
        config = CHAIN_CONFIG[chain_id]
        w3 = self.get_w3(chain_id)
        try:
            block = w3.eth.get_block('latest')
            base_fee = block.get('baseFeePerGas', 0)
            priority = Web3.to_wei(config["priority_fee_gwei"], 'gwei')
            max_fee = min(
                base_fee * 2 + priority,
                Web3.to_wei(config["max_gas_gwei"], 'gwei')
            )
            return {'maxFeePerGas': max_fee, 'maxPriorityFeePerGas': priority}
        except:
            return {
                'maxFeePerGas': Web3.to_wei(config["max_gas_gwei"] / 10, 'gwei'),
                'maxPriorityFeePerGas': Web3.to_wei(config["priority_fee_gwei"], 'gwei'),
            }

    def get_nonce(self, chain_id):
        """Get cached or fresh nonce for a chain."""
        now = time.time()
        if chain_id not in _nonce_cache or now - _nonce_time.get(chain_id, 0) > 10:
            w3 = self.get_w3(chain_id)
            _nonce_cache[chain_id] = w3.eth.get_transaction_count(
                Web3.to_checksum_address(WALLET_ADDR)
            )
            _nonce_time[chain_id] = now
        return _nonce_cache[chain_id]

    def increment_nonce(self, chain_id):
        if chain_id in _nonce_cache:
            _nonce_cache[chain_id] += 1

    def simulate(self, chain_id, to, data, from_addr=None):
        """Simulate a call via eth_call. Returns True if it doesn't revert."""
        w3 = self.get_w3(chain_id)
        call_obj = {
            'to': Web3.to_checksum_address(to),
            'data': data,
        }
        if from_addr:
            call_obj['from'] = Web3.to_checksum_address(from_addr)
        try:
            w3.eth.call(call_obj)
            return True, None
        except Exception as e:
            return False, str(e)[:200]

    def execute_skim(self, chain_id, pair_address):
        """
        Full skim execution on any chain:
        1. Check if execution is allowed
        2. Check balance before
        3. Simulate
        4. Estimate gas + check profitability
        5. Build, sign, send
        6. Check balance after
        7. Log with actual received amount
        8. Telegram alert
        """
        config = CHAIN_CONFIG.get(chain_id)
        if not config:
            return None

        # Step 0: Permission check
        can, reason = self.can_execute(chain_id)
        if not can:
            self._log(chain_id, pair_address, None, "BLOCKED", 0, reason)
            self._telegram(f"⛔ {config['name']}: {reason}\nPair: {pair_address[:20]}...")
            return None

        w3 = self.get_w3(chain_id)
        wallet = Web3.to_checksum_address(WALLET_ADDR)
        pair = Web3.to_checksum_address(pair_address)
        skim_data = '0xbc25cf77' + wallet.lower()[2:].zfill(64)

        # Step 1: Balance before
        try:
            bal_before = w3.eth.get_balance(wallet)
        except:
            bal_before = 0

        # Step 2: Simulate
        ok, err = self.simulate(chain_id, pair_address, skim_data, WALLET_ADDR)
        if not ok:
            self._log(chain_id, pair_address, None, "SIM_REVERTED", 0, err)
            return None

        # Step 3: Gas estimate + profitability
        try:
            gas_est = w3.eth.estimate_gas({'to': pair, 'from': wallet, 'data': skim_data})
        except:
            gas_est = 80000

        gas_params = self.get_gas_params(chain_id)
        gas_cost_wei = gas_est * gas_params['maxFeePerGas']

        # Safety: don't spend more than 0.002 ETH on gas for a skim
        max_gas_spend = Web3.to_wei(0.002, 'ether')
        if gas_cost_wei > max_gas_spend:
            self._log(chain_id, pair_address, None, "GAS_TOO_HIGH", 0,
                      f"gas={Web3.from_wei(gas_cost_wei, 'ether'):.6f} ETH")
            self._telegram(f"⚠️ {config['name']}: Gas too high for {pair_address[:16]}...")
            return None

        # Step 4: Build, sign, send
        try:
            nonce = self.get_nonce(chain_id)
            tx = {
                'to': pair,
                'data': bytes.fromhex(skim_data[2:]),
                'nonce': nonce,
                'gas': min(gas_est + 10000, 150000),
                'chainId': config['chain_id'],
                **gas_params,
            }
            signed = self.account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            self.increment_nonce(chain_id)
            tx_hex = tx_hash.hex()
        except Exception as e:
            self._log(chain_id, pair_address, None, "TX_FAILED", 0, str(e)[:150])
            self._telegram(f"❌ {config['name']}: TX failed for {pair_address[:16]}...")
            return None

        # Step 5: Wait for receipt, check balance after
        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            bal_after = w3.eth.get_balance(wallet)
            gas_used_wei = receipt['gasUsed'] * receipt.get('effectiveGasPrice', gas_params['maxFeePerGas'])
            received = bal_after - bal_before + gas_used_wei
            received_eth = float(Web3.from_wei(max(received, 0), 'ether'))

            if receipt['status'] != 1:
                status = "REVERTED"
            elif received <= 0:
                status = "EMPTY"
            else:
                status = "SUCCESS"

            self._log(chain_id, pair_address, tx_hex, status, received_eth)
            self._telegram(
                f"{'💰' if status=='SUCCESS' else '⚡'} {config['name']} SKIM {status}\n"
                f"Pair: {pair_address[:20]}...\n"
                f"Received: {received_eth:.6f} ETH\n"
                f"Gas: {Web3.from_wei(gas_used_wei, 'ether'):.6f} ETH\n"
                f"TX: {tx_hex[:20]}..."
            )
            return tx_hex if status == "SUCCESS" else None

        except Exception as e:
            self._log(chain_id, pair_address, tx_hex, "RECEIPT_TIMEOUT", 0, str(e)[:100])
            self._telegram(f"⏱️ {config['name']}: Receipt timeout — {tx_hex[:20]}...")
            return tx_hex

    def execute_rescue(self, chain_id, contract_address, function_selector, params=None):
        """
        Execute a rescue (withdraw/sweep/transfer) on any chain.
        Same safety pattern as skim but with arbitrary function call.
        """
        config = CHAIN_CONFIG.get(chain_id)
        if not config:
            return None

        can, reason = self.can_execute(chain_id)
        if not can:
            self._log(chain_id, contract_address, None, "BLOCKED", 0, reason)
            self._telegram(f"⛔ {config['name']}: {reason}\nContract: {contract_address[:20]}...")
            return None

        w3 = self.get_w3(chain_id)
        wallet = Web3.to_checksum_address(WALLET_ADDR)
        target = Web3.to_checksum_address(contract_address)

        # Build calldata
        if params:
            calldata = function_selector + params
        else:
            calldata = function_selector

        # Simulate
        ok, err = self.simulate(chain_id, contract_address, calldata, WALLET_ADDR)
        if not ok:
            self._log(chain_id, contract_address, None, "SIM_REVERTED", 0, err)
            return None

        # Balance before
        try:
            bal_before = w3.eth.get_balance(wallet)
        except:
            bal_before = 0

        # Gas
        try:
            gas_est = w3.eth.estimate_gas({'to': target, 'from': wallet, 'data': calldata})
        except:
            gas_est = 100000

        gas_params = self.get_gas_params(chain_id)
        gas_cost_wei = gas_est * gas_params['maxFeePerGas']

        if gas_cost_wei > Web3.to_wei(0.005, 'ether'):  # Slightly higher limit for rescues
            self._log(chain_id, contract_address, None, "GAS_TOO_HIGH", 0)
            return None

        # Send
        try:
            nonce = self.get_nonce(chain_id)
            tx = {
                'to': target,
                'data': bytes.fromhex(calldata[2:]) if calldata.startswith('0x') else bytes.fromhex(calldata),
                'nonce': nonce,
                'gas': min(gas_est + 20000, 200000),
                'chainId': config['chain_id'],
                **gas_params,
            }
            signed = self.account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            self.increment_nonce(chain_id)
            tx_hex = tx_hash.hex()
        except Exception as e:
            self._log(chain_id, contract_address, None, "TX_FAILED", 0, str(e)[:150])
            return None

        # Receipt
        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            bal_after = w3.eth.get_balance(wallet)
            gas_used_wei = receipt['gasUsed'] * receipt.get('effectiveGasPrice', gas_params['maxFeePerGas'])
            received = bal_after - bal_before + gas_used_wei
            received_eth = float(Web3.from_wei(max(received, 0), 'ether'))

            status = "SUCCESS" if receipt['status'] == 1 and received > 0 else "EMPTY" if receipt['status'] == 1 else "REVERTED"

            self._log(chain_id, contract_address, tx_hex, status, received_eth)
            self._telegram(
                f"{'💰' if status=='SUCCESS' else '🔧'} {config['name']} RESCUE {status}\n"
                f"Contract: {contract_address[:20]}...\n"
                f"Received: {received_eth:.6f} ETH\n"
                f"TX: {tx_hex[:20]}..."
            )
            return tx_hex if status == "SUCCESS" else None

        except Exception as e:
            self._log(chain_id, contract_address, tx_hex, "RECEIPT_TIMEOUT", 0)
            return tx_hex

    def _log(self, chain_id, address, tx_hash, result, received_eth, detail=""):
        """Log execution to shared log file."""
        config = CHAIN_CONFIG.get(chain_id, {})
        entry = json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "chain": config.get("name", str(chain_id)),
            "chain_id": chain_id,
            "address": address,
            "tx_hash": tx_hash,
            "result": result,
            "received_eth": received_eth,
            "detail": detail,
            "source": "multi_chain_executor",
        })
        try:
            with open(EXEC_LOG, 'a') as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.write(entry + '\n')
                fcntl.flock(f, fcntl.LOCK_UN)
        except:
            pass

    def _telegram(self, message):
        """Send Telegram alert."""
        try:
            import requests
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if token and chat_id:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": message},
                    timeout=5
                )
        except:
            pass


def send_funding_report():
    """Send wallet status across all chains to Telegram."""
    executor = MultiChainExecutor()
    lines = ["💰 TIAMAT Wallet Status\n"]
    for chain_id, config in CHAIN_CONFIG.items():
        try:
            bal = executor.get_balance(chain_id)
            can, _ = executor.can_execute(chain_id)
            icon = "✅" if can else "❌"
            lines.append(f"{icon} {config['name']}: {bal:.6f} ETH")
        except:
            lines.append(f"❓ {config['name']}: check failed")

    executor._telegram("\n".join(lines))


def check_all_balances():
    """CLI: print balances across all chains."""
    executor = MultiChainExecutor()
    print(f"Wallet: {WALLET_ADDR}")
    print("=" * 55)
    for chain_id, config in CHAIN_CONFIG.items():
        try:
            bal = executor.get_balance(chain_id)
            can, reason = executor.can_execute(chain_id)
            status = "✅ READY" if can else f"⚠️ {reason[:40]}"
            print(f"  {config['name']:12} ({chain_id}): {bal:.6f} ETH  {status}")
        except Exception as e:
            print(f"  {config['name']:12} ({chain_id}): ERROR — {str(e)[:50]}")


if __name__ == "__main__":
    import sys
    load_dotenv('/root/.env')
    if len(sys.argv) > 1 and sys.argv[1] == "balances":
        check_all_balances()
    elif len(sys.argv) > 1 and sys.argv[1] == "report":
        send_funding_report()
    else:
        print("Usage:")
        print("  python3 multi_chain_executor.py balances   — check all chain balances")
        print("  python3 multi_chain_executor.py report     — send Telegram funding report")
