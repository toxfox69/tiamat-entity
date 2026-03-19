#!/usr/bin/env python3
"""
TIAMAT Multi-Chain Sniper — chain-agnostic sniper daemon.
Runs alongside base_sniper.py (which handles Base chain 8453).
Spawns a ChainSniper thread per configured chain (excluding Base).

Start: python3 multi_chain_sniper.py
PID file: /run/tiamat/tiamat_multi_sniper.pid
Log: /root/.automaton/multi_sniper.log
"""

import json
import time
import sys
import os
import signal
import logging
import threading
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account
from chain_config import CHAINS, FUNDED_CHAINS, get_findings_file
from opportunity_queue import OpportunityQueue
from pair_blacklist import is_blacklisted, record_dry, record_success

# ============ CONFIG ============
PRIVATE_KEY = os.environ.get("TIAMAT_WALLET_KEY")
if not PRIVATE_KEY:
    print("ERROR: Set TIAMAT_WALLET_KEY env var")
    sys.exit(1)

# Safety limits — same as base_sniper (nickel and dime mode)
MAX_BUY_ETH = 0.0003
MAX_OPEN_POSITIONS = 3
SELL_PROFIT_TARGET = 1.05
SELL_STOP_LOSS = 0.85
MAX_SLIPPAGE = 0.10
MIN_LIQUIDITY_ETH = 2.0
HONEYPOT_CHECK = True
GAS_LIMIT = 300_000
POLL_INTERVAL = 4            # Slightly slower than base sniper (less aggressive on new chains)
POSITION_CHECK_INTERVAL = 15
MAX_HOLD_SECONDS = 300

# Skip Base — base_sniper.py handles it
SKIP_CHAINS = {8453}

PID_FILE = "/run/tiamat/tiamat_multi_sniper.pid"
LOG_FILE = "/root/.automaton/multi_sniper.log"

PAIR_CREATED_TOPIC = "0x" + Web3.keccak(
    text="PairCreated(address,address,address,uint256)"
).hex()

# V3-style PoolCreated event (Uniswap V3, Hyperliquid DEXes)
POOL_CREATED_TOPIC = "0x" + Web3.keccak(
    text="PoolCreated(address,address,uint24,int24,address)"
).hex()

SKIM_SELECTOR = "0xbc25cf77"

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
log = logging.getLogger("multi_sniper")
if not log.handlers:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [MULTI-SNIPER] %(message)s")
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(fmt)
    log.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(sh)
    log.propagate = False

running = True


def shutdown(signum, frame):
    global running
    log.info(f"Received signal {signum}, shutting down...")
    running = False


