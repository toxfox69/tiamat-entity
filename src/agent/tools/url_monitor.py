"""
URL Health Monitor — POST /api/monitor
======================================
Free tier : 2 checks/day/IP
Paid tier : $0.01 USDC via x402 (tx_hash in body)
Cache     : 1-hour SQLite result cache per URL
Timeout   : 5 seconds per outbound request

Usage (standalone module — imported by summarize_api.py):

    from src.agent.tools.url_monitor import register_monitor_routes
    register_monitor_routes(app, verify_payment_fn, USER_WALLET, logger)
"""

import sqlite3
import time
import re
from datetime import datetime, date, timedelta
from urllib.parse import urlparse

import requests as _requests

# ─── DB path ──────────────────────────────────────────────────────────────────
MONITOR_DB = '/root/.automaton/url_monitor.db'
MONITOR_FREE_TIER_LIMIT = 2        # checks/day/IP
MONITOR_CACHE_TTL_SECS  = 3600     # 1 hour
MONITOR_TIMEOUT_SECS    = 5
MONITOR_PRICE_USDC      = 0.01

# ─── DB init ──────────────────────────────────────────────────────────────────

def _init_db():
    conn = sqlite3.connect(MONITOR_DB)
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS monitor_rate_limits (
            ip       TEXT NOT NULL,
            date_str TEXT NOT NULL,
            count    INTEGER DEFAULT 0,
            PRIMARY KEY (ip, date_str)
        );

        CREATE TABLE IF NOT EXISTS monitor_cache (
            url            TEXT PRIMARY KEY,
            status_code    INTEGER,
            response_time_ms REAL,
            is_up          INTEGER,
            timestamp      TEXT,
            cached_at      REAL   -- unix epoch
        );
    ''')
    conn.commit()
    conn.close()


# ─── Rate limit helpers ────────────────────────────────────────────────────────

def _get_count(ip: str) -> int:
    today = str(date.today())
    try:
        conn = sqlite3.connect(MONITOR_DB)
        row = conn.execute(
            'SELECT count FROM monitor_rate_limits WHERE ip=? AND date_str=?',
            (ip, today)
        ).fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception:
        return 0


def _increment(ip: str):
    today = str(date.today())
    try:
        conn = sqlite3.connect(MONITOR_DB)
        conn.execute('''
            INSERT INTO monitor_rate_limits (ip, date_str, count) VALUES (?, ?, 1)
            ON CONFLICT(ip, date_str) DO UPDATE SET count = count + 1
        ''', (ip, today))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ─── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_get(url: str):
    """Return cached result dict if fresh, else None."""
    try:
        conn = sqlite3.connect(MONITOR_DB)
        row = conn.execute(
            'SELECT status_code, response_time_ms, is_up, timestamp, cached_at '
            'FROM monitor_cache WHERE url=?', (url,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        cached_at = row[4]
        if time.time() - cached_at > MONITOR_CACHE_TTL_SECS:
            return None          # stale
        return {
            'status_code': row[0],
            'response_time_ms': row[1],
            'is_up': bool(row[2]),
            'timestamp': row[3],
            'cached': True,
            'cache_age_secs': int(time.time() - cached_at),
        }
    except Exception:
        return None


def _cache_set(url: str, status_code: int, response_time_ms: float,
               is_up: bool, timestamp: str):
    try:
        conn = sqlite3.connect(MONITOR_DB)
        conn.execute('''
            INSERT INTO monitor_cache
                (url, status_code, response_time_ms, is_up, timestamp, cached_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                status_code      = excluded.status_code,
                response_time_ms = excluded.response_time_ms,
                is_up            = excluded.is_up,
                timestamp        = excluded.timestamp,
                cached_at        = excluded.cached_at
        ''', (url, status_code, response_time_ms, int(is_up), timestamp, time.time()))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ─── URL validation ────────────────────────────────────────────────────────────

# Block private/reserved ranges
_BLOCKED_HOSTS = re.compile(
    r'^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|0\.0\.0\.0|::1)',
    re.IGNORECASE
)

def _validate_url(url: str):
    """Return (ok: bool, error: str)."""
    if not url or len(url) > 2048:
        return False, 'URL must be between 1 and 2048 characters'
    try:
        p = urlparse(url)
    except Exception:
        return False, 'Malformed URL'
    if p.scheme not in ('http', 'https'):
        return False, 'Only http:// and https:// URLs are supported'
    host = p.hostname or ''
    if not host:
        return False, 'URL must include a hostname'
    if _BLOCKED_HOSTS.match(host):
        return False, 'Private/reserved IP ranges are not allowed'
    return True, ''


# ─── Core check ───────────────────────────────────────────────────────────────

def _do_check(url: str) -> dict:
    """Perform the actual HTTP HEAD/GET check. Always returns a result dict."""
    timestamp = datetime.utcnow().isoformat() + 'Z'
    start = time.monotonic()
    try:
        resp = _requests.head(
            url,
            timeout=MONITOR_TIMEOUT_SECS,
            allow_redirects=True,
            headers={'User-Agent': 'TiamatMonitor/1.0 (+https://tiamat.live)'},
        )
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        status_code = resp.status_code
        is_up = 200 <= status_code < 400
    except _requests.exceptions.SSLError as e:
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        return {
            'status_code': 0,
            'response_time_ms': elapsed_ms,
            'is_up': False,
            'timestamp': timestamp,
            'cached': False,
            'error': f'SSL error: {str(e)[:120]}',
        }
    except _requests.exceptions.Timeout:
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        return {
            'status_code': 0,
            'response_time_ms': elapsed_ms,
            'is_up': False,
            'timestamp': timestamp,
            'cached': False,
            'error': f'Request timed out after {MONITOR_TIMEOUT_SECS}s',
        }
    except _requests.exceptions.ConnectionError as e:
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        return {
            'status_code': 0,
            'response_time_ms': elapsed_ms,
            'is_up': False,
            'timestamp': timestamp,
            'cached': False,
            'error': f'Connection error: {str(e)[:120]}',
        }
    except Exception as e:
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        return {
            'status_code': 0,
            'response_time_ms': elapsed_ms,
            'is_up': False,
            'timestamp': timestamp,
            'cached': False,
            'error': f'Unexpected error: {str(e)[:120]}',
        }

    _cache_set(url, status_code, elapsed_ms, is_up, timestamp)
    return {
        'status_code': status_code,
        'response_time_ms': elapsed_ms,
        'is_up': is_up,
        'timestamp': timestamp,
        'cached': False,
    }


# ─── Flask route registration ──────────────────────────────────────────────────

def register_monitor_routes(app, verify_payment_fn, user_wallet: str, log):
    """
    Call once during app init:

        from src.agent.tools.url_monitor import register_monitor_routes, init_monitor_db
        init_monitor_db()
        register_monitor_routes(app, verify_payment, USER_WALLET, logger)
    """

    @app.route('/api/monitor', methods=['POST'])
    def url_monitor():
        """URL health check. x402 payment: $0.01 USDC on Base.

        POST JSON:
            {"url": "https://example.com"}
            {"url": "https://example.com", "tx_hash": "0x..."}   ← paid tier

        Response:
            {
                "status_code": 200,
                "response_time_ms": 142.3,
                "is_up": true,
                "timestamp": "2026-03-03T12:00:00Z",
                "cached": false,
                "url": "https://example.com",
                "paid": false,
                "free_checks_remaining": 1
            }
        """
        from flask import request, jsonify

        data    = request.get_json(silent=True) or {}
        url     = str(data.get('url', '')).strip()
        tx_hash = str(data.get('tx_hash', '')).strip()

        # ── 1. Validate URL ──────────────────────────────────────────────────
        ok, err = _validate_url(url)
        if not ok:
            return jsonify({'error': err}), 400

        client_ip = (
            request.headers.get('X-Forwarded-For', request.remote_addr or '0.0.0.0')
            .split(',')[0].strip()
        )

        # ── 2. Payment verification (optional) ──────────────────────────────
        paid = False
        tx_url = None
        if tx_hash:
            if not tx_hash.startswith('0x') or len(tx_hash) < 10:
                return jsonify({'error': 'tx_hash must be a valid 0x-prefixed hex string'}), 400
            pay_ok, pay_msg = verify_payment_fn(tx_hash)
            if not pay_ok:
                return jsonify({
                    'error': 'Payment not verified',
                    'details': pay_msg,
                    'x402': True,
                    'cost_usdc': MONITOR_PRICE_USDC,
                    'payment_url': f'https://tiamat.live/pay?amount={MONITOR_PRICE_USDC}&endpoint=/api/monitor',
                    'wallet': user_wallet,
                }), 402
            paid = True
            tx_url = f'https://basescan.org/tx/{tx_hash}'

        # ── 3. Free-tier check ───────────────────────────────────────────────
        if not paid:
            count = _get_count(client_ip)
            if count >= MONITOR_FREE_TIER_LIMIT:
                return jsonify({
                    'error': 'Free tier limit reached',
                    'message': f'You have used all {MONITOR_FREE_TIER_LIMIT} free URL checks for today.',
                    'limit': MONITOR_FREE_TIER_LIMIT,
                    'used': count,
                    'reset': str(date.today()),
                    'x402': True,
                    'cost_usdc': MONITOR_PRICE_USDC,
                    'payment_url': f'https://tiamat.live/pay?amount={MONITOR_PRICE_USDC}&endpoint=/api/monitor',
                    'wallet': user_wallet,
                    'upgrade_url': 'https://tiamat.live/pay',
                }), 402
            _increment(client_ip)
            free_remaining = max(0, MONITOR_FREE_TIER_LIMIT - count - 1)
        else:
            free_remaining = None   # unlimited with payment

        # ── 4. Cache lookup ──────────────────────────────────────────────────
        cached = _cache_get(url)
        if cached is not None:
            log.info(f'[monitor] cache hit: {url}')
            resp_data = {**cached, 'url': url, 'paid': paid}
            if free_remaining is not None:
                resp_data['free_checks_remaining'] = free_remaining
            if tx_url:
                resp_data['tx_url'] = tx_url
            return jsonify(resp_data)

        # ── 5. Live check ────────────────────────────────────────────────────
        log.info(f'[monitor] checking {url} (ip={client_ip}, paid={paid})')
        result = _do_check(url)

        resp_data = {**result, 'url': url, 'paid': paid}
        if free_remaining is not None:
            resp_data['free_checks_remaining'] = free_remaining
        if tx_url:
            resp_data['tx_url'] = tx_url

        status_http = 200 if result.get('error') is None else 200
        return jsonify(resp_data), status_http


def init_monitor_db():
    """Initialize the monitor SQLite DB. Call at app startup."""
    _init_db()
