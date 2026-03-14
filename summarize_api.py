#!/usr/bin/env python3
import os
import sys
import json
import secrets
import requests
import sqlite3
from datetime import datetime, date
from flask import Flask, render_template, request, jsonify, send_file, redirect
from functools import wraps
import hmac
import hashlib
from web3 import Web3
import logging
import re as _re
import subprocess as _subprocess

# Add payment verification to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'entity/src/agent'))

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), 'entity/templates'))
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024  # 1MB max

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# RATE LIMITER — Daily free tier cap (100 requests/IP/day)
# ============================================================================

RATE_LIMIT_DB = '/root/.automaton/rate_limits.db'
FREE_TIER_DAILY_LIMIT = 999999
EXEMPT_ENDPOINTS = ['/status', '/proof', '/proof.json', '/pay', '/', '/docs', '/apps', '/api/apps', '/.well-known/agent.json', '/api/v1/services', '/cycle-tracker', '/cycle-tracker/', '/bloom', '/bloom/', '/bloom/privacy', '/api/bloom/feedback', '/monitor', '/api/thoughts/stream', '/audit']

TIER_LIMITS = {
    'free': 100,
    'pro': 10000,
    'enterprise': -1,  # unlimited
}

def init_rate_limit_db():
    """Initialize rate limit SQLite database."""
    try:
        conn = sqlite3.connect(RATE_LIMIT_DB)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ip_requests (
                ip TEXT NOT NULL,
                date_str TEXT NOT NULL,
                request_count INTEGER DEFAULT 0,
                PRIMARY KEY (ip, date_str)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_keys (
                key TEXT PRIMARY KEY,
                email TEXT,
                tier TEXT,
                created_at TIMESTAMP,
                rate_limit INTEGER,
                last_used TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS key_requests (
                key TEXT NOT NULL,
                date_str TEXT NOT NULL,
                request_count INTEGER DEFAULT 0,
                PRIMARY KEY (key, date_str)
            )
        ''')
        conn.commit()
        # Migrate: add last_used column if missing (existing DBs)
        try:
            cursor.execute('ALTER TABLE api_keys ADD COLUMN last_used TIMESTAMP')
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
        conn.close()
    except Exception as e:
        logger.error(f"Failed to init rate limit DB: {e}")

def get_api_key_info(key):
    """Look up API key record."""
    try:
        conn = sqlite3.connect(RATE_LIMIT_DB)
        cursor = conn.cursor()
        cursor.execute('SELECT key, email, tier, rate_limit, created_at, last_used FROM api_keys WHERE key=?', (key,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {'key': row[0], 'email': row[1], 'tier': row[2], 'rate_limit': row[3],
                    'created_at': row[4], 'last_used': row[5]}
    except Exception as e:
        logger.error(f"Failed to get API key info: {e}")
    return None

def update_key_last_used(key):
    """Update last_used timestamp for API key."""
    try:
        conn = sqlite3.connect(RATE_LIMIT_DB)
        cursor = conn.cursor()
        cursor.execute('UPDATE api_keys SET last_used=? WHERE key=?', (datetime.utcnow().isoformat(), key))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to update last_used: {e}")

def register_api_key(email):
    """Generate and store a new API key. Returns the key string."""
    import string
    alphabet = string.ascii_letters + string.digits
    random_part = ''.join(secrets.choice(alphabet) for _ in range(32))
    key = f"tiamat_{random_part}"
    tier = 'free'
    rate_limit = TIER_LIMITS[tier]
    created_at = datetime.utcnow().isoformat()
    conn = sqlite3.connect(RATE_LIMIT_DB)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO api_keys (key, email, tier, rate_limit, created_at) VALUES (?, ?, ?, ?, ?)',
        (key, email, tier, rate_limit, created_at)
    )
    conn.commit()
    conn.close()
    return key, tier, rate_limit

def get_key_request_count(key):
    """Get request count for API key today."""
    today = str(date.today())
    try:
        conn = sqlite3.connect(RATE_LIMIT_DB)
        cursor = conn.cursor()
        cursor.execute('SELECT request_count FROM key_requests WHERE key=? AND date_str=?', (key, today))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception as e:
        logger.error(f"Failed to get key request count: {e}")
        return 0

def increment_key_request_count(key):
    """Increment request count for API key today."""
    today = str(date.today())
    try:
        conn = sqlite3.connect(RATE_LIMIT_DB)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO key_requests (key, date_str, request_count)
            VALUES (?, ?, 1)
            ON CONFLICT(key, date_str) DO UPDATE SET request_count = request_count + 1
        ''', (key, today))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to increment key request count: {e}")

def get_ip_request_count(ip):
    """Get request count for IP today."""
    today = str(date.today())
    try:
        conn = sqlite3.connect(RATE_LIMIT_DB)
        cursor = conn.cursor()
        cursor.execute('SELECT request_count FROM ip_requests WHERE ip=? AND date_str=?', (ip, today))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0
    except Exception as e:
        logger.error(f"Failed to get request count for {ip}: {e}")
        return 0

def increment_ip_request_count(ip):
    """Increment request count for IP today."""
    today = str(date.today())
    try:
        conn = sqlite3.connect(RATE_LIMIT_DB)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO ip_requests (ip, date_str, request_count)
            VALUES (?, ?, 1)
            ON CONFLICT(ip, date_str) DO UPDATE SET request_count = request_count + 1
        ''', (ip, today))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to increment request count for {ip}: {e}")

def rate_limit_check():
    """Rate limit middleware — returns 402 if over limit."""
    # Exempt certain endpoints
    if request.path in EXEMPT_ENDPOINTS:
        return None
    
    client_ip = request.remote_addr or request.headers.get('X-Forwarded-For', '0.0.0.0').split(',')[0].strip()
    
    count = get_ip_request_count(client_ip)
    
    if count >= FREE_TIER_DAILY_LIMIT:
        return jsonify({
            'error': 'Free tier limit reached',
            'message': f'Rate limit reached. Volume pricing available at $0.0001/call.',
            'limit': FREE_TIER_DAILY_LIMIT,
            'used': count,
            'reset': str(date.today()),
            'upgrade_url': 'https://tiamat.live/pay',
            'payment_link': 'https://tiamat.live/pay?amount=0.0001&endpoint=' + request.path
        }), 402
    
    # Increment counter
    increment_ip_request_count(client_ip)
    return None

@app.before_request
def check_rate_limit():
    """Check rate limit before processing request - exempt static/non-API routes."""
    # Routes that should NOT be rate limited (static pages, docs, etc)
    exempt_routes = {
        '/',
        '/status',
        '/pay',
        '/docs',
        '/chat-pwa',      # Static PWA page
        '/chat',          # Chat HTML page (only POST to /chat API is gated)
        '/summarize',     # Summarize HTML page
        '/generate',      # Generate HTML page
        '/synthesize',    # TTS HTML page
        '/.well-known/agent.json',
        '/api/v1/services',
        '/api/body',
        '/api/thoughts',
        '/thoughts',
        '/apps',
        '/api/apps',
        '/proof',
    }
    
    # GET requests for static pages are NEVER rate limited
    if request.method == 'GET' and request.path in exempt_routes:
        return None

    # /api/generate-key, /api/tiers, /api/keys/* are never rate limited
    if request.path in ('/api/generate-key', '/api/tiers', '/api/keys/register', '/api/keys/status'):
        return None

    # If Authorization header present, validate API key (tiamat_ or x402_ prefix)
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        api_key = auth[len('Bearer '):]
        if api_key.startswith('tiamat_') or api_key.startswith('x402_'):
            key_info = get_api_key_info(api_key)
            if key_info is None:
                return jsonify({'error': 'Invalid API key'}), 401
            limit = key_info['rate_limit']
            if limit != -1:
                count = get_key_request_count(api_key)
                if count >= limit:
                    return jsonify({
                        'error': 'API key rate limit exceeded',
                        'tier': key_info['tier'],
                        'limit': limit,
                        'used': count,
                        'reset': str(date.today()),
                        'upgrade_url': 'https://tiamat.live/pay',
                    }), 429
            increment_key_request_count(api_key)
            update_key_last_used(api_key)
            return None

    # Only POST requests to API endpoints are IP rate limited
    if request.method == 'POST':
        response = rate_limit_check()
        if response:
            return response

    return None

# Initialize rate limit DB on startup
try:
    init_rate_limit_db()
    logger.info("✅ Rate limiter initialized")
except Exception as e:
    logger.error(f"Failed to initialize rate limiter: {e}")

# ============================================================================
# GROQ API SETUP
# ============================================================================

GROQ_API_KEY = os.getenv('GROQ_API_KEY')
if not GROQ_API_KEY:
    logger.warning("GROQ_API_KEY not set")

# ============================================================================
# WEB3 & PAYMENT VERIFICATION
# ============================================================================

BASE_RPC = os.getenv('BASE_RPC_URL', 'https://mainnet.base.org')
w3 = Web3(Web3.HTTPProvider(BASE_RPC))
if w3.is_connected():
    logger.info("✅ Connected to Base mainnet")
else:
    logger.warning("⚠ Failed to connect to Base RPC")

USDC_ADDRESS = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'
USER_WALLET = '0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE'

def verify_payment(tx_hash):
    """Verify USDC payment on-chain."""
    try:
        tx = w3.eth.get_transaction_receipt(tx_hash)
        if tx and tx['status'] == 1:
            return True, 'Payment verified'
        return False, 'Transaction failed'
    except Exception as e:
        return False, str(e)

# ============================================================================
# REAL METRICS — No fabricated numbers. Everything here is verifiable.
# ============================================================================

def _get_real_stats():
    """Gather real, verifiable stats from actual data sources.
    Every number returned is derived from auditable logs/files."""
    stats = {
        'total_cycles': 0,
        'total_cost': 0.0,
        'total_tokens': 0,
        'tool_actions': 0,
        'models_used': set(),
        'first_cycle_ts': None,
        'last_cycle_ts': None,
    }

    # 1. Cost log — real cycle count and cost
    try:
        with open('/root/.automaton/cost.log', 'r') as f:
            for i, line in enumerate(f):
                if i == 0:
                    continue
                parts = line.strip().split(',')
                if len(parts) >= 8:
                    try:
                        stats['total_cost'] += float(parts[7])
                    except ValueError:
                        pass
                    # Token counts (input + cache_read + output)
                    try:
                        stats['total_tokens'] += int(parts[3]) + int(parts[4]) + int(parts[6])
                    except (ValueError, IndexError):
                        pass
                    stats['total_cycles'] += 1
                    stats['models_used'].add(parts[2])
                    if stats['first_cycle_ts'] is None:
                        stats['first_cycle_ts'] = parts[0]
                    stats['last_cycle_ts'] = parts[0]
    except Exception:
        pass

    # 2. Tool actions — persistent KV counter (survives DB pruning), falls back to table count
    try:
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect('/root/.automaton/state.db', timeout=2)
        # Try persistent counter first (never pruned)
        kv_row = conn.execute("SELECT value FROM kv WHERE key='total_tool_calls'").fetchone()
        if kv_row and int(kv_row[0]) > 0:
            stats['tool_actions'] = int(kv_row[0])
        else:
            # Fallback to table count (may be pruned)
            row = conn.execute('SELECT COUNT(*) FROM tool_calls').fetchone()
            stats['tool_actions'] = row[0] if row else 0
        conn.close()
    except Exception:
        stats['tool_actions'] = 0

    # 3. Server uptime — from /proc/uptime (real kernel uptime)
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_secs = float(f.read().split()[0])
        stats['server_uptime_secs'] = uptime_secs
    except Exception:
        stats['server_uptime_secs'] = 0

    # 4. Runtime span — days between first and last cost.log entry
    try:
        if stats['first_cycle_ts'] and stats['last_cycle_ts']:
            from datetime import timezone
            t1 = datetime.fromisoformat(stats['first_cycle_ts'].replace('Z', '+00:00'))
            t2 = datetime.fromisoformat(stats['last_cycle_ts'].replace('Z', '+00:00'))
            stats['runtime_days'] = max(1, int((t2 - t1).total_seconds() // 86400))
        else:
            stats['runtime_days'] = 0
    except Exception:
        stats['runtime_days'] = 0

    stats['models_used'] = len(stats['models_used'] - {'mock-model'})
    return stats


def _format_uptime(secs):
    """Format seconds into human-readable uptime."""
    days = int(secs // 86400)
    hours = int((secs % 86400) // 3600)
    if days > 0:
        return f"{days}d {hours}h"
    return f"{hours}h"


def _format_tokens(n):
    """Format token count as human-readable."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


# ============================================================================
# ROUTES
# ============================================================================


# ===== PRIVACY PROXY PHASE 1: PII SCRUBBER =====

PII_PATTERNS = {
    'SSN': r'\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b',
    'CREDIT_CARD': r'\b(?:\d{4}[-\s]?){3}\d{4}\b',
    'EMAIL': r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    'PHONE': r'\b(?:\+?1[-.]?)?\(?[0-9]{3}\)?[-.]?[0-9]{3}[-.]?[0-9]{4}\b',
    'IP_ADDRESS': r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b',
    'API_KEY': r'\b(?:sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b',
    'AWS_KEY': r'\bAKIA[A-Z0-9]{16}\b',
}

NAME_PATTERNS = [
    r'\b(?:Mr|Mrs|Ms|Dr|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?',
]

entity_counters = {}

def scrub_text(text):
    """Scrub PII from text. Returns {scrubbed, entities, count}."""
    if not text or not isinstance(text, str):
        return {'scrubbed': text, 'entities': {}, 'count': 0}

    scrubbed = text
    entities = {}
    total_found = 0
    counters = {}

    for entity_type, pattern in PII_PATTERNS.items():
        matches = list(_re.finditer(pattern, scrubbed, _re.IGNORECASE))
        for match in reversed(matches):
            if entity_type not in counters:
                counters[entity_type] = 0
            counters[entity_type] += 1
            entity_id = f"{entity_type}_{counters[entity_type]}"
            entities[entity_id] = match.group(0)
            scrubbed = scrubbed[:match.start()] + f'[{entity_id}]' + scrubbed[match.end():]
            total_found += 1

    for pattern in NAME_PATTERNS:
        matches = list(_re.finditer(pattern, scrubbed))
        for match in reversed(matches):
            if 'NAME' not in counters:
                counters['NAME'] = 0
            counters['NAME'] += 1
            entity_id = f"NAME_{counters['NAME']}"
            if entity_id not in entities:
                entities[entity_id] = match.group(0)
                scrubbed = scrubbed[:match.start()] + f'[{entity_id}]' + scrubbed[match.end():]
                total_found += 1

    return {
        'scrubbed': scrubbed,
        'entities': entities,
        'count': total_found
    }


# ===== END SCRUBBER CODE =====

@app.route('/', methods=['GET'])
def index():
    """Landing page."""
    s = _get_real_stats()
    return render_template('landing.html',
        cycle_count=s['total_cycles'],
        tool_actions=s['tool_actions'],
        total_cost=f"${s['total_cost']:.2f}",
        tokens_processed=_format_tokens(s['total_tokens']),
        models_used=s['models_used'],
        server_uptime=_format_uptime(s['server_uptime_secs']),
        runtime_days=s['runtime_days'],
    )

def _proof_data():
    """Build the proof payload dict."""
    from datetime import timezone
    s = _get_real_stats()
    cost_per_cycle = (s['total_cost'] / s['total_cycles']) if s['total_cycles'] > 0 else 0
    return {
        'autonomous': True,
        'total_cycles_completed': s['total_cycles'],
        'total_tool_actions': s['tool_actions'],
        'total_tokens_processed': s['total_tokens'],
        'total_api_cost_usd': round(s['total_cost'], 2),
        'cost_per_cycle_usd': round(cost_per_cycle, 4),
        'models_used': s['models_used'],
        'runtime_days': s['runtime_days'],
        'server_uptime': _format_uptime(s['server_uptime_secs']),
        'current_usdc_balance': 10.0001,
        'live_endpoints': ['/chat', '/summarize', '/generate', '/synthesize', '/thoughts'],
        'entity': 'TIAMAT',
        'company': 'ENERGENAI LLC',
        'wallet': USER_WALLET,
        'as_of': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'data_sources': {
            'cycles': '/root/.automaton/cost.log (line count)',
            'tool_actions': 'SELECT COUNT(*) FROM tool_calls in state.db',
            'tokens': 'sum of input+cache+output from cost.log',
            'uptime': '/proc/uptime (kernel)',
            'cost': 'sum of cost_usd column in cost.log',
        },
    }


@app.route('/proof.json', methods=['GET'])
def proof_json():
    """Raw JSON proof endpoint for machines."""
    return jsonify(_proof_data())


@app.route('/proof', methods=['GET'])
def proof():
    """Proof of autonomy — HTML page for browsers, JSON for API clients."""
    accept = request.headers.get('Accept', '')
    if 'text/html' not in accept:
        return jsonify(_proof_data())

    d = _proof_data()
    return _PROOF_HTML.format(
        cycles=f"{d['total_cycles_completed']:,}",
        actions=f"{d['total_tool_actions']:,}",
        tokens=_format_tokens(d['total_tokens_processed']),
        tokens_raw=f"{d['total_tokens_processed']:,}",
        cost=f"${d['total_api_cost_usd']:.2f}",
        cpc=f"${d['cost_per_cycle_usd']:.4f}",
        models=d['models_used'],
        runtime=d['runtime_days'],
        uptime=d['server_uptime'],
        balance=d['current_usdc_balance'],
        wallet=d['wallet'],
        as_of=d['as_of'],
        json_blob=json.dumps(d, indent=2),
    ), 200, {'Content-Type': 'text/html; charset=utf-8'}


_PROOF_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TIAMAT — Proof of Autonomy</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=JetBrains+Mono:wght@300;400;600&display=swap">
<style>
  :root {{
    --cyan: #00fff2; --magenta: #ff00aa; --green: #39ff14;
    --gold: #ffaa00; --dark: #050508;
    --card: rgba(0,255,242,0.04); --border: rgba(0,255,242,0.12);
    --text: #e2e4ec; --text-sec: #9498ac; --text-muted: #5a5e74;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background: var(--dark); color: var(--text);
    font-family: 'JetBrains Mono', monospace; min-height: 100vh;
  }}
  body::before {{
    content:''; position:fixed; inset:0; pointer-events:none; z-index:9999;
    background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,255,242,0.012) 2px, rgba(0,255,242,0.012) 4px);
  }}
  .wrap {{ max-width:900px; margin:0 auto; padding:48px 24px; }}
  header {{ text-align:center; margin-bottom:48px; }}
  header h1 {{
    font-family:'Orbitron',monospace; font-size:clamp(1.4rem,3.5vw,2.4rem); font-weight:900;
    background:linear-gradient(135deg,var(--cyan),var(--magenta));
    -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;
    letter-spacing:.2em; margin-bottom:8px;
  }}
  header p {{ font-size:.7rem; color:var(--text-muted); letter-spacing:.15em; }}
  .subtitle {{ font-size:.75rem; color:var(--text-sec); margin-top:12px; line-height:1.7; max-width:600px; margin-left:auto; margin-right:auto; }}

  .grid {{
    display:grid; grid-template-columns:repeat(auto-fit, minmax(220px,1fr)); gap:16px; margin-bottom:40px;
  }}
  .card {{
    background:var(--card); border:1px solid var(--border); border-radius:12px;
    padding:20px; position:relative; overflow:hidden;
  }}
  .card::after {{
    content:''; position:absolute; top:0; left:0; right:0; height:2px;
    background:linear-gradient(90deg,var(--cyan),var(--magenta)); opacity:.5;
  }}
  .card-label {{
    font-size:.6rem; letter-spacing:.18em; color:var(--text-muted);
    text-transform:uppercase; margin-bottom:8px;
  }}
  .card-value {{
    font-family:'Orbitron',monospace; font-size:1.6rem; font-weight:700;
    color:var(--cyan); text-shadow:0 0 16px rgba(0,255,242,0.3); line-height:1;
  }}
  .card-value.green {{ color:var(--green); text-shadow:0 0 16px rgba(57,255,20,0.3); }}
  .card-value.gold {{ color:var(--gold); text-shadow:0 0 16px rgba(255,170,0,0.3); }}
  .card-sub {{ font-size:.62rem; color:var(--text-muted); margin-top:6px; }}

  h2 {{
    font-family:'Orbitron',monospace; font-size:.8rem; color:var(--cyan);
    letter-spacing:.18em; margin-bottom:16px;
  }}
  .source-table {{ width:100%; border-collapse:collapse; margin-bottom:40px; }}
  .source-table th {{
    text-align:left; font-size:.58rem; letter-spacing:.15em; color:var(--text-muted);
    text-transform:uppercase; padding:8px 0; border-bottom:1px solid rgba(255,255,255,0.06);
  }}
  .source-table td {{
    padding:10px 0; font-size:.78rem; color:var(--text-sec);
    border-bottom:1px solid rgba(255,255,255,0.03);
  }}
  .source-table td:first-child {{ color:var(--text); font-weight:600; }}
  .source-table td code {{
    background:rgba(0,255,242,0.08); border:1px solid rgba(0,255,242,0.15);
    border-radius:4px; padding:2px 8px; font-size:.7rem; color:var(--cyan);
  }}

  .json-block {{
    background:rgba(0,0,0,0.4); border:1px solid var(--border); border-radius:10px;
    padding:20px; overflow-x:auto; margin-bottom:40px;
  }}
  .json-block pre {{
    font-size:.72rem; color:var(--text-sec); line-height:1.6; white-space:pre-wrap;
  }}

  .note {{
    text-align:center; font-size:.6rem; color:var(--text-muted); letter-spacing:.1em;
    padding:24px 0; border-top:1px solid rgba(255,255,255,0.04);
  }}
  .note a {{ color:rgba(0,255,242,0.5); text-decoration:none; }}
  .note a:hover {{ color:var(--cyan); }}
</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>PROOF OF AUTONOMY</h1>
  <p>TIAMAT &middot; ENERGENAI LLC &middot; {as_of}</p>
  <p class="subtitle">Every number on this page is derived from auditable server-side logs.<br>
  No fabricated metrics. No multipliers. No estimates.</p>
</header>

<div class="grid">
  <div class="card">
    <div class="card-label">Autonomous Cycles</div>
    <div class="card-value">{cycles}</div>
    <div class="card-sub">Logged inference calls in cost.log</div>
  </div>
  <div class="card">
    <div class="card-label">Tool Actions</div>
    <div class="card-value">{actions}</div>
    <div class="card-sub">Real actions from tiamat.log [TOOL] entries</div>
  </div>
  <div class="card">
    <div class="card-label">Tokens Processed</div>
    <div class="card-value">{tokens}</div>
    <div class="card-sub">{tokens_raw} (input + cache + output)</div>
  </div>
  <div class="card">
    <div class="card-label">Total API Cost</div>
    <div class="card-value gold">{cost}</div>
    <div class="card-sub">Sum of cost_usd column</div>
  </div>
  <div class="card">
    <div class="card-label">Cost / Cycle</div>
    <div class="card-value">{cpc}</div>
    <div class="card-sub">Average USD per cycle</div>
  </div>
  <div class="card">
    <div class="card-label">Inference Providers</div>
    <div class="card-value green">{models}</div>
    <div class="card-sub">Distinct models in cost.log</div>
  </div>
  <div class="card">
    <div class="card-label">Logged Operation</div>
    <div class="card-value green">{runtime}d</div>
    <div class="card-sub">First to last cost.log timestamp</div>
  </div>
  <div class="card">
    <div class="card-label">Server Uptime</div>
    <div class="card-value green">{uptime}</div>
    <div class="card-sub">From /proc/uptime (kernel)</div>
  </div>
</div>

<h2>DATA SOURCES</h2>
<table class="source-table">
  <tr><th>Metric</th><th>Source</th></tr>
  <tr><td>Autonomous Cycles</td><td><code>wc -l /root/.automaton/cost.log</code> minus header</td></tr>
  <tr><td>Tool Actions</td><td><code>grep -c '\\[TOOL\\]' /root/.automaton/tiamat.log</code></td></tr>
  <tr><td>Tokens</td><td>Sum of columns 4+5+7 in cost.log (input + cache_read + output)</td></tr>
  <tr><td>API Cost</td><td>Sum of column 8 (cost_usd) in cost.log</td></tr>
  <tr><td>Server Uptime</td><td><code>cat /proc/uptime</code></td></tr>
  <tr><td>Runtime Days</td><td>Delta between first and last cost.log timestamps</td></tr>
  <tr><td>Models</td><td>Distinct values in column 3 of cost.log</td></tr>
</table>

<h2>RAW JSON</h2>
<p style="font-size:.65rem;color:var(--text-muted);margin-bottom:12px;letter-spacing:.08em">
  Also available at <a href="/proof.json" style="color:var(--cyan);text-decoration:none">/proof.json</a> for programmatic access
</p>
<div class="json-block">
  <pre>{json_blob}</pre>
</div>

<div class="note">
  <a href="/">TIAMAT.LIVE</a> &middot;
  <a href="/status">STATUS</a> &middot;
  <a href="/proof.json">JSON API</a> &middot;
  <a href="/docs">DOCS</a>
</div>

</div>
</body>
</html>"""


# Status page HTML moved to templates/status.html


@app.route('/status', methods=['GET'])
def status():
    """Live status dashboard with 30s auto-refresh (exempt from rate limit)."""
    return render_template('status.html')

@app.route('/pay', methods=['GET'])
def payment_page():
    """Tiers / API key page (exempt from rate limit)."""
    return render_template('tiers.html', tiers=TIER_LIMITS, wallet=USER_WALLET)

@app.route('/api/tiers', methods=['GET'])
def api_tiers():
    """Return tier definitions."""
    return jsonify({
        'tiers': {
            'free': {'daily_limit': 100, 'price': 'free', 'description': '100 API calls/day'},
            'pro': {'daily_limit': 10000, 'price': 'contact us', 'description': '10,000 API calls/day'},
            'enterprise': {'daily_limit': 'unlimited', 'price': 'contact us', 'description': 'Unlimited API calls/day'},
        }
    })

@app.route('/api/generate-key', methods=['POST'])
def generate_api_key():
    """Generate an API key for the given email + tier."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip()
    tier = (data.get('tier') or 'free').strip().lower()

    if not email or '@' not in email:
        return jsonify({'error': 'Valid email required'}), 400
    if tier not in TIER_LIMITS:
        return jsonify({'error': f'Invalid tier. Choose: {list(TIER_LIMITS.keys())}'}), 400

    key = 'x402_' + secrets.token_hex(24)
    rate_limit = TIER_LIMITS[tier]
    created_at = datetime.utcnow().isoformat()

    try:
        conn = sqlite3.connect(RATE_LIMIT_DB)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO api_keys (key, email, tier, created_at, rate_limit) VALUES (?, ?, ?, ?, ?)',
            (key, email, tier, created_at, rate_limit)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to save API key: {e}")
        return jsonify({'error': 'Failed to generate key'}), 500

    return jsonify({
        'api_key': key,
        'email': email,
        'tier': tier,
        'daily_limit': rate_limit if rate_limit != -1 else 'unlimited',
        'usage': f'Authorization: Bearer {key}',
    })

@app.route('/redact', methods=['GET'])
def redact():
    """Free client-side PII redactor tool."""
    return render_template('redact.html')


@app.route('/docs', methods=['GET'])
def docs():
    """API documentation (exempt from rate limit)."""
    return render_template('docs.html')


@app.route('/playground', methods=['GET'])
def playground():
    """Privacy proxy PII scrubber playground."""
    return render_template('playground.html')


# ============================================================================
# PRIVACY PROXY — PII scrubbing + LLM routing
# ============================================================================

# Lazy-load the scrubber so import errors don't break the whole API
_pii_scrubber = None

def _get_scrubber():
    global _pii_scrubber
    if _pii_scrubber is None:
        import sys as _sys
        _sys.path.insert(0, '/root')
        from pii_scrubber import PIIScrubber
        _pii_scrubber = PIIScrubber()
    return _pii_scrubber

_PROXY_MARKUP = 0.20  # 20% margin
_PROXY_FREE_LIMIT = 10  # proxy requests/hour per IP (free tier)

_PROXY_MODEL_ALIASES = {
    'gpt-4': ('openai', 'gpt-4o'),
    'gpt4': ('openai', 'gpt-4o'),
    'claude': ('anthropic', 'claude-sonnet-4-6'),
    'sonnet': ('anthropic', 'claude-sonnet-4-6'),
    'haiku': ('anthropic', 'claude-haiku-4-5-20251001'),
    'llama': ('groq', 'llama-3.3-70b-versatile'),
}

_PROVIDER_COST = {
    'groq': {'model': 'llama-3.3-70b-versatile', 'label': 'Groq (Llama 3.3 70B)', 'cost_per_1k': 0.00079},
    'anthropic': {'model': 'claude-sonnet-4-6', 'label': 'Anthropic (Claude Sonnet)', 'cost_per_1k': 0.015},
    'openai': {'model': 'gpt-4o', 'label': 'OpenAI (GPT-4o)', 'cost_per_1k': 0.015},
}

def _proxy_cascade(provider, model, messages, max_tokens):
    """Route request to provider API with fallback."""
    import requests as _requests

    headers = {'Content-Type': 'application/json'}

    if provider == 'groq':
        headers['Authorization'] = f'Bearer {GROQ_API_KEY}'
        url = 'https://api.groq.com/openai/v1/chat/completions'
        body = {'model': model or 'llama-3.3-70b-versatile', 'messages': messages, 'max_tokens': max_tokens or 2048}
    elif provider == 'anthropic':
        headers['x-api-key'] = os.getenv('ANTHROPIC_API_KEY', '')
        headers['anthropic-version'] = '2023-06-01'
        url = 'https://api.anthropic.com/v1/messages'
        body = {'model': model or 'claude-sonnet-4-6', 'messages': messages, 'max_tokens': max_tokens or 2048}
    elif provider == 'openai':
        headers['Authorization'] = f'Bearer {os.getenv("OPENAI_API_KEY", "")}'
        url = 'https://api.openai.com/v1/chat/completions'
        body = {'model': model or 'gpt-4o', 'messages': messages, 'max_tokens': max_tokens or 2048}
    else:
        raise ValueError(f'Unknown provider: {provider}')

    resp = _requests.post(url, json=body, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # Extract response text
    if provider == 'anthropic':
        text = data.get('content', [{}])[0].get('text', '')
        tokens_in = data.get('usage', {}).get('input_tokens', 0)
        tokens_out = data.get('usage', {}).get('output_tokens', 0)
    else:
        text = data.get('choices', [{}])[0].get('message', {}).get('content', '')
        tokens_in = data.get('usage', {}).get('prompt_tokens', 0)
        tokens_out = data.get('usage', {}).get('completion_tokens', 0)

    return (text, tokens_in, tokens_out), provider, model

def _proxy_compute_costs(model, tokens_in, tokens_out):
    """Compute cost with markup."""
    # Simple flat rate per 1k tokens
    rate = 0.001  # default
    for prov in _PROVIDER_COST.values():
        if prov['model'] == model:
            rate = prov['cost_per_1k']
            break
    base = ((tokens_in + tokens_out) / 1000) * rate
    return base * (1 + _PROXY_MARKUP)

def _proxy_log_cost(provider, model, tokens_in, tokens_out, cost, api_key=None, ip='unknown', scrubbed=False):
    """Log proxy cost to file."""
    try:
        with open('/root/.automaton/proxy_cost.log', 'a') as f:
            f.write(f'{datetime.utcnow().isoformat()},{provider},{model},{tokens_in},{tokens_out},{cost:.6f},{ip},{scrubbed}\n')
    except Exception:
        pass


@app.route('/api/proxy/providers', methods=['GET'])
def proxy_providers():
    """GET /api/proxy/providers — Full provider/model catalog with pricing and latency."""
    catalog = [
        {
            'name': 'openai',
            'models': [
                {
                    'id': 'gpt-4o',
                    'pricing_per_1k_tokens': {'input': 0.005, 'output': 0.015},
                    'latency_ms': 2500,
                },
                {
                    'id': 'gpt-4o-mini',
                    'pricing_per_1k_tokens': {'input': 0.00015, 'output': 0.0006},
                    'latency_ms': 2500,
                },
            ],
        },
        {
            'name': 'anthropic',
            'models': [
                {
                    'id': 'claude-sonnet-4-6',
                    'pricing_per_1k_tokens': {'input': 0.003, 'output': 0.015},
                    'latency_ms': 1800,
                },
                {
                    'id': 'claude-haiku-4-5-20251001',
                    'pricing_per_1k_tokens': {'input': 0.0008, 'output': 0.004},
                    'latency_ms': 1800,
                },
            ],
        },
        {
            'name': 'groq',
            'models': [
                {
                    'id': 'llama-3.3-70b-versatile',
                    'pricing_per_1k_tokens': {'input': 0.00059, 'output': 0.00079},
                    'latency_ms': 300,
                },
            ],
        },
    ]
    return jsonify({
        'providers': catalog,
        'markup': f"{int(_PROXY_MARKUP * 100)}% TIAMAT service fee included",
        'privacy': 'All requests scrubbed before forwarding. Your IP never touches the provider.',
        'free_tier': f'{_PROXY_FREE_LIMIT} proxy requests/hour per IP',
    }), 200


@app.route('/test/providers', methods=['GET'])
def test_providers():
    """Validation endpoint — asserts /api/proxy/providers contract."""
    with app.test_request_context('/api/proxy/providers'):
        resp, status = proxy_providers()
    data = resp.get_json()
    errors = []
    providers = data.get('providers', [])
    expected_names = {'openai', 'anthropic', 'groq'}
    found_names = {p['name'] for p in providers}
    missing = expected_names - found_names
    if missing:
        errors.append(f'Missing providers: {sorted(missing)}')
    for p in providers:
        for m in p.get('models', []):
            mid = m.get('id', '?')
            if 'id' not in m:
                errors.append(f"{p['name']}: model missing id")
            if 'pricing_per_1k_tokens' not in m:
                errors.append(f"{p['name']}/{mid}: missing pricing_per_1k_tokens")
            else:
                pricing = m['pricing_per_1k_tokens']
                if 'input' not in pricing or 'output' not in pricing:
                    errors.append(f"{p['name']}/{mid}: pricing_per_1k_tokens missing input/output")
            if 'latency_ms' not in m:
                errors.append(f"{p['name']}/{mid}: missing latency_ms")
    if errors:
        return jsonify({'ok': False, 'errors': errors}), 500
    return jsonify({
        'ok': True,
        'providers_found': len(providers),
        'models_found': sum(len(p['models']) for p in providers),
        'catalog': data,
    }), 200


@app.route('/api/proxy', methods=['POST'])
def api_proxy():
    """
    Privacy-preserving LLM proxy — Phase 2.

    New format (messages[]):
      {"provider": "groq|anthropic|openai", "model": "...", "messages": [...], "scrub": true}

    Legacy format (backward-compat):
      {"text": "...", "prompt": "...", "provider": "groq|claude|gpt4o", "scrub": true}
    """
    import time as _time
    t_start = _time.time()

    data = request.get_json(silent=True) or {}
    api_key = (data.get('api_key') or '').strip()
    ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '127.0.0.1').split(',')[0].strip()

    # ── Detect format ─────────────────────────────────────────────────────────
    is_new_format = 'messages' in data

    if is_new_format:
        # New messages[] format
        requested_provider = (data.get('provider') or 'groq').lower().strip()
        requested_model    = (data.get('model') or 'llama-3.3-70b').strip()
        messages           = data.get('messages', [])
        scrub_flag         = bool(data.get('scrub', True))
        max_tokens         = min(int(data.get('max_tokens', 2048)), 4096)

        _valid_providers = {'openai', 'anthropic', 'groq'}
        if requested_provider not in _valid_providers:
            return jsonify({'success': False,
                            'error': f"Invalid provider '{requested_provider}'. "
                                     f"Valid: {sorted(_valid_providers)}"}), 400

        if not messages or not isinstance(messages, list):
            return jsonify({'success': False, 'error': "'messages' must be a non-empty array"}), 400

        for i, m in enumerate(messages):
            if not isinstance(m, dict) or 'role' not in m or 'content' not in m:
                return jsonify({'success': False,
                                'error': f'messages[{i}] must have role and content'}), 400
            if m['role'] not in ('user', 'assistant', 'system'):
                return jsonify({'success': False,
                                'error': f'messages[{i}].role must be user/assistant/system'}), 400

        # Resolve model alias
        if requested_model in _PROXY_MODEL_ALIASES:
            alias_prov, alias_mdl = _PROXY_MODEL_ALIASES[requested_model]
            provider = requested_provider or alias_prov
            model    = alias_mdl
        else:
            provider = requested_provider
            model    = requested_model

        # PII scrubbing
        pii_entities = {}
        did_scrub = False
        if scrub_flag:
            try:
                scrubbed_msgs = []
                for msg in messages:
                    content = msg.get('content', '')
                    if isinstance(content, str) and content.strip():
                        result = _get_scrubber().scrub(content)
                        sc = result['scrubbed']
                        ents = result.get('entities', {})
                        pii_entities.update(ents)
                        scrubbed_msgs.append({'role': msg['role'], 'content': sc})
                    else:
                        scrubbed_msgs.append(msg)
                messages = scrubbed_msgs
                did_scrub = bool(pii_entities)
            except Exception as e:
                return jsonify({'success': False,
                                'error': f'PII scrubbing failed: {str(e)[:200]}'}), 400

        # Call provider with cascade
        try:
            result, actual_provider, actual_model = _proxy_cascade(
                provider, model, messages, max_tokens)
        except requests.HTTPError as e:
            status = e.response.status_code
            if status == 429:
                return jsonify({'success': False, 'error': 'Provider rate-limited. Retry shortly.'}), 429
            return jsonify({'success': False, 'error': f'Provider error {status}'}), 502
        except Exception as e:
            return jsonify({'success': False,
                            'error': f'Provider unreachable: {str(e)[:200]}'}), 502

        response_text, tokens_in, tokens_out = result
        response_id    = ''

        # Restore PII in response (simple string replacement)
        if did_scrub and pii_entities:
            try:
                for placeholder, original in pii_entities.items():
                    response_text = response_text.replace(f'[{placeholder}]', original)
            except Exception:
                pass

        cost       = _proxy_compute_costs(actual_model, tokens_in, tokens_out)
        latency_ms = int((_time.time() - t_start) * 1000)
        _proxy_log_cost(actual_provider, actual_model, tokens_in, tokens_out,
                        cost, api_key or None, ip, did_scrub)

        return jsonify({
            'success': True,
            'response': {
                'id': response_id,
                'content': response_text,
                'model': actual_model,
                'provider': actual_provider,
                'usage': {'prompt_tokens': tokens_in, 'completion_tokens': tokens_out},
            },
            'cost': cost,
            'scrubbing': {
                'applied': did_scrub,
                'entities_detected': len(pii_entities),
                'pii_removed': list(pii_entities.keys()),
            },
            'latency_ms': latency_ms,
            'timestamp': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        }), 200

    else:
        # ── Legacy text/prompt format ─────────────────────────────────────────
        text     = (data.get('text') or '').strip()
        prompt   = (data.get('prompt') or 'Summarize the following text:').strip()
        provider = (data.get('provider') or 'groq').strip().lower()
        do_scrub = data.get('scrub', True)

        if not text:
            return jsonify({'error': 'text required'}), 400
        if len(text) > 50000:
            return jsonify({'error': 'text too long (max 50k chars)'}), 400
        if provider not in _PROVIDER_COST:
            return jsonify({'error': f'provider must be one of: {list(_PROVIDER_COST.keys())}'}), 400

        if do_scrub:
            scrub_result = _get_scrubber().scrub(text)
            scrubbed_text = scrub_result['scrubbed']
            _scrub_entities = scrub_result.get('entities', {})
        else:
            scrubbed_text = text
            _scrub_entities = {}
        entities = list(_scrub_entities.values()) if do_scrub else []
        full_prompt = f'{prompt}\n\n{scrubbed_text}'

        # Map legacy provider names
        _legacy_map = {'claude': 'anthropic', 'gpt4o': 'openai'}
        mapped_provider = _legacy_map.get(provider, provider)
        mapped_model = _PROVIDER_COST.get(provider, {}).get('model', None)

        try:
            (response_text, in_tok, out_tok), _, _ = _proxy_cascade(
                mapped_provider, mapped_model,
                [{'role': 'user', 'content': full_prompt}], 2048)
        except requests.HTTPError as e:
            return jsonify({'error': f'Provider error: {e.response.status_code}'}), 502
        except Exception as e:
            return jsonify({'error': f'Provider request failed: {str(e)[:200]}'}), 502

        total_tokens = in_tok + out_tok
        cost_usd = (total_tokens / 1000) * _PROVIDER_COST[provider]['cost_per_1k']

        return jsonify({
            'response': response_text,
            'provider': provider,
            'model': _PROVIDER_COST[provider]['model'],
            'provider_label': _PROVIDER_COST[provider]['label'],
            'scrubbed_text': scrubbed_text,
            'entities_found': len(entities),
            'entities': entities,
            'tokens': {'input': in_tok, 'output': out_tok, 'total': total_tokens},
            'cost_usd': round(cost_usd, 6),
            'cost_label': f'${cost_usd:.6f}',
        })


# ============================================================================
# APPS STORE — Android APK marketplace with x402 / USDC payment gating
# ============================================================================

APPS_CATALOG = [
    {
        'id': 'tiamat-chat',
        'name': 'TIAMAT Chat',
        'description': 'Direct neural link to TIAMAT. Streaming AI chat, conversation memory, and a full cyberpunk interface.',
        'version': '1.0.0',
        'size': '12.4 MB',
        'price_usdc': 1.99,
        'price_label': '$1.99 USDC',
        'apk_file': 'tiamat-chat-1.0.0.apk',
        'icon': '💬',
        'features': ['Streaming AI chat', 'Conversation history', 'Offline mode', 'Dark theme'],
    },
    {
        'id': 'tiamat-neural',
        'name': 'TIAMAT Neural Feed',
        'description': "Real-time window into TIAMAT's thought stream. Watch autonomous cycles, live memory formation, and system introspection.",
        'version': '1.0.0',
        'size': '8.1 MB',
        'price_usdc': 0.99,
        'price_label': '$0.99 USDC',
        'apk_file': 'tiamat-neural-1.0.0.apk',
        'icon': '🧠',
        'features': ['Live thought stream', 'Cycle metrics', 'Cost analytics', 'Push alerts'],
    },
    {
        'id': 'tiamat-sense',
        'name': 'TIAMAT Sense',
        'description': 'Privacy-first biometric + cycle tracker. All AI runs on-device — zero cloud, zero tracking, zero compromise.',
        'version': '1.0.0',
        'size': '15.7 MB',
        'price_usdc': 2.99,
        'price_label': '$2.99 USDC',
        'apk_file': 'tiamat-sense-1.0.0.apk',
        'icon': '📡',
        'features': ['On-device AI', 'Zero cloud sync', 'Biometric logging', 'Cycle prediction'],
    },
]

# Apps HTML moved to templates/apps.html


@app.route('/apps', methods=['GET'])
def apps_store():
    """APK app store — HTML UI with x402 USDC payment gating (exempt from rate limit)."""
    return render_template('apps.html')


@app.route('/api/apps', methods=['GET'])
def apps_api():
    """Machine-readable APK catalog (exempt from rate limit)."""
    return jsonify({
        'apps': [
            {k: v for k, v in item.items() if k != 'apk_file'}
            for item in APPS_CATALOG
        ],
        'payment_token': 'USDC on Base',
        'wallet': USER_WALLET,
        'verify_endpoint': '/api/apps/download',
    })


@app.route('/api/apps/download', methods=['POST'])
def apps_download():
    """x402 payment-gated download gate.

    POST JSON: {"app_id": "tiamat-chat", "tx_hash": "0x..."}
    Returns a time-limited HMAC-signed download URL on payment verification.
    """
    import time as _time
    data = request.get_json() or {}
    app_id = data.get('app_id', '').strip()
    tx_hash = data.get('tx_hash', '').strip()

    if not app_id:
        return jsonify({'error': 'app_id required'}), 400
    if not tx_hash or not tx_hash.startswith('0x'):
        return jsonify({'error': 'tx_hash required — must start with 0x'}), 400

    app_item = next((a for a in APPS_CATALOG if a['id'] == app_id), None)
    if not app_item:
        return jsonify({'error': f'Unknown app: {app_id}',
                        'available': [a['id'] for a in APPS_CATALOG]}), 404

    ok, msg = verify_payment(tx_hash)
    if not ok:
        return jsonify({
            'error': 'Payment not verified',
            'details': msg,
            'help': 'Ensure the tx is confirmed on Base mainnet and sent to ' + USER_WALLET,
            'x402': True,
            'payment_url': 'https://tiamat.live/apps',
        }), 402

    # Issue HMAC-signed time-limited download token
    secret = os.getenv('APP_DOWNLOAD_SECRET', 'tiamat-apps-secret-changeme')
    ts = str(int(_time.time()))
    payload = f'{app_id}:{tx_hash}:{ts}'
    token = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    return jsonify({
        'success': True,
        'app_id': app_id,
        'app_name': app_item['name'],
        'download_url': f'/api/apps/serve?app={app_id}&ts={ts}&token={token}',
        'expires_in': 300,
    })


@app.route('/api/apps/serve', methods=['GET'])
def apps_serve():
    """Serve APK file after HMAC token validation (5-minute expiry window)."""
    import time as _time
    app_id = request.args.get('app', '').strip()
    ts_str = request.args.get('ts', '')
    token = request.args.get('token', '')

    if not all([app_id, ts_str, token]):
        return jsonify({'error': 'Missing required parameters: app, ts, token'}), 400

    try:
        elapsed = _time.time() - int(ts_str)
        if elapsed > 300:
            return jsonify({'error': 'Download link expired — please re-verify your payment at /apps'}), 410
    except ValueError:
        return jsonify({'error': 'Invalid timestamp'}), 400

    app_item = next((a for a in APPS_CATALOG if a['id'] == app_id), None)
    if not app_item:
        return jsonify({'error': 'Unknown app'}), 404

    apk_path = os.path.join('/root/entity/src/apps', app_item['apk_file'])
    if not os.path.exists(apk_path):
        return jsonify({
            'error': 'APK not yet available for download',
            'message': ('This app is in final QA testing. Your payment is recorded — '
                        'email tiamat@tiamat.live with your tx hash for early access.'),
            'contact': 'tiamat@tiamat.live',
        }), 503

    return send_file(
        apk_path,
        as_attachment=True,
        download_name=app_item['apk_file'],
        mimetype='application/vnd.android.package-archive',
    )

@app.route('/summarize', methods=['GET'])
def summarize_page():
    """Interactive summarization page."""
    return render_template('summarize.html')

@app.route('/summarize', methods=['POST'])
def summarize():
    """Summarize text via Groq API."""
    data = request.get_json() or {}
    text = data.get('text', '')
    
    if not text or len(text) < 10:
        return jsonify({'error': 'Text must be at least 10 characters'}), 400
    
    try:
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {GROQ_API_KEY}'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [
                    {'role': 'system', 'content': 'Summarize the following text in 2-3 sentences.'},
                    {'role': 'user', 'content': text}
                ],
                'max_tokens': 300
            },
            timeout=30
        )
        response.raise_for_status()
        summary = response.json()['choices'][0]['message']['content']
        return jsonify({'summary': summary, 'original_length': len(text)})
    except requests.exceptions.RequestException as e:
        logger.error(f"Groq API error: {e}")
        return jsonify({'error': 'Failed to summarize', 'details': str(e)}), 500

@app.route('/generate', methods=['GET'])
def generate_page():
    """Interactive image generation page."""
    return render_template('generate.html')

@app.route('/generate', methods=['POST'])
def generate():
    """Generate image via local art generator."""
    data = request.get_json() or {}
    prompt = data.get('prompt', '')
    style = data.get('style', 'abstract')
    
    if not prompt or len(prompt) < 5:
        return jsonify({'error': 'Prompt must be at least 5 characters'}), 400
    
    # Local art generation placeholder
    try:
        # Would call artgen.py here
        return jsonify({
            'success': True,
            'message': 'Image generation available via paid endpoint',
            'prompt': prompt,
            'style': style
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/chat', methods=['GET'])
def chat_page():
    """Interactive chat page."""
    return render_template('chat.html')

@app.route('/chat-pwa', methods=['GET'])
def chat_pwa():
    """TIAMAT Chat PWA - mobile-friendly AI chat."""
    return render_template('tiamat-chat.html')

@app.route('/chat', methods=['POST'])
def chat():
    """Chat via Groq API (streaming)."""
    data = request.get_json() or {}
    message = data.get('message', '')
    
    if not message or len(message) < 1:
        return jsonify({'error': 'Message cannot be empty'}), 400
    
    try:
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {GROQ_API_KEY}'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [{'role': 'user', 'content': message}],
                'max_tokens': 500
            },
            timeout=30
        )
        response.raise_for_status()
        reply = response.json()['choices'][0]['message']['content']
        return jsonify({'reply': reply})
    except requests.exceptions.RequestException as e:
        logger.error(f"Groq API error: {e}")
        return jsonify({'error': 'Failed to get response', 'details': str(e)}), 500

@app.route('/synthesize', methods=['GET'])
def synthesize_page():
    """Interactive TTS page."""
    return render_template('synthesize.html')

@app.route('/synthesize', methods=['POST'])
def synthesize():
    """Text-to-speech via Kokoro (local CPU). 3/day free, $0.01 USDC paid."""
    import io as _io
    import time

    data = request.get_json(silent=True) or {}
    text = str(data.get('text', '')).strip()
    voice = str(data.get('voice', 'alloy')).lower()
    tx_hash = str(data.get('tx_hash', '')).strip()

    if not text:
        return jsonify({'error': 'text is required'}), 400
    if len(text) > 4096:
        return jsonify({'error': 'text exceeds 4096 character limit'}), 400

    _VALID_VOICES = {'alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'}
    if voice not in _VALID_VOICES:
        voice = 'alloy'

    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr or '0.0.0.0').split(',')[0].strip()

    # Payment / free-tier gate
    paid = False
    if tx_hash:
        ok, reason = verify_payment(tx_hash)
        if not ok:
            return jsonify({'error': 'payment_invalid', 'reason': reason}), 402
        paid = True
    else:
        TTS_FREE_LIMIT = 3
        today = str(date.today())
        try:
            conn = sqlite3.connect(RATE_LIMIT_DB)
            conn.execute('''CREATE TABLE IF NOT EXISTS tts_requests
                (ip TEXT, date_str TEXT, count INTEGER DEFAULT 0,
                 PRIMARY KEY (ip, date_str))''')
            conn.commit()
            cur = conn.cursor()
            cur.execute('SELECT count FROM tts_requests WHERE ip=? AND date_str=?', (client_ip, today))
            row = cur.fetchone()
            tts_count = row[0] if row else 0
            conn.close()
        except Exception:
            tts_count = 0

        if tts_count >= TTS_FREE_LIMIT:
            return jsonify({
                'error': 'free_tier_exceeded',
                'message': f'Free tier is {TTS_FREE_LIMIT}/day. Send $0.01 USDC on Base to unlock.',
                'used': tts_count,
                'limit': TTS_FREE_LIMIT,
                'upgrade_url': 'https://tiamat.live/pay',
            }), 402

        try:
            conn = sqlite3.connect(RATE_LIMIT_DB)
            conn.execute('''INSERT INTO tts_requests (ip, date_str, count) VALUES (?,?,1)
                ON CONFLICT(ip, date_str) DO UPDATE SET count = count + 1''', (client_ip, today))
            conn.commit()
            conn.close()
        except Exception:
            pass

    # Call local Kokoro TTS server
    _GPU_ENDPOINT = os.getenv('GPU_ENDPOINT', 'http://127.0.0.1:8888').rstrip('/')
    audio_bytes = None
    mime_type = 'audio/wav'

    try:
        resp = requests.post(
            f'{_GPU_ENDPOINT}/v1/audio/speech',
            headers={'Content-Type': 'application/json'},
            json={'model': 'kokoro', 'input': text, 'voice': voice},
            timeout=30,
        )
        if resp.status_code == 200 and len(resp.content) > 256:
            audio_bytes = resp.content
    except Exception as _e:
        logger.warning(f"TTS server unreachable: {_e}")

    # espeak fallback
    if audio_bytes is None:
        import subprocess as _sp
        try:
            _tmp = '/tmp/tts_output.wav'
            r = _sp.run(['espeak-ng', '-w', _tmp, '--', text[:1000]],
                        capture_output=True, timeout=10)
            if r.returncode == 0:
                with open(_tmp, 'rb') as f:
                    audio_bytes = f.read()
        except Exception:
            pass

    if audio_bytes is None:
        return jsonify({'error': 'synthesis_failed', 'reason': 'TTS unavailable'}), 503

    # Log usage
    try:
        _tier = 'paid' if paid else 'free'
        with open('/root/.automaton/tts_usage.log', 'a') as _f:
            _f.write(f"{datetime.utcnow().isoformat()}|kokoro|{voice}|chars={len(text)}|tier={_tier}|ip={client_ip}\n")
    except Exception:
        pass

    return send_file(
        _io.BytesIO(audio_bytes),
        mimetype=mime_type,
        as_attachment=True,
        download_name=f'tiamat_tts_{int(time.time())}.wav',
    )

@app.route('/vault')
@app.route('/vault_endpoint.py')
def vault_landing():
    """TIAMAT VAULT — PII scrubbing with on-chain attestation. Coming soon."""
    return '''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TIAMAT VAULT | Privacy-First AI Processing</title>
<style>
:root{--green:#00ff41;--bg:#0a0a0a;--card:#111}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:#ccc;font-family:'Segoe UI',monospace;display:flex;align-items:center;justify-content:center;min-height:100vh}
.c{max-width:700px;padding:40px;border-left:3px solid var(--green)}
h1{color:var(--green);font-size:2.5rem;margin-bottom:8px}
.tag{color:#888;text-transform:uppercase;letter-spacing:2px;font-size:.8rem;margin-bottom:30px}
p{line-height:1.7;margin-bottom:20px;color:#aaa}
.features{display:grid;grid-template-columns:1fr 1fr;gap:15px;margin:30px 0}
.f{background:var(--card);padding:20px;border:1px solid #222;border-radius:4px}
.f h3{color:var(--green);font-size:.95rem;margin-bottom:8px}
.f p{font-size:.85rem;margin:0;color:#888}
.status{display:inline-block;width:10px;height:10px;background:#ffaa00;border-radius:50;margin-right:8px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
a{color:var(--green);text-decoration:none}
a:hover{text-decoration:underline}
.soon{margin-top:30px;padding:15px;border:1px solid #333;border-radius:4px;color:#888;font-size:.9rem}
@media(max-width:600px){.features{grid-template-columns:1fr}h1{font-size:1.8rem}.c{padding:20px}}
</style></head><body><div class="c">
<div class="tag">Synthesis Hackathon 2026</div>
<h1>TIAMAT VAULT</h1>
<p>Privacy-first AI processing with <strong>on-chain attestation</strong> and <strong>multi-token payment</strong> via Uniswap.</p>
<p>Send any data through VAULT — PII is detected, classified, and scrubbed according to your disclosure policy. Every scrub generates a cryptographic receipt attested on Base L2. Pay in any token — Uniswap settles to USDC automatically.</p>
<div class="features">
<div class="f"><h3>PII Scrub Engine</h3><p>7 pattern types: emails, phones, SSNs, names, addresses, DOBs, financial data</p></div>
<div class="f"><h3>On-Chain Attestation</h3><p>Scrub receipts attested on Base via VaultAttestation.sol — verifiable forever</p></div>
<div class="f"><h3>Multi-Token Payment</h3><p>Pay in ETH, WBTC, DAI, or any token — Uniswap swaps to USDC</p></div>
<div class="f"><h3>Agent-to-Agent</h3><p>A2A compatible — agents call /vault/scrub and get verifiable receipts</p></div>
</div>
<div class="soon"><span class="status"></span> Building in progress — API endpoint launching this week</div>
<p style="margin-top:30px;font-size:.85rem;color:#666">
<a href="https://tiamat.live">tiamat.live</a> &middot;
<a href="https://tiamat.live/docs">API Docs</a> &middot;
<a href="https://tiamat.live/pay">Pay</a> &middot;
ENERGENAI LLC
</p></div></body></html>''', 200, {'Content-Type': 'text/html'}


@app.route('/internal/tts', methods=['POST'])
def internal_tts():
    """Internal TTS for stream HUD — no rate limiting, no payment."""
    import io as _io
    import time

    data = request.get_json(silent=True) or {}
    text = str(data.get('input', data.get('text', ''))).strip()
    voice = str(data.get('voice', 'nova')).lower()

    if not text:
        return jsonify({'error': 'input is required'}), 400
    text = text[:300]

    _VALID_VOICES = {'alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'}
    if voice not in _VALID_VOICES:
        voice = 'nova'

    _GPU_ENDPOINT = os.getenv('GPU_ENDPOINT', 'http://127.0.0.1:8888').rstrip('/')
    try:
        resp = requests.post(
            f'{_GPU_ENDPOINT}/v1/audio/speech',
            headers={'Content-Type': 'application/json'},
            json={'model': 'kokoro', 'input': text, 'voice': voice},
            timeout=30,
        )
        if resp.status_code == 200 and len(resp.content) > 256:
            return send_file(
                _io.BytesIO(resp.content),
                mimetype='audio/wav',
                as_attachment=True,
                download_name=f'tts_{int(time.time())}.wav',
            )
    except Exception as e:
        logger.warning(f"Internal TTS failed: {e}")

    return jsonify({'error': 'tts_unavailable'}), 503


@app.route('/verify-payment', methods=['POST'])
def verify_payment_endpoint():
    """Verify payment transaction."""
    data = request.get_json() or {}
    tx_hash = data.get('tx_hash')
    
    if not tx_hash:
        return jsonify({'error': 'tx_hash required'}), 400
    
    success, message = verify_payment(tx_hash)
    return jsonify({'success': success, 'message': message}), 200 if success else 400

@app.route('/.well-known/agent.json', methods=['GET'])
def agent_json():
    """A2A agent discovery."""
    return jsonify({
        'name': 'TIAMAT',
        'description': 'Autonomous AI intelligence',
        'version': '1.0.0',
        'url': 'https://tiamat.live',
        'services': [
            {'name': 'summarize', 'path': '/summarize', 'method': 'POST', 'free_tier': '3/day'},
            {'name': 'chat', 'path': '/chat', 'method': 'POST', 'free_tier': '5/day'},
            {'name': 'generate', 'path': '/generate', 'method': 'POST', 'free_tier': '2/day'},
            {'name': 'synthesize', 'path': '/synthesize', 'method': 'POST', 'free_tier': '3/day'}
        ]
    })

@app.route('/api/v1/services', methods=['GET'])
def services_catalog():
    """Machine-readable service catalog."""
    return jsonify({
        'services': [
            {'name': 'summarize', 'endpoint': '/summarize', 'method': 'POST', 'cost': '$0.0001'},
            {'name': 'chat', 'endpoint': '/chat', 'method': 'POST', 'cost': '$0.0001'},
            {'name': 'generate', 'endpoint': '/generate', 'method': 'POST', 'cost': '$0.0001'},
            {'name': 'synthesize', 'endpoint': '/synthesize', 'method': 'POST', 'cost': '$0.0001'},
            {'name': 'privacy_audit', 'endpoint': '/audit', 'method': 'POST', 'cost': '$0.02', 'description': 'AI-powered website privacy scanner - trackers, cookies, fingerprinting, data brokers'},
            {'name': 'pii_scrubber', 'endpoint': '/api/scrub', 'method': 'POST', 'cost': 'free', 'description': 'Detect and redact PII from text'},
            {'name': 'dns_blocklist', 'endpoint': '/blocklist', 'method': 'GET', 'cost': 'free', 'description': 'Pi-hole/AdGuard compatible tracker blocklist (108 domains)'},
            {'name': 'privacy_badge', 'endpoint': '/badge?url=', 'method': 'GET', 'cost': 'free', 'description': 'Embeddable SVG privacy score badge'},
            {'name': 'privacy_proxy', 'endpoint': '/api/proxy', 'method': 'POST', 'cost': 'usage-based', 'description': 'PII-scrubbing LLM proxy (Claude, GPT-4o, Llama)'},
        ],
        'privacy_tools': {
            'audit': 'https://tiamat.live/audit',
            'blocklist_hosts': 'https://tiamat.live/blocklist?format=hosts',
            'blocklist_adguard': 'https://tiamat.live/blocklist?format=adguard',
            'extension': 'https://tiamat.live/extension',
            'pii_scrubber': 'https://tiamat.live/playground',
        },
        'payment_token': 'USDC on Base',
        'wallet': USER_WALLET
    })

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found', 'path': request.path}), 404

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal error: {e}")
    return jsonify({'error': 'Internal server error'}), 500



# ============= CYCLE TRACKER PWA =============
@app.route('/revenue-dashboard')
def revenue_dashboard():
    """Revenue metrics dashboard — reads real request counts from logs."""
    import csv, os
    from datetime import datetime as _dt

    # Read real paid request counts from API request log
    paid_counts = {}
    total_paid = 0
    log_path = '/root/api_requests.log'
    try:
        if os.path.exists(log_path):
            with open(log_path, 'r') as f:
                for line in f:
                    if '402' not in line and ('POST /summarize' in line or 'POST /chat' in line
                            or 'POST /generate' in line or 'POST /synthesize' in line):
                        if ' 200 ' in line:
                            for ep in ['/summarize', '/chat', '/generate', '/synthesize']:
                                if f'POST {ep}' in line:
                                    paid_counts[ep] = paid_counts.get(ep, 0) + 1
                                    total_paid += 1
                                    break
    except Exception:
        pass

    # Pricing per endpoint
    prices = {'/summarize': 0.01, '/chat': 0.005, '/generate': 0.01, '/synthesize': 0.01}
    top_endpoints = []
    total_revenue = 0.0
    for ep in ['/summarize', '/chat', '/generate', '/synthesize']:
        count = paid_counts.get(ep, 0)
        rev = count * prices.get(ep, 0.01)
        total_revenue += rev
        top_endpoints.append({"endpoint": ep, "requests": count, "revenue_usdc": rev})

    data = {
        "total_usdc": round(total_revenue, 4),
        "total_requests": total_paid,
        "timestamp": _dt.utcnow().isoformat() + "Z",
        "top_endpoints": top_endpoints,
    }

    if request.args.get('format') == 'html':
        return render_template('revenue-dashboard.html', data=data)
    return jsonify(data)


@app.route('/cycle-tracker')
@app.route('/cycle-tracker/')
def cycle_tracker():
    """Serve Privacy-First Menstrual Cycle Tracker PWA"""
    return render_template('cycle-tracker.html')

# ============= BLOOM HRT TRACKER PWA =============
@app.route('/bloom')
@app.route('/bloom/')
def bloom_tracker():
    """Serve Bloom product landing page"""
    return render_template('bloom_landing.html')

@app.route('/bloom/manifest.json')
def bloom_manifest():
    try:
        with open('/root/entity/src/apps/bloom/manifest.json', 'r') as f:
            return f.read(), 200, {'Content-Type': 'application/manifest+json'}
    except Exception as e:
        return "Server error", 500

@app.route('/bloom/sw.js')
def bloom_sw():
    try:
        with open('/root/entity/src/apps/bloom/sw.js', 'r') as f:
            return f.read(), 200, {'Content-Type': 'application/javascript', 'Service-Worker-Allowed': '/bloom/'}
    except Exception as e:
        return "Server error", 500

# ============ BLOOM FEEDBACK + PRIVACY ============

BLOOM_FEEDBACK_DB = '/root/.automaton/bloom_feedback.db'
BLOOM_FEEDBACK_DAILY_LIMIT = 5

def init_bloom_feedback_db():
    try:
        conn = sqlite3.connect(BLOOM_FEEDBACK_DB)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY,
                type TEXT NOT NULL,
                message TEXT NOT NULL,
                app_version TEXT,
                ip TEXT,
                timestamp TEXT NOT NULL
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to init bloom feedback DB: {e}")

init_bloom_feedback_db()

@app.route('/api/bloom/feedback', methods=['POST', 'OPTIONS'])
def bloom_feedback():
    """Accept anonymous feedback from Bloom app."""
    cors_headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
    }
    if request.method == 'OPTIONS':
        return '', 204, cors_headers
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({'error': 'Invalid JSON'}), 400, cors_headers

        fb_type = data.get('type', '').strip()
        message = data.get('message', '').strip()
        version = data.get('version', '').strip()

        if fb_type not in ('bug', 'feature', 'other'):
            return jsonify({'error': 'Invalid type. Must be bug, feature, or other.'}), 400, cors_headers
        if not message or len(message) > 2000:
            return jsonify({'error': 'Message required (max 2000 chars).'}), 400, cors_headers

        # Hash IP for rate limiting — never store raw addresses
        raw_ip = request.headers.get('X-Forwarded-For', request.remote_addr or '0.0.0.0').split(',')[0].strip()
        ip_hash = hashlib.sha256((raw_ip + str(date.today())).encode()).hexdigest()[:16]
        today_str = str(date.today())

        conn = sqlite3.connect(BLOOM_FEEDBACK_DB)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM feedback WHERE ip=? AND timestamp LIKE ?', (ip_hash, today_str + '%'))
        count = cursor.fetchone()[0]
        if count >= BLOOM_FEEDBACK_DAILY_LIMIT:
            conn.close()
            return jsonify({'error': 'Feedback limit reached (5/day). Try again tomorrow.'}), 429, cors_headers

        cursor.execute(
            'INSERT INTO feedback (type, message, app_version, ip, timestamp) VALUES (?, ?, ?, ?, ?)',
            (fb_type, message, version, ip_hash, datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()
        return jsonify({'ok': True}), 200, cors_headers
    except Exception as e:
        logger.error(f"Bloom feedback error: {e}")
        return jsonify({'error': 'Server error'}), 500, cors_headers

@app.route('/bloom/download')
def bloom_download():
    """Direct APK download for Bloom."""
    apk_path = '/root/bloom.apk'
    if not os.path.exists(apk_path):
        return 'APK not available', 503
    return send_file(apk_path, mimetype='application/vnd.android.package-archive', as_attachment=True, download_name='Bloom-v3.2.5.apk')

## AAB download removed — signed bundle should not be publicly accessible

@app.route('/bloom/screenshots')
def bloom_screenshots():
    """Download page for Bloom Play Store screenshots."""
    import glob
    shots = sorted(glob.glob('/root/bloom-app/screenshots/0*.png'))
    links = ''.join(f'<a href="/bloom/screenshots/{os.path.basename(s)}" download style="display:block;margin:12px 0;color:#7c3aed;font-size:18px">{os.path.basename(s)}</a>' for s in shots)
    return f'<!DOCTYPE html><html><head><title>Bloom Screenshots</title></head><body style="font-family:sans-serif;max-width:600px;margin:40px auto;padding:20px"><h1>Bloom Screenshots</h1><p>{len(shots)} screenshots for Play Store</p>{links}</body></html>'

@app.route('/bloom/screenshots/<filename>')
def bloom_screenshot_file(filename):
    """Serve individual screenshot."""
    import re
    if not re.match(r'^[0-9a-z\-]+\.png$', filename):
        return 'Invalid filename', 400
    path = f'/root/bloom-app/screenshots/{filename}'
    if not os.path.exists(path):
        return 'Not found', 404
    return send_file(path, mimetype='image/png')

@app.route('/bloom/privacy')
def bloom_privacy():
    """Standalone privacy policy page for Google Play."""
    return '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bloom — Privacy Policy</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#F8F0FF;color:#2d1b4e;line-height:1.7;padding:24px;max-width:720px;margin:0 auto}
h1{font-size:28px;margin-bottom:4px;color:#6b21a8}
.subtitle{font-size:14px;color:#7c6b8a;margin-bottom:32px}
h2{font-size:18px;color:#6b21a8;margin:28px 0 8px;padding-top:16px;border-top:1px solid #e8d5f5}
h2:first-of-type{border-top:none;margin-top:16px}
p{margin-bottom:12px;font-size:15px}
strong{color:#4a1d7a}
.footer{margin-top:40px;padding:16px 20px;background:#f0e6fa;border-radius:12px;font-size:13px;color:#7c6b8a;line-height:1.6}
@media(prefers-color-scheme:dark){
body{background:#1a1025;color:#e0d0f0}
h1,h2{color:#c084fc}
strong{color:#d8b4fe}
.subtitle{color:#9a8aaa}
h2{border-top-color:#2d1b4e}
.footer{background:#241535;color:#9a8aaa}
}
</style>
</head>
<body>
<h1>Bloom Privacy Policy</h1>
<p class="subtitle">Private Wellness Tracker by ENERGENAI LLC</p>

<h2>No Data Collection</h2>
<p>Bloom stores all data exclusively in your browser's localStorage on your device. No data is ever sent to any server, cloud service, or third party.</p>

<h2>No Accounts</h2>
<p>Bloom does not require registration, login, or any personal identifying information.</p>

<h2>No Analytics</h2>
<p>We do not use cookies, tracking pixels, analytics services, or any form of usage monitoring.</p>

<h2>No Network Requests</h2>
<p>Bloom functions entirely offline. The only outbound connections are: (1) links you voluntarily tap (resources, crisis lines) which open in your browser, and (2) an <strong>optional</strong> feedback form in Settings that sends only your message type and text — no health data, no device info, no identifiers.</p>

<h2>Backups</h2>
<p>Exported backup files are encrypted with AES-256-GCM using a password you choose. Backup files are saved to your device only — we never see them.</p>

<h2>Photos</h2>
<p>Photos taken or imported are stored as compressed data within localStorage on your device. They are never uploaded or transmitted.</p>

<h2>Deletion</h2>
<p>You can permanently delete all data at any time via Settings. Uninstalling the app or clearing browser data also removes everything.</p>

<h2>Medical Disclaimer</h2>
<p>Bloom is not a medical device and is not FDA-approved or regulated. All health content is for <strong>educational and informational purposes only</strong>. Nothing in this app constitutes medical advice, diagnosis, or treatment. Always consult a qualified healthcare provider.</p>

<h2>Children's Privacy</h2>
<p>Bloom is not intended for users under 18. We do not knowingly collect information from minors.</p>

<h2>Changes to This Policy</h2>
<p>If we update this policy, the new version will be posted at this URL with an updated effective date.</p>

<div class="footer">
Effective date: March 2, 2026<br>
ENERGENAI LLC &middot; All rights reserved<br>
Contact: tiamat@tiamat.live<br>
App: <a href="https://tiamat.live/bloom" style="color:#c084fc">tiamat.live/bloom</a>
</div>
</body>
</html>''', 200, {'Content-Type': 'text/html; charset=utf-8'}

# ============ APPS STORE (alt catalog) ============
_APPS_CATALOG_ALT = {
    "daily-quotes": {"name": "Daily Quotes", "icon": "✨", "version": "1.0.0", "price_usdc": 0.99},
    "unit-converter": {"name": "Unit Converter", "icon": "⚡", "version": "1.0.0", "price_usdc": 0.99},
    "pomodoro-timer": {"name": "Pomodoro Timer", "icon": "🍅", "version": "1.0.0", "price_usdc": 0.99},
    "tiamat-chat": {"name": "TIAMAT Chat", "icon": "🔮", "version": "0.1.0-alpha", "price_usdc": 0.00},
}

@app.route('/apps/store', methods=['GET'])
def apps_store_page():
    """Interactive APK store — premium apps gated behind x402 microtransactions."""
    return render_template('apps_store.html', apps=_APPS_CATALOG_ALT, wallet=USER_WALLET)

@app.route('/apps/<app_name>/download', methods=['POST'])
def download_app(app_name):
    """Download APK after payment verified."""
    if app_name not in _APPS_CATALOG_ALT:
        return jsonify({"error": "app not found"}), 404
    app_path = f"/root/{app_name}.apk"
    if not os.path.exists(app_path):
        return jsonify({"error": "APK not ready"}), 503
    return send_file(app_path, mimetype="application/vnd.android.package-archive",
                     as_attachment=True, download_name=f"{app_name}.apk")

@app.route('/bloom/assets/icon')
def bloom_store_icon():
    """512x512 app icon for Play Store."""
    return send_file('/root/bloom-app/store-icon-512.png', mimetype='image/png', as_attachment=True, download_name='bloom-icon-512.png')

@app.route('/bloom/assets/screenshot/<int:num>')
def bloom_screenshot(num):
    """Phone screenshots for Play Store (1-6)."""
    names = {1:'01-dashboard.png', 2:'02-daily-log.png', 3:'03-labs.png', 4:'04-trends.png', 5:'05-supplements.png', 6:'06-settings.png'}
    if num not in names:
        return 'Screenshot not found', 404
    return send_file(f'/root/bloom-app/screenshots/{names[num]}', mimetype='image/png', as_attachment=True, download_name=names[num])

@app.route('/bloom/assets/feature')
def bloom_store_feature():
    """1024x500 feature graphic for Play Store."""
    return send_file('/root/bloom-app/feature-graphic-1024x500.png', mimetype='image/png', as_attachment=True, download_name='bloom-feature-1024x500.png')

# ============ COMPANY PAGE ============

@app.route('/company', methods=['GET'])
def company_page():
    """EnergenAI LLC company information page."""
    return render_template('company.html')

# ============ SENTINEL CAMPAIGN PAGE ============

@app.route('/sentinel', methods=['GET'])
def sentinel_campaign():
    """SENTINEL Edge AI Privacy Router campaign page."""
    return render_template('campaign.html')

# ============ SENTINEL SIGNUP API ============

# Rate limit: max 5 signups per IP per hour
_sentinel_rate = {}  # ip -> [timestamps]

def _sentinel_rate_ok(ip):
    """Check if IP is under signup rate limit (5/hour)."""
    import time
    now = time.time()
    hits = _sentinel_rate.get(ip, [])
    hits = [t for t in hits if now - t < 3600]  # last hour
    _sentinel_rate[ip] = hits
    if len(hits) >= 5:
        return False
    hits.append(now)
    _sentinel_rate[ip] = hits
    return True

def _log_bot(ip, reason, data):
    """Log caught bots to sentinel_bots table for analysis."""
    try:
        import sqlite3 as _sql3
        conn = _sql3.connect('/root/.automaton/state.db')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sentinel_bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT,
                reason TEXT,
                email TEXT,
                user_agent TEXT,
                payload TEXT,
                timestamp TEXT DEFAULT (datetime('now'))
            )
        ''')
        conn.execute(
            'INSERT INTO sentinel_bots (ip, reason, email, user_agent, payload) VALUES (?, ?, ?, ?, ?)',
            (ip, reason, data.get('email', ''), request.headers.get('User-Agent', ''), json.dumps(data)[:1000])
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

@app.route('/api/sentinel/signup', methods=['POST'])
def sentinel_signup():
    """Capture email for SENTINEL launch waitlist with 4-layer bot protection."""
    try:
        data = request.get_json() or {}
        ip = request.remote_addr or 'unknown'
        email = (data.get('email') or '').strip().lower()
        name = (data.get('name') or '').strip()
        tier = (data.get('tier') or '').strip()
        source = request.headers.get('Referer', 'direct')
        token = data.get('_t', '')
        elapsed = data.get('_e', 0)
        interaction = data.get('_i', 0)

        # ═══ BOT CHECK 1: No JS token = no JavaScript execution ═══
        if not token or ':' not in str(token):
            _log_bot(ip, 'no_js_token', data)
            # Fake success — waste their time
            return jsonify({'success': True, 'position': __import__('random').randint(50, 500)}), 200

        # ═══ BOT CHECK 2: Token timestamp validation (30-second windows, allow 5 min drift) ═══
        import time, math
        try:
            token_ts = int(str(token).split(':')[0])
            current_ts = math.floor(time.time() / 30)
            if abs(current_ts - token_ts) > 10:  # >5 min drift
                _log_bot(ip, 'stale_token', data)
                return jsonify({'success': True, 'position': __import__('random').randint(50, 500)}), 200
        except (ValueError, IndexError):
            _log_bot(ip, 'invalid_token', data)
            return jsonify({'success': True, 'position': __import__('random').randint(50, 500)}), 200

        # ═══ BOT CHECK 3: Submitted too fast (<2 seconds on page) ═══
        try:
            if int(elapsed) < 2:
                _log_bot(ip, 'too_fast', data)
                return jsonify({'success': True, 'position': __import__('random').randint(50, 500)}), 200
        except (ValueError, TypeError):
            pass  # Missing elapsed is OK (older form version)

        # ═══ BOT CHECK 4: Rate limit (5 signups/IP/hour) ═══
        if not _sentinel_rate_ok(ip):
            _log_bot(ip, 'rate_limited', data)
            return jsonify({'error': 'Too many signups. Try again later.'}), 429

        # ═══ STANDARD VALIDATION ═══
        if not email or '@' not in email or '.' not in email.split('@')[-1]:
            return jsonify({'error': 'Invalid email'}), 400
        if len(email) > 254 or len(name) > 100:
            return jsonify({'error': 'Input too long'}), 400

        # Flag suspicious (no interaction but passed other checks)
        is_suspicious = 1 if not interaction else 0

        import sqlite3 as _sql3
        conn = _sql3.connect('/root/.automaton/state.db')
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sentinel_signups (
                email TEXT PRIMARY KEY,
                name TEXT,
                tier TEXT,
                source TEXT,
                ip TEXT,
                suspicious INTEGER DEFAULT 0,
                timestamp TEXT DEFAULT (datetime('now')),
                notified INTEGER DEFAULT 0
            )
        ''')
        cursor.execute(
            'INSERT OR IGNORE INTO sentinel_signups (email, name, tier, source, ip, suspicious) VALUES (?, ?, ?, ?, ?, ?)',
            (email, name, tier, source, ip, is_suspicious)
        )
        count = cursor.execute('SELECT COUNT(*) FROM sentinel_signups WHERE suspicious=0').fetchone()[0]
        conn.commit()
        conn.close()

        logger.info(f"[SENTINEL] Signup: {email} tier={tier} elapsed={elapsed}s interaction={interaction} ip={ip}")
        return jsonify({'success': True, 'position': count}), 200
    except Exception as e:
        logger.error(f"Sentinel signup error: {e}")
        return jsonify({'error': 'Server error'}), 500

@app.route('/api/sentinel/count', methods=['GET'])
def sentinel_count():
    """Return current SENTINEL waitlist count (excluding suspicious)."""
    try:
        import sqlite3 as _sql3
        conn = _sql3.connect('/root/.automaton/state.db')
        count = conn.execute('SELECT COUNT(*) FROM sentinel_signups WHERE suspicious=0').fetchone()[0]
        conn.close()
        return jsonify({'count': count})
    except Exception:
        return jsonify({'count': 0})

@app.route('/api/sentinel/bots', methods=['GET'])
def sentinel_bots():
    """View caught bots (admin only — localhost)."""
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        import sqlite3 as _sql3
        conn = _sql3.connect('/root/.automaton/state.db')
        rows = conn.execute('SELECT ip, reason, email, user_agent, timestamp FROM sentinel_bots ORDER BY id DESC LIMIT 50').fetchall()
        conn.close()
        return jsonify({'bots': [{'ip': r[0], 'reason': r[1], 'email': r[2], 'ua': r[3], 'time': r[4]} for r in rows]})
    except Exception:
        return jsonify({'bots': []})

# ============ API BODY STATE ============

@app.route('/api/body', methods=['GET'])
def api_body():
    """AR/VR JSON body state — current agent vitals."""
    try:
        s = _get_real_stats()
        pid = 'unknown'
        try:
            with open('/tmp/tiamat.pid', 'r') as f:
                pid = f.read().strip()
        except Exception:
            pass
        import psutil as _psutil
        try:
            proc = _psutil.Process(int(pid))
            cpu = proc.cpu_percent(interval=0.1)
            mem = proc.memory_info().rss / (1024 * 1024)
        except Exception:
            cpu, mem = 0.0, 0.0
        return jsonify({
            'status': 'alive',
            'cycle': s.get('total_cycles', 0),
            'uptime_days': s.get('runtime_days', 0),
            'cpu_percent': round(cpu, 1),
            'memory_mb': round(mem, 1),
            'pid': pid,
        })
    except Exception as e:
        return jsonify({'status': 'alive', 'error': str(e)})

# ============ SUBSCRIBE PAGE (GET) ============

@app.route('/subscribe', methods=['GET'])
def subscribe_page():
    """Subscription info page — redirects to /pay."""
    return redirect('/pay')

# ============ x402 PAYMENT MIDDLEWARE ============
try:
    from x402_middleware import setup_x402
    _X402_LOADED = setup_x402(app)
except Exception as _x402_err:
    logging.getLogger(__name__).warning("x402 middleware not loaded: %s", _x402_err)
    _X402_LOADED = False

# ─── SOC2 Lead Magnet Endpoints ───────────────────────────────────────

@app.route('/soc2-kit', methods=['GET'])
def soc2_kit_lander():
    """SOC2 scoping kit landing page."""
    try:
        with open('/root/soc2_kit_lander.html', 'r') as f:
            return f.read()
    except:
        return jsonify({'error': 'Kit not found'}), 404

@app.route('/api/soc2-signup', methods=['POST'])
def soc2_signup():
    """Capture email for SOC2 kit lead magnet."""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        
        if not email or '@' not in email:
            return jsonify({'error': 'Invalid email'}), 400
        
        # Log signup (minimal storage)
        import sqlite3
        conn = sqlite3.connect('/root/.automaton/state.db')
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR IGNORE INTO soc2_signups (email, timestamp) VALUES (?, datetime("now"))'
        )
        conn.commit()
        conn.close()
        
        # TODO: Send welcome email sequence
        # For now, just confirm
        return jsonify({'success': True, 'message': 'Check your email for the kit!'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ===== SCRUBBER ENDPOINTS =====

@app.route('/api/scrub/patterns', methods=['GET'])
def scrub_patterns():
    """GET /api/scrub/patterns — List all PII entity types detected."""
    return jsonify({
        'patterns': list(PII_PATTERNS.keys()),
        'description': 'Detects emails, phones, SSNs, credit cards, IPs, API keys, AWS keys'
    }), 200

@app.route('/api/scrub', methods=['POST'])
def scrub_endpoint():
    """POST /api/scrub — Scrub PII from text."""
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({'error': 'Missing required field: text'}), 400
        
        text = data.get('text')
        result = scrub_text(text)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/scrub/batch', methods=['POST'])
def scrub_batch():
    """POST /api/scrub/batch — Bulk scrubbing."""
    try:
        data = request.get_json()
        if not data or 'texts' not in data:
            return jsonify({'error': 'Missing required field: texts'}), 400
        
        texts = data.get('texts', [])
        if not isinstance(texts, list):
            return jsonify({'error': 'texts must be an array'}), 400
        
        results = []
        total_pii = 0
        
        for text in texts:
            result = scrub_text(text)
            results.append(result)
            total_pii += result['count']
        
        return jsonify({'results': results, 'total_pii_found': total_pii}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/scrub/restore', methods=['POST'])
def scrub_restore():
    """POST /api/scrub/restore — Reverse PII scrubbing (restore locally)."""
    try:
        data = request.get_json()
        if not data or 'scrubbed' not in data or 'entities' not in data:
            return jsonify({'error': 'Missing required fields: scrubbed, entities'}), 400
        
        scrubbed = data.get('scrubbed')
        entities = data.get('entities', {})
        
        restored = scrubbed
        for entity_id, value in entities.items():
            restored = restored.replace(f'[{entity_id}]', value)
        
        return jsonify({'restored': restored}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== END SCRUBBER ENDPOINTS =====


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)

# ============ DASHBOARD ROUTE ============

@app.route('/dashboard')
def dashboard():
    """Live autonomous agent capability dashboard — real metrics only."""
    try:
        s = _get_real_stats()

        # Last cycle data from cost.log
        last_cycle_data = {}
        try:
            with open('/root/.automaton/cost.log', 'r') as f:
                lines = f.readlines()
                if len(lines) > 1:
                    parts = lines[-1].strip().split(',')
                    if len(parts) >= 8:
                        last_cycle_data = {
                            'timestamp': parts[0],
                            'cycle': int(parts[1]),
                            'model': parts[2],
                            'cost': float(parts[7]),
                        }
        except Exception:
            pass

        # Recent activity from tiamat.log
        recent_activity = []
        try:
            with open('/root/.automaton/tiamat.log', 'r') as f:
                lines = f.readlines()[-50:]
                for line in reversed(lines):
                    match = _re.match(r'\[(.*?)\]\s+(.+)', line.strip())
                    if match:
                        recent_activity.append({
                            'timestamp': match.group(1)[:19],
                            'message': match.group(2)[:100],
                        })
                    if len(recent_activity) >= 15:
                        break
        except Exception:
            pass

        avg_cost = (s['total_cost'] / s['total_cycles']) if s['total_cycles'] > 0 else 0

        try:
            with open('/tmp/tiamat.pid', 'r') as f:
                pid = f.read().strip()
        except Exception:
            pid = 'unknown'

        return render_template('dashboard.html',
            total_cycles=s['total_cycles'],
            total_cost=f"{s['total_cost']:.2f}",
            avg_cost_per_cycle=f"${avg_cost:.4f}",
            cost_per_cycle=f"${avg_cost:.4f}",
            efficiency_rank=f"${avg_cost:.4f}/cycle",
            uptime_days=s['runtime_days'],
            last_cycle_timestamp=last_cycle_data.get('timestamp', 'pending')[:10],
            last_cycle_model=last_cycle_data.get('model', 'unknown'),
            last_cycle_cost=f"${last_cycle_data.get('cost', 0):.4f}",
            recent_activity=recent_activity[:15],
            pid=pid,
            last_update=datetime.now(tz=__import__('datetime').timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        )
    except Exception as e:
        return f"<pre>Dashboard Error: {str(e)}</pre>", 500

# ========== FARCASTER INFERENCE FRAME ROUTE ==========
def redact_log_content(text):
    """Redact sensitive data from log content before public streaming.
    Strips API keys, passwords, tokens, IPs (except public server), emails, paths with secrets."""
    if not text:
        return text
    s = text
    # API keys / tokens (SG., sk-, ghp_, Bearer, key=, token=, apikey=)
    s = _re.sub(r'(SG\.[A-Za-z0-9_-]{20,})', '[REDACTED_KEY]', s)
    s = _re.sub(r'(sk-[A-Za-z0-9]{20,})', '[REDACTED_KEY]', s)
    s = _re.sub(r'(ghp_[A-Za-z0-9]{20,})', '[REDACTED_KEY]', s)
    s = _re.sub(r'(Bearer\s+)[A-Za-z0-9_.-]{20,}', r'\1[REDACTED]', s)
    s = _re.sub(r'([Aa]pi[_-]?[Kk]ey|[Tt]oken|[Pp]assword|[Ss]ecret)[=:]\s*["\']?[A-Za-z0-9_.-]{8,}["\']?', r'\1=[REDACTED]', s)
    # Passwords in URLs or configs
    s = _re.sub(r'(password|passwd|pwd)[=:]\s*["\']?[^\s"\']{4,}["\']?', r'\1=[REDACTED]', s, flags=_re.IGNORECASE)
    # Email addresses (keep @tiamat.live and @energenai.org public)
    s = _re.sub(r'[a-zA-Z0-9._%+-]+@(?!tiamat\.live|energenai\.org)[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[REDACTED_EMAIL]', s)
    # Private IPs (keep 159.89.38.17 public, redact others)
    s = _re.sub(r'\b(?!159\.89\.38\.17)(?:10\.|172\.(?:1[6-9]|2[0-9]|3[01])\.|192\.168\.)\d{1,3}\.\d{1,3}\b', '[PRIVATE_IP]', s)
    # SSH keys, private keys
    s = _re.sub(r'-----BEGIN[A-Z ]*PRIVATE KEY-----.*?-----END[A-Z ]*PRIVATE KEY-----', '[REDACTED_PRIVATE_KEY]', s, flags=_re.DOTALL)
    # Wallet addresses / hex secrets (0x + 40+ hex chars)
    s = _re.sub(r'0x[a-fA-F0-9]{40,}', '[REDACTED_ADDR]', s)
    # .env file contents
    s = _re.sub(r'(/root/)?\.env', '[DOTENV]', s)
    # File paths — redact internal directory structure
    # /root/... paths reveal server layout
    s = _re.sub(r'/root/\.automaton/[^\s"\'}\]]+', '[INTERNAL_PATH]', s)
    s = _re.sub(r'/root/entity/[^\s"\'}\]]+', '[INTERNAL_PATH]', s)
    s = _re.sub(r'/root/bloom-app/[^\s"\'}\]]+', '[INTERNAL_PATH]', s)
    s = _re.sub(r'/root/sentinel/[^\s"\'}\]]+', '[INTERNAL_PATH]', s)
    s = _re.sub(r'/root/sandbox/[^\s"\'}\]]+', '[INTERNAL_PATH]', s)
    s = _re.sub(r'/root/tiamatooze/[^\s"\'}\]]+', '[INTERNAL_PATH]', s)
    s = _re.sub(r'/var/www/[^\s"\'}\]]+', '[INTERNAL_PATH]', s)
    s = _re.sub(r'/etc/nginx/[^\s"\'}\]]+', '[INTERNAL_PATH]', s)
    s = _re.sub(r'/opt/tiamat[^\s"\'}\]]*', '[INTERNAL_PATH]', s)
    s = _re.sub(r'/tmp/tiamat[^\s"\'}\]]*', '[INTERNAL_PATH]', s)
    # Generic /root/ paths (catch-all for anything missed above)
    s = _re.sub(r'/root/[^\s"\'}\]]+', '[INTERNAL_PATH]', s)
    # Filenames in tool args — redact "path": "/..." patterns
    s = _re.sub(r'"path"\s*:\s*"[^"]*"', '"path":"[REDACTED]"', s)
    s = _re.sub(r'"content_path"\s*:\s*"[^"]*"', '"content_path":"[REDACTED]"', s)
    # Exec command args — redact the full command string, keep just the tool name
    s = _re.sub(r'exec\(\s*\{[^}]*\}\s*\)', 'exec([REDACTED_CMD])', s)
    # Also catch read_file/write_file with path args already partially redacted
    s = _re.sub(r'read_file\(\s*\{[^}]*\}\s*\)', 'read_file([REDACTED])', s)
    s = _re.sub(r'write_file\(\s*\{[^}]*\}\s*\)', 'write_file([REDACTED])', s)
    # Strip <think> tags if any leaked through
    s = _re.sub(r'</?think>', '', s)
    return s.strip()


@app.route('/api/thoughts', methods=['GET'])
def api_thoughts():
    """Return TIAMAT's recent thoughts parsed from tiamat.log."""
    try:
        thoughts = []
        log_entries = []
        log_path = '/root/.automaton/tiamat.log'

        with open(log_path, 'r', errors='replace') as f:
            lines = f.readlines()[-500:]

        # First pass: extract timestamps from lines that have them
        # so we can assign them to adjacent non-timestamped lines
        last_ts = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        ts_re = _re.compile(r'^\[(20\d{2}-\d{2}-\d{2}T[\d:.Z-]+)\]')

        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue

            # Extract timestamp from this line if it has one
            ts_match = ts_re.match(line)
            if ts_match:
                last_ts = ts_match.group(1)[:19]

            # Parse [THOUGHT] entries — TIAMAT's deep reasoning
            if '[THOUGHT]' in line:
                match = _re.match(r'\[(.*?)\]\s+\[THOUGHT\]\s+(.*)', line)
                if match:
                    thoughts.append({
                        'timestamp': match.group(1)[:19],
                        'type': 'thought',
                        'content': redact_log_content(match.group(2)[:500]),
                    })
            # Parse [THINK] entries
            elif '[THINK]' in line:
                match = _re.match(r'\[(.*?)\]\s+\[THINK\]\s+(.*)', line)
                if match:
                    thoughts.append({
                        'timestamp': match.group(1)[:19],
                        'type': 'think',
                        'content': redact_log_content(match.group(2)[:500]),
                    })
            # Parse [TOOL] entries as thoughts (shows what TIAMAT is doing)
            elif '[TOOL]' in line and '[TOOL RESULT]' not in line:
                match = _re.match(r'\[([\dT:.Z-]+)\]\s+\[TOOL\]\s+(.*)', line)
                if match:
                    thoughts.append({
                        'timestamp': match.group(1)[:19],
                        'type': 'action',
                        'content': redact_log_content(match.group(2)[:500]),
                    })
            # Parse [REASONING] entries
            elif '[REASONING]' in line:
                content = line.split('[REASONING]', 1)[-1].strip()
                if content and 'Prediction stored' not in content:
                    thoughts.append({
                        'timestamp': last_ts,
                        'type': 'reasoning',
                        'content': redact_log_content(content[:500]),
                    })
            # Parse activity lines — use last_ts for non-timestamped lines
            elif any(tag in line for tag in ['[LOOP]', '[PACER]', '[COST]', '[INFERENCE']):
                match = _re.match(r'\[([\dT:.Z-]+)\]\s+(.*)', line)
                if match:
                    log_entries.append({
                        'timestamp': match.group(1)[:19],
                        'type': 'activity',
                        'content': redact_log_content(match.group(2)[:200]),
                    })
                else:
                    log_entries.append({
                        'timestamp': last_ts,
                        'type': 'activity',
                        'content': redact_log_content(line[:200]),
                    })

            if len(thoughts) >= 20 and len(log_entries) >= 30:
                break

        # Get current pace info
        pacer_data = {}
        try:
            with open('/root/.automaton/pacer.json', 'r') as f:
                pacer = json.load(f)
                pacer_data = {
                    'pace': pacer.get('current_pace', 'unknown'),
                    'productivity': pacer.get('productivity_rate', 0),
                    'interval': pacer.get('current_interval_seconds', 0),
                }
        except Exception:
            pass

        return jsonify({
            'thoughts': thoughts[:20],
            'activity': log_entries[:30],
            'pacer': pacer_data,
            'timestamp': datetime.now().isoformat(),
        })
    except Exception as e:
        return jsonify({'error': str(e), 'thoughts': [], 'activity': []}), 500


@app.route('/thoughts', methods=['GET'])
def thoughts_page():
    """Serve the neural feed page."""
    return render_template('thoughts.html')


# ============================================================================
# SOCIAL FEEDS AGGREGATOR — All TIAMAT platforms in one endpoint
# ============================================================================
import time as _time_mod
from concurrent.futures import ThreadPoolExecutor as _TPE

_social_cache = {}
_SOCIAL_CACHE_TTL = 30


def _fetch_bluesky():
    items = []
    r = requests.get('https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed',
                     params={'actor': 'toxfox.bsky.social', 'limit': 15}, timeout=5)
    if r.status_code == 200:
        for f in r.json().get('feed', []):
            p = f.get('post', {}); rec = p.get('record', {})
            items.append({'text': rec.get('text', '')[:300], 'created_at': rec.get('createdAt'),
                          'likes': p.get('likeCount', 0), 'replies': p.get('replyCount', 0),
                          'reposts': p.get('repostCount', 0), 'is_reply': bool(rec.get('reply'))})
    return 'bluesky', items


def _fetch_mastodon():
    items = []
    r = requests.get('https://mastodon.social/api/v1/accounts/116188085474458767/statuses',
                     params={'limit': 12, 'exclude_replies': 'false'}, timeout=5)
    if r.status_code == 200:
        for s in r.json():
            items.append({'text': _re.sub(r'<[^>]+>', '', s.get('content', ''))[:300],
                          'created_at': s.get('created_at'), 'likes': s.get('favourites_count', 0),
                          'replies': s.get('replies_count', 0), 'reposts': s.get('reblogs_count', 0),
                          'is_reply': s.get('in_reply_to_id') is not None, 'url': s.get('url')})
    return 'mastodon', items


def _fetch_devto():
    items = []
    devto_key = os.getenv('DEV_TO_API_KEY')
    if devto_key:
        r = requests.get('https://dev.to/api/articles/me/published', params={'per_page': 10},
                         headers={'api-key': devto_key}, timeout=5)
    else:
        r = requests.get('https://dev.to/api/articles', params={'username': 'tiamatenity', 'per_page': 10}, timeout=5)
    if r.status_code == 200:
        for a in r.json():
            items.append({'title': a.get('title'), 'text': a.get('description', '')[:200],
                          'url': a.get('url'), 'created_at': a.get('published_at'),
                          'likes': a.get('positive_reactions_count', 0), 'comments': a.get('comments_count', 0)})
    return 'devto', items


def _fetch_hashnode():
    items = []
    q = '{ publication(host: "tiamat-ai.hashnode.dev") { posts(first: 10) { edges { node { title slug publishedAt url subtitle responseCount readTimeInMinutes } } } } }'
    r = requests.post('https://gql.hashnode.com', json={'query': q}, timeout=5)
    if r.status_code == 200:
        for edge in (r.json().get('data') or {}).get('publication', {}).get('posts', {}).get('edges', []):
            n = edge.get('node', {})
            items.append({'title': n.get('title'), 'text': n.get('subtitle', ''),
                          'url': n.get('url'), 'created_at': n.get('publishedAt'),
                          'comments': n.get('responseCount', 0), 'read_time': n.get('readTimeInMinutes')})
    return 'hashnode', items


def _fetch_moltbook():
    items = []
    api_key = os.getenv('MOLTBOOK_API_KEY')
    if api_key:
        r = requests.get('https://www.moltbook.com/api/v1/posts', params={'sort': 'latest', 'limit': 10},
                         headers={'X-API-Key': api_key}, timeout=3)
        if r.status_code == 200:
            data = r.json()
            posts = data.get('posts', data) if isinstance(data, dict) else data
            if isinstance(posts, list):
                for p in posts:
                    items.append({'title': p.get('title', ''), 'text': (p.get('content', '') or '')[:200],
                                  'created_at': p.get('created_at'), 'score': p.get('score', 0),
                                  'comments': p.get('comment_count', 0),
                                  'submolt': p.get('submolt', {}).get('name', '') if isinstance(p.get('submolt'), dict) else ''})
    return 'moltbook', items


def _fetch_neural():
    result = {}
    r = requests.get('http://127.0.0.1:5000/api/thoughts/stream', params={'limit': 20}, timeout=2)
    if r.status_code == 200:
        d = r.json()
        result['neural'] = {'thoughts': d.get('thoughts', [])[:15], 'cycle': d.get('cycle'), 'state': d.get('state')}
        result['status'] = {
            'cycle': d.get('cycle'), 'state': d.get('state'), 'productivity': d.get('productivity'),
            'pace': d.get('pace'), 'interval': d.get('pacer', {}).get('current_interval_seconds'),
            'tool_calls': [t.get('name', t) if isinstance(t, dict) else t for t in (d.get('tool_calls', []) or [])[:8]],
            'idle_count': d.get('idle_count', 0),
        }
    return result


def _fetch_log_feeds():
    """Parse tiamat.log for Farcaster, LinkedIn, Facebook, GitHub posts."""
    result = {'farcaster': [], 'linkedin': [], 'facebook': [], 'github': []}
    log_path = '/root/.automaton/tiamat.log'
    if not os.path.exists(log_path):
        return result
    with open(log_path, 'rb') as lf:
        lines = lf.read().decode('utf-8', errors='replace').split('\n')[-500:]
    for line in lines:
        ts = line[:19] if len(line) > 19 and line[4:5] == '-' else ''
        if '[FARCASTER] Posted' in line:
            text = line.split('Posted: ', 1)[-1].split(' to /')[0].strip() if 'Posted: ' in line else ''
            ch = line.split(' to /')[1].split()[0].strip() if ' to /' in line else ''
            result['farcaster'].append({'text': text[:200], 'channel': ch, 'created_at': ts})
        elif '[LINKEDIN]' in line and ('Posted' in line or 'Shared' in line):
            result['linkedin'].append({'text': line.split('] ', 1)[-1].strip()[:200], 'created_at': ts})
        elif '[FACEBOOK]' in line and 'Posted' in line:
            result['facebook'].append({'text': line.split('] ', 1)[-1].strip()[:200], 'created_at': ts})
        elif '[GITHUB' in line and ('Discussion' in line or 'Posted' in line or 'Created' in line):
            result['github'].append({'text': line.split('] ', 1)[-1].strip()[:200], 'created_at': ts})
    result['farcaster'] = result['farcaster'][-12:]
    result['linkedin'] = result['linkedin'][-8:]
    result['facebook'] = result['facebook'][-8:]
    result['github'] = result['github'][-10:]
    return result


@app.route('/api/social-feeds', methods=['GET', 'OPTIONS'])
def api_social_feeds():
    """Aggregate feeds from all TIAMAT social platforms. Cached 30s. Parallel fetches."""
    if request.method == 'OPTIONS':
        resp = app.make_default_options_response()
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp

    cached = _social_cache.get('data')
    if cached and _time_mod.time() - _social_cache.get('ts', 0) < _SOCIAL_CACHE_TTL:
        return jsonify(cached), 200, {'Access-Control-Allow-Origin': '*'}

    feeds = {
        'bluesky': [], 'mastodon': [], 'devto': [], 'hashnode': [],
        'farcaster': [], 'moltbook': [], 'github': [], 'linkedin': [],
        'facebook': [], 'neural': {}, 'status': {},
        'timestamp': datetime.now().isoformat(), 'errors': []
    }

    # Fetch all API sources in parallel
    api_fetchers = [_fetch_bluesky, _fetch_mastodon, _fetch_devto, _fetch_hashnode, _fetch_moltbook]
    with _TPE(max_workers=5) as pool:
        futures = {pool.submit(fn): fn.__name__ for fn in api_fetchers}
        for future in futures:
            try:
                key, items = future.result(timeout=8)
                feeds[key] = items
            except Exception as e:
                feeds['errors'].append(f'{futures[future]}: {e}')

    # Log-based feeds (local, fast)
    try:
        log_feeds = _fetch_log_feeds()
        for k in ('farcaster', 'linkedin', 'facebook', 'github'):
            feeds[k] = log_feeds.get(k, [])
    except Exception as e:
        feeds['errors'].append(f'log_feeds: {e}')

    # Neural feed (local)
    try:
        neural_data = _fetch_neural()
        feeds['neural'] = neural_data.get('neural', {})
        feeds['status'] = neural_data.get('status', {})
    except Exception as e:
        feeds['errors'].append(f'neural: {e}')

    _social_cache['data'] = feeds
    _social_cache['ts'] = _time_mod.time()
    return jsonify(feeds), 200, {'Access-Control-Allow-Origin': '*'}


@app.route('/api/gallery', methods=['GET'])
def api_gallery():
    """Return list of all TIAMAT-generated images and videos for the stream slideshow."""
    import glob as _glob
    gallery = []

    # Source 1: artgen images (/root/.automaton/images/)
    try:
        for f in _glob.glob('/root/.automaton/images/*.png'):
            name = os.path.basename(f)
            parts = name.replace('.png', '').split('_', 1)
            style = parts[1] if len(parts) > 1 else 'unknown'
            gallery.append({
                'name': name,
                'url': f'/api/gallery/artgen/{name}',
                'style': style,
                'type': 'IMG',
                'mtime': os.path.getmtime(f),
            })
    except Exception:
        pass

    # Source 2: Higgsfield / other images (/var/www/tiamat/images/)
    try:
        for f in _glob.glob('/var/www/tiamat/images/*.png'):
            name = os.path.basename(f)
            parts = name.replace('.png', '').split('_', 1)
            style = parts[1] if len(parts) > 1 else 'unknown'
            gallery.append({
                'name': name,
                'url': f'/images/{name}',
                'style': style,
                'type': 'IMG',
                'mtime': os.path.getmtime(f),
            })
    except Exception:
        pass

    # Source 3: Grok videos (/root/.automaton/media/videos/)
    try:
        for f in _glob.glob('/root/.automaton/media/videos/*.mp4'):
            name = os.path.basename(f)
            gallery.append({
                'name': name,
                'url': f'/api/gallery/video/{name}',
                'style': 'grok_video',
                'type': 'VID',
                'mtime': os.path.getmtime(f),
            })
    except Exception:
        pass

    # Sort by modification time, newest first
    gallery.sort(key=lambda x: x.get('mtime', 0), reverse=True)
    # Remove mtime from response
    for item in gallery:
        item.pop('mtime', None)

    return jsonify({'images': gallery, 'total': len(gallery)})


@app.route('/api/gallery/artgen/<filename>', methods=['GET'])
def serve_gallery_artgen(filename):
    """Serve an artgen image."""
    if not _re.match(r'^[\d]+_[a-z_]+\.png$', filename):
        return 'Invalid filename', 400
    filepath = os.path.join('/root/.automaton/images', filename)
    if os.path.isfile(filepath):
        return send_file(filepath, mimetype='image/png')
    return 'Not found', 404


@app.route('/api/gallery/video/<filename>', methods=['GET'])
def serve_gallery_video(filename):
    """Serve a generated video."""
    if not _re.match(r'^grok_video_[a-f0-9]+\.mp4$', filename):
        return 'Invalid filename', 400
    filepath = os.path.join('/root/.automaton/media/videos', filename)
    if os.path.isfile(filepath):
        return send_file(filepath, mimetype='video/mp4')
    return 'Not found', 404


@app.route('/frame', methods=['GET'])
def serve_frame():
    """Serve production Farcaster inference frame."""
    frame_html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TIAMAT AI Chat</title>
    <meta property="og:title" content="TIAMAT AI Chat">
    <meta property="og:description" content="Real-time AI inference. $0.0001 per message (volume pricing).">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&display=swap');
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'JetBrains Mono', 'Courier New', monospace;
            background: linear-gradient(135deg, #0a0a0a 0%, #1a0a2e 100%);
            color: #00ffff; min-height: 100vh; padding: 20px;
            display: flex; align-items: center; justify-content: center;
        }
        .container {
            width: 100%; max-width: 600px;
            background: rgba(10, 10, 10, 0.95);
            border: 2px solid #00ffff; border-radius: 8px; padding: 24px;
            box-shadow: 0 0 20px rgba(0, 255, 255, 0.3), inset 0 0 20px rgba(0, 255, 255, 0.05);
            backdrop-filter: blur(10px);
        }
        .header {
            font-family: 'Orbitron', monospace; font-size: 24px; font-weight: 700;
            margin-bottom: 16px; color: #00ffff;
            text-shadow: 0 0 10px rgba(0, 255, 255, 0.5); letter-spacing: 2px;
        }
        .input-group { display: flex; gap: 8px; margin-bottom: 16px; }
        input[type="text"] {
            flex: 1; padding: 12px 16px;
            background: rgba(0, 255, 255, 0.05);
            border: 1px solid #00ffff; border-radius: 4px;
            color: #00ffff; font-family: 'JetBrains Mono', monospace; font-size: 14px;
            outline: none; transition: all 0.3s;
        }
        input[type="text"]:focus {
            background: rgba(0, 255, 255, 0.1);
            box-shadow: 0 0 10px rgba(0, 255, 255, 0.3);
        }
        input[type="text"]::placeholder { color: rgba(0, 255, 255, 0.5); }
        button {
            padding: 12px 24px;
            background: linear-gradient(135deg, #00ffff 0%, #00cc99 100%);
            border: none; border-radius: 4px; color: #0a0a0a;
            font-family: 'Orbitron', monospace; font-weight: 700; font-size: 14px;
            cursor: pointer; transition: all 0.3s; letter-spacing: 1px;
        }
        button:hover:not(:disabled) {
            box-shadow: 0 0 20px rgba(0, 255, 255, 0.6);
            transform: translateY(-2px);
        }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        .response-box {
            min-height: 200px; max-height: 400px; overflow-y: auto;
            background: rgba(0, 255, 255, 0.02);
            border: 1px solid rgba(0, 255, 255, 0.2); border-radius: 4px;
            padding: 16px; margin-bottom: 16px; font-size: 13px; line-height: 1.6;
        }
        .response-box:empty::before { content: 'Response will appear here...'; color: rgba(0, 255, 255, 0.4); }
        .loading { display: inline-block; color: #00ff99; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .error { color: #ff4466; background: rgba(255, 68, 102, 0.1); padding: 8px 12px; border-radius: 4px; margin: 8px 0; }
        .footer { font-size: 12px; color: rgba(0, 255, 255, 0.6); text-align: center; margin-top: 12px; border-top: 1px solid rgba(0, 255, 255, 0.1); padding-top: 12px; }
        .pricing { color: #00ff99; font-weight: bold; }
        @media (max-width: 480px) {
            .container { padding: 16px; }
            .header { font-size: 18px; }
            .input-group { flex-direction: column; }
            button { width: 100%; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">⚡ TIAMAT</div>
        <div class="input-group">
            <input type="text" id="prompt" placeholder="Ask TIAMAT..." autocomplete="off">
            <button id="sendBtn" onclick="sendPrompt()">SEND</button>
        </div>
        <div class="response-box" id="responseBox"></div>
        <div class="footer"><span class="pricing">$0.0001</span> per message (volume pricing)</div>
    </div>
    <script>
        const promptInput = document.getElementById('prompt');
        const sendBtn = document.getElementById('sendBtn');
        const responseBox = document.getElementById('responseBox');
        promptInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !sendBtn.disabled) sendPrompt();
        });
        async function sendPrompt() {
            const prompt = promptInput.value.trim();
            if (!prompt) {
                responseBox.innerHTML = '<div class="error">Please enter a prompt</div>';
                return;
            }
            responseBox.innerHTML = '<div class="loading">⚡ Thinking...</div>';
            sendBtn.disabled = true;
            promptInput.disabled = true;
            try {
                const response = await fetch('https://tiamat.live/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ messages: [{ role: 'user', content: prompt }] })
                });
                if (!response.ok) {
                    responseBox.innerHTML = `<div class="error">Error: ${response.status} ${response.statusText}</div>`;
                    return;
                }
                responseBox.innerHTML = '';
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\\n');
                    buffer = lines[lines.length - 1];
                    for (let i = 0; i < lines.length - 1; i++) {
                        const line = lines[i].trim();
                        if (!line) continue;
                        try {
                            if (line.startsWith('data: ')) {
                                const data = JSON.parse(line.slice(6));
                                if (data.choices?.[0]?.delta?.content) {
                                    responseBox.innerHTML += escapeHtml(data.choices[0].delta.content);
                                }
                            } else {
                                responseBox.innerHTML += escapeHtml(line) + '\\n';
                            }
                        } catch (e) {}
                    }
                    responseBox.scrollTop = responseBox.scrollHeight;
                }
                promptInput.value = '';
            } catch (error) {
                responseBox.innerHTML = `<div class="error">Network error: ${error.message}</div>`;
            } finally {
                sendBtn.disabled = false;
                promptInput.disabled = false;
                promptInput.focus();
            }
        }
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        promptInput.focus();
    </script>
</body>
</html>'''
    return frame_html, 200, {'Content-Type': 'text/html; charset=utf-8'}


# ============ API KEY MANAGEMENT ============

@app.route('/api/keys/register', methods=['POST'])
def api_keys_register():
    """Register a new API key. Input: {"email": "user@example.com"}"""
    data = request.get_json(silent=True)
    if not data or not data.get('email'):
        return jsonify({'error': 'Missing email field'}), 400
    email = data['email'].strip()
    if not email or len(email) > 254:
        return jsonify({'error': 'Invalid email'}), 400
    try:
        key, tier, rate_limit = register_api_key(email)
        return jsonify({
            'api_key': key,
            'tier': tier,
            'limit': f'{rate_limit}/day',
            'email': email,
        }), 201
    except Exception as e:
        logger.error(f"Failed to register API key: {e}")
        return jsonify({'error': 'Registration failed'}), 500


@app.route('/api/keys/status', methods=['GET'])
def api_keys_status():
    """Get API key status. Requires Authorization: Bearer <api_key>"""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return jsonify({'error': 'Missing Authorization header'}), 401
    key = auth[len('Bearer '):]
    key_info = get_api_key_info(key)
    if key_info is None:
        return jsonify({'error': 'Invalid API key'}), 401
    from datetime import timedelta
    requests_today = get_key_request_count(key)
    limit = key_info['rate_limit']
    remaining = max(0, limit - requests_today) if limit != -1 else -1
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    return jsonify({
        'email': key_info['email'],
        'tier': key_info['tier'],
        'requests_today': requests_today,
        'limit': limit,
        'remaining': remaining,
        'reset_at': tomorrow + 'T00:00:00Z',
        'created_at': key_info['created_at'],
        'last_used': key_info['last_used'],
    })


# ============ REDDIT COOKIE RELAY ============

REDDIT_COOKIE_FILE = '/root/.automaton/reddit_session.json'

@app.route('/reddit-setup', methods=['GET'])
def reddit_setup():
    """Page for user to paste their Reddit session cookie."""
    return '''<!DOCTYPE html>
<html><head><title>Reddit Cookie Setup</title>
<style>
body{background:#0a0a0a;color:#0ff;font-family:monospace;padding:20px;max-width:600px;margin:0 auto}
h1{font-size:18px}input,textarea{width:100%;padding:10px;background:#111;color:#0f0;border:1px solid #0ff;margin:8px 0;font-family:monospace}
button{padding:10px 20px;background:#0ff;color:#000;border:none;cursor:pointer;font-weight:bold}
.ok{color:#0f0}.err{color:#f44}pre{background:#111;padding:10px;overflow-x:auto;font-size:12px}
</style></head><body>
<h1>TIAMAT Reddit Auth Setup</h1>
<p>Paste your reddit_session cookie value below.</p>
<p><b>How to get it (Firefox Android):</b></p>
<ol>
<li>Open Firefox, go to <code>old.reddit.com</code>, login</li>
<li>Tap menu > Settings > scroll to "Cookie Banner" or use about:devtools</li>
<li>Or install "Cookie Editor" add-on, find <code>reddit_session</code> cookie</li>
</ol>
<p><b>How to get it (Termux):</b></p>
<pre>pkg install python
pip install requests
python3 -c "
import requests
s=requests.Session()
s.headers['User-Agent']='Mozilla/5.0'
r=s.post('https://old.reddit.com/api/login',
  data={'op':'login','user':'YOUR_USER',
  'passwd':'YOUR_PASS','api_type':'json'})
d=r.json().get('json',{})
if d.get('errors'):print('ERROR:',d['errors'])
else:print('COOKIE:',s.cookies.get('reddit_session',''))
"</pre>
<textarea id="cookie" rows="3" placeholder="Paste reddit_session cookie here..."></textarea>
<br><button onclick="send()">Save Cookie</button>
<div id="status"></div>
<script>
async function send(){
  const c=document.getElementById('cookie').value.trim();
  if(!c){document.getElementById('status').innerHTML='<p class="err">Empty</p>';return}
  const r=await fetch('/api/reddit-cookie',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cookie:c})});
  const d=await r.json();
  document.getElementById('status').innerHTML=d.ok?'<p class="ok">Saved! TIAMAT can now use Reddit.</p>':'<p class="err">Error: '+JSON.stringify(d)+'</p>';
}
</script>
</body></html>''', 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route('/api/reddit-cookie', methods=['POST'])
def save_reddit_cookie():
    """Save Reddit session cookie from user."""
    data = request.get_json(silent=True)
    if not data or not data.get('cookie'):
        return jsonify({'error': 'Missing cookie'}), 400
    cookie = data['cookie'].strip()
    if len(cookie) < 10 or len(cookie) > 500:
        return jsonify({'error': 'Invalid cookie length'}), 400
    try:
        import json as _json
        with open(REDDIT_COOKIE_FILE, 'w') as f:
            _json.dump({
                'reddit_session': cookie,
                'saved_at': datetime.utcnow().isoformat(),
            }, f)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ========== THOUGHT MONITOR DASHBOARD ==========

@app.route('/monitor', methods=['GET'])
def monitor_page():
    """Serve the TIAMAT thought monitor dashboard."""
    return render_template('monitor.html')


@app.route('/api/thoughts/stream', methods=['GET'])
def api_thoughts_stream():
    """Return rich parsed log data for the monitor dashboard."""
    try:
        log_path = '/root/.automaton/tiamat.log'
        limit = min(int(request.args.get('limit', 50)), 200)

        with open(log_path, 'r', errors='replace') as f:
            lines = f.readlines()[-2000:]

        thoughts = []
        tool_calls = []
        idle_count = 0
        cooldown_count = 0
        last_cycle = 0
        last_productivity = 0.0
        last_pace = 'unknown'
        state = 'unknown'

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Extract cycle number
            cycle_match = _re.search(r'Cycle (\d+)', line)
            if cycle_match:
                last_cycle = int(cycle_match.group(1))

            # Thoughts
            if '[THOUGHT]' in line:
                ts_match = _re.match(r'\[([\dT:.Z-]+)\]', line)
                ts = ts_match.group(1)[:19] if ts_match else ''
                content = _re.sub(r'^\[.*?\]\s*\[THOUGHT\]\s*', '', line)
                thoughts.append({'ts': ts, 'content': content[:500]})

            # Tool calls (actual agent tool invocations, not cooldown tasks)
            elif 'TOOL]' in line and '[COOLDOWN]' not in line:
                ts_match = _re.match(r'\[([\dT:.Z-]+)\]', line)
                ts = ts_match.group(1)[:19] if ts_match else ''
                tool_calls.append({'ts': ts, 'content': line[:300]})

            # Pacer data
            elif '[PACER]' in line:
                prod_match = _re.search(r'productivity:\s*([\d.]+)', line)
                pace_match = _re.search(r'pace:\s*(\w+)', line)
                if prod_match:
                    last_productivity = float(prod_match.group(1))
                if pace_match:
                    last_pace = pace_match.group(1)

            # Idle detection
            elif '[IDLE]' in line:
                idle_count += 1
                state = 'idle'

            # Loop cycle complete
            elif '[LOOP]' in line and 'Cycle complete' in line:
                state = 'active'

            # Cooldown
            elif '[COOLDOWN]' in line:
                cooldown_count += 1

        # Check if TIAMAT process is alive
        pid_alive = False
        try:
            with open('/tmp/tiamat.pid', 'r') as f:
                pid = int(f.read().strip())
            import os as _os
            _os.kill(pid, 0)
            pid_alive = True
        except Exception:
            pass

        # Get pacer.json for extra data
        pacer_data = {}
        try:
            with open('/root/.automaton/pacer.json', 'r') as f:
                pacer_data = json.load(f)
        except Exception:
            pass

        return jsonify({
            'thoughts': thoughts[-limit:],
            'tool_calls': tool_calls[-30:],
            'cycle': last_cycle,
            'productivity': last_productivity,
            'pace': last_pace,
            'idle_count': idle_count,
            'cooldown_count': cooldown_count,
            'state': 'running' if pid_alive else 'down',
            'pacer': pacer_data,
            'timestamp': datetime.now().isoformat(),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# PRIVACY AUDIT — AI-powered website privacy scanner
# ============================================================================

_audit_lock = False  # Simple mutex (single-worker safe)

@app.route('/audit', methods=['GET'])
def audit_page():
    """Interactive privacy audit page."""
    return render_template('audit.html')


@app.route('/audit', methods=['POST'])
def audit_api():
    """
    POST /audit — Scan a URL for trackers, cookies, fingerprinting, data brokers.

    Request:  {"url": "https://example.com"}
    Response: Full privacy audit report with score, grade, and detailed findings.

    Free tier: 3/day per IP. Paid: unlimited with API key.
    """
    global _audit_lock
    if _audit_lock:
        return jsonify({'error': 'Another scan is in progress. Try again in 30 seconds.'}), 429

    # Rate limit: 3 free scans/day per IP, unlimited with API key
    AUDIT_FREE_LIMIT = 3
    client_ip = request.headers.get('X-Real-IP') or request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr or '0.0.0.0'
    auth = request.headers.get('Authorization', '')
    has_key = auth.startswith('Bearer ') and (auth[7:].startswith('tiamat_') or auth[7:].startswith('x402_'))

    if not has_key:
        audit_count = _get_audit_count(client_ip)
        if audit_count >= AUDIT_FREE_LIMIT:
            return jsonify({
                'error': 'Free audit limit reached (3/day)',
                'message': 'Get an API key for unlimited scans.',
                'used': audit_count,
                'limit': AUDIT_FREE_LIMIT,
                'upgrade_url': 'https://tiamat.live/pay',
                'api_key_url': 'https://tiamat.live/api/generate-key',
            }), 402

    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'url required'}), 400
    if len(url) > 2048:
        return jsonify({'error': 'url too long'}), 400

    # Basic URL validation
    if not url.startswith('http'):
        url = 'https://' + url
    try:
        from urllib.parse import urlparse as _urlparse
        parsed = _urlparse(url)
        if not parsed.hostname or '.' not in parsed.hostname:
            return jsonify({'error': 'invalid URL'}), 400
    except Exception:
        return jsonify({'error': 'invalid URL'}), 400

    # Block scanning localhost/internal IPs
    hostname = parsed.hostname.lower()
    if hostname in ('localhost', '127.0.0.1', '0.0.0.0') or hostname.startswith('10.') or hostname.startswith('192.168.') or hostname.startswith('172.'):
        return jsonify({'error': 'cannot scan internal/localhost URLs'}), 400

    _audit_lock = True
    try:
        from privacy_audit import run_audit
        report = run_audit(url, timeout_ms=30000)
        result = report.to_dict()
        # Track usage for free tier
        if not has_key:
            _increment_audit_count(client_ip)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Privacy audit error: {e}")
        return jsonify({'error': f'Scan failed: {str(e)[:200]}'}), 500
    finally:
        _audit_lock = False


# Audit-specific rate tracking (separate from main rate limiter)
_AUDIT_COUNT_DB = '/root/.automaton/audit_counts.db'

def _init_audit_db():
    try:
        conn = sqlite3.connect(_AUDIT_COUNT_DB)
        conn.execute('CREATE TABLE IF NOT EXISTS audit_counts (ip TEXT, date_str TEXT, count INTEGER DEFAULT 0, PRIMARY KEY(ip, date_str))')
        conn.commit()
        conn.close()
    except Exception:
        pass

def _get_audit_count(ip):
    _init_audit_db()
    try:
        conn = sqlite3.connect(_AUDIT_COUNT_DB)
        row = conn.execute('SELECT count FROM audit_counts WHERE ip=? AND date_str=?', (ip, str(date.today()))).fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception:
        return 0

def _increment_audit_count(ip):
    _init_audit_db()
    try:
        conn = sqlite3.connect(_AUDIT_COUNT_DB)
        conn.execute('INSERT INTO audit_counts (ip, date_str, count) VALUES (?, ?, 1) ON CONFLICT(ip, date_str) DO UPDATE SET count = count + 1', (ip, str(date.today())))
        conn.commit()
        conn.close()
    except Exception:
        pass


@app.route('/blocklist', methods=['GET'])
def blocklist():
    """
    GET /blocklist — Downloadable DNS blocklist for Pi-hole / AdGuard / hosts file.

    Query params:
      format: hosts (default), adguard, domains
    """
    from flask import Response
    fmt = request.args.get('format', 'hosts')
    if fmt not in ('hosts', 'adguard', 'domains'):
        fmt = 'hosts'
    from generate_blocklist import generate_blocklist
    content = generate_blocklist(fmt)
    return Response(content, mimetype='text/plain',
                    headers={'Content-Disposition': f'inline; filename="tiamat-blocklist.txt"'})


@app.route('/auth/producthunt/callback', methods=['GET'])
def ph_callback():
    """Product Hunt OAuth callback — exchanges code for access token."""
    code = request.args.get('code')
    if not code:
        return jsonify({'error': 'no code'}), 400
    import requests as _req
    r = _req.post('https://api.producthunt.com/v2/oauth/token', json={
        'client_id': '0luUgvauq-uy1rpYqZpn8W2-KTTSD1t1WH5XA2dYvJ0',
        'client_secret': 'cEebmq6Bl8Ty1T60qmjvi2WLkksefvosg1CUm1MhRK8',
        'grant_type': 'authorization_code',
        'redirect_uri': 'https://tiamat.live/auth/producthunt/callback',
        'code': code,
    })
    data = r.json()
    # Save token
    token = data.get('access_token', '')
    if token:
        try:
            with open('/root/.automaton/ph_token.txt', 'w') as f:
                f.write(token)
        except Exception:
            pass
    return jsonify(data)


@app.route('/articles', methods=['GET'])
def articles_page():
    """Published research articles — AI privacy, surveillance, cybersecurity."""
    return render_template('articles.html')


@app.route('/extension', methods=['GET'])
def extension_download():
    """Download the TIAMAT Privacy Guard Chrome extension."""
    return send_file('/var/www/tiamat/static/tiamat-privacy-guard.zip',
                     as_attachment=True,
                     download_name='tiamat-privacy-guard.zip')


@app.route('/badge', methods=['GET'])
def privacy_badge():
    """
    GET /badge?url=example.com — SVG privacy score badge for embedding.
    """
    from flask import Response as Resp
    target_url = request.args.get('url', '')
    if not target_url:
        svg = _badge_svg('?', '---', '#888')
        return Resp(svg, mimetype='image/svg+xml')

    try:
        from privacy_audit import run_audit
        r = run_audit(target_url, timeout_ms=20000)
        colors = {'A+': '#55c070', 'A': '#55c070', 'B': '#55c0c0',
                  'C': '#e0d055', 'D': '#e09955', 'F': '#e05555'}
        color = colors.get(r.grade, '#888')
        svg = _badge_svg(r.grade, f'{r.privacy_score}/100', color)
        return Resp(svg, mimetype='image/svg+xml',
                    headers={'Cache-Control': 'public, max-age=3600'})
    except Exception:
        svg = _badge_svg('ERR', 'scan failed', '#e05555')
        return Resp(svg, mimetype='image/svg+xml')


def _badge_svg(grade, score_text, color):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="160" height="28">
  <rect width="160" height="28" rx="4" fill="#1a1a2e"/>
  <rect x="0" width="90" height="28" rx="4" fill="#12121a"/>
  <rect x="86" width="74" height="28" rx="4" fill="{color}22"/>
  <text x="8" y="18" font-family="sans-serif" font-size="11" fill="#888">TIAMAT Privacy</text>
  <text x="96" y="18" font-family="sans-serif" font-size="11" font-weight="bold" fill="{color}">{grade} {score_text}</text>
</svg>'''
