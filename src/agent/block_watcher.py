#!/usr/bin/env python3
"""
Block-reactive scanner for Base L2.
Subscribes to new blocks via websocket.
On each new block: check watched pairs for skimmable excess, execute within 500ms.
Runs as a thread inside continuous_scanner.py.
"""

import os
import sys
import json
import time
import logging
import asyncio
import threading
import fcntl

sys.path.insert(0, os.path.dirname(__file__))

try:
    import websockets
except ImportError:
    os.system("pip install websockets --break-system-packages -q")
    import websockets

from web3 import Web3

try:
    from multi_chain_executor import MultiChainExecutor
    HAS_MULTI_EXEC = True
except ImportError:
    HAS_MULTI_EXEC = False

LOG_FILE = "/root/.automaton/block_watcher.log"
WATCH_FILE = "/root/.automaton/watched_pairs.json"
EXEC_LOG = "/root/.automaton/execution_log.json"
RESCUE_WATCH_FILE = "/root/.automaton/watched_rescues.json"

# Multicall3 — deployed at same address on all EVM chains
MULTICALL3 = "0xcA11bde05977b3631167028862bE2a173976CA11"

# Uniswap V2 / Aerodrome factory addresses on Base
UNISWAP_V2_FACTORY = "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"

# PairCreated event topic: PairCreated(address,address,address,uint256)
PAIR_CREATED_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"

# Swap event topic: Swap(address,uint256,uint256,uint256,uint256,address)
SWAP_TOPIC = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"

# WETH on Base
WETH = "0x4200000000000000000000000000000000000006"

# Rescue function selectors (same as auto_executor.py)
RESCUE_SELECTORS = {
    "0x3ccfd60b": "withdraw()",
    "0x853828b6": "withdrawAll()",
    "0xe9fad8ee": "exit()",
    "0x7b103999": "claimReward()",
    "0x51cff8d9": "withdraw(address)",
    "0x01681a62": "sweep(address)",
    "0x2e1a7d4d": "withdraw(uint256)",
}

# Min ETH value to bother acting on
MIN_ETH_VALUE = 0.01

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [BLOCK] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger('block_watcher')

# Free websocket endpoints for Base (Alchemy demo is junk — shared pool, always 429/1008)
WS_ENDPOINTS = [
    "wss://base.drpc.org",
    "wss://base-rpc.publicnode.com",
]

# HTTP RPC for eth_call and tx submission
RPC_URLS = [
    "https://base.drpc.org",
    "https://mainnet.base.org",
    "https://base.meowrpc.com",
]

WALLET_KEY = os.environ.get("TIAMAT_WALLET_KEY")
WALLET_ADDR = os.environ.get("TIAMAT_WALLET_ADDR", "0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE")


