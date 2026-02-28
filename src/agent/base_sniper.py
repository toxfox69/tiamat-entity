#!/usr/bin/env python3
"""
TIAMAT Base Chain Sniper
Watches for new liquidity pair creation on Base DEXes.
Executes micro-snipes on new tokens with safety checks.

RUNS AS SEPARATE PROCESS — not part of TIAMAT's cycle loop.
Start: /root/start-sniper.sh
PID file: /tmp/tiamat_sniper.pid
Log: /root/.automaton/sniper.log
"""

import json
import time
import sys
import os
import logging
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account
from opportunity_queue import OpportunityQueue

# ============ CONFIG ============
BASE_HTTP_RPCS = [
    "https://base.drpc.org",
    "https://mainnet.base.org",
    "https://base-mainnet.public.blastapi.io",
    "https://1rpc.io/base",
]

# Read private key from env — NEVER hardcode
PRIVATE_KEY = os.environ.get("TIAMAT_WALLET_KEY")
if not PRIVATE_KEY:
    print("ERROR: Set TIAMAT_WALLET_KEY env var")
    sys.exit(1)

# Safety limits
MAX_BUY_ETH = 0.001          # Max 0.001 ETH per snipe (~$2.50)
MAX_OPEN_POSITIONS = 5        # Never hold more than 5 tokens
SELL_PROFIT_TARGET = 1.5      # Sell at 50% profit
SELL_STOP_LOSS = 0.5          # Sell at 50% loss
MAX_SLIPPAGE = 0.15           # 15% max slippage
MIN_LIQUIDITY_ETH = 0.5      # Don't snipe if pool has < 0.5 ETH
HONEYPOT_CHECK = True         # Always check if token can be sold back
GAS_LIMIT = 300_000
MAX_GAS_GWEI = 0.05          # Base gas is cheap
POLL_INTERVAL = 4             # Seconds between polls
POSITION_CHECK_INTERVAL = 30  # Seconds between position checks
MAX_HOLD_SECONDS = 3600       # 1 hour max hold time

# Key addresses
ADDRESSES = {
    "WETH": "0x4200000000000000000000000000000000000006",
    "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "uniswap_v2_factory": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6",
    "uniswap_v3_factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
    "aerodrome_factory": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da",
    "uniswap_v2_router": "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24",
}

# Factory PairCreated event signature
PAIR_CREATED_TOPIC = Web3.keccak(text="PairCreated(address,address,address,uint256)").hex()

# Minimal ABIs
ROUTER_ABI = json.loads("""[
{"inputs":[{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactETHForTokensSupportingFeeOnTransferTokens","outputs":[],"stateMutability":"payable","type":"function"},
{"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactTokensForETHSupportingFeeOnTransferTokens","outputs":[],"stateMutability":"nonpayable","type":"function"},
{"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"}
]""")

