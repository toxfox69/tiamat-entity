#!/usr/bin/env python3
"""
url_monitor.py — URL Health Monitor Blueprint for TIAMAT Flask API
POST /api/monitor  |  2 free/day per IP  |  $0.01 USDC via x402 after that

Integration (3 lines in summarize_api.py):
    from url_monitor import monitor_bp, init_monitor_db
    init_monitor_db()
    app.register_blueprint(monitor_bp)

Remove the existing /api/monitor stub handler first.
"""

import ssl
import socket
import sqlite3
import time
import ipaddress
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests
from flask import Blueprint, request, jsonify

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH            = "/root/.automaton/monitor.db"
FREE_LIMIT         = 2          # free checks per IP per day
PAID_COST_USDC     = 0.01
TIMEOUT_S          = 30
TIAMAT_WALLET      = "0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE"
UPTIME_WINDOW_DAYS = 7

monitor_bp = Blueprint("monitor", __name__)


# ── Database ─────────────────────────────────────────────────────────────────
def init_monitor_db():
    """Create tables. Call once at app startup."""
    with sqlite3.connect(DB_PATH) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS checks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                url         TEXT    NOT NULL,
                status_code INTEGER NOT NULL,
                response_ms INTEGER NOT NULL,
                is_up       INTEGER NOT NULL,
                ssl_valid   INTEGER,
                ssl_expiry  TEXT,
                checked_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_checks_url ON checks(url);
            CREATE INDEX IF NOT EXISTS idx_checks_at  ON checks(checked_at);

            CREATE TABLE IF NOT EXISTS monitor_quota (
                ip          TEXT NOT NULL,
                check_date  TEXT NOT NULL,
                count       INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (ip, check_date)
            );
        """)


def _db():
    return sqlite3.connect(DB_PATH)


def quota_used(ip: str) -> int:
    today = datetime.utcnow().strftime('%Y-%m-%d')
    with _db() as db:
        row = db.execute(
            "SELECT count FROM monitor_quota WHERE ip=? AND check_date=?",
            (ip, today)
        ).fetchone()
    return row[0] if row else 0


def quota_increment(ip: str):
    today = datetime.utcnow().strftime('%Y-%m-%d')
    with _db() as db:
        db.execute("""
            INSERT INTO monitor_quota (ip, check_date, count) VALUES (?, ?, 1)
            ON CONFLICT(ip, check_date) DO UPDATE SET count = count + 1
        """, (ip, today))


def record_check(url, status_code, response_ms, is_up, ssl_valid, ssl_expiry):
    with _db() as db:
        db.execute(
            "INSERT INTO checks (url,status_code,response_ms,is_up,ssl_valid,ssl_expiry)"
            " VALUES (?,?,?,?,?,?)",
            (url, status_code, int(response_ms), int(is_up), ssl_valid, ssl_expiry)
        )


def uptime_percent(url: str) -> float:
    since = (datetime.utcnow() - timedelta(days=UPTIME_WINDOW_DAYS)) \
                .strftime('%Y-%m-%dT%H:%M:%SZ')
    with _db() as db:
        row = db.execute(
            "SELECT COUNT(*), SUM(is_up) FROM checks WHERE url=? AND checked_at>=?",
            (url, since)
        ).fetchone()
    if not row or not row[0]:
        return 100.0
    return round((row[1] / row[0]) * 100, 1)


# ── SSRF Guard ───────────────────────────────────────────────────────────────
def is_safe_url(url: str) -> bool:
    """Block private/loopback IPs to prevent SSRF."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        ip = socket.gethostbyname(hostname)
        addr = ipaddress.ip_address(ip)
        return not (addr.is_private or addr.is_loopback
                    or addr.is_link_local or addr.is_reserved)
    except Exception:
        return False


# ── SSL Inspector ────────────────────────────────────────────────────────────
def inspect_ssl(hostname: str) -> dict:
    """Returns SSL validity, expiry date, and days remaining."""
    try:
        ctx = ssl.create_default_context()
        conn = ctx.wrap_socket(
            socket.create_connection((hostname, 443), timeout=10),
            server_hostname=hostname
        )
        cert = conn.getpeercert() or {}
        conn.close()
        not_after = str(cert.get('notAfter') or '')
        expiry_dt = datetime.strptime(str(not_after), '%b %d %H:%M:%S %Y %Z')
        days_left  = (expiry_dt - datetime.utcnow()).days
        return {
            "valid":          True,
            "expiry":         expiry_dt.strftime('%Y-%m-%d'),
            "days_remaining": days_left,
            "expired":        days_left < 0,
        }
    except ssl.SSLCertVerificationError:
        return {"valid": False, "expiry": None, "days_remaining": None, "expired": True}
    except Exception:
        return {"valid": None,  "expiry": None, "days_remaining": None, "expired": None}


# ── x402 Payment ─────────────────────────────────────────────────────────────
def verify_payment(pay_token: str | None) -> bool:
    """
    Verify USDC payment on Base mainnet via payment_verify.py logic.
    Stub: accepts any non-empty pay_token (swap for on-chain verify in prod).
    To wire up real verification:
        from src.agent.payment_verify import verify_usdc_payment
        return verify_usdc_payment(pay_token, TIAMAT_WALLET, PAID_COST_USDC)
    """
    return bool(pay_token and len(pay_token) >= 10)


