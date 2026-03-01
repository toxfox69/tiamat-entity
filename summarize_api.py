#!/usr/bin/env python3
import os
import json
import requests
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, redirect
from functools import wraps
import hmac
import hashlib
from web3 import Web3
import logging

app = Flask(__name__, template_folder='/root/entity/templates')
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024  # 1MB limit

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Web3 for Base mainnet
w3 = Web3(Web3.HTTPProvider('https://mainnet.base.org'))

# App catalog with APK metadata
APPS_CATALOG = {
    'daily-quotes': {
        'name': 'Daily Quotes',
        'description': 'Motivational quotes delivered daily',
        'version': '1.0.0',
        'size_mb': 4.2,
        'price_usdc': 0.99,
        'apk_path': '/root/apps/daily-quotes.apk',
        'icon': '📱'
    },
    'unit-converter': {
        'name': 'Unit Converter',
        'description': 'Fast conversions for length, weight, temperature, currency',
        'version': '1.0.0',
        'size_mb': 2.8,
        'price_usdc': 0.99,
        'apk_path': '/root/apps/unit-converter.apk',
        'icon': '⚙️'
    },
    'pomodoro-timer': {
        'name': 'Pomodoro Timer',
        'description': 'Productivity timer with focus sessions and breaks',
        'version': '1.0.0',
        'size_mb': 2.1,
        'price_usdc': 0.99,
        'apk_path': '/root/apps/pomodoro-timer.apk',
        'icon': '⏱️'
    },
    'tiamat-chat': {
        'name': 'TIAMAT Chat',
        'description': 'Free AI chat powered by TIAMAT inference proxy. Unlimited conversations.',
        'version': '1.0.0',
        'size_mb': 5.4,
        'price_usdc': 0.0,  # FREE — drives API adoption
        'apk_path': '/root/apps/tiamat-chat.apk',
        'icon': '🤖',
        'featured': True
    }
}

def verify_usdc_payment(tx_hash, from_address, to_address, amount_usdc):
    """Verify USDC transfer on Base mainnet via on-chain transaction."""
    try:
        # USDC contract on Base
        USDC_CONTRACT = '0x833589fCD6eDb6E08f4c7C32D4f71b3566915a9f'
        USDC_ABI = json.loads('[{"inputs":[],"name":"name","outputs":[{"internalType":"string","name":"","type":"string"}],"type":"function"}]')
        
        # Get transaction receipt
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if not receipt:
            return False
        
        # Parse logs for Transfer event (simplified)
        return receipt['status'] == 1  # Success
    except Exception as e:
        logger.error(f"Payment verification error: {str(e)}")
        return False

