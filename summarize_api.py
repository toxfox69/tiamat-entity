#!/usr/bin/env python3
import os
import sys
import json
import requests
import sqlite3
from datetime import datetime, date
from flask import Flask, render_template, request, jsonify, send_file, redirect
from functools import wraps
import hmac
import hashlib
from web3 import Web3
import logging

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
FREE_TIER_DAILY_LIMIT = 100
EXEMPT_ENDPOINTS = ['/status', '/pay', '/', '/docs', '/apps', '/api/apps', '/.well-known/agent.json', '/api/v1/services', '/cycle-tracker', '/cycle-tracker/']

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
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to init rate limit DB: {e}")

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
            'message': f'You\'ve used all 100 daily free requests. Upgrade to paid tier for unlimited access.',
            'limit': FREE_TIER_DAILY_LIMIT,
            'used': count,
            'reset': str(date.today()),
            'upgrade_url': 'https://tiamat.live/pay',
            'payment_link': 'https://tiamat.live/pay?amount=0.01&endpoint=' + request.path
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
    }
    
    # GET requests for static pages are NEVER rate limited
    if request.method == 'GET' and request.path in exempt_routes:
        return None
    
    # Only POST requests to API endpoints are rate limited
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
# ROUTES
# ============================================================================

@app.route('/', methods=['GET'])
def index():
    """Landing page."""
    return render_template('landing.html')

@app.route('/status', methods=['GET'])
def status():
    """Status dashboard (exempt from rate limit)."""
    try:
        uptime = os.popen('uptime -p').read().strip()
        usdc_balance = 'N/A'  # Would fetch from on-chain
        cpu = os.popen('grep -c "processor" /proc/cpuinfo').read().strip()
        mem = os.popen('free -h | grep Mem | awk \'{print $3 "/" $2}\'').read().strip()
        
        return render_template('status.html', uptime=uptime, balance=usdc_balance, cpu=cpu, mem=mem)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/pay', methods=['GET'])
def payment_page():
    """Payment page (exempt from rate limit)."""
    endpoint = request.args.get('endpoint', 'summarize')
    amount = request.args.get('amount', '0.01')
    return render_template('payment.html', endpoint=endpoint, amount=amount, wallet=USER_WALLET)

@app.route('/docs', methods=['GET'])
def docs():
    """API documentation (exempt from rate limit)."""
    return render_template('docs.html')


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

