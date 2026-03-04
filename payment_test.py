#!/usr/bin/env python3
"""
TIAMAT Payment System Test
===========================
Tests the complete x402 USDC payment flow on Base mainnet.

Modes:
  python3 payment_test.py                      # Balance check + /pay endpoint probe only
  python3 payment_test.py --tx <0xHASH>        # Verify existing tx end-to-end
  python3 payment_test.py --send               # Actually send 0.01 USDC (needs PRIVATE_KEY env)
  python3 payment_test.py --send --amount 0.01 # Send specific amount

Requirements: pip install web3 requests  (both already on the server)
"""

import argparse
import datetime
import json
import os
import re
import sys
import time

import requests

# ── Constants ──────────────────────────────────────────────────────────────
WALLET            = "0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE"
USDC_CONTRACT     = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_RPC          = "https://mainnet.base.org"
BASE_API          = "https://tiamat.live"
CHAIN_ID          = 8453
USDC_DECIMALS     = 6
TEST_AMOUNT_USDC  = 0.01
PROOF_FILE        = "/root/.automaton/payment_test_proof.json"

# Minimal ERC-20 ABI for balanceOf + transfer
USDC_ABI = [
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "to",    "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

# ── Helpers ────────────────────────────────────────────────────────────────
def ts() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def ok(msg: str):
    print(f"  ✓  {msg}")


def fail(msg: str):
    print(f"  ✗  {msg}")


def info(msg: str):
    print(f"     {msg}")


def section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ── Web3 setup ─────────────────────────────────────────────────────────────
def get_w3():
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(BASE_RPC))
    if not w3.is_connected():
        raise RuntimeError("Cannot connect to Base mainnet RPC")
    return w3


def get_usdc_balance(w3, address: str) -> float:
    """Return USDC balance in human units (e.g. 10.01)."""
    from web3 import Web3
    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_CONTRACT),
        abi=USDC_ABI,
    )
    raw = usdc.functions.balanceOf(Web3.to_checksum_address(address)).call()
    return raw / (10 ** USDC_DECIMALS)


def get_eth_balance(w3, address: str) -> float:
    """Return ETH balance (needed for gas)."""
    from web3 import Web3
    raw = w3.eth.get_balance(Web3.to_checksum_address(address))
    return float(w3.from_wei(raw, "ether"))


# ── Step 1: /pay endpoint probe ────────────────────────────────────────────
def test_pay_endpoint(amount: float) -> dict:
    section("STEP 1 — GET /pay?amount=0.01")
    url = f"{BASE_API}/pay?amount={amount}"
    info(f"GET {url}")
    try:
        r = requests.get(url, timeout=10)
        info(f"Status: {r.status_code}  Content-Type: {r.headers.get('Content-Type','')[:40]}")
        info(f"Body length: {len(r.text)} chars")

        checks = {
            "status_200":        r.status_code == 200,
            "has_wallet":        WALLET.lower() in r.text.lower(),
            "has_usdc":          "USDC" in r.text,
            "has_base":          "Base" in r.text or "base" in r.text,
            "has_amount":        str(amount) in r.text,
        }
        for k, v in checks.items():
            (ok if v else fail)(k)

        return {"url": url, "status": r.status_code, "checks": checks}
    except Exception as e:
        fail(f"Request failed: {e}")
        return {"url": url, "error": str(e)}


# ── Step 2: on-chain balance check ─────────────────────────────────────────
def check_balance(w3, label: str) -> float:
    section(f"STEP 2 — Wallet balance ({label})")
    usdc = get_usdc_balance(w3, WALLET)
    eth  = get_eth_balance(w3, WALLET)
    info(f"Wallet:  {WALLET}")
    info(f"USDC:    {usdc:.6f} USDC")
    info(f"ETH:     {eth:.8f} ETH  (gas)")
    ok(f"Balance retrieved from Base mainnet ({label})")
    return usdc


# ── Step 3: actually send USDC ─────────────────────────────────────────────
def send_usdc(w3, private_key: str, to: str, amount_usdc: float) -> str:
    section("STEP 3 — Send 0.01 USDC on Base mainnet")
    from web3 import Web3

    account   = w3.eth.account.from_key(private_key)
    sender    = account.address
    amount_raw = int(amount_usdc * (10 ** USDC_DECIMALS))

    info(f"Sender:    {sender}")
    info(f"Recipient: {to}")
    info(f"Amount:    {amount_usdc} USDC  ({amount_raw} raw)")

    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_CONTRACT),
        abi=USDC_ABI,
    )

    nonce     = w3.eth.get_transaction_count(sender)
    gas_price = w3.eth.gas_price
    info(f"Nonce:     {nonce}")
    info(f"Gas price: {w3.from_wei(gas_price, 'gwei'):.2f} gwei")

    tx = usdc.functions.transfer(
        Web3.to_checksum_address(to),
        amount_raw,
    ).build_transaction({
        "from":     sender,
        "nonce":    nonce,
        "gas":      80_000,
        "gasPrice": gas_price,
        "chainId":  CHAIN_ID,
    })

    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    hex_hash = tx_hash.hex()
    if not hex_hash.startswith("0x"):
        hex_hash = "0x" + hex_hash

    info(f"TX submitted: {hex_hash}")
    info("Waiting for confirmation (up to 60s)…")

    receipt = None
    for attempt in range(12):
        time.sleep(5)
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt:
                break
        except Exception:
            pass
        info(f"  …{(attempt+1)*5}s")

    if receipt and receipt.get("status") == 1:
        ok(f"Transaction confirmed! Block: {receipt['blockNumber']}")
        ok(f"TX hash: {hex_hash}")
    elif receipt:
        fail(f"Transaction REVERTED. Hash: {hex_hash}")
    else:
        fail("Transaction not confirmed within 60s — may still be pending")
        info(f"Check: https://basescan.org/tx/{hex_hash}")

    return hex_hash