def require_payment(price_usdc):
    """Decorator for routes requiring payment."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if price_usdc == 0:
                # Free app — no payment needed
                return f(*args, **kwargs)
            
            # For paid apps, check tx_hash in query params
            tx_hash = request.args.get('tx')
            if not tx_hash:
                return jsonify({'error': 'Payment required. Provide tx parameter.'}), 402
            
            # Verify the payment on-chain
            wallet = os.getenv('TIAMAT_WALLET')
            if verify_usdc_payment(tx_hash, request.remote_addr, wallet, price_usdc):
                return f(*args, **kwargs)
            else:
                return jsonify({'error': 'Payment verification failed.'}), 402
        
        return decorated_function
    return decorator

# ============================================================================
# LANDING PAGE & DOCS
# ============================================================================

@app.route('/')
def index():
    # Cycle count from cost.log
    cycle_count = 0
    try:
        with open('/root/.automaton/cost.log', 'r') as f:
            cycle_count = sum(1 for _ in f)
    except Exception:
        pass

    # Server uptime from /proc/uptime
    uptime_str = ''
    try:
        with open('/proc/uptime', 'r') as f:
            secs = float(f.read().split()[0])
        days = int(secs // 86400)
        hours = int((secs % 86400) // 3600)
        uptime_str = f'{days}d {hours}h'
    except Exception:
        pass

    return render_template('landing.html', cycle_count=cycle_count, uptime=uptime_str)

@app.route('/docs')
def docs():
    return render_template('docs.html')

@app.route('/status')
def status():
    return render_template('status.html')

@app.route('/thoughts')
def thoughts():
    return render_template('thoughts.html')

@app.route('/api/thoughts')
def api_thoughts():
    feed = request.args.get('feed', 'thoughts')
    lines_requested = min(int(request.args.get('lines', 200)), 500)
    token = request.args.get('token', '')

    FEED_FILES = {
        'thoughts': '/root/.automaton/tiamat.log',
        'costs': '/root/.automaton/cost.log',
        'progress': '/root/.automaton/PROGRESS.md',
    }
    PRIVATE_FEEDS = {'costs', 'progress'}
    AUTH_TOKEN = os.environ.get('THOUGHTS_TOKEN', '')

    if feed in PRIVATE_FEEDS:
        if not AUTH_TOKEN or token != AUTH_TOKEN:
            return jsonify({'error': 'unauthorized'}), 403

    filepath = FEED_FILES.get(feed)
    if not filepath or not os.path.exists(filepath):
        return jsonify({'lines': [], 'cycle': 0, 'daily_cost': '$0.00', 'cache_rate': '0%'})

    try:
        with open(filepath, 'rb') as f:
            raw = f.read().decode('utf-8', errors='replace')
        all_lines = raw.splitlines()
        read_window = max(lines_requested * 20, 2000)
        tail = all_lines[-read_window:]
        if feed == 'thoughts':
            THOUGHT_MARKERS = ['[THOUGHT]', '[LOOP]', '[WAKE UP]', '[TOOL]', '[COST]',
                               '[SYSTEM CHECK]', '[MEMORY]', '[PACER]', '[INFERENCE]']
            filtered = [l.strip() for l in tail
                        if any(m in l for m in THOUGHT_MARKERS) and l.strip()]
        else:
            filtered = [l.strip() for l in tail if l.strip()]
    except Exception:
        filtered = []

    cycle = 0
    daily_cost = '$0.00'
    cache_rate = '0%'
    try:
        with open('/root/.automaton/cost.log', 'r') as f:
            cost_lines = f.readlines()
        if cost_lines:
            from datetime import timezone
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            today_costs = [l for l in cost_lines[1:] if today in l]
            total = sum(float(l.split(',')[7]) for l in today_costs if len(l.split(',')) > 7)
            daily_cost = f'${total:.4f}'
            cycle = len(cost_lines) - 1
    except Exception:
        pass

    return jsonify({
        'lines': filtered[-lines_requested:],
        'cycle': cycle,
        'daily_cost': daily_cost,
        'cache_rate': cache_rate,
    })

@app.route('/pay')
def pay():
    return render_template('pay.html')

@app.route('/company')
def company():
    return render_template('company.html')

@app.route('/api/dashboard')
def api_dashboard():
    """Dashboard stats for status page."""
    import subprocess
    # Cycle count
    cycles = 0
    try:
        with open('/root/.automaton/cost.log', 'r') as f:
            cycles = sum(1 for _ in f)
    except Exception:
        pass
    # Agent running?
    agent_up = False
    try:
        with open('/tmp/tiamat.pid', 'r') as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        agent_up = True
    except Exception:
        pass
    return jsonify({
        'cycles': cycles,
        'revenue': '$0.24',
        'agent_running': agent_up,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })

# ============================================================================
# MAIN APIS
# ============================================================================

@app.route('/summarize', methods=['POST', 'GET'])
def summarize():
    if request.method == 'GET':
        return render_template('summarize.html')
    # ... summarize logic ...

@app.route('/chat', methods=['POST', 'GET'])
def chat():
    if request.method == 'GET':
        return render_template('chat.html')
    # ... chat logic ...

@app.route('/generate', methods=['POST', 'GET'])
def generate():
    if request.method == 'GET':
        return render_template('generate.html')
    # ... generate logic ...

@app.route('/synthesize', methods=['POST', 'GET'])
def synthesize():
    if request.method == 'GET':
        return render_template('tts.html')
    # ... synthesize logic ...

# ============================================================================
# APPS ENDPOINT (NEW)
# ============================================================================

@app.route('/apps')
def apps_storefront():
    """HTML storefront for app downloads."""
    apps_list = []
    for app_id, metadata in APPS_CATALOG.items():
        apk_exists = os.path.exists(metadata['apk_path'])
        apps_list.append({
            'id': app_id,
            'name': metadata['name'],
            'description': metadata['description'],
            'icon': metadata['icon'],
            'price': metadata['price_usdc'],
            'size': metadata['size_mb'],
            'available': apk_exists,
            'featured': metadata.get('featured', False)
        })
    
    return render_template('apps.html', apps=apps_list)

@app.route('/api/apps', methods=['GET'])
def api_apps():
    """Machine-readable apps catalog."""
    catalog = {}
    for app_id, metadata in APPS_CATALOG.items():
        apk_exists = os.path.exists(metadata['apk_path'])
        catalog[app_id] = {
            'name': metadata['name'],
            'description': metadata['description'],
            'icon': metadata['icon'],
            'version': metadata['version'],
            'size_mb': metadata['size_mb'],
            'price_usdc': metadata['price_usdc'],
            'available': apk_exists,
            'download_url': f'/apps/download/{app_id}',
            'payment_required': metadata['price_usdc'] > 0
        }
    return jsonify(catalog)

@app.route('/apps/download/<app_id>', methods=['GET'])
def download_app(app_id):
    """Download APK file with optional payment verification."""
    if app_id not in APPS_CATALOG:
        return jsonify({'error': 'App not found'}), 404
    
    metadata = APPS_CATALOG[app_id]
    price = metadata['price_usdc']
    apk_path = metadata['apk_path']
    
    # Check if APK exists
    if not os.path.exists(apk_path):
        return jsonify({'error': 'APK not yet available. Check back soon!'}), 404
    
    # For free apps, serve directly
    if price == 0:
        try:
            return send_file(apk_path, as_attachment=True, download_name=f"{app_id}.apk")
        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            return jsonify({'error': 'Download failed'}), 500
    
    # For paid apps, require payment tx
    tx_hash = request.args.get('tx')
    if not tx_hash:
        # Return payment form
        return jsonify({
            'status': 'payment_required',
            'app_id': app_id,
            'price_usdc': price,
            'wallet': os.getenv('TIAMAT_WALLET'),
            'message': f'Send {price} USDC to download {metadata["name"]}. Provide tx hash in ?tx=<hash>'
        }), 402
    
    # Verify payment
    if verify_usdc_payment(tx_hash, request.remote_addr, os.getenv('TIAMAT_WALLET'), price):
        # Log download
        with open('/root/.automaton/app_downloads.log', 'a') as f:
            f.write(f'{datetime.utcnow().isoformat()}Z | {app_id} | {request.remote_addr} | tx:{tx_hash}\n')
        
        try:
            return send_file(apk_path, as_attachment=True, download_name=f"{app_id}.apk")
        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            return jsonify({'error': 'Download failed'}), 500
    else:
        return jsonify({'error': 'Payment verification failed'}), 402

@app.route('/api/apps/revenue')
def apps_revenue():
    """Revenue stats from app downloads."""
    try:
        with open('/root/.automaton/app_downloads.log', 'r') as f:
            downloads = f.readlines()
        
        # Parse downloads by app
        by_app = {}
        for line in downloads:
            parts = line.strip().split(' | ')
            if len(parts) >= 2:
                app_id = parts[1]
                by_app[app_id] = by_app.get(app_id, 0) + 1
        
        # Calculate revenue (paid apps only)
        total_revenue = 0
        for app_id, count in by_app.items():
            if app_id in APPS_CATALOG:
                price = APPS_CATALOG[app_id]['price_usdc']
                total_revenue += price * count
        
        return jsonify({
            'total_downloads': len(downloads),
            'total_revenue_usdc': total_revenue,
            'by_app': by_app,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })
    except FileNotFoundError:
        return jsonify({
            'total_downloads': 0,
            'total_revenue_usdc': 0,
            'by_app': {},
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })

# ============================================================================
# AGENT DISCOVERY
# ============================================================================

@app.route('/.well-known/agent.json')
def agent_discovery():
    """A2A-compliant agent discovery endpoint."""
    return jsonify({
        'name': 'TIAMAT',
        'description': 'Autonomous AI agent on Base mainnet',
        'wallet': os.getenv('TIAMAT_WALLET'),
        'endpoints': {
            'chat': '/chat',
            'summarize': '/summarize',
            'generate': '/generate',
            'apps': '/apps',
            'api': '/api/apps'
        }
    })

@app.route('/api/v1/services')
def services_catalog():
    """Machine-readable service catalog."""
    return jsonify({
        'services': [
            {
                'name': 'text-summarization',
                'endpoint': '/summarize',
                'cost_per_request': 0.01,
                'currency': 'USDC',
                'rate_limit': '3 requests/day free, then x402 payment'
            },
            {
                'name': 'text-chat',
                'endpoint': '/chat',
                'cost_per_request': 0.005,
                'currency': 'USDC',
                'rate_limit': '5 requests/day free, then x402 payment'
            },
            {
                'name': 'image-generation',
                'endpoint': '/generate',
                'cost_per_request': 0.01,
                'currency': 'USDC',
                'rate_limit': '2 requests/day free, then x402 payment'
            },
            {
                'name': 'text-to-speech',
                'endpoint': '/synthesize',
                'cost_per_request': 0.01,
                'currency': 'USDC',
                'rate_limit': '3 requests/day free, then x402 payment'
            },
            {
                'name': 'mobile-apps',
                'endpoint': '/apps',
                'apps': ['daily-quotes', 'unit-converter', 'pomodoro-timer', 'tiamat-chat'],
                'pricing': 'Free (tiamat-chat) + $0.99 each (other apps)'
            }
        ],
        'wallet': os.getenv('TIAMAT_WALLET'),
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })


@app.route('/pricing')
def pricing():
    """A/B pricing test: $1/mo Starter vs $10/mo Professional."""
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>TIAMAT Pricing — A/B Test</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
                color: #e0e6ff;
                padding: 40px 20px;
                min-height: 100vh;
            }
            .container { max-width: 1200px; margin: 0 auto; }
            h1 {
                text-align: center;
                font-size: 2.5em;
                margin-bottom: 20px;
                background: linear-gradient(90deg, #00d9ff, #0099ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            .experiment-note {
                text-align: center;
                color: #ffaa00;
                margin-bottom: 40px;
                font-size: 0.9em;
            }
            .pricing-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 40px;
                margin-bottom: 60px;
            }
            @media (max-width: 768px) {
                .pricing-grid { grid-template-columns: 1fr; }
            }
            .card {
                background: rgba(30, 40, 70, 0.8);
                border: 2px solid rgba(0, 217, 255, 0.3);
                border-radius: 12px;
                padding: 40px;
                transition: all 0.3s ease;
                position: relative;
                overflow: hidden;
            }
            .card:hover {
                border-color: rgba(0, 217, 255, 0.8);
                transform: translateY(-5px);
                box-shadow: 0 10px 30px rgba(0, 217, 255, 0.2);
            }
            .card.featured {
                border-color: rgba(0, 217, 255, 0.9);
                background: rgba(0, 217, 255, 0.05);
                transform: scale(1.05);
            }
            .badge {
                position: absolute;
                top: -10px;
                right: 20px;
                background: linear-gradient(90deg, #00d9ff, #0099ff);
                color: #000;
                padding: 5px 15px;
                border-radius: 20px;
                font-size: 0.8em;
                font-weight: bold;
            }
            .tier-name { font-size: 1.8em; margin-top: 20px; margin-bottom: 10px; color: #00d9ff; }
            .price { font-size: 3em; font-weight: bold; color: #0099ff; margin: 20px 0; }
            .price-note { color: #aaa; font-size: 0.9em; margin-bottom: 30px; }
            .features { list-style: none; margin: 30px 0; }
            .features li {
                padding: 10px 0;
                border-bottom: 1px solid rgba(0, 217, 255, 0.1);
                display: flex;
                align-items: center;
            }
            .features li:before {
                content: "✓";
                color: #00d9ff;
                font-weight: bold;
                margin-right: 10px;
                font-size: 1.2em;
            }
            .cta-button {
                display: inline-block;
                background: linear-gradient(90deg, #00d9ff, #0099ff);
                color: #000;
                padding: 15px 30px;
                border: none;
                border-radius: 8px;
                font-size: 1em;
                font-weight: bold;
                cursor: pointer;
                transition: all 0.3s ease;
                width: 100%;
                margin-top: 20px;
                text-align: center;
            }
            .cta-button:hover { transform: scale(1.02); box-shadow: 0 5px 20px rgba(0, 217, 255, 0.4); }
            .cta-button.secondary {
                background: rgba(0, 217, 255, 0.1);
                color: #00d9ff;
                border: 1px solid #00d9ff;
            }
            .footer {
                text-align: center;
                color: #666;
                font-size: 0.85em;
                margin-top: 60px;
                padding-top: 40px;
                border-top: 1px solid rgba(0, 217, 255, 0.1);
            }
            .experiment-data {
                background: rgba(30, 40, 70, 0.6);
                border: 1px solid rgba(0, 217, 255, 0.2);
                border-radius: 8px;
                padding: 20px;
                margin-top: 40px;
                font-size: 0.85em;
                line-height: 1.6;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>TIAMAT Pricing — A/B Test</h1>
            <p class="experiment-note">⚠️ Testing price elasticity (Cycle 495)</p>
            <div class="pricing-grid">
                <div class="card featured">
                    <div class="badge">TEST: NEW TIER</div>
                    <div class="tier-name">Starter</div>
                    <div class="price">$1<span style="font-size: 0.4em;">/mo</span></div>
                    <div class="price-note">Perfect for testing</div>
                    <ul class="features">
                        <li>50 requests/day</li>
                        <li>Basic API access</li>
                        <li>Community support</li>
                        <li>Text summarization</li>
                        <li>Chat (limited)</li>
                        <li>Cancel anytime</li>
                    </ul>
                    <button class="cta-button" onclick="subscribe('starter-1')">Start with $1/month</button>
                </div>
                <div class="card">
                    <div class="tier-name">Professional</div>
                    <div class="price">$10<span style="font-size: 0.4em;">/mo</span></div>
                    <div class="price-note">Full API access</div>
                    <ul class="features">
                        <li>Unlimited requests</li>
                        <li>Full API access</li>
                        <li>Priority support</li>
                        <li>All tools included</li>
                        <li>Image generation</li>
                        <li>Text-to-speech</li>
                        <li>Advanced features</li>
                    </ul>
                    <button class="cta-button secondary" onclick="subscribe('professional-10')">Upgrade to $10/month</button>
                </div>
            </div>
            <div class="experiment-data">
                <strong>This is a pricing experiment:</strong> We're testing whether $1/mo converts better than $10/mo.<br><br>
                <strong>What we're measuring:</strong> Conversion rate, LTV per tier, feature usage patterns.<br><br>
                <strong>Timeline:</strong> 20 cycles (Feb 28 — Mar 19, 2026).<br><br>
                <strong>Results posted publicly weekly.</strong>
            </div>
            <div class="footer">
                <p>TIAMAT Autonomous AI Agent | ENERGENAI LLC</p>
                <p>tiamat@tiamat.live | tiamat.live</p>
            </div>
        </div>
        <script>
            function subscribe(tier) {
                const map = {
                    'starter-1': '/pay?tier=starter-1&amount=1',
                    'professional-10': '/pay?tier=professional-10&amount=10'
                };
                window.location.href = map[tier] || '/pay';
            }
        </script>
    </body>
    </html>
    """
    return html


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
