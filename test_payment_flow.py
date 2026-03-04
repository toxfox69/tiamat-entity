#!/usr/bin/env python3
"""
TIAMAT Payment Flow Test
========================
Produces real on-chain proof that the payment system works.

Modes:
  python3 test_payment_flow.py            # Scan for real historical USDC tx, verify it
  python3 test_payment_flow.py --send     # Send 0.01 USDC (needs PRIVATE_KEY env), verify
  python3 test_payment_flow.py --tx 0x…  # Verify a specific tx hash

Output always ends with one of:
  Payment verified: 0x<tx_hash>
  Payment failed: <reason>
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse

# ── Constants ──────────────────────────────────────────────────────────────
TIAMAT_WALLET  = "0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE"
USDC_CONTRACT  = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_RPC       = "https://mainnet.base.org"
BLOCKSCOUT_API = "https://base.blockscout.com/api/v2"
CHAIN_ID       = 8453
USDC_DECIMALS  = 6
TEST_AMOUNT    = 0.01
PROOF_FILE     = "/root/.automaton/payment_flow_proof.json"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# ── Helpers ─────────────────────────────────────────────────────────────
def ts() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def rpc_call(method: str, params: list) -> dict:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        BASE_RPC, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "TIAMAT/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def blockscout_get(path: str, params: dict = None) -> dict:
    url = BLOCKSCOUT_API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "TIAMAT/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def usdc_balance_raw(address: str) -> int:
    """Call balanceOf via eth_call — no web3 needed."""
    # keccak256("balanceOf(address)")[:4] = 0x70a08231
    padded = address.lower().replace("0x", "").zfill(64)
    data = "0x70a08231" + padded
    resp = rpc_call("eth_call", [{"to": USDC_CONTRACT, "data": data}, "latest"])
    raw = resp.get("result", "0x0")
    return int(raw, 16)

def usdc_balance(address: str) -> float:
    return usdc_balance_raw(address) / (10 ** USDC_DECIMALS)

def eth_balance(address: str) -> float:
    resp = rpc_call("eth_getBalance", [address, "latest"])
    raw = int(resp.get("result", "0x0"), 16)
    return raw / 1e18

# ── Core: fetch & verify a tx receipt ──────────────────────────────────
def verify_tx(tx_hash: str, recipient: str = TIAMAT_WALLET) -> dict:
    """
    Parse a tx receipt for a USDC transfer to `recipient`.
    Returns {"valid": bool, "amount_usdc": float, "sender": str, "reason": str, "block": int}
    """
    resp = rpc_call("eth_getTransactionReceipt", [tx_hash])
    if "error" in resp:
        return {"valid": False, "reason": f"RPC error: {resp['error'].get('message')}"}
    receipt = resp.get("result")
    if not receipt:
        return {"valid": False, "reason": "Transaction not found or pending"}
    if receipt.get("status", "0x0") != "0x1":
        return {"valid": False, "reason": "Transaction reverted on-chain"}

    recipient_stripped = recipient.lower().replace("0x", "").lstrip("0") or "0"
    usdc_lower = USDC_CONTRACT.lower()
    total = 0.0
    sender = ""

    for log in receipt.get("logs", []):
        if log.get("address", "").lower() != usdc_lower:
            continue
        topics = log.get("topics", [])
        if len(topics) < 3 or topics[0].lower() != TRANSFER_TOPIC.lower():
            continue
        log_to = topics[2].lower().replace("0x", "").lstrip("0") or "0"
        if log_to != recipient_stripped:
            continue
        total += int(log.get("data", "0x0"), 16) / (10 ** USDC_DECIMALS)
        sender = "0x" + topics[1].lower().replace("0x", "")[-40:]

    if total == 0.0:
        return {"valid": False, "reason": f"No USDC transfer to {recipient} in this tx"}

    return {
        "valid": True,
        "amount_usdc": total,
        "sender": sender,
        "block": int(receipt.get("blockNumber", "0x0"), 16),
        "reason": "Payment confirmed on-chain",
    }

# ── Mode A: scan Basescan for recent real incoming USDC txs ─────────────
def find_recent_incoming_tx(limit: int = 20) -> dict | None:
    """
    Query Blockscout for incoming USDC transfers to TIAMAT_WALLET.
    Returns the most recent real external transfer, or None.
    """
    print("  Querying Blockscout for incoming USDC transfers…")
    try:
        data = blockscout_get(
            f"/addresses/{TIAMAT_WALLET}/token-transfers",
            {"type": "ERC-20", "token": USDC_CONTRACT},
        )
    except Exception as e:
        print(f"  Blockscout query failed: {e}")
        return None

    items = data.get("items", [])
    print(f"  Found {len(items)} USDC transfer(s) via Blockscout")

    for item in items:
        to_addr  = item.get("to",   {}).get("hash", "")
        frm_addr = item.get("from", {}).get("hash", "")
        # Only incoming transfers from external addresses
        if to_addr.lower() != TIAMAT_WALLET.lower():
            continue
        if frm_addr.lower() == TIAMAT_WALLET.lower():
            continue
        tx_hash = item.get("transaction_hash", "")
        amount  = int(item.get("total", {}).get("value", "0")) / (10 ** USDC_DECIMALS)
        block   = item.get("block_number", 0)
        ts_str  = item.get("timestamp", "")
        print(f"  Found: {tx_hash[:20]}…  ${amount:.6f} USDC from {frm_addr[:14]}…  block {block}  {ts_str[:19]}")
        return {"tx_hash": tx_hash, "amount_usdc": amount, "sender": frm_addr, "block": block}

    print("  No incoming external USDC transfers found")
    return None

# ── Mode B: actually send USDC ───────────────────────────────────────────
def send_usdc(private_key: str, to: str, amount_usdc: float) -> str:
    """Send USDC via web3. Returns tx hash."""
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(BASE_RPC))
    if not w3.is_connected():
        raise RuntimeError("Cannot connect to Base mainnet")

    USDC_ABI = [
        {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
         "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
        {"inputs": [{"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}],
         "name": "transfer", "outputs": [{"name": "", "type": "bool"}],
         "stateMutability": "nonpayable", "type": "function"},
    ]

    account    = w3.eth.account.from_key(private_key)
    sender     = account.address
    amount_raw = int(amount_usdc * (10 ** USDC_DECIMALS))

    print(f"  Sender:    {sender}")
    print(f"  Recipient: {to}")
    print(f"  Amount:    {amount_usdc} USDC  ({amount_raw} units)")

    usdc  = w3.eth.contract(address=Web3.to_checksum_address(USDC_CONTRACT), abi=USDC_ABI)
    nonce = w3.eth.get_transaction_count(sender)
    gas_price = w3.eth.gas_price
    print(f"  Gas price: {w3.from_wei(gas_price, 'gwei'):.2f} gwei  nonce={nonce}")

    tx = usdc.functions.transfer(
        Web3.to_checksum_address(to), amount_raw
    ).build_transaction({
        "from": sender, "nonce": nonce,
        "gas": 80_000, "gasPrice": gas_price, "chainId": CHAIN_ID,
    })
    signed  = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    hex_hash = tx_hash.hex()
    if not hex_hash.startswith("0x"):
        hex_hash = "0x" + hex_hash

    print(f"  TX submitted: {hex_hash}")
    print("  Waiting for confirmation (up to 90s)…")

    for attempt in range(18):
        time.sleep(5)
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt:
                status = receipt.get("status", 0)
                print(f"  Confirmed — block {receipt['blockNumber']}  status={'✓' if status == 1 else '✗'}")
                return hex_hash
        except Exception:
            pass
        if attempt % 3 == 2:
            print(f"  …{(attempt+1)*5}s")

    print("  Not confirmed in 90s — may still be pending")
    return hex_hash

# ── Main ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="TIAMAT Payment Flow Test")
    parser.add_argument("--send",   action="store_true", help="Actually send 0.01 USDC (needs PRIVATE_KEY env)")
    parser.add_argument("--tx",     metavar="HASH",      help="Verify a specific tx hash directly")
    parser.add_argument("--amount", type=float, default=TEST_AMOUNT, help="USDC amount (default 0.01)")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  TIAMAT PAYMENT FLOW TEST")
    print(f"  {ts()}")
    print("=" * 60)
    print(f"  Wallet:  {TIAMAT_WALLET}")
    print(f"  Chain:   Base mainnet (chain_id={CHAIN_ID})")
    print(f"  USDC:    {USDC_CONTRACT}")

    proof = {
        "test_run_at": ts(),
        "wallet":       TIAMAT_WALLET,
        "chain":        "Base mainnet",
        "chain_id":     CHAIN_ID,
        "usdc_contract": USDC_CONTRACT,
        "amount_usdc":  args.amount,
    }

    # ── Balance BEFORE ──────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  BALANCE CHECK (before)")
    print(f"{'─'*60}")
    try:
        bal_before = usdc_balance(TIAMAT_WALLET)
        eth_bal    = eth_balance(TIAMAT_WALLET)
        print(f"  USDC:  {bal_before:.6f} USDC")
        print(f"  ETH:   {eth_bal:.8f} ETH  (gas)")
        proof["balance_before_usdc"] = bal_before
        proof["eth_balance"]         = eth_bal
    except Exception as e:
        final = f"Payment failed: cannot query on-chain balance — {e}"
        print(f"\n{final}")
        proof["result"] = final
        _write_proof(proof)
        return

    # ── Determine tx hash to verify ─────────────────────────────────────
    tx_hash     = None
    scan_result = None

    if args.tx:
        # User supplied a hash directly
        tx_hash = args.tx.strip()
        if not re.match(r'^0x[0-9a-fA-F]{64}$', tx_hash):
            final = f"Payment failed: invalid tx hash format — {tx_hash}"
            print(f"\n{final}")
            proof["result"] = final
            _write_proof(proof)
            return
        print(f"\n{'─'*60}")
        print("  USER-PROVIDED TX HASH")
        print(f"{'─'*60}")
        print(f"  TX: {tx_hash}")
        proof["mode"] = "verify_provided_tx"

    elif args.send:
        # Send USDC live
        print(f"\n{'─'*60}")
        print("  SENDING 0.01 USDC ON-CHAIN")
        print(f"{'─'*60}")
        private_key = (
            os.getenv("PRIVATE_KEY") or
            os.getenv("WALLET_PRIVATE_KEY") or
            os.getenv("DX_TERMINAL_PRIVATE_KEY")
        )
        if not private_key:
            final = "Payment failed: no PRIVATE_KEY / WALLET_PRIVATE_KEY / DX_TERMINAL_PRIVATE_KEY env var found"
            print(f"\n{final}")
            proof["result"] = final
            _write_proof(proof)
            return
        try:
            tx_hash = send_usdc(private_key, TIAMAT_WALLET, args.amount)
            proof["mode"]    = "live_send"
            proof["tx_hash"] = tx_hash
        except Exception as e:
            final = f"Payment failed: send error — {e}"
            print(f"\n{final}")
            proof["result"] = final
            _write_proof(proof)
            return

    else:
        # Default: scan Basescan for the most recent real incoming tx
        print(f"\n{'─'*60}")
        print("  SCANNING FOR REAL HISTORICAL PAYMENTS (Basescan)")
        print(f"{'─'*60}")
        scan_result = find_recent_incoming_tx(limit=50)
        if scan_result:
            tx_hash = scan_result["tx_hash"]
            proof["mode"] = "scan_historical"
            print(f"  Using tx: {tx_hash}")
        else:
            # No Basescan result — try on-chain logs directly (last 2000 blocks)
            print(f"\n  Falling back to direct on-chain eth_getLogs scan…")
            tx_hash = _scan_logs_direct()
            if tx_hash:
                proof["mode"] = "scan_logs_direct"
                print(f"  Found via logs: {tx_hash}")
            else:
                final = ("Payment failed: no real incoming USDC transactions found on-chain. "
                         "Run with --send to create a live test transaction, "
                         "or --tx 0x<hash> to verify a specific one.")
                print(f"\n{final}")
                proof["result"] = final
                _write_proof(proof)
                return

    # ── On-chain verification ────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  ON-CHAIN VERIFICATION")
    print(f"{'─'*60}")
    print(f"  TX:      {tx_hash}")
    print(f"  Network: Base mainnet via {BASE_RPC}")

    try:
        result = verify_tx(tx_hash, TIAMAT_WALLET)
    except Exception as e:
        final = f"Payment failed: RPC verification error — {e}"
        print(f"\n{final}")
        proof["result"] = final
        _write_proof(proof)
        return

    proof["verify_result"] = result
    proof["tx_hash"]        = tx_hash
    proof["basescan_url"]   = f"https://basescan.org/tx/{tx_hash}"

    if result["valid"]:
        print(f"  ✓  Status:    CONFIRMED")
        print(f"  ✓  Amount:    ${result['amount_usdc']:.6f} USDC")
        print(f"  ✓  Sender:    {result['sender']}")
        print(f"  ✓  Block:     {result.get('block', 'N/A')}")
        print(f"  ✓  Basescan:  https://basescan.org/tx/{tx_hash}")
    else:
        print(f"  ✗  Verification failed: {result['reason']}")

    # ── Balance AFTER (only meaningful for --send) ────────────────────
    if args.send:
        try:
            bal_after = usdc_balance(TIAMAT_WALLET)
            delta = bal_after - bal_before
            print(f"\n{'─'*60}")
            print("  BALANCE CHECK (after)")
            print(f"{'─'*60}")
            print(f"  Before: {bal_before:.6f} USDC")
            print(f"  After:  {bal_after:.6f} USDC")
            print(f"  Delta:  {delta:+.6f} USDC")
            proof["balance_after_usdc"] = bal_after
            proof["balance_delta_usdc"] = delta
        except Exception as e:
            print(f"  (balance-after query failed: {e})")

    # ── Also run through payment_verify module ───────────────────────────
    print(f"\n{'─'*60}")
    print("  MODULE VERIFICATION (payment_verify.py)")
    print(f"{'─'*60}")
    try:
        # src/agent takes priority — has _fetch_tx_amount
        sys.path.insert(0, "/root/entity/src/agent")
        import importlib, payment_verify as pv
        importlib.reload(pv)  # reload in case wrong version was cached
        pv_result = pv._fetch_tx_amount(tx_hash, TIAMAT_WALLET)
        if pv_result["valid"]:
            print(f"  ✓  Module confirmed: ${pv_result['amount_usdc']:.6f} USDC from {pv_result['sender']}")
        else:
            print(f"  ✗  Module: {pv_result['reason']}")
        proof["module_verify"] = pv_result
    except Exception as e:
        print(f"  (module not available: {e})")

    # ── Final proof line ─────────────────────────────────────────────────
    print(f"\n{'='*60}")
    if result["valid"]:
        final = f"Payment verified: {tx_hash}"
    else:
        final = f"Payment failed: {result['reason']}"

    proof["result"] = final
    _write_proof(proof)

    print(f"  {final}")
    print(f"  Amount:    ${result.get('amount_usdc', 0):.6f} USDC")
    print(f"  Sender:    {result.get('sender', 'N/A')}")
    print(f"  Block:     {result.get('block', 'N/A')}")
    print(f"  Basescan:  https://basescan.org/tx/{tx_hash}")
    print(f"  Proof at:  {PROOF_FILE}")
    print(f"{'='*60}\n")


def _scan_logs_direct(blocks_back: int = 2000) -> str | None:
    """
    Fallback: eth_getLogs scan for the last `blocks_back` blocks.
    Returns the most recent incoming USDC tx hash, or None.
    """
    try:
        latest_resp = rpc_call("eth_blockNumber", [])
        latest = int(latest_resp.get("result", "0x0"), 16)
        from_block = hex(max(0, latest - blocks_back))
        # topic[2] = recipient padded to 32 bytes
        recipient_topic = "0x" + TIAMAT_WALLET.lower().replace("0x", "").zfill(64)
        resp = rpc_call("eth_getLogs", [{
            "fromBlock": from_block,
            "toBlock":   "latest",
            "address":   USDC_CONTRACT,
            "topics":    [TRANSFER_TOPIC, None, recipient_topic],
        }])
        logs = resp.get("result", [])
        if logs:
            return logs[-1].get("transactionHash")
    except Exception:
        pass
    return None


def _write_proof(proof: dict):
    os.makedirs(os.path.dirname(PROOF_FILE), exist_ok=True)
    with open(PROOF_FILE, "w") as f:
        json.dump(proof, f, indent=2)
    print(f"\n  Proof saved to: {PROOF_FILE}")


if __name__ == "__main__":
    main()