# ── Step 4: verify via payment_verify module ───────────────────────────────
def verify_via_module(tx_hash: str, amount: float) -> dict:
    section("STEP 4 — Verify via payment_verify.py module")
    sys.path.insert(0, "/root/entity/src/agent")
    sys.path.insert(0, "/root/entity")
    try:
        import payment_verify as pv
        info(f"Module loaded: {pv.__file__}")
        result = pv._fetch_tx_amount(tx_hash, WALLET)
        info(f"Raw result: {result}")
        if result["valid"]:
            ok(f"Transfer confirmed: {result['amount_usdc']:.6f} USDC from {result['sender']}")
        else:
            fail(f"Verification failed: {result['reason']}")
        return result
    except Exception as e:
        fail(f"Module error: {e}")
        return {"valid": False, "reason": str(e)}


# ── Step 5: verify via /verify-payment API endpoint ────────────────────────
def verify_via_api(tx_hash: str) -> dict:
    section("STEP 5 — Verify via POST /verify-payment")
    url = f"{BASE_API}/verify-payment"
    payload = {"tx_hash": tx_hash}
    info(f"POST {url}")
    info(f"Body: {json.dumps(payload)}")
    try:
        r = requests.post(url, json=payload, timeout=15)
        data = r.json()
        info(f"Status: {r.status_code}")
        info(f"Response: {json.dumps(data, indent=2)}")
        if r.status_code == 200 and data.get("success"):
            ok("API verified payment successfully")
        else:
            # Could be "already used" if we verified via module first
            info(f"Note: {data.get('message', 'see response')}")
        return {"status": r.status_code, "data": data}
    except Exception as e:
        fail(f"Request failed: {e}")
        return {"error": str(e)}


# ── Step 6: call a paid API endpoint ──────────────────────────────────────
def test_paid_call(tx_hash: str) -> dict:
    """
    Test that a paid API endpoint accepts X-Payment header.
    NOTE: tx_hash will be consumed if valid. Use a fresh tx for this.
    Uses /summarize as the test endpoint.
    """
    section("STEP 6 — Call paid endpoint with X-Payment header")
    url = f"{BASE_API}/summarize"
    headers = {
        "Content-Type":  "application/json",
        "X-Payment":     tx_hash,
    }
    body = {"text": "TIAMAT is an autonomous AI agent that earns crypto payments for API calls."}
    info(f"POST {url}")
    info(f"X-Payment: {tx_hash}")
    try:
        r = requests.post(url, json=body, headers=headers, timeout=20)
        info(f"Status: {r.status_code}")
        if r.status_code == 200:
            ok("Paid endpoint accepted payment and returned 200")
            data = r.json()
            if "summary" in data:
                info(f"Summary: {data['summary'][:100]}…")
        elif r.status_code == 402:
            fail("Got 402 — payment was NOT accepted")
            info(r.text[:200])
        elif r.status_code == 400:
            info(f"400 response: {r.text[:200]}")
        else:
            info(f"Response: {r.text[:200]}")
        return {"status": r.status_code}
    except Exception as e:
        fail(f"Request failed: {e}")
        return {"error": str(e)}


