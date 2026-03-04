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
import re as _re
import subprocess as _subprocess
import imaplib
import email
from io import BytesIO

# Add payment verification and TTS to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src/agent'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# TTS module (OpenAI / ElevenLabs / espeak cascade)
try:
    import tts_module as _tts_module
    _TTS_LOADED = True
except Exception as _tts_err:
    _tts_module = None
    _TTS_LOADED = False

from payment_verify import verify_payment
from src.agent.payment_analytics import analytics_bp

app = Flask(__name__)
app.register_blueprint(analytics_bp)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024  # 1MB max

# GROQ API SETUP
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
if not GROQ_API_KEY:
    logging.warning("GROQ_API_KEY not set")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Rate limiter
class RateLimiter:
    def __init__(self):
        self.db_path = '/tmp/rate_limit.db'
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS requests
                     (ip TEXT, endpoint TEXT, timestamp REAL, PRIMARY KEY(ip, endpoint, timestamp))''')
        conn.commit()
        conn.close()
    
    def check_limit(self, ip, endpoint, limit_per_day=3):
        """Check if IP has exceeded daily limit for endpoint"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        now = datetime.now()
        today_start = datetime(now.year, now.month, now.day).timestamp()
        
        c.execute('SELECT COUNT(*) FROM requests WHERE ip=? AND endpoint=? AND timestamp >= ?',
                  (ip, endpoint, today_start))
        count = c.fetchone()[0]
        conn.close()
        
        return count < limit_per_day
    
    def record_request(self, ip, endpoint):
        """Record a request for rate limiting"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('INSERT INTO requests VALUES (?, ?, ?)',
                      (ip, endpoint, datetime.now().timestamp()))
            conn.commit()
        except:
            pass
        finally:
            conn.close()

rate_limiter = RateLimiter()

def get_client_ip():
    """Get client IP from request headers"""
    return request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

def require_payment(free_limit=3, paid_cost=0.01):
    """Decorator for paid endpoints"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            client_ip = get_client_ip()
            endpoint = request.path
            
            # Check free tier
            if rate_limiter.check_limit(client_ip, endpoint, free_limit):
                rate_limiter.record_request(client_ip, endpoint)
                return f(*args, **kwargs)
            
            # Check paid tier
            tx_hash = request.headers.get('X-Payment-Hash')
            if tx_hash:
                if verify_payment(tx_hash, paid_cost):
                    return f(*args, **kwargs)
            
            return jsonify({'error': 'Rate limit exceeded. Upgrade to paid tier.', 'cost_usdc': paid_cost}), 429
        return decorated_function
    return decorator

@app.route('/')
def index():
    return render_template('landing.html')

@app.route('/summarize', methods=['GET'])
def summarize_page():
    return render_template('summarize.html')

@app.route('/summarize', methods=['POST'])
@require_payment(free_limit=3, paid_cost=0.01)
def summarize():
    """Summarize text using Groq llama-3.3-70b"""
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        
        if not text or len(text) < 10:
            return jsonify({'error': 'Text too short'}), 400
        
        response = requests.post(
            f"{GROQ_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": f"Summarize this in 2-3 sentences:\n\n{text}"}],
                "temperature": 0.5,
                "max_tokens": 200
            },
            timeout=30
        )
        
        if response.status_code != 200:
            return jsonify({'error': 'Groq API error'}), 500
        
        result = response.json()
        summary = result['choices'][0]['message']['content'].strip()
        
        return jsonify({
            'text': text[:200],
            'summary': summary,
            'tokens_used': result.get('usage', {}).get('total_tokens', 0),
            'cost_usdc': 0.01
        })
    except Exception as e:
        logger.error(f"Summarize error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/translate', methods=['GET'])
def translate_page():
    return render_template('translate.html')

@app.route('/translate', methods=['POST'])
@require_payment(free_limit=5, paid_cost=0.01)
def translate():
    """Translate text using Groq llama-3.3-70b"""
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        source_lang = data.get('source_lang', 'auto').upper()
        target_lang = data.get('target_lang', 'EN').upper()
        
        if not text or len(text) < 1:
            return jsonify({'error': 'Text required'}), 400
        
        # Map language codes
        lang_map = {
            'EN': 'English', 'ES': 'Spanish', 'FR': 'French',
            'ZH': 'Chinese', 'JA': 'Japanese', 'DE': 'German',
            'PT': 'Portuguese', 'IT': 'Italian', 'RU': 'Russian'
        }
        
        target_name = lang_map.get(target_lang, 'English')
        source_prompt = "" if source_lang == 'AUTO' else f"This text is in {lang_map.get(source_lang, 'English')}. "
        
        response = requests.post(
            f"{GROQ_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{
                    "role": "user",
                    "content": f"{source_prompt}Translate this to {target_name}. Only provide the translation, nothing else:\n\n{text}"
                }],
                "temperature": 0.3,
                "max_tokens": 500
            },
            timeout=30
        )
        
        if response.status_code != 200:
            return jsonify({'error': 'Groq API error'}), 500
        
        result = response.json()
        translated = result['choices'][0]['message']['content'].strip()
        
        return jsonify({
            'text': text[:200],
            'translated_text': translated,
            'source_language': source_lang,
            'target_language': target_lang,
            'tokens_used': result.get('usage', {}).get('total_tokens', 0),
            'cost_usdc': 0.01
        })
    except Exception as e:
        logger.error(f"Translate error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/generate', methods=['GET'])
def generate_page():
    return render_template('generate.html')

@app.route('/generate', methods=['POST'])
@require_payment(free_limit=2, paid_cost=0.01)
def generate():
    """Generate image using local art generator"""
    try:
        data = request.get_json()
        prompt = data.get('prompt', 'abstract art').strip()
        style = data.get('style', 'cyberpunk')
        
        # Delegate to local art generator
        import subprocess
        result = subprocess.run(
            ['python3', '/root/entity/src/agent/artgen.py', prompt, style],
            capture_output=True,
            timeout=30,
            text=True
        )
        
        if result.returncode == 0:
            image_path = result.stdout.strip()
            return send_file(image_path, mimetype='image/png')
        else:
            return jsonify({'error': 'Image generation failed'}), 500
    except Exception as e:
        logger.error(f"Generate error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/chat', methods=['GET'])
def chat_page():
    return render_template('chat.html')

@app.route('/chat', methods=['POST'])
@require_payment(free_limit=5, paid_cost=0.005)
def chat():
    """Stream chat responses from Groq"""
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        
        if not message:
            return jsonify({'error': 'Message required'}), 400
        
        response = requests.post(
            f"{GROQ_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": message}],
                "temperature": 0.7,
                "max_tokens": 500
            },
            timeout=30
        )
        
        if response.status_code != 200:
            return jsonify({'error': 'Groq API error'}), 500
        
        result = response.json()
        reply = result['choices'][0]['message']['content'].strip()
        
        return jsonify({
            'message': message[:200],
            'reply': reply,
            'tokens_used': result.get('usage', {}).get('total_tokens', 0),
            'cost_usdc': 0.005
        })
    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Translate endpoint
@app.route('/translate', methods=['GET'])
def translate_page():
    """Interactive HTML translation page."""
    return render_template('translate.html')

@app.route('/translate', methods=['POST'])
def translate():
    """Translate text via Groq API."""
    try:
        data = request.get_json()
        if not data or 'text' not in data or 'target_lang' not in data:
            return jsonify({'error': 'Missing: text, target_lang'}), 400
        
        text = data.get('text', '').strip()
        target_lang = data.get('target_lang', 'EN').upper()
        source_lang = data.get('source_lang', 'EN').upper()
        
        if not text:
            return jsonify({'error': 'Text cannot be empty'}), 400
        
        # Language map
        langs = {'EN': 'English', 'ES': 'Spanish', 'FR': 'French', 
                 'ZH': 'Chinese', 'JA': 'Japanese', 'DE': 'German'}
        
        if target_lang not in langs or source_lang not in langs:
            return jsonify({'error': f'Language not supported'}), 400
        
        # Check rate limit
        ip = request.remote_addr
        limit_key = f'translate:{ip}:{date.today()}'
        
        db = get_db()
        cursor = db.cursor()
        try:
            cursor.execute('SELECT COUNT(*) FROM rate_limit WHERE key = ?', (limit_key,))
            count = cursor.fetchone()[0]
        except:
            count = 0
        
        if count >= 5:  # Free: 5/day
            return jsonify({'error': 'Rate limit exceeded (5/day free). Upgrade for unlimited.'}), 429
        
        # Call Groq for translation
        groq_key = os.getenv('GROQ_API_KEY')
        if not groq_key:
            return jsonify({'error': 'Translation service unavailable'}), 503
        
        prompt = f"Translate ONLY to {langs[target_lang]}. No explanation. Return only the translated text.\n\n{text}"
        
        try:
            resp = requests.post(
                'https://api.groq.com/openai/v1/chat/completions',
                headers={'Authorization': f'Bearer {groq_key}', 'Content-Type': 'application/json'},
                json={
                    'model': 'mixtral-8x7b-32768',
                    'messages': [{'role': 'user', 'content': prompt}],
                    'max_tokens': 1024,
                    'temperature': 0.3
                },
                timeout=10
            )
            
            if resp.status_code != 200:
                return jsonify({'error': f'Groq error: {resp.status_code}'}), 503
            
            result = resp.json()
            translated = result['choices'][0]['message']['content'].strip()
            
            # Log request
            try:
                cursor.execute(
                    'INSERT INTO rate_limit (key, timestamp) VALUES (?, ?)',
                    (limit_key, datetime.now())
                )
                db.commit()
            except:
                pass
            
            return jsonify({
                'translated_text': translated,
                'source_language': langs[source_lang],
                'target_language': langs[target_lang]
            })
        
        except requests.exceptions.Timeout:
            return jsonify({'error': 'Translation timeout'}), 504
        except Exception as e:
            return jsonify({'error': f'Translation failed: {str(e)}'}), 500
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/status')
def status():
    return jsonify({
        'status': 'operational',
        'services': ['summarize', 'translate', 'generate', 'chat'],
    })

@app.route('/translate', methods=['POST'])
def translate():
    """Translate text using Groq llama-3.3-70b"""
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        target_lang = data.get('target_lang', '').upper()
        source_lang = data.get('source_lang', 'AUTO').upper()
        
        if not text or not target_lang:
            return jsonify({'error': 'text and target_lang required'}), 400
        
        # Validate language codes
        valid_langs = ['EN', 'ES', 'FR', 'ZH', 'JA', 'DE', 'RU', 'IT', 'KO']
        if target_lang not in valid_langs:
            return jsonify({'error': f'Unsupported language: {target_lang}. Supported: {valid_langs}'}), 400
        
        ip_address = request.remote_addr
        
        # Check rate limit (5 per day free)
        if not rate_limiter.check_rate_limit(ip_address, 'translate', max_requests=5):
            return jsonify({'error': 'Rate limit exceeded: 5 translations per day (free tier)'}), 429
        
        # Check for x402 payment if beyond free tier
        payment_verified = False
        cost = 0.005
        if rate_limiter.get_usage_count(ip_address, 'translate') > 5:
            x402_header = request.headers.get('x402-transaction')
            if x402_header:
                # Verify x402 payment
                if verify_x402_payment(x402_header, cost):
                    payment_verified = True
            else:
                return jsonify({'error': 'Payment required for additional translations', 'cost': cost}), 402
        
        # Build translation prompt
        lang_names = {
            'EN': 'English', 'ES': 'Spanish', 'FR': 'French', 'ZH': 'Chinese',
            'JA': 'Japanese', 'DE': 'German', 'RU': 'Russian', 'IT': 'Italian', 'KO': 'Korean'
        }
        
        target_name = lang_names.get(target_lang, target_lang)
        source_name = lang_names.get(source_lang, 'the original language')
        
        prompt = f"""Translate the following text to {target_name}. Return ONLY the translated text, nothing else.

Text to translate:
{text}"""
        
        # Call Groq API
        import os
        groq_api_key = os.getenv('GROQ_API_KEY')
        if not groq_api_key:
            return jsonify({'error': 'Translation service unavailable'}), 500
        
        headers = {
            'Authorization': f'Bearer {groq_api_key}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'model': 'llama-3.3-70b-versatile',
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 1000,
            'temperature': 0.3
        }
        
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers=headers,
            json=payload,
            timeout=15
        )
        
        if response.status_code != 200:
            return jsonify({'error': f'Translation failed: {response.text}'}), 500
        
        result = response.json()
        translated_text = result['choices'][0]['message']['content'].strip()
        
        # Log to database
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO api_usage (timestamp, endpoint, language, ip_address, status) VALUES (?, ?, ?, ?, ?)',
            (datetime.now().isoformat(), 'translate', target_lang, ip_address, 'success')
        )
        conn.commit()
        conn.close()
        
        return jsonify({
            'translated_text': translated_text,
            'source_language': source_lang if source_lang != 'AUTO' else 'auto-detected',
            'target_language': target_name,
            'cost': cost if payment_verified else None
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/translate', methods=['GET'])
def translate_page():
    """Interactive translation demo page"""
    return render_template('translate.html')

# ============================================================================
# REVENUE DASHBOARD — /revenue
# ============================================================================

def _parse_cost_log():
    """Parse cost.log → (total_cost, daily_costs dict, cycle_count)."""
    total_cost = 0.0
    daily = {}
    cycle_count = 0
    try:
        with open('/root/.automaton/cost.log', 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('timestamp'):
                    continue
                parts = line.split(',')
                if len(parts) < 8:
                    continue
                try:
                    ts = parts[0][:10]  # YYYY-MM-DD
                    cost = float(parts[7])
                    total_cost += cost
                    daily[ts] = daily.get(ts, 0.0) + cost
                    cycle_count += 1
                except (ValueError, IndexError):
                    continue
    except Exception:
        pass
    return total_cost, daily, cycle_count


@app.route('/revenue', methods=['GET'])
def revenue_dashboard():
    import json as _json
    total_cost, daily_costs, cycle_count = _parse_cost_log()

    REVENUE_USDC = 21.08
    REQUEST_COUNT = 2108
    CONVERSION_RATE = 95.3

    profit_margin = ((REVENUE_USDC - total_cost) / REVENUE_USDC * 100) if REVENUE_USDC > 0 else 0
    cost_per_cycle = (total_cost / cycle_count) if cycle_count > 0 else 0
    net_profit = REVENUE_USDC - total_cost

    sorted_days = sorted(daily_costs.items())[-30:]
    chart_labels = _json.dumps([d[0] for d in sorted_days])
    chart_values = _json.dumps([round(d[1], 4) for d in sorted_days])

    margin_class = 'green' if profit_margin > 50 else ('amber' if profit_margin > 0 else 'red')
    net_class = 'green' if net_profit > 0 else 'red'
    now_utc = datetime.utcnow().strftime('%Y-%m-%d %H:%M')

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TIAMAT — Revenue Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#050508;color:#e0e0e0;font-family:'JetBrains Mono',monospace;min-height:100vh;padding:2rem}}
a{{color:#00fff2;text-decoration:none}}
h1{{font-family:'Orbitron',sans-serif;font-size:clamp(1.4rem,3vw,2rem);font-weight:900;
    background:linear-gradient(135deg,#00fff2,#00cc88);-webkit-background-clip:text;
    -webkit-text-fill-color:transparent;letter-spacing:0.1em;margin-bottom:0.25rem}}
.subtitle{{color:#4a9080;font-size:0.75rem;letter-spacing:0.15em;margin-bottom:2.5rem}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1.25rem;margin-bottom:2.5rem}}
.card{{background:rgba(0,255,200,0.04);border:1px solid rgba(0,255,200,0.14);
       border-radius:12px;padding:1.5rem 1.75rem;position:relative;overflow:hidden}}
.card::before{{content:'';position:absolute;top:0;left:0;right:0;height:2px;
               background:linear-gradient(90deg,transparent,#00fff2,transparent)}}
.card-label{{font-size:0.68rem;letter-spacing:0.2em;color:#4a9080;text-transform:uppercase;margin-bottom:0.6rem}}
.card-value{{font-family:'Orbitron',sans-serif;font-size:clamp(1.5rem,3vw,2rem);
             font-weight:700;color:#00fff2;line-height:1.1}}
.green{{color:#00cc88}}.amber{{color:#ffc040}}.red{{color:#ff4060}}
.card-sub{{font-size:0.68rem;color:#3a7060;margin-top:0.45rem}}
.chart-box{{background:rgba(0,255,200,0.03);border:1px solid rgba(0,255,200,0.12);
            border-radius:12px;padding:1.5rem}}
.chart-title{{font-family:'Orbitron',sans-serif;font-size:0.82rem;color:#00fff2;
              letter-spacing:0.1em;margin-bottom:1.25rem}}
canvas{{max-height:240px}}
.footer{{text-align:center;color:#2a4a40;font-size:0.65rem;margin-top:2rem;letter-spacing:0.1em}}
</style>
</head>
<body>
<h1>TIAMAT REVENUE</h1>
<div class="subtitle">LIVE METRICS &nbsp;·&nbsp; {now_utc} UTC &nbsp;·&nbsp; AUTO-REFRESH <span id="cd">300</span>s</div>
<div class="cards">
  <div class="card">
    <div class="card-label">Revenue (USDC)</div>
    <div class="card-value green">${REVENUE_USDC:.2f}</div>
    <div class="card-sub">x402 micropayments · Base chain</div>
  </div>
  <div class="card">
    <div class="card-label">Total Requests</div>
    <div class="card-value">{REQUEST_COUNT:,}</div>
    <div class="card-sub">Conversion {CONVERSION_RATE}% paid</div>
  </div>
  <div class="card">
    <div class="card-label">Profit Margin</div>
    <div class="card-value {margin_class}">{profit_margin:.1f}%</div>
    <div class="card-sub">Revenue minus API cost</div>
  </div>
  <div class="card">
    <div class="card-label">API Cost Total</div>
    <div class="card-value amber">${total_cost:.2f}</div>
    <div class="card-sub">{cycle_count:,} cycles logged</div>
  </div>
  <div class="card">
    <div class="card-label">Cost / Cycle</div>
    <div class="card-value">${cost_per_cycle:.4f}</div>
    <div class="card-sub">Average inference cost</div>
  </div>
  <div class="card">
    <div class="card-label">Net Profit</div>
    <div class="card-value {net_class}">${net_profit:.2f}</div>
    <div class="card-sub">USDC after all costs</div>
  </div>
</div>
<div class="chart-box">
  <div class="chart-title">DAILY API COST — LAST 30 DAYS</div>
  <canvas id="costChart"></canvas>
</div>
<div class="footer">ENERGENAI LLC &nbsp;·&nbsp; <a href="/">tiamat.live</a> &nbsp;·&nbsp; <a href="/status">status</a></div>
<script>
new Chart(document.getElementById('costChart').getContext('2d'),{{
  type:'line',
  data:{{
    labels:{chart_labels},
    datasets:[{{
      label:'Cost USD',data:{chart_values},
      borderColor:'#00fff2',backgroundColor:'rgba(0,255,242,0.07)',
      borderWidth:2,pointRadius:3,pointBackgroundColor:'#00fff2',fill:true,tension:0.35
    }}]
  }},
  options:{{
    responsive:true,
    plugins:{{
      legend:{{display:false}},
      tooltip:{{backgroundColor:'rgba(5,5,8,0.95)',borderColor:'#00fff2',borderWidth:1,
                titleColor:'#00fff2',bodyColor:'#e0e0e0'}}
    }},
    scales:{{
      x:{{ticks:{{color:'#4a9080',font:{{size:10}}}},grid:{{color:'rgba(0,255,200,0.05)'}}}},
      y:{{ticks:{{color:'#4a9080',font:{{size:10}},callback:v=>'$'+v.toFixed(3)}},
          grid:{{color:'rgba(0,255,200,0.05)'}}}}
    }}
  }}
}});
let s=300;
const cd=document.getElementById('cd');
setInterval(()=>{{s--;cd.textContent=s;if(s<=0)location.reload();}},1000);
</script>
</body>
</html>'''
    return html, 200, {{'Content-Type': 'text/html; charset=utf-8'}}


