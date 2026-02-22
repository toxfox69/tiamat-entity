#!/usr/bin/env python3
"""Quick scan of TIAMAT's wallet on Base"""
from base_scanner import BaseScanner
import json

scanner = BaseScanner()

# TIAMAT's wallet from x402 payment config
TIAMAT_WALLET = "0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE"

print("=== TIAMAT WALLET SCAN ===")
print(f"Chain: Base (8453)")
print(f"RPC: {scanner.rpc}")
print()

result = scanner.scan_wallet(TIAMAT_WALLET)
print(f"ETH Balance: {result['eth']} ETH")
print(f"Tokens found: {len(result['tokens'])}")
for t in result["tokens"]:
    print(f"  {t['name']}: {t['balance']} {t['symbol']}")

print()
print("=== PENDING TX CHECK ===")
pending = scanner.check_pending_txs(TIAMAT_WALLET)
print(f"Confirmed nonce: {pending['confirmed_nonce']}")
print(f"Pending nonce: {pending['pending_nonce']}")
print(f"Stuck txs: {pending['stuck_txs']}")

print()
print("=== RECENT TRANSFERS (last 10k blocks) ===")
transfers = scanner.scan_recent_transfers(TIAMAT_WALLET)
if isinstance(transfers, list):
    if transfers:
        for t in transfers:
            sym = t.get("symbol", "???")
            bal = t.get("current_balance", "?")
            print(f"  {sym}: balance={bal} | token={t['token']}")
    else:
        print("  No recent incoming transfers found")
else:
    print(f"  Error: {transfers.get('error', 'unknown')}")

print()
print("=== ARB SCAN ===")
opps = scanner.scan_arb_opportunities()
if opps:
    for o in opps:
        flag = "PROFITABLE" if o["profitable_after_gas"] else "  "
        print(f"{flag} {o['pair']} spread: {o['spread_pct']}%")
else:
    print("No significant spreads found right now")

print()
print("=== RAW WALLET DATA ===")
print(json.dumps(result, indent=2, default=str))
