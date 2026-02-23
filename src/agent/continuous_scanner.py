"""
TIAMAT Continuous Vulnerability Scanner — Multi-Chain Background Daemon
Runs scanner threads for Base, Arbitrum, Optimism, and Ethereum.
Base retains websocket block watcher. Other chains use polling.

PID file: /run/tiamat/tiamat_scanner.pid
Log: /root/.automaton/vuln_scan.log
"""
import os
import json
import time
import signal
import logging
import threading
import urllib.parse
import urllib.request
from contract_scanner import ContractScanner
from chain_config import CHAINS, FUNDED_CHAINS, get_findings_file, get_watched_pairs_file
from opportunity_queue import OpportunityQueue
from agent_ipc import AgentIPC
from auto_executor import AutoExecutor
from block_watcher import BlockWatcher
from multi_chain_executor import MultiChainExecutor

try:
    from etherscan_v2 import enrich_finding as etherscan_enrich
    HAS_ETHERSCAN = True
except ImportError:
    HAS_ETHERSCAN = False

PID_FILE = "/run/tiamat/tiamat_scanner.pid"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Shared Etherscan rate limiter: max 5 calls/sec across all chains
etherscan_semaphore = threading.Semaphore(5)
etherscan_lock = threading.Lock()
_etherscan_calls: list[float] = []

log = logging.getLogger("vuln_scanner")

running = True


def shutdown(signum, frame):
    global running
    log.info(f"Received signal {signum}, shutting down all chain scanners...")
    running = False


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        }).encode("utf-8")
        urllib.request.urlopen(url, data=data, timeout=10)
    except Exception as e:
        log.debug(f"Telegram alert failed: {e}")