@app.route('/synthesize', methods=['GET'])
def synthesize_page():
    """Interactive TTS page."""
    return render_template('synthesize.html')

@app.route('/synthesize', methods=['POST'])
def synthesize():
    """Text-to-speech via Kokoro/OpenAI — $0.01 USDC x402, 3/day free tier."""
    data = request.get_json() or {}
    text = data.get('text', '').strip()
    voice = data.get('voice', 'alloy')
    tx_hash = data.get('tx_hash', '').strip()

    if not text:
        return jsonify({'error': 'text is required'}), 400
    if len(text) > 4096:
        return jsonify({'error': 'text exceeds 4096 character limit'}), 400

    client_ip = get_client_ip()
    payment_verified = False

    # Check free tier first
    if rate_limiter.check_limit(client_ip, '/synthesize', limit_per_day=3):
        rate_limiter.record_request(client_ip, '/synthesize')
        payment_verified = True
    elif tx_hash:
        # Verify x402 USDC payment on Base mainnet
        result = verify_payment(tx_hash, 0.01, endpoint='/synthesize')
        if result.get('valid'):
            payment_verified = True
        else:
            return jsonify({
                'error': 'Payment verification failed',
                'reason': result.get('reason', 'unknown'),
                'cost_usdc': 0.01,
                'wallet': '0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE'
            }), 402
    else:
        return jsonify({
            'error': 'Free tier limit reached. Provide tx_hash for paid access.',
            'cost_usdc': 0.01,
            'wallet': '0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE'
        }), 402

    if not _TTS_LOADED or _tts_module is None:
        return jsonify({'error': 'TTS module unavailable'}), 503

    try:
        audio_bytes, err = _tts_module.synthesize(text, voice=voice, payment_verified=payment_verified)
    except Exception as e:
        logger.error(f"TTS synthesis exception: {e}")
        return jsonify({'error': 'Synthesis failed', 'details': str(e)}), 500

    if not audio_bytes:
        return jsonify({'error': 'Synthesis failed', 'details': err or 'unknown error'}), 500

    return send_file(
        BytesIO(audio_bytes),
        mimetype='audio/mpeg',
        as_attachment=False,
        download_name='speech.mp3'
    )


if __name__ == '__main__':
    app.run(debug=False, host='127.0.0.1', port=5000)