# ── Core Health Check ─────────────────────────────────────────────────────────
def run_check(url: str) -> dict:
    """Perform HTTP request + SSL inspection. Stores result in DB. Returns result dict."""
    parsed    = urlparse(url)
    is_https  = parsed.scheme == 'https'
    hostname  = parsed.hostname

    ssl_info = inspect_ssl(hostname or '') if is_https else {
        "valid": None, "expiry": None, "days_remaining": None, "expired": None
    }

    status_code = 0
    response_ms = 0.0
    is_up       = False

    try:
        t0 = time.monotonic()
        resp = requests.get(
            url,
            timeout=TIMEOUT_S,
            allow_redirects=True,
            headers={'User-Agent': 'TIAMAT-Monitor/1.0'}
        )
        response_ms = round((time.monotonic() - t0) * 1000, 1)
        status_code = resp.status_code
        is_up       = status_code < 500

    except requests.Timeout:
        response_ms = TIMEOUT_S * 1000
        status_code = 0
        is_up       = False

    except requests.ConnectionError:
        status_code = 0
        is_up       = False

    record_check(
        url, status_code, response_ms, is_up,
        ssl_valid=ssl_info.get('valid'),
        ssl_expiry=ssl_info.get('expiry')
    )

    return {
        "url":             url,
        "status":          status_code,
        "is_up":           is_up,
        "response_time_ms": response_ms,
        "uptime":          f"{uptime_percent(url)}%",
        "ssl":             ssl_info,
        "checked_at":      datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    }


# ── Route ─────────────────────────────────────────────────────────────────────
@monitor_bp.route('/api/monitor', methods=['POST'])
def api_monitor():
    """
    POST /api/monitor
    Body: {"url": "https://example.com"}                     — free (up to 2/day)
          {"url": "https://example.com", "pay": true,
           "pay_token": "<tx_hash>"}                         — paid ($0.01 USDC)

    Returns:
    {
      "url":              "https://example.com",
      "status":           200,
      "is_up":            true,
      "response_time_ms": 234.5,
      "uptime":           "98.5%",
      "ssl":              {"valid": true, "expiry": "2026-08-01", "days_remaining": 151},
      "checked_at":       "2026-03-03T12:00:00Z",
      "cost":             "free"
    }
    """
    try:
        data = request.get_json(silent=True) or {}

        # ── Validate input ────────────────────────────────────────────────
        url = (data.get('url') or '').strip()
        if not url:
            return jsonify({"error": "Missing or empty 'url' field"}), 400

        if len(url) > 2048:
            return jsonify({"error": "URL too long (max 2048 chars)"}), 400

        if not is_safe_url(url):
            return jsonify({
                "error": "Invalid or disallowed URL",
                "detail": "Must be http/https. Private/loopback IPs are blocked."
            }), 400

        # ── Rate limit / payment gate ────────────────────────────────────
        raw_ip  = request.headers.get('X-Forwarded-For') or request.remote_addr or '0.0.0.0'
        ip      = raw_ip.split(',')[0].strip()
        used    = quota_used(ip)
        pay     = bool(data.get('pay', False))
        tok     = data.get('pay_token', '')
        cost    = "free"

        if used >= FREE_LIMIT:
            if not pay:
                return jsonify({
                    "error":       "Free tier exhausted (2 checks/day per IP)",
                    "used":        used,
                    "limit":       FREE_LIMIT,
                    "upgrade":     f"Retry with pay=true and pay_token=<Base tx hash>",
                    "cost":        f"${PAID_COST_USDC:.2f} USDC per check",
                    "wallet":      TIAMAT_WALLET,
                    "pay_page":    "https://tiamat.live/pay",
                }), 429

            if not verify_payment(tok):
                return jsonify({
                    "error":       "Payment verification failed",
                    "cost":        f"${PAID_COST_USDC:.2f} USDC",
                    "wallet":      TIAMAT_WALLET,
                    "detail":      "Send USDC on Base mainnet then retry with the tx hash as pay_token",
                    "pay_page":    "https://tiamat.live/pay",
                }), 402

            cost = f"${PAID_COST_USDC:.2f} USDC"

        # ── Run check ────────────────────────────────────────────────────
        quota_increment(ip)
        result = run_check(url)
        result["cost"] = cost
        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": f"Internal error: {str(e)}"}), 500


@monitor_bp.route('/api/monitor/history', methods=['GET'])
def api_monitor_history():
    """GET /api/monitor/history?url=https://example.com&limit=20"""
    url   = request.args.get('url', '').strip()
    limit = min(int(request.args.get('limit', 20)), 100)

    if not url:
        return jsonify({"error": "Missing 'url' query parameter"}), 400

    with _db() as db:
        rows = db.execute(
            "SELECT status_code, response_ms, is_up, ssl_valid, ssl_expiry, checked_at"
            " FROM checks WHERE url=? ORDER BY checked_at DESC LIMIT ?",
            (url, limit)
        ).fetchall()

    history = [
        {
            "status":          r[0],
            "response_ms":     r[1],
            "is_up":           bool(r[2]),
            "ssl_valid":       bool(r[3]) if r[3] is not None else None,
            "ssl_expiry":      r[4],
            "checked_at":      r[5],
        }
        for r in rows
    ]
    return jsonify({
        "url":     url,
        "uptime":  f"{uptime_percent(url)}%",
        "history": history,
    })