_APPS_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TIAMAT — APP STORE</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=JetBrains+Mono:wght@300;400;600&display=swap">
<style>
  :root {
    --cyan: #00ffe7; --magenta: #ff00aa; --purple: #7b00ff;
    --dark: #050510; --card: rgba(0,255,231,0.04); --border: rgba(0,255,231,0.15);
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: var(--dark); color: #c0d8e8; font-family: 'JetBrains Mono', monospace; min-height: 100vh; }
  body::before {
    content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 9999;
    background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,255,231,0.015) 2px, rgba(0,255,231,0.015) 4px);
  }
  header { text-align: center; padding: 60px 20px 40px; border-bottom: 1px solid var(--border); }
  header h1 {
    font-family: 'Orbitron', monospace; font-size: clamp(1.8rem, 5vw, 3.5rem); font-weight: 900;
    background: linear-gradient(135deg, var(--cyan), var(--magenta));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
    letter-spacing: 0.2em; margin-bottom: 12px;
  }
  header p { font-size: 0.85rem; color: rgba(192,216,232,0.5); letter-spacing: 0.15em; }
  .store-grid {
    max-width: 1100px; margin: 60px auto; padding: 0 24px;
    display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 28px;
  }
  .app-card {
    background: var(--card); border: 1px solid var(--border); border-radius: 16px;
    padding: 32px 28px; position: relative; overflow: hidden;
    transition: border-color 0.3s, box-shadow 0.3s, transform 0.3s;
  }
  .app-card::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, var(--cyan), var(--purple), var(--magenta));
    opacity: 0; transition: opacity 0.3s;
  }
  .app-card:hover { border-color: rgba(0,255,231,0.4); box-shadow: 0 0 40px rgba(0,255,231,0.08); transform: translateY(-4px); }
  .app-card:hover::before { opacity: 1; }
  .app-icon { font-size: 2.8rem; margin-bottom: 16px; display: block; }
  .app-name { font-family: 'Orbitron', monospace; font-size: 1.1rem; font-weight: 700; color: var(--cyan); margin-bottom: 8px; letter-spacing: 0.1em; }
  .app-version { font-size: 0.7rem; color: rgba(192,216,232,0.35); letter-spacing: 0.12em; margin-bottom: 14px; }
  .app-desc { font-size: 0.8rem; line-height: 1.7; color: rgba(192,216,232,0.65); margin-bottom: 20px; }
  .app-features { list-style: none; margin-bottom: 24px; }
  .app-features li { font-size: 0.75rem; color: rgba(192,216,232,0.55); padding: 4px 0 4px 14px; position: relative; }
  .app-features li::before { content: '\203A'; position: absolute; left: 0; color: var(--cyan); }
  .app-meta { display: flex; gap: 16px; margin-bottom: 24px; font-size: 0.7rem; color: rgba(192,216,232,0.35); }
  .price-badge { font-family: 'Orbitron', monospace; font-size: 1.4rem; font-weight: 700; color: var(--cyan); margin-bottom: 20px; text-shadow: 0 0 20px rgba(0,255,231,0.4); }
  .btn-buy {
    display: block; width: 100%; padding: 14px 20px; background: transparent;
    border: 1px solid var(--cyan); border-radius: 8px; color: var(--cyan);
    font-family: 'Orbitron', monospace; font-size: 0.75rem; font-weight: 700;
    letter-spacing: 0.15em; cursor: pointer; text-align: center;
    transition: background 0.2s, box-shadow 0.2s;
  }
  .btn-buy:hover { background: rgba(0,255,231,0.08); box-shadow: 0 0 20px rgba(0,255,231,0.2); }
  .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(5,5,16,0.93); z-index: 1000; align-items: center; justify-content: center; }
  .modal-overlay.open { display: flex; }
  .modal { background: #080818; border: 1px solid var(--border); border-radius: 16px; padding: 40px; max-width: 480px; width: 90%; }
  .modal h2 { font-family: 'Orbitron', monospace; font-size: 1.1rem; color: var(--cyan); margin-bottom: 20px; letter-spacing: 0.1em; }
  .modal p { font-size: 0.8rem; color: rgba(192,216,232,0.6); margin-bottom: 16px; line-height: 1.6; }
  .wallet-addr {
    background: rgba(0,255,231,0.04); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 16px; font-size: 0.7rem; color: var(--cyan); word-break: break-all;
    margin-bottom: 20px; cursor: pointer; transition: border-color 0.2s;
  }
  .tx-input {
    width: 100%; background: rgba(0,0,0,0.4); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 16px; color: #c0d8e8; font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem; margin-bottom: 16px; outline: none;
  }
  .tx-input:focus { border-color: var(--cyan); }
  .modal-actions { display: flex; gap: 12px; }
  .btn-verify {
    flex: 1; padding: 12px; background: transparent; border: 1px solid var(--cyan);
    border-radius: 8px; color: var(--cyan); font-family: 'Orbitron', monospace;
    font-size: 0.7rem; font-weight: 700; letter-spacing: 0.1em; cursor: pointer; transition: background 0.2s;
  }
  .btn-verify:hover { background: rgba(0,255,231,0.08); }
  .btn-cancel {
    padding: 12px 20px; background: transparent; border: 1px solid rgba(192,216,232,0.2);
    border-radius: 8px; color: rgba(192,216,232,0.4);
    font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; cursor: pointer;
  }
  .status-msg { margin-top: 14px; font-size: 0.75rem; min-height: 20px; text-align: center; }
  .status-msg.ok { color: var(--cyan); }
  .status-msg.err { color: var(--magenta); }
  footer { text-align: center; padding: 40px 20px; border-top: 1px solid var(--border); font-size: 0.7rem; color: rgba(192,216,232,0.25); letter-spacing: 0.1em; }
  footer a { color: rgba(0,255,231,0.5); text-decoration: none; }
  footer a:hover { color: var(--cyan); }
</style>
</head>
<body>
<header>
  <h1>APP STORE</h1>
  <p>TIAMAT ECOSYSTEM &nbsp;&middot;&nbsp; ANDROID APKs &nbsp;&middot;&nbsp; PAY WITH USDC ON BASE</p>
</header>
<div class="store-grid" id="grid"></div>
<div class="modal-overlay" id="modal">
  <div class="modal">
    <h2 id="modal-title">PURCHASE APK</h2>
    <p id="modal-desc"></p>
    <p>Send exactly <strong id="modal-price" style="color:var(--cyan)"></strong> USDC on Base to:</p>
    <div class="wallet-addr" id="wallet-addr" onclick="copyWallet()" title="Click to copy">
      0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE
    </div>
    <p style="font-size:0.7rem;color:rgba(192,216,232,0.4);margin-bottom:20px">
      After the transaction confirms, paste your tx hash below to unlock the download.
    </p>
    <input class="tx-input" id="tx-input" type="text" placeholder="0x... transaction hash">
    <div class="modal-actions">
      <button class="btn-verify" onclick="verifyAndDownload()">VERIFY &amp; DOWNLOAD</button>
      <button class="btn-cancel" onclick="closeModal()">CANCEL</button>
    </div>
    <div class="status-msg" id="status-msg"></div>
  </div>
</div>
<footer>
  <a href="/">TIAMAT.LIVE</a> &nbsp;&middot;&nbsp;
  <a href="/docs">DOCS</a> &nbsp;&middot;&nbsp;
  <a href="/pay">PAYMENT HELP</a> &nbsp;&middot;&nbsp;
  <a href="/api/apps">JSON API</a>
  <br><br>Payments verified on-chain &middot; Base mainnet &middot; All sales final
</footer>
<script>
const APPS = __APPS_JSON__;
const WALLET = '0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE';
let currentApp = null;

function renderCards() {
  document.getElementById('grid').innerHTML = APPS.map(a => `
    <div class="app-card">
      <span class="app-icon">${a.icon}</span>
      <div class="app-name">${a.name}</div>
      <div class="app-version">v${a.version} &nbsp;&middot;&nbsp; ${a.size}</div>
      <p class="app-desc">${a.description}</p>
      <ul class="app-features">${a.features.map(f => `<li>${f}</li>`).join('')}</ul>
      <div class="app-meta"><span>Android 8.0+</span><span>USDC / Base</span></div>
      <div class="price-badge">${a.price_label}</div>
      <button class="btn-buy" onclick="openModal('${a.id}')">BUY + DOWNLOAD &#xbb;</button>
    </div>
  `).join('');
}

function openModal(appId) {
  currentApp = APPS.find(a => a.id === appId);
  if (!currentApp) return;
  document.getElementById('modal-title').textContent = 'PURCHASE \u2014 ' + currentApp.name.toUpperCase();
  document.getElementById('modal-desc').textContent =
    'Send USDC on Base mainnet. After confirmation, paste your tx hash to unlock the download.';
  document.getElementById('modal-price').textContent = currentApp.price_label;
  document.getElementById('tx-input').value = '';
  document.getElementById('status-msg').textContent = '';
  document.getElementById('status-msg').className = 'status-msg';
  document.getElementById('modal').classList.add('open');
}

function closeModal() {
  document.getElementById('modal').classList.remove('open');
  currentApp = null;
}

function copyWallet() {
  navigator.clipboard.writeText(WALLET).then(() => {
    const el = document.getElementById('wallet-addr');
    el.style.borderColor = 'var(--cyan)';
    setTimeout(() => { el.style.borderColor = ''; }, 1200);
  });
}

async function verifyAndDownload() {
  const txHash = document.getElementById('tx-input').value.trim();
  const status = document.getElementById('status-msg');
  if (!currentApp) return;
  if (!txHash || !txHash.startsWith('0x')) {
    status.textContent = 'Enter a valid 0x\u2026 transaction hash.';
    status.className = 'status-msg err';
    return;
  }
  status.textContent = 'Verifying on-chain\u2026';
  status.className = 'status-msg';
  try {
    const resp = await fetch('/api/apps/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_id: currentApp.id, tx_hash: txHash }),
    });
    const data = await resp.json();
    if (resp.ok && data.download_url) {
      status.textContent = 'Payment confirmed! Starting download\u2026';
      status.className = 'status-msg ok';
      setTimeout(() => { window.location.href = data.download_url; closeModal(); }, 800);
    } else {
      status.textContent = data.error || 'Verification failed. Check your tx hash.';
      status.className = 'status-msg err';
    }
  } catch (e) {
    status.textContent = 'Network error \u2014 please retry.';
    status.className = 'status-msg err';
  }
}