def etherscan_rate_limit():
    """Enforce 5 calls/sec across all chains for Etherscan V2."""
    with etherscan_lock:
        now = time.time()
        # Remove calls older than 1 second
        while _etherscan_calls and _etherscan_calls[0] < now - 1.0:
            _etherscan_calls.pop(0)
        if len(_etherscan_calls) >= 5:
            sleep_time = 1.0 - (now - _etherscan_calls[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
        _etherscan_calls.append(time.time())


def update_watched_pairs(pair_address, chain_id=8453):
    """Add a pair to the chain-specific watch list."""
    watch_file = get_watched_pairs_file(chain_id)
    try:
        with open(watch_file) as f:
            pairs = json.load(f)
    except Exception:
        pairs = []

    if pair_address not in pairs:
        pairs.append(pair_address)
        if len(pairs) > 50:
            pairs = pairs[-50:]
        with open(watch_file, 'w') as f:
            json.dump(pairs, f)


def process_finding(finding, chain_id, chain_config, auto_exec, multi_exec=None):
    """Process a finding: enrich, auto-execute if possible, alert, queue."""
    eth_val = finding.get("eth_value", 0)
    if eth_val < chain_config.get("min_eth_value", 0.01):
        return

    chain_name = chain_config["name"]
    ftype = finding["type"]
    faddr = finding["address"]
    details = finding.get("details", {})

    # ── Etherscan V2 enrichment (rate-limited) ──
    enrichment = None
    if HAS_ETHERSCAN:
        try:
            etherscan_rate_limit()
            enrichment = etherscan_enrich(faddr, chain_id)
            finding["etherscan"] = enrichment

            if enrichment.get("recommendation") == "skip":
                reason = enrichment.get("skip_reason", "access control detected")
                log.info(f"[{chain_name}] ETHERSCAN SKIP: {ftype} at {faddr} — {reason}")
                return
            log.info(f"[{chain_name}] ETHERSCAN: {faddr} verified={enrichment.get('source_verified')} "
                     f"rec={enrichment.get('recommendation')} conf={enrichment.get('confidence')}")
        except Exception as e:
            log.debug(f"[{chain_name}] Etherscan enrichment failed: {e}")

    executed = False

    # ── Fast path: multi-chain executor (preferred) ──
    etherscan_ok = (not enrichment or
                    enrichment.get("recommendation") in ("execute", "review"))

    if multi_exec and etherscan_ok:
        can, reason = multi_exec.can_execute(chain_id)
        if can:
            if ftype == "skimmable_pair":
                tx = multi_exec.execute_skim(chain_id, faddr)
                executed = tx is not None
            elif ftype in ("unguarded_functions", "stuck_trading_fees") and details.get("callable_functions"):
                for func_sel in details["callable_functions"]:
                    tx = multi_exec.execute_rescue(chain_id, faddr, func_sel)
                    if tx:
                        executed = True
                        break
        elif not can and chain_config.get("auto_execute", False):
            log.info(f"[{chain_name}] Cannot auto-execute: {reason}")

    # ── Fallback: legacy Base-only executor ──
    if not executed:
        can_auto = (chain_config.get("auto_execute", False) and
                    chain_id in FUNDED_CHAINS and
                    auto_exec and auto_exec.enabled)
        if can_auto and etherscan_ok:
            if ftype == "unguarded_functions" and details.get("callable_functions"):
                executed = auto_exec.try_rescue(faddr, details["callable_functions"], eth_val)
            elif ftype == "stuck_trading_fees" and details.get("callable_functions"):
                executed = auto_exec.try_rescue(faddr, details["callable_functions"], eth_val)

    if executed:
        log.info(f"[{chain_name}] AUTO-EXECUTED: {ftype} at {faddr} for {eth_val:.4f} ETH")
        return

    # ── Slow path: alert + queue ──
    enrichment_note = ""
    if enrichment and enrichment.get("source_verified"):
        risk = enrichment.get("source_analysis", {}).get("risk_level", "?")
        enrichment_note = f"\nSource: VERIFIED (risk: {risk})"
    elif enrichment:
        enrichment_note = "\nSource: unverified"

    # Chain-specific alert formatting
    review_note = ""
    if not chain_config.get("auto_execute", False):
        review_note = f"\n⚠️ REVIEW REQUIRED — {chain_name}, manual execution only"
    elif chain_id not in FUNDED_CHAINS:
        review_note = f"\n⚠️ UNFUNDED — {chain_name} wallet has no ETH for gas"

    if eth_val > chain_config.get("min_eth_value", 0.01):
        send_telegram(
            f"<b>🔗 FINDING: [{chain_name}] {ftype}</b>\n"
            f"Addr: {faddr}\n"
            f"ETH: {eth_val:.4f}"
            f"{enrichment_note}"
            f"{review_note}"
        )

    # IPC inbox with chain info
    AgentIPC.send("scanner", "SKIM", {
        "addr": faddr,
        "eth": eth_val,
        "type": ftype,
        "chain": chain_id,
        "chain_name": chain_name,
        "action": finding.get("action", "review"),
        "etherscan": enrichment,
    })
    # Legacy queue
    OpportunityQueue.push({
        "source": f"scanner_{chain_name.lower()}",
        "type": ftype,
        "address": faddr,
        "eth_value": eth_val,
        "chain_id": chain_id,
        "chain_name": chain_name,
        "details": details,
        "action": finding.get("action", "review"),
        "etherscan": enrichment,
    })
    # Block watcher (Base only for now)
    if chain_id == 8453 and ftype in ("skimmable_pair", "stuck_trading_fees"):
        update_watched_pairs(faddr, chain_id)


def scan_chain_loop(chain_id, chain_config, auto_exec, multi_exec=None):
    """Main scanning loop for a single chain. Runs in its own thread."""
    chain_name = chain_config["name"]
    poll_interval = max(chain_config["block_time"] * 3, 6)

    log.info(f"[{chain_name}] Scanner thread starting (chain {chain_id}, poll every {poll_interval:.1f}s)")

    try:
        scanner = ContractScanner.from_chain_config(chain_id)
    except Exception as e:
        log.error(f"[{chain_name}] Failed to connect: {e}")
        return

    last_block = scanner.w3.eth.block_number
    cycle = 0
    factories = chain_config.get("factories", {})

    log.info(f"[{chain_name}] Connected at block {last_block}, {len(factories)} factories configured")

    while running:
        try:
            current_block = scanner.w3.eth.block_number

            if current_block > last_block:
                blocks_to_scan = min(current_block - last_block, 20)
                new_contracts = []

                for block_num in range(last_block + 1, last_block + 1 + blocks_to_scan):
                    try:
                        block = scanner.w3.eth.get_block(block_num, full_transactions=True)
                        for tx in block.transactions:
                            if tx.get("to") is None:
                                receipt = scanner.w3.eth.get_transaction_receipt(tx["hash"])
                                if receipt and receipt.get("contractAddress"):
                                    new_contracts.append(receipt["contractAddress"])
                    except Exception:
                        continue

                if new_contracts:
                    log.info(f"[{chain_name}] Blocks {last_block+1}-{last_block+blocks_to_scan}: "
                             f"{len(new_contracts)} new contracts")
                    for addr in new_contracts:
                        for check_fn in [
                            scanner.check_stuck_eth,
                            scanner.check_proxy_dead,
                            scanner.check_unguarded_functions,
                            scanner.check_uninitialized_proxy,
                            scanner.check_stuck_trading_fees,
                        ]:
                            try:
                                finding = check_fn(addr)
                                if finding:
                                    process_finding(finding, chain_id, chain_config, auto_exec, multi_exec)
                            except Exception:
                                pass

                last_block = last_block + blocks_to_scan
                cycle += 1

            # Periodic skim scan every 100 cycles
            if cycle > 0 and cycle % 100 == 0:
                log.info(f"[{chain_name}] Cycle {cycle}: Periodic skim scan")
                try:
                    for dex_name, factory_addr in factories.items():
                        pre_count = len(scanner.findings)
                        scanner.scan_pairs_for_skim(factory_addr, num_pairs=30)

                        for f in scanner.findings[pre_count:]:
                            if f.get("type") == "skimmable_pair":
                                eth_val = f.get("eth_value", 0)
                                executed = False

                                # Try multi-chain executor first
                                if multi_exec and eth_val > chain_config.get("min_eth_value", 0.01):
                                    can, _ = multi_exec.can_execute(chain_id)
                                    if can:
                                        tx = multi_exec.execute_skim(chain_id, f["address"])
                                        executed = tx is not None

                                # Fallback to legacy Base-only executor
                                if not executed:
                                    can_auto = (chain_config.get("auto_execute", False) and
                                                chain_id in FUNDED_CHAINS and
                                                auto_exec and auto_exec.enabled)
                                    if can_auto and eth_val > chain_config.get("min_eth_value", 0.01):
                                        executed = auto_exec.try_skim(f["address"], eth_val)

                                if executed:
                                    log.info(f"[{chain_name}] AUTO-SKIMMED: {f['address']} for {eth_val:.4f} ETH")
                                else:
                                    AgentIPC.send(f"skim_{chain_name.lower()}", "SKIM", {
                                        "addr": f["address"],
                                        "eth": eth_val,
                                        "chain": chain_id,
                                        "chain_name": chain_name,
                                    })
                                    OpportunityQueue.push({
                                        "source": f"skim_{chain_name.lower()}",
                                        "type": "skimmable_pair",
                                        "address": f["address"],
                                        "eth_value": eth_val,
                                        "chain_id": chain_id,
                                        "chain_name": chain_name,
                                        "details": f.get("details", {}),
                                        "action": "skim",
                                    })
                                    if chain_id == 8453:
                                        update_watched_pairs(f["address"], chain_id)

                        time.sleep(15)  # Cool down between factory scans
                except Exception as e:
                    log.error(f"[{chain_name}] Periodic skim scan failed: {e}")

            # Heartbeat every 50 cycles
            if cycle > 0 and cycle % 50 == 0:
                log.info(f"[{chain_name}] HEARTBEAT: cycle={cycle} block={last_block} "
                         f"findings={len(scanner.findings)}")
                AgentIPC.heartbeat(f"scanner_{chain_name.lower()}", cycles=cycle,
                                   block=last_block, findings=len(scanner.findings))

        except Exception as e:
            log.error(f"[{chain_name}] Cycle error: {e}")
            try:
                scanner._reconnect()
            except Exception:
                log.error(f"[{chain_name}] Reconnect failed, waiting 30s...")
                time.sleep(30)
                continue

        time.sleep(poll_interval)

    log.info(f"[{chain_name}] Scanner thread stopped.")


def main():
    global running

    # Write PID with restrictive permissions
    fd = os.open(PID_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info("=" * 60)
    log.info("MULTI-CHAIN CONTINUOUS SCANNER STARTED")
    log.info(f"PID: {os.getpid()}")
    log.info(f"Chains: {', '.join(c['name'] for c in CHAINS.values())}")
    log.info(f"Funded chains: {FUNDED_CHAINS}")
    log.info(f"Etherscan V2: {'ENABLED' if HAS_ETHERSCAN else 'DISABLED'}")
    log.info("=" * 60)

    # Create executors: legacy Base-only + new multi-chain
    auto_exec = AutoExecutor()
    multi_exec = MultiChainExecutor()

    # Start Base block watcher thread (websocket-based reactive scanner)
    try:
        block_watcher = BlockWatcher()
        watcher_thread = block_watcher.start_thread()
        log.info(f"[Base] Block watcher thread started (watching {len(block_watcher.watched_pairs)} pairs)")
    except Exception as e:
        log.warning(f"[Base] Block watcher failed to start: {e}")

    # Start scanner threads for each chain
    threads = {}
    for chain_id, config in CHAINS.items():
        thread = threading.Thread(
            target=scan_chain_loop,
            args=(chain_id, config, auto_exec, multi_exec),
            daemon=True,
            name=f"scanner_{config['name'].lower()}",
        )
        thread.start()
        threads[chain_id] = thread
        log.info(f"Started scanner thread for {config['name']} (chain {chain_id})")
        time.sleep(2)  # Stagger thread starts to avoid RPC thundering herd

    # Main thread: just wait for shutdown signal
    while running:
        time.sleep(5)

        # Check thread health
        for chain_id, thread in list(threads.items()):
            if not thread.is_alive():
                config = CHAINS[chain_id]
                log.warning(f"[{config['name']}] Scanner thread died, restarting...")
                new_thread = threading.Thread(
                    target=scan_chain_loop,
                    args=(chain_id, config, auto_exec, multi_exec),
                    daemon=True,
                    name=f"scanner_{config['name'].lower()}",
                )
                new_thread.start()
                threads[chain_id] = new_thread

    # Cleanup
    log.info("Multi-chain scanner stopped gracefully.")
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
