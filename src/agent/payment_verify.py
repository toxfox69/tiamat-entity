#!/usr/bin/env python3
"""
TIAMAT Payment Verification Module
Verifies USDC transfers on Base mainnet via JSON-RPC.
Uses only Python stdlib (urllib, sqlite3, json) — no pip deps.
"""

import base64
import json
import os
import re
import sqlite3
import urllib.request
import datetime

# ── Constants ─────────────────────────────────────────────────
TIAMAT_WALLET = "0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE"
USDC_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_RPC_URL = "https://mainnet.base.org"
# keccak256("Transfer(address,address,uint256)")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
USDC_DECIMALS = 6

PAYMENTS_DB = "/root/api/payments.db"
PREMIUM_AMOUNT = 5.0  # $5 USDC unlocks premium subscription tier

# ── SQLite setup ──────────────────────────────────────────────
def _init_db():
    os.makedirs(os.path.dirname(PAYMENTS_DB), exist_ok=True)
    conn = sqlite3.connect(PAYMENTS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS used_tx_hashes (
            tx_hash TEXT PRIMARY KEY,
            amount_usdc REAL NOT NULL,
            sender TEXT NOT NULL,
            endpoint TEXT DEFAULT '',
            verified_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS premium_subscriptions (
            tx_hash TEXT PRIMARY KEY,
            amount_usdc REAL NOT NULL,
            sender TEXT NOT NULL,
            activated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

_init_db()


def _is_tx_used(tx_hash: str) -> bool:
    conn = sqlite3.connect(PAYMENTS_DB)
    row = conn.execute("SELECT 1 FROM used_tx_hashes WHERE tx_hash=?", (tx_hash.lower(),)).fetchone()
    conn.close()
    return row is not None


def _mark_tx_used(tx_hash: str, amount_usdc: float, sender: str, endpoint: str = ""):
    conn = sqlite3.connect(PAYMENTS_DB)
    conn.execute(
        "INSERT OR IGNORE INTO used_tx_hashes (tx_hash, amount_usdc, sender, endpoint, verified_at) VALUES (?,?,?,?,?)",
        (tx_hash.lower(), amount_usdc, sender, endpoint, datetime.datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


def _is_premium_sub(tx_hash: str) -> bool:
    """Check if tx_hash is an active premium subscription (reusable)."""
    conn = sqlite3.connect(PAYMENTS_DB)
    row = conn.execute("SELECT 1 FROM premium_subscriptions WHERE tx_hash=?", (tx_hash.lower(),)).fetchone()
    conn.close()
    return row is not None


def _mark_premium(tx_hash: str, amount_usdc: float, sender: str):
    conn = sqlite3.connect(PAYMENTS_DB)
    conn.execute(
        "INSERT OR IGNORE INTO premium_subscriptions (tx_hash, amount_usdc, sender, activated_at) VALUES (?,?,?,?)",
        (tx_hash.lower(), amount_usdc, sender, datetime.datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


# ── RPC helper ────────────────────────────────────────────────
def _rpc_call(method: str, params: list) -> dict:
    """Make a JSON-RPC call to Base mainnet."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }).encode()
    req = urllib.request.Request(
        BASE_RPC_URL,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "TIAMAT/1.0"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": {"message": str(e)}}


# ── Core verification ────────────────────────────────────────
def _fetch_tx_amount(tx_hash: str, recipient: str = TIAMAT_WALLET) -> dict:
    """
    Fetch and parse a USDC transfer tx WITHOUT marking it as used.
    Returns: {"valid": bool, "reason": str, "amount_usdc": float, "sender": str}
    """
    result = {"valid": False, "reason": "", "amount_usdc": 0.0, "sender": ""}

    rpc_resp = _rpc_call("eth_getTransactionReceipt", [tx_hash])
    if "error" in rpc_resp:
        result["reason"] = f"RPC error: {rpc_resp['error'].get('message', 'unknown')}"
        return result

    receipt = rpc_resp.get("result")
    if not receipt:
        result["reason"] = "Transaction not found or not yet confirmed on Base"
        return result

    if receipt.get("status", "0x0") != "0x1":
        result["reason"] = "Transaction failed (reverted)"
        return result

    recipient_lower = recipient.lower().replace("0x", "").zfill(64)
    usdc_lower = USDC_CONTRACT.lower()
    total_amount = 0.0
    sender_addr = ""
    found_transfer = False

    for log in receipt.get("logs", []):
        if log.get("address", "").lower() != usdc_lower:
            continue
        topics = log.get("topics", [])
        if len(topics) < 3 or topics[0].lower() != TRANSFER_TOPIC.lower():
            continue
        log_to = (topics[2].lower().replace("0x", "").lstrip("0")) or "0"
        expected_to = recipient_lower.lstrip("0") or "0"
        if log_to != expected_to:
            continue
        raw_amount = int(log.get("data", "0x0"), 16)
        total_amount += raw_amount / (10 ** USDC_DECIMALS)
        sender_raw = topics[1].lower().replace("0x", "")
        sender_addr = "0x" + sender_raw[-40:]
        found_transfer = True

    if not found_transfer:
        result["reason"] = f"No USDC transfer to {recipient} found in transaction"
        return result

    result["valid"] = True
    result["amount_usdc"] = total_amount
    result["sender"] = sender_addr
    return result


def verify_payment(tx_hash: str, expected_amount_usdc: float,
                   recipient: str = TIAMAT_WALLET,
                   endpoint: str = "") -> dict:
    """
    Verify a USDC payment on Base mainnet and consume the tx hash (one-time use).
    Returns: {"valid": bool, "reason": str, "amount_usdc": float, "sender": str}
    """
    result = {"valid": False, "reason": "", "amount_usdc": 0.0, "sender": ""}

    tx_hash = tx_hash.strip()
    if not re.match(r'^0x[0-9a-fA-F]{64}$', tx_hash):
        result["reason"] = "Invalid tx hash format (expected 0x + 64 hex chars)"
        return result

    if _is_tx_used(tx_hash):
        result["reason"] = "Transaction already used for a previous request"
        return result

    tx = _fetch_tx_amount(tx_hash, recipient)
    if not tx["valid"]:
        result["reason"] = tx["reason"]
        return result

    if tx["amount_usdc"] < expected_amount_usdc:
        result["reason"] = f"Insufficient payment: sent ${tx['amount_usdc']:.6f}, required ${expected_amount_usdc:.6f}"
        result["amount_usdc"] = tx["amount_usdc"]
        result["sender"] = tx["sender"]
        return result

    _mark_tx_used(tx_hash, tx["amount_usdc"], tx["sender"], endpoint)
    result["valid"] = True
    result["reason"] = "Payment verified"
    result["amount_usdc"] = tx["amount_usdc"]
    result["sender"] = tx["sender"]
    return result


def check_tier(tx_hash: str, request_amount: float = 0.01, endpoint: str = "") -> dict:
    """
    Determine payment tier from a tx hash. Single entry point for all endpoint payment checks.

    - Premium ($5 USDC): returns {"tier": "premium", "sub_id": str} — reusable, 100/50/200 daily limits
    - Per-request ($0.01+): returns {"tier": "per_request", "amount": float} — tx consumed, no daily limit
    - Free: returns {"tier": "free"} — no tx_hash provided
    - Invalid: returns {"tier": "invalid", "reason": str}
    """
    if not tx_hash:
        return {"tier": "free"}

    tx_hash = tx_hash.strip()
    if not re.match(r'^0x[0-9a-fA-F]{64}$', tx_hash):
        return {"tier": "invalid", "reason": "Invalid tx hash format (expected 0x + 64 hex chars)"}

    # Premium subscription — reuse without consuming
    if _is_premium_sub(tx_hash):
        return {"tier": "premium", "sub_id": "sub_" + tx_hash[2:18]}

    # Already consumed as per-request
    if _is_tx_used(tx_hash):
        return {"tier": "invalid", "reason": "Transaction already used for a previous request"}

    # Fetch from blockchain
    tx = _fetch_tx_amount(tx_hash)
    if not tx["valid"]:
        return {"tier": "invalid", "reason": tx["reason"]}

    amount = tx["amount_usdc"]

    # $5+ → premium subscription (stored permanently, reusable daily)
    if amount >= PREMIUM_AMOUNT:
        _mark_premium(tx_hash, amount, tx["sender"])
        return {"tier": "premium", "sub_id": "sub_" + tx_hash[2:18], "sender": tx["sender"]}

    # Sufficient for this endpoint → per-request (consumed)
    if amount >= request_amount:
        _mark_tx_used(tx_hash, amount, tx["sender"], endpoint)
        return {"tier": "per_request", "amount": amount, "sender": tx["sender"]}

    return {"tier": "invalid", "reason": f"Insufficient payment: ${amount:.6f}, required ${request_amount:.6f}"}


# ── Extract payment proof from request headers ───────────────
def extract_payment_proof(flask_request) -> str:
    """
    Extract tx hash from request headers.
    Checks: X-Payment, X-Payment-Proof, X-Payment-Authorization, Authorization: Bearer
    Handles plain tx hashes and base64-encoded x402 payloads.
    """
    for header in ("X-Payment", "X-Payment-Proof", "X-Payment-Authorization"):
        val = flask_request.headers.get(header, "").strip()
        if val:
            return _parse_tx_hash(val)

    auth = flask_request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return _parse_tx_hash(token)

    return ""


def _parse_tx_hash(value: str) -> str:
    """Parse a tx hash from a raw value — handles plain hashes and base64 JSON."""
    value = value.strip()

    # Plain tx hash
    if re.match(r'^0x[0-9a-fA-F]{64}$', value):
        return value

    # Try base64-encoded JSON payload (x402 format)
    try:
        decoded = base64.b64decode(value).decode("utf-8")
        data = json.loads(decoded)
        # Look for tx hash in common x402 payload fields
        for key in ("txHash", "tx_hash", "transactionHash", "transaction_hash", "hash", "receipt"):
            if key in data and re.match(r'^0x[0-9a-fA-F]{64}$', str(data[key])):
                return str(data[key])
    except Exception:
        pass

    # Maybe it's a bare hex hash without 0x prefix
    if re.match(r'^[0-9a-fA-F]{64}$', value):
        return "0x" + value

    return ""


# ── Standardized 402 response body ───────────────────────────
def payment_required_response(amount_usdc: float, endpoint: str = "") -> dict:
    """Return a clean 402 response body. No redundant fields. Developer-first."""
    amount_raw = int(amount_usdc * (10 ** USDC_DECIMALS))
    return {
        "error": "payment_required",
        "message": f"Free tier exhausted. Send ${amount_usdc} USDC to continue.",
        "how_to_pay": {
            "1_send": f"Send {amount_usdc} USDC on Base to {TIAMAT_WALLET}",
            "2_copy": "Copy the transaction hash (0x...)",
            "3_use": "Add header: X-Payment: <tx_hash>",
            "curl": f'curl -X POST https://tiamat.live{endpoint} -H "Content-Type: application/json" -H "X-Payment: 0xYOUR_TX_HASH" -d \'{{"text": "your text here"}}\'',
        },
        "payment": {
            "wallet": TIAMAT_WALLET,
            "chain_id": 8453,
            "chain": "Base",
            "token": "USDC",
            "contract": USDC_CONTRACT,
            "amount": amount_usdc,
            "amount_wei": amount_raw,
        },
        "plans": [
            {"name": "pay_per_use", "price": f"${amount_usdc}", "unit": "per request"},
            {"name": "premium", "price": "$5 USDC", "unit": "one-time", "requests": "100 summarize + 50 art + 200 chat daily, resets midnight UTC", "note": "Send $5 USDC, use the tx hash as your API key forever"},
        ],
        "pay_page": "https://tiamat.live/pay",
        "resets": "midnight UTC",
    }


def payment_required_headers(amount_usdc: float) -> dict:
    """x402-compatible HTTP headers for the 402 response."""
    amount_raw = int(amount_usdc * (10 ** USDC_DECIMALS))
    return {
        "X-Payment-Required": "true",
        "X-Payment-Chain-Id": "8453",
        "X-Payment-Token": USDC_CONTRACT,
        "X-Payment-Recipient": TIAMAT_WALLET,
        "X-Payment-Amount": str(amount_raw),
        "X-Payment-Pay-Page": "https://tiamat.live/pay",
    }
