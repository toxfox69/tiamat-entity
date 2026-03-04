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

# Add payment verification to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'entity/src/agent'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'entity/src'))

from payment_verify import verify_payment

app = Flask(__name__)
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
        
        prompt = f"Translate ONLY to {langs[target_lang]}. No explanation.

{text}"
        
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

if __name__ == '__main__':
    app.run(debug=False, host='127.0.0.1', port=5000)