class BlockWatcher:
    def __init__(self):
        self.rpc_index = 0
        self.ws_index = 0
        self.w3 = Web3(Web3.HTTPProvider(RPC_URLS[0]))
        self.watched_pairs = []
        self.last_block = 0
        self.cached_nonce = None
        self.cached_nonce_time = 0
        self.running = False

        # Multi-chain executor (preferred for skim execution)
        self.multi_exec = MultiChainExecutor() if HAS_MULTI_EXEC else None

        if WALLET_KEY:
            self.account = self.w3.eth.account.from_key(WALLET_KEY)
            log.info(f"Wallet: {self.account.address}")
        else:
            self.account = None
            log.warning("No wallet key — monitor only")

    # ==========================================
    # RPC MANAGEMENT
    # ==========================================

    def _rotate_rpc(self):
        self.rpc_index = (self.rpc_index + 1) % len(RPC_URLS)
        self.w3 = Web3(Web3.HTTPProvider(RPC_URLS[self.rpc_index]))
        log.info(f"Rotated RPC to {RPC_URLS[self.rpc_index]}")

    def _rotate_ws(self):
        self.ws_index = (self.ws_index + 1) % len(WS_ENDPOINTS)
        log.info(f"Rotated WS to {WS_ENDPOINTS[self.ws_index]}")

    # ==========================================
    # NONCE CACHE — pre-compute for instant tx
    # ==========================================

    def _refresh_nonce(self):
        try:
            self.cached_nonce = self.w3.eth.get_transaction_count(
                Web3.to_checksum_address(WALLET_ADDR)
            )
            self.cached_nonce_time = time.time()
        except Exception:
            pass

    def _get_nonce(self):
        if self.cached_nonce is None or time.time() - self.cached_nonce_time > 10:
            self._refresh_nonce()
        return self.cached_nonce

    def _increment_nonce(self):
        if self.cached_nonce is not None:
            self.cached_nonce += 1

    # ==========================================
    # GAS MANAGEMENT
    # ==========================================

    def _capped_gas_params(self):
        """EIP-1559 gas with priority bump, capped at 100 gwei"""
        try:
            block = self.w3.eth.get_block('latest')
            base_fee = block.get('baseFeePerGas', 0)
            # 0.1 gwei priority — 10x default, still <$0.001 on Base
            priority = Web3.to_wei(0.1, 'gwei')
            max_fee = min(base_fee * 2 + priority, Web3.to_wei(100, 'gwei'))
            return {'maxFeePerGas': max_fee, 'maxPriorityFeePerGas': priority}
        except Exception:
            return {'maxFeePerGas': Web3.to_wei(1, 'gwei'), 'maxPriorityFeePerGas': Web3.to_wei(0.1, 'gwei')}

    # ==========================================
    # WATCHED PAIRS
    # ==========================================

    def reload_watched_pairs(self):
        """Load pairs to monitor from file. Scanner populates this."""
        try:
            with open(WATCH_FILE) as f:
                data = json.load(f)
                # Support both list of strings and list of objects
                self.watched_pairs = []
                for item in data:
                    if isinstance(item, str):
                        self.watched_pairs.append(item)
                    elif isinstance(item, dict):
                        self.watched_pairs.append(item.get("address", ""))
                self.watched_pairs = [p for p in self.watched_pairs if p]
        except Exception:
            self.watched_pairs = []

    # ==========================================
    # SKIM CHECK — compare reserves vs balances
    # ==========================================

    def check_pair_excess(self, pair_address):
        """
        Check if a Uniswap V2 style pair has skimmable excess.
        Compares actual token balances to reported reserves.
        If balance > reserve for either token, there's excess to skim.
        Returns (has_excess, excess0, excess1)
        """
        try:
            pair = Web3.to_checksum_address(pair_address)

            # getReserves()
            reserves_raw = self.w3.eth.call({'to': pair, 'data': '0x0902f1ac'})
            reserve0 = int.from_bytes(reserves_raw[0:32], 'big')
            reserve1 = int.from_bytes(reserves_raw[32:64], 'big')

            # token0()
            t0_raw = self.w3.eth.call({'to': pair, 'data': '0x0dfe1681'})
            token0 = Web3.to_checksum_address('0x' + t0_raw.hex()[-40:])

            # token1()
            t1_raw = self.w3.eth.call({'to': pair, 'data': '0xd21220a7'})
            token1 = Web3.to_checksum_address('0x' + t1_raw.hex()[-40:])

            # balanceOf(pair) for both tokens
            pair_hex = pair.lower()[2:].zfill(64)

            bal0_raw = self.w3.eth.call({'to': token0, 'data': '0x70a08231' + pair_hex})
            balance0 = int.from_bytes(bal0_raw, 'big')

            bal1_raw = self.w3.eth.call({'to': token1, 'data': '0x70a08231' + pair_hex})
            balance1 = int.from_bytes(bal1_raw, 'big')

            excess0 = balance0 - reserve0
            excess1 = balance1 - reserve1

            if excess0 > 0 or excess1 > 0:
                return True, excess0, excess1

            return False, 0, 0

        except Exception:
            return False, 0, 0

    # ==========================================
    # EXECUTE SKIM — simulate then send
    # ==========================================

    def execute_skim(self, pair_address):
        """
        Full execution pipeline:
        1. Check wallet balance before
        2. Simulate skim via eth_call
        3. Build tx with cached nonce + priority fee
        4. Sign and send
        5. Check wallet balance after
        6. Log actual received amount
        7. Telegram alert
        8. IPC report to TIAMAT
        """
        if not self.account:
            return None

        wallet = Web3.to_checksum_address(WALLET_ADDR)
        pair = Web3.to_checksum_address(pair_address)
        skim_data = '0xbc25cf77' + wallet.lower()[2:].zfill(64)

        # Step 1: Balance BEFORE
        try:
            bal_before = self.w3.eth.get_balance(wallet)
        except Exception:
            bal_before = 0

        # Step 2: Simulate
        try:
            self.w3.eth.call({'to': pair, 'from': wallet, 'data': skim_data})
        except Exception as e:
            log.warning(f"Simulation reverted {pair_address[:16]}...: {str(e)[:80]}")
            self._log_exec(pair_address, None, "SIMULATION_REVERTED", 0)
            return None

        # Step 3: Estimate gas and check profitability
        try:
            gas_estimate = self.w3.eth.estimate_gas({'to': pair, 'from': wallet, 'data': skim_data})
        except Exception:
            gas_estimate = 80000

        gas_params = self._capped_gas_params()
        gas_cost_wei = gas_estimate * gas_params['maxFeePerGas']
        # Skip if gas > 0.001 ETH (~$2.50) as safety
        if gas_cost_wei > Web3.to_wei(0.001, 'ether'):
            log.warning(f"Gas too high for {pair_address[:16]}...: {Web3.from_wei(gas_cost_wei, 'ether'):.6f} ETH")
            self._log_exec(pair_address, None, "GAS_TOO_HIGH", 0)
            self._send_telegram(f"SKIP: gas too high for {pair_address[:16]}...")
            return None

        # Step 4: Build, sign, send
        try:
            nonce = self._get_nonce()
            tx = {
                'to': pair,
                'data': bytes.fromhex(skim_data[2:]),
                'nonce': nonce,
                'gas': min(gas_estimate + 10000, 150000),
                'chainId': 8453,
                **gas_params,
            }
            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            self._increment_nonce()
            tx_hex = tx_hash.hex()
            log.info(f"SKIM TX SENT: {tx_hex} for {pair_address}")
        except Exception as e:
            log.error(f"TX failed {pair_address[:16]}...: {str(e)[:100]}")
            self._log_exec(pair_address, None, "TX_FAILED", 0)
            self._send_telegram(f"TX FAILED: {pair_address[:16]}... — {str(e)[:80]}")
            return None

        # Step 5: Wait for receipt and check balance AFTER
        try:
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=15)
            bal_after = self.w3.eth.get_balance(wallet)
            received = bal_after - bal_before + gas_cost_wei  # Add back gas to get gross received
            received_eth = float(Web3.from_wei(max(received, 0), 'ether'))

            status = "SUCCESS" if receipt['status'] == 1 else "REVERTED"
            if receipt['status'] == 1 and received <= 0:
                status = "EMPTY"

            log.info(f"SKIM {status}: {tx_hex} received={received_eth:.6f} ETH")
            self._log_exec(pair_address, tx_hex, status, received_eth)
            self._send_telegram(f"SKIM {status}: {pair_address[:16]}... received={received_eth:.6f} ETH tx={tx_hex[:16]}...")

            # IPC report to TIAMAT
            try:
                from agent_ipc import AgentIPC
                AgentIPC.send("block_watcher", "REPORT", {
                    "metric": "skim_executed",
                    "value": received_eth,
                    "pair": pair_address,
                    "tx": tx_hex,
                    "status": status,
                })
            except Exception:
                pass

            return tx_hex if status == "SUCCESS" and received > 0 else None

        except Exception as e:
            log.error(f"Receipt wait failed: {str(e)[:100]}")
            self._log_exec(pair_address, tx_hex, "RECEIPT_TIMEOUT", 0)
            self._send_telegram(f"SKIM SENT but receipt timeout: {tx_hex[:16]}...")
            return tx_hex

    # ==========================================
    # LOGGING AND ALERTS
    # ==========================================

    def _log_exec(self, address, tx_hash, result, received_eth):
        entry = json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": "block_watcher",
            "action": "skim",
            "address": address,
            "tx_hash": tx_hash,
            "result": result,
            "received_eth": received_eth,
        })
        try:
            with open(EXEC_LOG, 'a') as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.write(entry + '\n')
                fcntl.flock(f, fcntl.LOCK_UN)
        except Exception:
            pass

    def _send_telegram(self, message):
        try:
            import urllib.parse
            import urllib.request
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if token and chat_id:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                data = urllib.parse.urlencode({
                    "chat_id": chat_id,
                    "text": f"⚡ {message}",
                }).encode("utf-8")
                urllib.request.urlopen(url, data=data, timeout=5)
        except Exception:
            pass

    # ==========================================
    # MAIN WEBSOCKET LOOP
    # ==========================================

    async def _ws_loop(self):
        """Subscribe to newHeads, react to each block"""
        while self.running:
            ws_url = WS_ENDPOINTS[self.ws_index]
            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                    # Subscribe
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": 1,
                        "method": "eth_subscribe",
                        "params": ["newHeads"]
                    }))
                    sub_resp = await ws.recv()
                    sub_data = json.loads(sub_resp)
                    if "result" in sub_data:
                        log.info(f"Subscribed to blocks via {ws_url} (sub_id: {sub_data['result']})")
                    else:
                        log.warning(f"Subscription response: {sub_resp[:200]}")

                    self.reload_watched_pairs()
                    self._refresh_nonce()

                    # IPC heartbeat on connect
                    try:
                        from agent_ipc import AgentIPC
                        AgentIPC.heartbeat("block_watcher", ws=ws_url, pairs=len(self.watched_pairs))
                    except Exception:
                        pass

                    while self.running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=30)
                            data = json.loads(msg)

                            if "params" not in data:
                                continue

                            block_num = int(data["params"]["result"]["number"], 16)
                            if block_num <= self.last_block:
                                continue
                            self.last_block = block_num

                            # Refresh state every 100 blocks (~200 seconds)
                            if block_num % 100 == 0:
                                self.reload_watched_pairs()
                                self._refresh_nonce()
                                log.info(f"Block {block_num} | Watching {len(self.watched_pairs)} pairs")

                                # IPC heartbeat every 100 blocks
                                try:
                                    from agent_ipc import AgentIPC
                                    AgentIPC.heartbeat("block_watcher", cycles=block_num, pairs=len(self.watched_pairs))
                                except Exception:
                                    pass

                            # REACT: check all watched pairs
                            if not self.watched_pairs:
                                continue

                            start = time.time()
                            for pair_addr in self.watched_pairs:
                                has_excess, ex0, ex1 = self.check_pair_excess(pair_addr)
                                if has_excess:
                                    elapsed = time.time() - start
                                    log.info(f"Block {block_num}: EXCESS at {pair_addr[:16]}... (detected in {elapsed*1000:.0f}ms)")
                                    # Use multi-chain executor (Base = 8453) if available
                                    if self.multi_exec:
                                        self.multi_exec.execute_skim(8453, pair_addr)
                                    else:
                                        self.execute_skim(pair_addr)

                            elapsed = time.time() - start
                            if elapsed > 1.5:
                                log.warning(f"Block scan took {elapsed:.2f}s — too slow, reduce watched pairs")

                        except asyncio.TimeoutError:
                            await ws.ping()

            except Exception as e:
                log.error(f"WS error: {str(e)[:150]}")
                self._rotate_ws()
                await asyncio.sleep(5)

    # ==========================================
    # THREAD ENTRY POINTS
    # ==========================================

    def start_thread(self):
        """Start as background thread inside continuous_scanner"""
        self.running = True
        thread = threading.Thread(target=self._run_async, daemon=True, name="block_watcher")
        thread.start()
        log.info("Block watcher thread started")
        return thread

    def _run_async(self):
        """Run the async loop in a new event loop for this thread"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._ws_loop())

    def stop(self):
        self.running = False

    def run_standalone(self):
        """Run as standalone process (for testing)"""
        self.running = True
        asyncio.run(self._ws_loop())


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv('/root/.env')
    watcher = BlockWatcher()
    watcher.run_standalone()