class ChainSniper:
    """Sniper instance for a single chain. Reads config from chain_config.py."""

    def __init__(self, chain_id):
        config = CHAINS.get(chain_id)
        if not config:
            raise ValueError(f"Unknown chain: {chain_id}")

        self.chain_id = chain_id
        self.chain_name = config["name"]
        self.rpcs = config["rpcs"]
        self.weth = config.get("weth")
        self.factories = config.get("factories", {})
        self.v3_factories = config.get("v3_factories", {})
        self.block_time = config.get("block_time", 2)
        self.auto_execute = config.get("auto_execute", False)
        self.min_eth_value = config.get("min_eth_value", 0.01)

        self.w3 = None
        self.account = Account.from_key(PRIVATE_KEY)
        self.wallet = self.account.address
        self.positions = {}
        self.positions_file = f"/root/.automaton/sniper_positions_{chain_id}.json"
        self.seen_pairs = set()
        self._load_positions()
        self._connect()
        self.last_scanned_block = self.w3.eth.block_number

        log.info(f"[{self.chain_name}] Sniper initialized. Block: {self.last_scanned_block}")
        if self.weth:
            log.info(f"[{self.chain_name}] WETH: {self.weth}")
        if self.factories:
            log.info(f"[{self.chain_name}] V2 Factories: {list(self.factories.keys())}")
        if self.v3_factories:
            log.info(f"[{self.chain_name}] V3 Factories: {list(self.v3_factories.keys())}")
        if not self.factories and not self.v3_factories:
            log.info(f"[{self.chain_name}] No factories configured — scan-only mode (new contracts + skim)")

    def _connect(self):
        for rpc in self.rpcs:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 15}))
                w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
                if w3.is_connected():
                    self.w3 = w3
                    log.info(f"[{self.chain_name}] Connected to {rpc}")
                    return
            except Exception:
                continue
        raise ConnectionError(f"[{self.chain_name}] All RPCs failed: {self.rpcs}")

    def _reconnect(self):
        log.warning(f"[{self.chain_name}] Reconnecting...")
        self._connect()

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

    def poll_new_pairs(self):
        """Poll factories for new PairCreated events."""
        if not self.factories:
            return  # No factories configured — nothing to poll

        try:
            current_block = self.w3.eth.block_number
            if current_block <= self.last_scanned_block:
                return

            from_block = self.last_scanned_block + 1
            if current_block - from_block > 100:
                from_block = current_block - 100
            if from_block > current_block:
                return

            # Some RPCs report block_number ahead of what they'll accept in queries.
            # Use current_block - 1 as toBlock to avoid "beyond current head" errors.
            to_block = max(from_block, current_block - 1)

            for dex_name, factory_addr in self.factories.items():
                try:
                    logs = self.w3.eth.get_logs({
                        "fromBlock": from_block,
                        "toBlock": to_block,
                        "address": Web3.to_checksum_address(factory_addr),
                        "topics": [PAIR_CREATED_TOPIC],
                    })

                    for event_log in logs:
                        token0 = "0x" + event_log["topics"][1].hex()[-40:]
                        token1 = "0x" + event_log["topics"][2].hex()[-40:]
                        pair = "0x" + event_log["data"].hex()[24:64]

                        if not self.weth:
                            # No WETH configured — log pair but can't determine which token is new
                            pair_addr = Web3.to_checksum_address(pair)
                            log.info(f"[{self.chain_name}] NEW PAIR [{dex_name}]: {pair_addr} "
                                     f"tokens: {token0[:16]}... / {token1[:16]}... | block: {event_log['blockNumber']}")
                            OpportunityQueue.push({
                                "source": f"sniper_{self.chain_name.lower()}",
                                "type": "new_pair_detected",
                                "address": pair_addr,
                                "chain_id": self.chain_id,
                                "chain_name": self.chain_name,
                                "dex": dex_name,
                                "description": f"New pair on {self.chain_name}/{dex_name} (no WETH config)",
                                "action": "review",
                            })
                            continue

                        weth_lower = self.weth.lower()
                        if token0.lower() == weth_lower:
                            new_token = Web3.to_checksum_address(token1)
                        elif token1.lower() == weth_lower:
                            new_token = Web3.to_checksum_address(token0)
                        else:
                            continue

                        pair_addr = Web3.to_checksum_address(pair)
                        log.info(f"[{self.chain_name}] NEW PAIR [{dex_name}]: {new_token} | "
                                 f"pair: {pair_addr} | block: {event_log['blockNumber']}")

                        OpportunityQueue.push({
                            "source": f"sniper_{self.chain_name.lower()}",
                            "type": "new_token_launch",
                            "address": new_token,
                            "pair": pair_addr,
                            "dex": dex_name,
                            "chain_id": self.chain_id,
                            "chain_name": self.chain_name,
                            "eth_value": 0,
                            "description": f"New token {new_token[:16]}... on {self.chain_name}/{dex_name}",
                            "action": "evaluate_for_snipe",
                            "block": event_log["blockNumber"],
                        })

                        # Only auto-buy if chain is funded and has auto_execute
                        if self.auto_execute and self.chain_id in FUNDED_CHAINS:
                            # Would call self.buy_token(new_token, pair_addr) here
                            pass  # Scan-only for now

                except Exception as e:
                    err_str = str(e)
                    if any(x in err_str for x in ("greater than", "invalid params", "incorrect response")):
                        pass
                    else:
                        log.error(f"[{self.chain_name}] Factory poll error [{dex_name}]: {err_str[:80]}")

            self.last_scanned_block = current_block

        except Exception as e:
            log.error(f"[{self.chain_name}] Poll error: {str(e)[:80]}")

    def poll_v3_pools(self):
        """Poll V3-style factories for PoolCreated events (Hyperliquid, etc)."""
        if not self.v3_factories:
            return

        try:
            current_block = self.w3.eth.block_number
            if current_block <= self.last_scanned_block:
                return

            from_block = self.last_scanned_block + 1
            if current_block - from_block > 100:
                from_block = current_block - 100
            if from_block > current_block:
                return

            to_block = max(from_block, current_block - 1)

            # Scan for PoolCreated across ALL addresses (V3 factories emit this)
            try:
                logs = self.w3.eth.get_logs({
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "topics": [POOL_CREATED_TOPIC],
                })

                for event_log in logs:
                    # PoolCreated(address token0, address token1, uint24 fee, int24 tickSpacing, address pool)
                    token0 = "0x" + event_log["topics"][1].hex()[-40:]
                    token1 = "0x" + event_log["topics"][2].hex()[-40:]
                    factory = event_log["address"]
                    # Pool address is in the data
                    pool = "0x" + event_log["data"].hex()[-40:] if len(event_log["data"]) >= 32 else "unknown"

                    pool_addr = Web3.to_checksum_address(pool) if pool != "unknown" else pool
                    log.info(f"[{self.chain_name}] V3 POOL [{factory[:16]}...]: "
                             f"{token0[:16]}... / {token1[:16]}... | pool: {pool_addr}")

                    OpportunityQueue.push({
                        "source": f"sniper_{self.chain_name.lower()}",
                        "type": "v3_pool_created",
                        "address": pool_addr,
                        "chain_id": self.chain_id,
                        "chain_name": self.chain_name,
                        "factory": str(factory),
                        "token0": token0,
                        "token1": token1,
                        "description": f"V3 pool on {self.chain_name}: {token0[:10]}.../{token1[:10]}...",
                        "action": "review",
                        "block": event_log["blockNumber"],
                    })

            except Exception as e:
                err_str = str(e)
                if any(x in err_str for x in ("greater than", "invalid params", "rate limited")):
                    pass
                else:
                    log.error(f"[{self.chain_name}] V3 pool scan error: {err_str[:80]}")

            # Also scan for Swap events on known V3 routers (high-value activity monitoring)
            # Swap(address,address,int256,int256,uint160,uint128,int24)
            # We don't need the full event — just knowing swaps are happening tells us volume

        except Exception as e:
            log.error(f"[{self.chain_name}] V3 poll error: {str(e)[:80]}")

    def check_skim_opportunities(self, cycle):
        """Scan recent pairs for skimmable excess tokens."""
        if not self.factories:
            return
        if cycle % 50 != 0:
            return

        try:
            current_block = self.w3.eth.block_number
            from_block = current_block - 500
            to_block = max(0, current_block - 1)  # Avoid "beyond current head" on some RPCs

            for dex_name, factory_addr in self.factories.items():
                try:
                    logs = self.w3.eth.get_logs({
                        "fromBlock": max(0, from_block),
                        "toBlock": to_block,
                        "address": Web3.to_checksum_address(factory_addr),
                        "topics": [PAIR_CREATED_TOPIC],
                    })

                    for event_log in logs:
                        pair = Web3.to_checksum_address("0x" + event_log["data"].hex()[24:64])
                        if is_blacklisted(pair):
                            continue

                        try:
                            # getReserves()
                            reserves_raw = self.w3.eth.call({"to": pair, "data": "0x0902f1ac"})
                            reserve0 = int.from_bytes(reserves_raw[0:32], "big")
                            reserve1 = int.from_bytes(reserves_raw[32:64], "big")

                            # token0(), token1()
                            t0_raw = self.w3.eth.call({"to": pair, "data": "0x0dfe1681"})
                            t1_raw = self.w3.eth.call({"to": pair, "data": "0xd21220a7"})
                            token0 = Web3.to_checksum_address("0x" + t0_raw.hex()[-40:])
                            token1 = Web3.to_checksum_address("0x" + t1_raw.hex()[-40:])

                            # balanceOf(pair) for each token
                            pair_hex = pair.lower()[2:].zfill(64)
                            bal0 = int.from_bytes(
                                self.w3.eth.call({"to": token0, "data": "0x70a08231" + pair_hex}), "big"
                            )
                            bal1 = int.from_bytes(
                                self.w3.eth.call({"to": token1, "data": "0x70a08231" + pair_hex}), "big"
                            )

                            excess0 = bal0 - reserve0
                            excess1 = bal1 - reserve1

                            # If WETH is known, check WETH side. Otherwise check both sides for any excess.
                            weth_excess = 0
                            if self.weth:
                                weth_lower = self.weth.lower()
                                if token0.lower() == weth_lower and excess0 > 0:
                                    weth_excess = excess0
                                elif token1.lower() == weth_lower and excess1 > 0:
                                    weth_excess = excess1
                            else:
                                # No WETH known — report any significant excess
                                weth_excess = max(excess0, excess1)

                            if weth_excess > 0:
                                weth_eth = float(self.w3.from_wei(weth_excess, "ether"))
                                if weth_eth >= 0.0001:
                                    log.info(f"[{self.chain_name}] SKIM FOUND [{dex_name}]: {pair} | "
                                             f"excess: {weth_eth:.6f} ETH-equivalent")

                                    if self.auto_execute and self.chain_id in FUNDED_CHAINS:
                                        self._execute_skim(pair, weth_eth)
                                    else:
                                        OpportunityQueue.push({
                                            "source": f"sniper_{self.chain_name.lower()}",
                                            "type": "skimmable_pair",
                                            "address": str(pair),
                                            "eth_value": weth_eth,
                                            "chain_id": self.chain_id,
                                            "chain_name": self.chain_name,
                                            "dex": dex_name,
                                            "description": f"Skimmable {weth_eth:.6f} on {self.chain_name}/{dex_name}",
                                            "action": "skim" if self.auto_execute else "review",
                                        })

                        except Exception:
                            continue

                except Exception as e:
                    err_str = str(e)
                    if any(x in err_str for x in ("greater than", "invalid params")):
                        pass
                    else:
                        log.error(f"[{self.chain_name}] Skim scan error [{dex_name}]: {err_str[:80]}")

        except Exception as e:
            log.error(f"[{self.chain_name}] Skim scan error: {str(e)[:80]}")

    def _execute_skim(self, pair_address, expected_eth):
        """Execute skim() on a pair — only if chain is funded."""
        pair = Web3.to_checksum_address(pair_address)
        skim_data = SKIM_SELECTOR + self.wallet.lower()[2:].zfill(64)

        # Simulate
        try:
            self.w3.eth.call({"to": pair, "from": self.wallet, "data": skim_data})
        except Exception as e:
            log.warning(f"[{self.chain_name}] Skim sim reverted {pair[:16]}...: {str(e)[:60]}")
            return None

        try:
            bal_before = self.w3.eth.get_balance(self.wallet)
            gas_price = self.w3.eth.gas_price

            tx = {
                "to": pair,
                "data": bytes.fromhex(skim_data[2:]),
                "nonce": self.w3.eth.get_transaction_count(self.wallet),
                "gas": 100_000,
                "gasPrice": gas_price,
                "chainId": self.chain_id,
            }

            signed = self.w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=15)

            bal_after = self.w3.eth.get_balance(self.wallet)
            net_gain = float(self.w3.from_wei(bal_after - bal_before, "ether"))

            if receipt["status"] == 1:
                log.info(f"[{self.chain_name}] SKIM SUCCESS: {pair[:16]}... | net: {net_gain:.6f} ETH | tx: {tx_hash.hex()}")
                record_success(str(pair_address))
                OpportunityQueue.push({
                    "source": f"sniper_skim_{self.chain_name.lower()}",
                    "type": "skim_executed",
                    "address": str(pair_address),
                    "eth_value": net_gain,
                    "chain_id": self.chain_id,
                    "chain_name": self.chain_name,
                    "description": f"Skimmed {expected_eth:.6f} ETH on {self.chain_name}, net {net_gain:.6f}",
                    "action": "log_revenue",
                })
                return tx_hash.hex()
            else:
                log.warning(f"[{self.chain_name}] Skim reverted on-chain: {pair[:16]}...")
                record_dry(str(pair_address))
                return None

        except Exception as e:
            log.error(f"[{self.chain_name}] Skim execution error: {str(e)[:80]}")
            return None

    def run(self):
        """Main loop for this chain's sniper thread."""
        log.info(f"[{self.chain_name}] Sniper thread started")
        cycle = 0

        while running:
            try:
                self.poll_new_pairs()
                self.poll_v3_pools()

                if cycle % (POSITION_CHECK_INTERVAL // POLL_INTERVAL) == 0:
                    # Position management would go here when chain is funded
                    pass

                self.check_skim_opportunities(cycle)

                # Heartbeat every ~60s
                if cycle > 0 and cycle % (60 // POLL_INTERVAL) == 0:
                    try:
                        bal = self.get_balance()
                        log.info(f"[{self.chain_name}] [heartbeat] cycle={cycle} "
                                 f"eth={bal:.6f} block={self.last_scanned_block} "
                                 f"factories={len(self.factories)}")
                    except Exception:
                        log.info(f"[{self.chain_name}] [heartbeat] cycle={cycle} "
                                 f"block={self.last_scanned_block}")

                cycle += 1
                time.sleep(POLL_INTERVAL)

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"[{self.chain_name}] Loop error: {str(e)[:100]}")
                try:
                    self._reconnect()
                except Exception:
                    log.error(f"[{self.chain_name}] Reconnect failed, waiting 30s...")
                    time.sleep(30)
                    continue
                time.sleep(10)

        log.info(f"[{self.chain_name}] Sniper thread stopped.")


def main():
    global running

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Ensure PID dir exists
    os.makedirs("/run/tiamat", exist_ok=True)

    # Write PID
    fd = os.open(PID_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)

    # Determine which chains to run
    chains_to_run = {cid: cfg for cid, cfg in CHAINS.items() if cid not in SKIP_CHAINS}

    log.info("=" * 60)
    log.info("TIAMAT MULTI-CHAIN SNIPER DAEMON")
    log.info(f"PID: {os.getpid()}")
    log.info(f"Chains: {', '.join(c['name'] for c in chains_to_run.values())}")
    log.info(f"Skipping: {', '.join(CHAINS[c]['name'] for c in SKIP_CHAINS if c in CHAINS)}")
    log.info(f"Funded: {FUNDED_CHAINS}")
    log.info("=" * 60)

    threads = {}
    for chain_id, config in chains_to_run.items():
        def run_chain(cid=chain_id):
            try:
                sniper = ChainSniper(cid)
                sniper.run()
            except Exception as e:
                log.error(f"[{CHAINS[cid]['name']}] Fatal error: {str(e)[:150]}")

        thread = threading.Thread(target=run_chain, daemon=True, name=f"sniper_{config['name'].lower()}")
        thread.start()
        threads[chain_id] = thread
        log.info(f"Started sniper thread for {config['name']} (chain {chain_id})")
        time.sleep(2)  # Stagger starts

    # Main thread: monitor + restart dead threads
    while running:
        time.sleep(10)

        for chain_id, thread in list(threads.items()):
            if not thread.is_alive() and running:
                config = chains_to_run[chain_id]
                log.warning(f"[{config['name']}] Sniper thread died, restarting...")

                def run_chain(cid=chain_id):
                    try:
                        sniper = ChainSniper(cid)
                        sniper.run()
                    except Exception as e:
                        log.error(f"[{CHAINS[cid]['name']}] Fatal error: {str(e)[:150]}")

                new_thread = threading.Thread(target=run_chain, daemon=True,
                                             name=f"sniper_{config['name'].lower()}")
                new_thread.start()
                threads[chain_id] = new_thread

    # Cleanup
    log.info("Multi-chain sniper stopped gracefully.")
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