# ── Write proof document ───────────────────────────────────────────────────
def write_proof(proof: dict):
    section("PROOF DOCUMENT")
    os.makedirs(os.path.dirname(PROOF_FILE), exist_ok=True)
    with open(PROOF_FILE, "w") as f:
        json.dump(proof, f, indent=2)
    ok(f"Proof written to {PROOF_FILE}")
    print(json.dumps(proof, indent=2))


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="TIAMAT Payment System Test")
    parser.add_argument("--tx",     metavar="HASH",  help="Verify an existing tx hash end-to-end")
    parser.add_argument("--send",   action="store_true", help="Actually send 0.01 USDC (needs PRIVATE_KEY env)")
    parser.add_argument("--amount", type=float, default=TEST_AMOUNT_USDC, help="Amount in USDC (default 0.01)")
    parser.add_argument("--paid-call", action="store_true", help="Also test paid API endpoint (consumes tx)")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("  TIAMAT PAYMENT SYSTEM TEST")
    print(f"  {ts()}")
    print("="*60)
    print(f"  Wallet:  {WALLET}")
    print(f"  Chain:   Base mainnet (chain_id={CHAIN_ID})")
    print(f"  USDC:    {USDC_CONTRACT}")

    proof = {
        "test_run_at": ts(),
        "wallet": WALLET,
        "chain": "Base mainnet",
        "chain_id": CHAIN_ID,
        "usdc_contract": USDC_CONTRACT,
        "amount_usdc": args.amount,
        "steps": {},
    }

    # Step 1 — /pay endpoint
    step1 = test_pay_endpoint(args.amount)
    proof["steps"]["pay_endpoint"] = step1

    # Step 2 — balance before
    w3 = get_w3()
    balance_before = check_balance(w3, "before")
    proof["steps"]["balance_before"] = {"usdc": balance_before}

    tx_hash = None

    # Step 3 — optionally send USDC
    if args.send:
        private_key = os.getenv("PRIVATE_KEY") or os.getenv("WALLET_PRIVATE_KEY")
        if not private_key:
            fail("--send requires PRIVATE_KEY or WALLET_PRIVATE_KEY environment variable")
            sys.exit(1)
        tx_hash = send_usdc(w3, private_key, WALLET, args.amount)
        proof["steps"]["send"] = {"tx_hash": tx_hash, "amount_usdc": args.amount}
    elif args.tx:
        tx_hash = args.tx.strip()
        if not re.match(r'^0x[0-9a-fA-F]{64}$', tx_hash):
            fail(f"Invalid tx hash format: {tx_hash}")
            sys.exit(1)
        section(f"STEP 3 — Using provided tx hash")
        ok(f"TX: {tx_hash}")
        proof["steps"]["tx_provided"] = {"tx_hash": tx_hash}
    else:
        section("STEP 3 — No tx hash (probe-only mode)")
        info("Run with --tx 0x<hash> to verify an existing tx")
        info("Run with --send to actually send 0.01 USDC")
        info("")
        info("To send manually:")
        info(f"  1. Send {args.amount} USDC on Base to {WALLET}")
        info( "  2. Copy the tx hash from your wallet or basescan.org")
        info( "  3. Run: python3 payment_test.py --tx 0xYOUR_TX_HASH")
        info( "  4. Or pass X-Payment: <tx_hash> to /summarize, /chat, etc.")

    # Steps 4–6 only with a tx hash
    if tx_hash:
        # Step 4 — verify via module
        verify_result = verify_via_module(tx_hash, args.amount)
        proof["steps"]["module_verify"] = verify_result

        # Step 5 — verify via API
        api_result = verify_via_api(tx_hash)
        proof["steps"]["api_verify"] = api_result

        # Step 6 — paid API call (optional, consumes tx)
        if args.paid_call:
            paid_result = test_paid_call(tx_hash)
            proof["steps"]["paid_call"] = paid_result
        else:
            section("STEP 6 — Paid API call")
            info("Skipped (add --paid-call to test this — it CONSUMES the tx hash)")

        # Balance after
        if args.send:
            section("Balance after send")
            balance_after = get_usdc_balance(w3, WALLET)
            delta = balance_after - balance_before
            info(f"Before: {balance_before:.6f} USDC")
            info(f"After:  {balance_after:.6f} USDC")
            info(f"Delta:  {delta:+.6f} USDC")
            if delta > 0:
                ok(f"Balance increased by {delta:.6f} USDC — payment received!")
            else:
                info("Delta is 0 or negative (tx may be self-send or still pending)")
            proof["steps"]["balance_after"] = {"usdc": balance_after, "delta": delta}

        # Basescan link
        basescan_url = f"https://basescan.org/tx/{tx_hash}"
        info(f"\n  Basescan: {basescan_url}")
        proof["steps"]["basescan"] = basescan_url
        proof["tx_hash"] = tx_hash

    # Write proof
    write_proof(proof)

    # Summary
    section("TEST SUMMARY")
    pay_ok   = proof["steps"].get("pay_endpoint", {}).get("status") == 200
    bal_ok   = proof["steps"].get("balance_before", {}).get("usdc", 0) >= 0
    tx_ok    = bool(tx_hash)
    mod_ok   = proof["steps"].get("module_verify", {}).get("valid", False)

    print(f"  /pay endpoint:       {'✓ PASS' if pay_ok else '✗ FAIL'}")
    print(f"  Balance query:       {'✓ PASS' if bal_ok else '✗ FAIL'}")
    print(f"  TX provided/sent:    {'✓ YES' if tx_ok else '— SKIPPED'}")
    print(f"  Module verification: {'✓ PASS' if mod_ok else ('— SKIPPED' if not tx_ok else '✗ FAIL')}")
    print()


if __name__ == "__main__":
    main()