ERC20_ABI = json.loads("""[
{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
{"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},
{"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"},
{"constant":true,"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"type":"function"},
{"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},
{"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}
]""")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SNIPER] %(message)s",
    handlers=[
        logging.FileHandler("/root/.automaton/sniper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("sniper")


class TokenSafetyCheck:
    """Checks if a token is likely a honeypot or rug"""

    def __init__(self, w3, router_address):
        self.w3 = w3
        self.router = self.w3.eth.contract(
            address=Web3.to_checksum_address(router_address),
            abi=ROUTER_ABI,
        )

    def check_sellable(self, token_address):
        """Simulate: can we sell this token back to WETH?"""
        try:
            token = self.w3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC20_ABI,
            )
            decimals = token.functions.decimals().call()
            total_supply = token.functions.totalSupply().call()

            if total_supply == 0:
                return False, "zero supply"

            test_amount = 10 ** decimals  # 1 token
            path = [Web3.to_checksum_address(token_address), ADDRESSES["WETH"]]
            amounts = self.router.functions.getAmountsOut(test_amount, path).call()
            if amounts[1] > 0:
                return True, "sellable"
            return False, "zero output"
        except Exception as e:
            return False, f"check failed: {str(e)[:50]}"

    def check_liquidity(self, pair_address):
        """Check WETH side of liquidity pool"""
        try:
            weth = self.w3.eth.contract(
                address=Web3.to_checksum_address(ADDRESSES["WETH"]),
                abi=ERC20_ABI,
            )
            liq = weth.functions.balanceOf(Web3.to_checksum_address(pair_address)).call()
            return float(self.w3.from_wei(liq, "ether"))
        except Exception:
            return 0

    def is_safe(self, token_address, pair_address):
        """Full safety check — returns (safe: bool, reason: str)"""
        liq = self.check_liquidity(pair_address)
        if liq < MIN_LIQUIDITY_ETH:
            return False, f"low liquidity: {liq:.4f} ETH (need {MIN_LIQUIDITY_ETH})"

        sellable, reason = self.check_sellable(token_address)
        if not sellable:
            return False, f"honeypot: {reason}"

        return True, f"safe (liq: {liq:.4f} ETH)"


class BaseSniper:
    def __init__(self):
        self.w3 = None
        self.account = Account.from_key(PRIVATE_KEY)
        self.wallet = self.account.address
        self.positions = {}
        self.positions_file = "/root/.automaton/sniper_positions.json"
        self.seen_pairs = set()  # avoid double-buying same pair
        self._load_positions()
        self._connect()
        self.safety = TokenSafetyCheck(self.w3, ADDRESSES["uniswap_v2_router"])
        self.last_scanned_block = self.w3.eth.block_number

        log.info(f"Sniper initialized. Wallet: {self.wallet}")
        log.info(f"ETH balance: {self.get_balance():.6f}")
        log.info(f"Open positions: {len(self.positions)}")

    def _connect(self):
        for rpc in BASE_HTTP_RPCS:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
                w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
                if w3.is_connected():
                    self.w3 = w3
                    log.info(f"Connected to {rpc}")
                    return
            except Exception:
                continue
        raise ConnectionError("All HTTP RPCs failed")

    def _load_positions(self):
        try:
            with open(self.positions_file) as f:
                self.positions = json.load(f)
        except Exception:
            self.positions = {}

    def _save_positions(self):
        with open(self.positions_file, "w") as f:
            json.dump(self.positions, f, indent=2, default=str)

    def get_balance(self):
        bal = self.w3.eth.get_balance(self.wallet)
        return float(self.w3.from_wei(bal, "ether"))

    def buy_token(self, token_address, pair_address, eth_amount=None):
        """Buy a token with ETH via Uniswap V2 router. Returns tx hash or None."""
        if len(self.positions) >= MAX_OPEN_POSITIONS:
            log.warning("Max positions reached, skipping")
            return None

        if token_address.lower() in self.seen_pairs:
            return None
        self.seen_pairs.add(token_address.lower())

        if eth_amount is None:
            eth_amount = MAX_BUY_ETH
        eth_amount = min(eth_amount, MAX_BUY_ETH)

        eth_balance = self.get_balance()
        if eth_balance < eth_amount + 0.0005:
            log.warning(f"Insufficient ETH: {eth_balance:.6f} (need {eth_amount + 0.0005:.4f})")
            return None

        # Safety check
        if HONEYPOT_CHECK:
            safe, reason = self.safety.is_safe(token_address, pair_address)
            if not safe:
                log.warning(f"UNSAFE {token_address[:10]}...: {reason}")
                return None
            log.info(f"Safety OK: {reason}")

        router = self.w3.eth.contract(
            address=Web3.to_checksum_address(ADDRESSES["uniswap_v2_router"]),
            abi=ROUTER_ABI,
        )

        path = [ADDRESSES["WETH"], Web3.to_checksum_address(token_address)]
        value_wei = self.w3.to_wei(eth_amount, "ether")
        deadline = int(time.time()) + 120

        # Get expected output for slippage calc
        try:
            amounts_out = router.functions.getAmountsOut(value_wei, path).call()
            min_out = int(amounts_out[1] * (1 - MAX_SLIPPAGE))
        except Exception:
            min_out = 0  # new tokens may not quote yet

        try:
            gas_price = self.w3.eth.gas_price
            if gas_price > Web3.to_wei(MAX_GAS_GWEI, "gwei"):
                log.warning(f"Gas too high: {Web3.from_wei(gas_price, 'gwei'):.4f} gwei")
                return None

            tx = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
                min_out, path, self.wallet, deadline
            ).build_transaction({
                "from": self.wallet,
                "value": value_wei,
                "gas": GAS_LIMIT,
                "gasPrice": gas_price,
                "nonce": self.w3.eth.get_transaction_count(self.wallet),
            })

            signed = self.w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            if receipt["status"] == 1:
                token = self.w3.eth.contract(
                    address=Web3.to_checksum_address(token_address),
                    abi=ERC20_ABI,
                )
                balance = token.functions.balanceOf(self.wallet).call()

                self.positions[token_address] = {
                    "buy_tx": tx_hash.hex(),
                    "buy_eth": eth_amount,
                    "tokens": balance,
                    "buy_time": time.time(),
                    "pair": pair_address,
                }
                self._save_positions()
                log.info(f"BUY OK: {token_address[:10]}... for {eth_amount} ETH | tx: {tx_hash.hex()}")
                return tx_hash.hex()
            else:
                log.error(f"BUY REVERTED | tx: {tx_hash.hex()}")
                return None

        except Exception as e:
            log.error(f"BUY ERROR: {str(e)[:120]}")
            return None

    def sell_token(self, token_address):
        """Sell entire token position back to ETH. Returns tx hash or None."""
        if token_address not in self.positions:
            return None

        token = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI,
        )
        balance = token.functions.balanceOf(self.wallet).call()

        if balance == 0:
            del self.positions[token_address]
            self._save_positions()
            return None

        router_addr = Web3.to_checksum_address(ADDRESSES["uniswap_v2_router"])
        router = self.w3.eth.contract(address=router_addr, abi=ROUTER_ABI)

        try:
            # Approve if needed
            allowance = token.functions.allowance(self.wallet, router_addr).call()
            if allowance < balance:
                approve_tx = token.functions.approve(
                    router_addr, balance
                ).build_transaction({
                    "from": self.wallet,
                    "gas": 100_000,
                    "gasPrice": self.w3.eth.gas_price,
                    "nonce": self.w3.eth.get_transaction_count(self.wallet),
                })
                signed = self.w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
                tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            path = [Web3.to_checksum_address(token_address), ADDRESSES["WETH"]]
            deadline = int(time.time()) + 120

            # Calculate minimum output with slippage protection
            try:
                amounts_out = router.functions.getAmountsOut(balance, path).call()
                min_out = int(amounts_out[1] * (1 - MAX_SLIPPAGE))
            except Exception:
                min_out = 0  # fallback for tokens that can't quote

            tx = router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
                balance, min_out, path, self.wallet, deadline
            ).build_transaction({
                "from": self.wallet,
                "value": 0,
                "gas": GAS_LIMIT,
                "gasPrice": self.w3.eth.gas_price,
                "nonce": self.w3.eth.get_transaction_count(self.wallet),
            })

            signed = self.w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            if receipt["status"] == 1:
                pos = self.positions.pop(token_address, None)
                self._save_positions()
                log.info(f"SELL OK: {token_address[:10]}... | bought {pos['buy_eth'] if pos else '?'} ETH | tx: {tx_hash.hex()}")
                return tx_hash.hex()
            else:
                log.error(f"SELL REVERTED: {token_address[:10]}...")
                return None

        except Exception as e:
            log.error(f"SELL ERROR: {str(e)[:120]}")
            return None

    def check_positions(self):
        """Check open positions for take-profit, stop-loss, or time exit."""
        for token_addr in list(self.positions.keys()):
            pos = self.positions[token_addr]
            try:
                router = self.w3.eth.contract(
                    address=Web3.to_checksum_address(ADDRESSES["uniswap_v2_router"]),
                    abi=ROUTER_ABI,
                )
                token = self.w3.eth.contract(
                    address=Web3.to_checksum_address(token_addr),
                    abi=ERC20_ABI,
                )
                balance = token.functions.balanceOf(self.wallet).call()

                if balance == 0:
                    log.info(f"Position {token_addr[:10]}... empty, removing")
                    del self.positions[token_addr]
                    self._save_positions()
                    continue

                path = [Web3.to_checksum_address(token_addr), ADDRESSES["WETH"]]
                amounts = router.functions.getAmountsOut(balance, path).call()
                current_eth = float(self.w3.from_wei(amounts[1], "ether"))
                buy_eth = pos["buy_eth"]
                ratio = current_eth / buy_eth if buy_eth > 0 else 0

                log.info(f"POS {token_addr[:10]}...: {buy_eth} ETH -> {current_eth:.6f} ETH ({ratio:.2f}x)")

                sell_reason = None
                if ratio >= SELL_PROFIT_TARGET:
                    sell_reason = f"TAKE PROFIT {ratio:.2f}x"
                elif ratio <= SELL_STOP_LOSS:
                    sell_reason = f"STOP LOSS {ratio:.2f}x"
                elif time.time() - pos["buy_time"] > MAX_HOLD_SECONDS:
                    sell_reason = "TIME EXIT (1h max hold)"

                if sell_reason:
                    log.info(sell_reason)
                    tx = self.sell_token(token_addr)
                    if tx:
                        try:
                            OpportunityQueue.push({
                                "source": "sniper",
                                "type": "trade_closed",
                                "address": token_addr,
                                "eth_value": current_eth - buy_eth,
                                "description": f"{sell_reason} | {buy_eth} ETH -> {current_eth:.6f} ETH",
                                "action": "log_revenue",
                            })
                        except Exception:
                            pass

            except Exception as e:
                log.error(f"Position check error {token_addr[:10]}...: {str(e)[:60]}")

    def poll_new_pairs(self):
        """Poll for new PairCreated events since last checked block."""
        try:
            current_block = self.w3.eth.block_number
            if current_block <= self.last_scanned_block:
                return

            from_block = self.last_scanned_block + 1
            # Cap lookback to avoid RPC limits
            if current_block - from_block > 100:
                from_block = current_block - 100

            factories = [
                ADDRESSES["uniswap_v2_factory"],
                ADDRESSES["aerodrome_factory"],
            ]

            for factory_addr in factories:
                try:
                    logs = self.w3.eth.get_logs({
                        "fromBlock": from_block,
                        "toBlock": current_block,
                        "address": Web3.to_checksum_address(factory_addr),
                        "topics": [PAIR_CREATED_TOPIC],
                    })

                    for event_log in logs:
                        token0 = "0x" + event_log["topics"][1].hex()[-40:]
                        token1 = "0x" + event_log["topics"][2].hex()[-40:]
                        pair = "0x" + event_log["data"].hex()[24:64]

                        # Find the non-WETH token
                        weth = ADDRESSES["WETH"].lower()
                        if token0.lower() == weth:
                            new_token = Web3.to_checksum_address(token1)
                        elif token1.lower() == weth:
                            new_token = Web3.to_checksum_address(token0)
                        else:
                            continue  # Not a WETH pair

                        pair_addr = Web3.to_checksum_address(pair)
                        log.info(f"NEW PAIR: {new_token} | pair: {pair_addr} | block: {event_log['blockNumber']}")

                        # Push to opportunity queue for TIAMAT
                        try:
                            OpportunityQueue.push({
                                "source": "sniper",
                                "type": "new_token_launch",
                                "address": new_token,
                                "pair": pair_addr,
                                "eth_value": 0,
                                "description": f"New token {new_token[:16]}... paired with WETH",
                                "action": "evaluate_for_snipe",
                                "block": event_log["blockNumber"],
                            })
                        except Exception:
                            pass

                        self.buy_token(new_token, pair_addr)

                except Exception as e:
                    log.error(f"Factory poll error ({factory_addr[:10]}...): {str(e)[:80]}")

            self.last_scanned_block = current_block

        except Exception as e:
            log.error(f"Poll error: {str(e)[:80]}")

    def status(self):
        """Return current sniper status as dict."""
        return {
            "wallet": self.wallet,
            "eth_balance": self.get_balance(),
            "open_positions": len(self.positions),
            "positions": {k: {
                "buy_eth": v["buy_eth"],
                "age_min": round((time.time() - v["buy_time"]) / 60, 1),
            } for k, v in self.positions.items()},
            "last_scanned_block": self.last_scanned_block,
            "config": {
                "max_buy_eth": MAX_BUY_ETH,
                "max_positions": MAX_OPEN_POSITIONS,
                "tp": SELL_PROFIT_TARGET,
                "sl": SELL_STOP_LOSS,
                "min_liquidity": MIN_LIQUIDITY_ETH,
            },
        }

    def run(self):
        """Main loop — poll for new pairs, manage positions."""
        log.info("=" * 50)
        log.info("TIAMAT SNIPER STARTED")
        log.info(f"Wallet: {self.wallet}")
        log.info(f"ETH: {self.get_balance():.6f}")
        log.info(f"Max buy: {MAX_BUY_ETH} ETH | TP: {SELL_PROFIT_TARGET}x | SL: {SELL_STOP_LOSS}x")
        log.info(f"Min liquidity: {MIN_LIQUIDITY_ETH} ETH | Honeypot check: {HONEYPOT_CHECK}")
        log.info("=" * 50)

        # Write PID with restrictive permissions
        fd = os.open("/run/tiamat/tiamat_sniper.pid", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)

        cycle = 0
        while True:
            try:
                # Poll for new pairs every cycle
                self.poll_new_pairs()

                # Check positions less frequently
                if cycle % (POSITION_CHECK_INTERVAL // POLL_INTERVAL) == 0:
                    self.check_positions()

                # Log heartbeat every ~60s
                if cycle % (60 // POLL_INTERVAL) == 0:
                    bal = self.get_balance()
                    log.info(f"[heartbeat] cycle={cycle} eth={bal:.6f} positions={len(self.positions)} block={self.last_scanned_block}")

                cycle += 1
                time.sleep(POLL_INTERVAL)

            except KeyboardInterrupt:
                log.info("Shutting down gracefully...")
                break
            except Exception as e:
                log.error(f"Loop error: {str(e)[:100]}")
                time.sleep(10)  # back off on errors

        # Cleanup
        try:
            os.remove("/tmp/tiamat_sniper.pid")
        except Exception:
            pass
        log.info("Sniper stopped.")


if __name__ == "__main__":
    sniper = BaseSniper()
    sniper.run()
