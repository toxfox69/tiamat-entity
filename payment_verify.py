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
def verify_payment(tx_hash: str, expected_amount_usdc: float,
                   recipient: str = TIAMAT_WALLET,
                   endpoint: str = "") -> dict:
    """
    Verify a USDC payment on Base mainnet.

    Returns: {"valid": bool, "reason": str, "amount_usdc": float, "sender": str}
    """
    result = {"valid": False, "reason": "", "amount_usdc": 0.0, "sender": ""}

    # Validate tx hash format
    tx_hash = tx_hash.strip()
    if not re.match(r'^0x[0-9a-fA-F]{64}$', tx_hash):
        result["reason"] = "Invalid tx hash format (expected 0x + 64 hex chars)"
        return result

    # Check double-spend
    if _is_tx_used(tx_hash):
        result["reason"] = "Transaction already used for a previous request"
        return result

    # Fetch receipt from Base RPC
    rpc_resp = _rpc_call("eth_getTransactionReceipt", [tx_hash])
    if "error" in rpc_resp:
        result["reason"] = f"RPC error: {rpc_resp['error'].get('message', 'unknown')}"
        return result

    receipt = rpc_resp.get("result")
    if not receipt:
        result["reason"] = "Transaction not found or not yet confirmed on Base"
        return result

    # Check tx succeeded (status 0x1)
    status = receipt.get("status", "0x0")
    if status != "0x1":
        result["reason"] = "Transaction failed (reverted)"
        return result

    # Parse logs for USDC Transfer event
    recipient_lower = recipient.lower().replace("0x", "").zfill(64)
    usdc_lower = USDC_CONTRACT.lower()

    found_transfer = False
    total_amount = 0
    sender_addr = ""

    for log in receipt.get("logs", []):
        log_addr = log.get("address", "").lower()
        topics = log.get("topics", [])

        # Match USDC contract + Transfer event
        if log_addr != usdc_lower or len(topics) < 3:
            continue
        if topics[0].lower() != TRANSFER_TOPIC.lower():
            continue

        # topics[1] = from (sender), topics[2] = to (recipient)
        log_to = topics[2].lower().replace("0x", "").lstrip("0") or "0"
        expected_to = recipient_lower.lstrip("0") or "0"

        if log_to != expected_to:
            continue

        # Parse amount from data field (uint256, 6 decimals for USDC)
        raw_amount = int(log.get("data", "0x0"), 16)
        amount_usdc = raw_amount / (10 ** USDC_DECIMALS)

        sender_raw = topics[1].lower().replace("0x", "")
        sender_addr = "0x" + sender_raw[-40:]

        total_amount += amount_usdc
        found_transfer = True

    if not found_transfer:
        result["reason"] = f"No USDC transfer to {recipient} found in transaction"
        return result

    if total_amount < expected_amount_usdc:
        result["reason"] = f"Insufficient payment: sent ${total_amount:.6f}, required ${expected_amount_usdc:.6f}"
        result["amount_usdc"] = total_amount
        result["sender"] = sender_addr
        return result

    # All checks passed — mark as used and return success
    _mark_tx_used(tx_hash, total_amount, sender_addr, endpoint)

    result["valid"] = True
    result["reason"] = "Payment verified"
    result["amount_usdc"] = total_amount
    result["sender"] = sender_addr
    return result


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
    """Return a standardized 402 response body with payment instructions."""
    return {
        "error": "Payment required",
        "payment": {
            "protocol": "x402",
            "chain": "Base (Chain ID 8453)",
            "token": "USDC",
            "contract": USDC_CONTRACT,
            "recipient": TIAMAT_WALLET,
            "amount_usdc": amount_usdc,
            "amount_raw": int(amount_usdc * (10 ** USDC_DECIMALS)),
        },
        "instructions": {
            "1": f"Send {amount_usdc} USDC to {TIAMAT_WALLET} on Base",
            "2": "Include the tx hash in the X-Payment header",
            "3": "Retry your request with the header attached",
        },
        "pay_page": "https://tiamat.live/pay",
        "endpoint": endpoint,
    }
