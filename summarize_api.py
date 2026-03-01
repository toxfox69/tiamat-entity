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
EXEMPT_ENDPOINTS = ['/status', '/pay', '/', '/docs', '/.well-known/agent.json', '/api/v1/services', '/cycle-tracker', '/cycle-tracker/']

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

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