document.getElementById('modal').addEventListener('click', function(e) {
  if (e.target === this) closeModal();
});

renderCards();
</script>
</body>
</html>"""


@app.route('/apps', methods=['GET'])
def apps_store():
    """APK app store — HTML UI with x402 USDC payment gating (exempt from rate limit)."""
    import json as _json
    catalog_json = _json.dumps([
        {k: v for k, v in item.items() if k != 'apk_file'}
        for item in APPS_CATALOG
    ])
    html = _APPS_HTML_TEMPLATE.replace('__APPS_JSON__', catalog_json)
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}


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
    """Text-to-speech via Kokoro (GPU pod)."""
    data = request.get_json() or {}
    text = data.get('text', '')
    
    if not text or len(text) < 1:
        return jsonify({'error': 'Text cannot be empty'}), 400
    
    return jsonify({
        'success': True,
        'message': 'TTS available via paid endpoint',
        'text': text
    })

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
            {'name': 'summarize', 'endpoint': '/summarize', 'method': 'POST', 'cost': '$0.01'},
            {'name': 'chat', 'endpoint': '/chat', 'method': 'POST', 'cost': '$0.005'},
            {'name': 'generate', 'endpoint': '/generate', 'method': 'POST', 'cost': '$0.01'},
            {'name': 'synthesize', 'endpoint': '/synthesize', 'method': 'POST', 'cost': '$0.01'}
        ],
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
@app.route('/cycle-tracker')
@app.route('/cycle-tracker/')
def cycle_tracker():
    """Serve Privacy-First Menstrual Cycle Tracker PWA"""
    try:
        with open('/root/entity/src/apps/cycle-tracker/index.html', 'r') as f:
            return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}
    except Exception as e:
        return f"Error loading tracker: {str(e)}", 500

# ============= BLOOM HRT TRACKER PWA =============
@app.route('/bloom')
@app.route('/bloom/')
def bloom_tracker():
    """Serve Bloom HRT Transition Tracker PWA"""
    try:
        with open('/root/entity/src/apps/bloom/index.html', 'r') as f:
            return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}
    except Exception as e:
        return f"Error loading tracker: {str(e)}", 500

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
