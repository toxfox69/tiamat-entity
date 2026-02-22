"""
TIAMAT Continuous Vulnerability Scanner — Background Daemon
Polls new Base chain blocks, runs vulnerability checks on new deployments.
Periodic skim scans on DEX factories.

PID file: /tmp/tiamat_scanner.pid
Log: /root/.automaton/vuln_scan.log
"""
import os
import time
import signal
import logging
import urllib.parse
import urllib.request
from contract_scanner import (
    ContractScanner,
    UNISWAP_V2_FACTORY,
    AERODROME_FACTORY,
)
from opportunity_queue import OpportunityQueue
from auto_executor import executor as auto_exec

PID_FILE = "/run/tiamat/tiamat_scanner.pid"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Reuse vuln_scanner logger (contract_scanner.py already has FileHandler for SCAN_LOG)
log = logging.getLogger("vuln_scanner")

running = True


def shutdown(signum, frame):
    global running
    log.info(f"Received signal {signum}, shutting down...")
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


def main():
    global running

    # Write PID with restrictive permissions
    fd = os.open(PID_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info("=" * 50)
    log.info("CONTINUOUS SCANNER STARTED")
    log.info(f"PID: {os.getpid()}")
    log.info("=" * 50)

    scanner = ContractScanner()
    last_block = scanner.w3.eth.block_number
    cycle = 0

    while running:
        try:
            current_block = scanner.w3.eth.block_number

            if current_block > last_block:
                blocks_to_scan = min(current_block - last_block, 20)  # Cap at 20 blocks per cycle
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
                    log.info(f"Blocks {last_block+1}-{last_block+blocks_to_scan}: {len(new_contracts)} new contracts")
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
                                    eth_val = finding.get("eth_value", 0)
                                    if eth_val < 0.01:
                                        continue

                                    ftype = finding["type"]
                                    faddr = finding["address"]
                                    details = finding.get("details", {})
                                    executed = False

                                    # ── Fast path: try auto-execute immediately ──
                                    if auto_exec.enabled:
                                        if ftype == "unguarded_functions" and details.get("callable_functions"):
                                            executed = auto_exec.try_rescue(faddr, details["callable_functions"], eth_val)
                                        elif ftype == "stuck_trading_fees" and details.get("callable_functions"):
                                            executed = auto_exec.try_rescue(faddr, details["callable_functions"], eth_val)

                                    if executed:
                                        log.info(f"AUTO-EXECUTED: {ftype} at {faddr} for {eth_val:.4f} ETH")
                                        continue  # Don't queue — already handled

                                    # ── Slow path: alert + queue for TIAMAT review ──
                                    if eth_val > 0.01:
                                        msg = (
                                            f"<b>VULN FOUND</b>\n"
                                            f"Type: {ftype}\n"
                                            f"Addr: {faddr}\n"
                                            f"ETH: {eth_val:.4f}"
                                        )
                                        send_telegram(msg)
                                    OpportunityQueue.push({
                                        "source": "scanner",
                                        "type": ftype,
                                        "address": faddr,
                                        "eth_value": eth_val,
                                        "details": details,
                                        "action": finding.get("action", "review"),
                                    })
                            except Exception:
                                pass

                last_block = last_block + blocks_to_scan
                cycle += 1

            # Periodic skim scan every 100 cycles
            if cycle > 0 and cycle % 100 == 0:
                log.info(f"Cycle {cycle}: Periodic skim scan")
                try:
                    pre_count = len(scanner.findings)
                    scanner.scan_pairs_for_skim(UNISWAP_V2_FACTORY, num_pairs=30)
                    time.sleep(15)  # Cool down between factory scans to avoid 429
                    scanner.scan_pairs_for_skim(AERODROME_FACTORY, num_pairs=30)
                    # Auto-execute or queue new skim findings
                    for f in scanner.findings[pre_count:]:
                        if f.get("type") == "skimmable_pair":
                            eth_val = f.get("eth_value", 0)
                            executed = False
                            if auto_exec.enabled and eth_val > 0.01:
                                executed = auto_exec.try_skim(f["address"], eth_val)
                            if executed:
                                log.info(f"AUTO-SKIMMED: {f['address']} for {eth_val:.4f} ETH")
                            else:
                                OpportunityQueue.push({
                                    "source": "skim_scanner",
                                    "type": "skimmable_pair",
                                    "address": f["address"],
                                    "eth_value": eth_val,
                                    "details": f.get("details", {}),
                                    "action": "skim",
                                })
                except Exception as e:
                    log.error(f"Periodic skim scan failed: {e}")

            # Heartbeat every 50 cycles
            if cycle > 0 and cycle % 50 == 0:
                log.info(f"HEARTBEAT: cycle={cycle} block={last_block} findings={len(scanner.findings)}")

        except Exception as e:
            log.error(f"Cycle error: {e}")
            try:
                scanner._reconnect()
            except Exception:
                log.error("Reconnect failed, waiting 30s...")
                time.sleep(30)
                continue

        time.sleep(6)  # Base = 2s blocks, poll every 6s

    # Cleanup
    log.info("Scanner stopped gracefully.")
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
