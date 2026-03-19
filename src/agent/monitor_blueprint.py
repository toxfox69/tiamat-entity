#!/usr/bin/env python3
"""
URL Health Monitor — Flask Blueprint
=====================================
POST /api/monitor  {"url": "https://..."}
Returns: {status, response_time_ms, ssl_valid, domain, timestamp, is_up,
          redirect_count, server, content_type}

Rate limit : 2 free checks / IP / day
Paid tier  : $0.01 USDC on Base — send tx hash in X-Payment header
SQLite log : /root/.automaton/monitor_requests.db
"""

import ssl
import time
import socket
import sqlite3
import ipaddress
import re
from datetime import datetime, date, timezone
from urllib.parse import urlparse

import requests
from requests.exceptions import (
    Timeout as ReqTimeout,
    SSLError as ReqSSLError,
    ConnectionError as ReqConnectionError,
    TooManyRedirects as ReqTooManyRedirects,
)
from flask import Blueprint, request, jsonify

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------
monitor_bp = Blueprint("monitor", __name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MONITOR_DB        = "/root/.automaton/monitor_requests.db"
FREE_LIMIT        = 2          # free checks / IP / day
PRICE_USDC        = 0.01
WALLET            = "0xdA4A701aB24e2B6805b702dDCC3cB4D8f591d397"
USDC_CONTRACT     = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_RPC          = "https://mainnet.base.org"
REQUEST_TIMEOUT   = 8          # seconds
SSL_TIMEOUT       = 5          # seconds

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_monitor_db():
    """Create tables if they don't exist. Call once at import time."""
    conn = sqlite3.connect(MONITOR_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monitor_requests (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            ip               TEXT    NOT NULL,
            url              TEXT    NOT NULL,
            domain           TEXT,
            status           INTEGER,
            response_time_ms INTEGER,
            ssl_valid        INTEGER,   -- 1=valid 0=invalid NULL=n/a
            is_up            INTEGER,   -- 1=up 0=down
            redirect_count   INTEGER    DEFAULT 0,
            server_header    TEXT,
            content_type     TEXT,
            error            TEXT,
            paid             INTEGER    DEFAULT 0,
            tx_hash          TEXT,
            timestamp        TEXT       NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_monitor_ip_date
        ON monitor_requests(ip, timestamp)
    """)
    conn.commit()
    conn.close()


def _log_request(ip, url, domain, status, response_time_ms, ssl_valid,
                 is_up, redirect_count=0, server_header=None,
                 content_type=None, error=None, paid=0, tx_hash=None):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ssl_int = None
    if ssl_valid is True:
        ssl_int = 1
    elif ssl_valid is False:
        ssl_int = 0
    try:
        conn = sqlite3.connect(MONITOR_DB)
        conn.execute("""
            INSERT INTO monitor_requests
              (ip, url, domain, status, response_time_ms, ssl_valid, is_up,
               redirect_count, server_header, content_type, error, paid, tx_hash, timestamp)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (ip, url, domain, status, response_time_ms, ssl_int,
              1 if is_up else 0, redirect_count, server_header,
              content_type, error, paid, tx_hash, ts))
        conn.commit()
        conn.close()
    except Exception:
        pass  # never let logging crash the response


# ---------------------------------------------------------------------------
# Rate limiting (separate per-endpoint counter, stored in monitor DB)
# ---------------------------------------------------------------------------

def _monitor_rate_limit_db():
    """Ensure rate_limit table exists in monitor DB."""
    conn = sqlite3.connect(MONITOR_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monitor_rate_limits (
            ip       TEXT NOT NULL,
            date_str TEXT NOT NULL,
            count    INTEGER DEFAULT 0,
            PRIMARY KEY (ip, date_str)
        )
    """)
    conn.commit()
    conn.close()


def _get_free_count(ip: str) -> int:
    today = str(date.today())
    conn = sqlite3.connect(MONITOR_DB)
    row = conn.execute(
        "SELECT count FROM monitor_rate_limits WHERE ip=? AND date_str=?",
        (ip, today)
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def _increment_count(ip: str):
    today = str(date.today())
    conn = sqlite3.connect(MONITOR_DB)
    conn.execute("""
        INSERT INTO monitor_rate_limits (ip, date_str, count)
        VALUES (?, ?, 1)
        ON CONFLICT(ip, date_str) DO UPDATE SET count = count + 1
    """, (ip, today))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# x402 payment verification
# ---------------------------------------------------------------------------
_TX_RE = re.compile(r'^0x[0-9a-fA-F]{64}$')

def _is_tx_used(tx_hash: str) -> bool:
    """Return True if this tx hash was already used to pay for a check."""
    conn = sqlite3.connect(MONITOR_DB)
    row = conn.execute(
        "SELECT id FROM monitor_requests WHERE tx_hash=? LIMIT 1",
        (tx_hash,)
    ).fetchone()
    conn.close()
    return row is not None


def verify_x402_payment(tx_hash: str) -> tuple[bool, str]:
    """
    Verify a 0.01 USDC transfer to WALLET on Base mainnet.
    Returns (ok: bool, reason: str).
    """
    if not tx_hash or not _TX_RE.match(tx_hash):
        return False, "Invalid tx hash format"

    if _is_tx_used(tx_hash):
        return False, "Transaction already used"

    try:
        payload = {
            "jsonrpc": "2.0",
            "method": "eth_getTransactionReceipt",
            "params": [tx_hash],
            "id": 1,
        }
        r = requests.post(BASE_RPC, json=payload, timeout=6)
        receipt = r.json().get("result")
        if not receipt:
            return False, "Transaction not found or not yet mined"
        if receipt.get("status") != "0x1":
            return False, "Transaction reverted"

        # Scan logs for USDC Transfer to our wallet
        # Transfer(address indexed from, address indexed to, uint256 value)
        # topic[0] = keccak256("Transfer(address,address,uint256)")
        TRANSFER_TOPIC = (
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        )
        for log in receipt.get("logs", []):
            if log.get("address", "").lower() != USDC_CONTRACT.lower():
                continue
            topics = log.get("topics", [])
            if len(topics) < 3:
                continue
            if topics[0].lower() != TRANSFER_TOPIC:
                continue
            # topics[2] is the "to" address (padded to 32 bytes)
            to_addr = "0x" + topics[2][-40:]
            if to_addr.lower() != WALLET.lower():
                continue
            # data = transfer amount (uint256, 6 decimals for USDC)
            raw = log.get("data", "0x") or "0x"
            try:
                amount = int(raw, 16)
            except ValueError:
                amount = 0
            # 0.01 USDC = 10_000 (6 decimals)
            if amount >= 10_000:
                return True, "Payment verified"

        return False, "No qualifying USDC transfer found in tx"

    except requests.Timeout:
        return False, "Base RPC timeout"
    except Exception as e:
        return False, f"Verification error: {e}"


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------

def _is_safe_url(url: str) -> tuple[bool, str]:
    """
    Block private/loopback/link-local IPs (SSRF protection).
    Returns (safe: bool, reason: str).
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Malformed URL"

    if parsed.scheme not in ("http", "https"):
        return False, "Only http/https URLs are allowed"

    hostname = parsed.hostname
    if not hostname:
        return False, "No hostname in URL"

    if len(hostname) > 253:
        return False, "Hostname too long"

    try:
        ip_str = socket.gethostbyname(hostname)
        addr = ipaddress.ip_address(ip_str)
    except socket.gaierror:
        return False, f"Cannot resolve hostname: {hostname}"
    except ValueError:
        return False, "Invalid IP address"

    if (addr.is_private or addr.is_loopback or
            addr.is_link_local or addr.is_reserved or addr.is_multicast):
        return False, "Private/internal addresses are not allowed"

    return True, ""


# ---------------------------------------------------------------------------
# SSL certificate check
# ---------------------------------------------------------------------------

def _check_ssl(hostname: str, port: int = 443):
    """
    Returns True  — cert is present and not expired
            False  — cert is present but invalid/expired
            None   — couldn't determine (connection error, not HTTPS, etc.)
    """
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=SSL_TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                if cert is None:
                    return None
                not_after = cert.get("notAfter")
                if isinstance(not_after, str) and not_after:
                    expiry = ssl.cert_time_to_seconds(not_after)
                    return expiry > time.time()
                return True  # cert present, expiry unknown → assume ok
    except ssl.SSLCertVerificationError:
        return False
    except ssl.SSLError:
        return False
    except (socket.timeout, ConnectionRefusedError, OSError):
        return None  # couldn't reach 443, not necessarily invalid cert


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@monitor_bp.route("/api/monitor", methods=["POST"])
def api_monitor():
    # ---- parse input -------------------------------------------------------
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}

    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Missing 'url' field"}), 400

    # ---- SSRF guard --------------------------------------------------------
    safe, reason = _is_safe_url(url)
    if not safe:
        return jsonify({"error": f"Invalid URL: {reason}"}), 400

    parsed      = urlparse(url)
    domain      = parsed.hostname or ""
    is_https    = parsed.scheme == "https"
    ip          = (request.headers.get("X-Forwarded-For", "")
                   .split(",")[0].strip()) or request.remote_addr or "0.0.0.0"
    timestamp   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ---- x402 payment check (bypasses rate limit) --------------------------
    tx_hash = (request.headers.get("X-Payment") or "").strip()
    paid    = False

    if tx_hash:
        ok, msg = verify_x402_payment(tx_hash)
        if not ok:
            return jsonify({
                "error": f"Payment verification failed: {msg}",
                "wallet": WALLET,
                "amount_usdc": PRICE_USDC,
                "network": "Base mainnet",
            }), 402
        paid = True
    else:
        # ---- free-tier rate limit ------------------------------------------
        used = _get_free_count(ip)
        if used >= FREE_LIMIT:
            return jsonify({
                "error": f"Free tier limit reached ({FREE_LIMIT} checks/day)",
                "used_today": used,
                "limit": FREE_LIMIT,
                "upgrade": "Send 0.01 USDC to pay wallet and include tx hash "
                           "in X-Payment header",
                "wallet": WALLET,
                "amount_usdc": PRICE_USDC,
                "pay_page": "https://tiamat.live/pay",
            }), 402

    # ---- SSL check (non-blocking, parallel-ish via quick attempt) ----------
    ssl_valid = _check_ssl(domain) if is_https else None

    # ---- HTTP probe --------------------------------------------------------
    status           = 0
    response_time_ms = 0
    is_up            = False
    redirect_count   = 0
    server_header    = None
    content_type     = None
    error_msg        = None

    try:
        t0 = time.monotonic()
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": "TIAMAT-Monitor/1.0 (health-check)"},
            stream=False,
        )
        response_time_ms = int((time.monotonic() - t0) * 1000)
        status           = resp.status_code
        redirect_count   = len(resp.history)
        server_header    = resp.headers.get("Server")
        content_type     = resp.headers.get("Content-Type", "").split(";")[0].strip()
        is_up            = status < 500

    except ReqTimeout:
        response_time_ms = REQUEST_TIMEOUT * 1000
        error_msg        = "timeout"
    except ReqSSLError as e:
        ssl_valid  = False
        error_msg  = f"ssl_error: {str(e)[:120]}"
    except ReqConnectionError as e:
        error_msg  = f"connection_error: {str(e)[:120]}"
    except ReqTooManyRedirects:
        error_msg  = "too_many_redirects"
    except Exception as e:
        error_msg  = f"error: {str(e)[:120]}"

    # ---- increment rate-limit counter only after successful probe ----------
    if not paid:
        _increment_count(ip)

    # ---- log to SQLite -----------------------------------------------------
    _log_request(
        ip=ip, url=url, domain=domain,
        status=status, response_time_ms=response_time_ms,
        ssl_valid=ssl_valid, is_up=is_up,
        redirect_count=redirect_count,
        server_header=server_header, content_type=content_type,
        error=error_msg, paid=1 if paid else 0,
        tx_hash=tx_hash or None,
    )

    # ---- build response ----------------------------------------------------
    result = {
        "url":             url,
        "domain":          domain,
        "status":          status,
        "response_time_ms": response_time_ms,
        "ssl_valid":       ssl_valid,
        "is_up":           is_up,
        "timestamp":       timestamp,
        "redirect_count":  redirect_count,
    }
    if server_header:
        result["server"] = server_header
    if content_type:
        result["content_type"] = content_type
    if error_msg:
        result["error"] = error_msg

    return jsonify(result), 200


# ---------------------------------------------------------------------------
# Analytics endpoint (GET /api/monitor/stats)
# ---------------------------------------------------------------------------

@monitor_bp.route("/api/monitor/stats", methods=["GET"])
def monitor_stats():
    """Return aggregate analytics from the monitor log."""
    try:
        conn = sqlite3.connect(MONITOR_DB)
        total = conn.execute("SELECT COUNT(*) FROM monitor_requests").fetchone()[0]
        up    = conn.execute("SELECT COUNT(*) FROM monitor_requests WHERE is_up=1").fetchone()[0]
        paid  = conn.execute("SELECT COUNT(*) FROM monitor_requests WHERE paid=1").fetchone()[0]
        avg_ms = conn.execute(
            "SELECT AVG(response_time_ms) FROM monitor_requests WHERE status > 0"
        ).fetchone()[0]
        conn.close()
        return jsonify({
            "total_checks":     total,
            "checks_up":        up,
            "checks_down":      total - up,
            "paid_checks":      paid,
            "free_checks":      total - paid,
            "avg_response_ms":  round(avg_ms or 0, 1),
            "uptime_rate":      round(up / total * 100, 1) if total else 0,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Init DB on import
# ---------------------------------------------------------------------------
try:
    init_monitor_db()
    _monitor_rate_limit_db()
except Exception as _e:
    import logging
    logging.getLogger(__name__).error(f"monitor_blueprint: DB init failed: {_e}")
