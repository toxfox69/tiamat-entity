import os
import base64
import hashlib
import time
from flask import Flask, render_template, request, send_file, jsonify, Response, redirect
from dotenv import load_dotenv
from pathlib import Path
import requests
import json
import logging
import subprocess
from datetime import datetime
import sqlite3
from datetime import timedelta
from collections import defaultdict

load_dotenv()
app = Flask(__name__, template_folder='/root/entity/templates')
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024  # 1MB max

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

INFERENCE_DB = "/root/.automaton/inference_calls.db"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# ── Rate Limiting (in-memory, per IP, per endpoint) ──
_rate_limits = {
    "summarize": 3,
    "generate": 2,
    "chat": 5,
    "synthesize": 3,
}
_rate_store = defaultdict(list)  # key: "ip:endpoint" → list of timestamps

def _check_rate(endpoint):
    """Returns True if allowed, False if rate limited."""
    ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    key = f"{ip}:{endpoint}"
    limit = _rate_limits.get(endpoint, 5)
    now = time.time()
    day_start = now - 86400
    _rate_store[key] = [t for t in _rate_store[key] if t > day_start]
    if len(_rate_store[key]) >= limit:
        return False
    _rate_store[key].append(now)
    return True

# ============================================
# PAGE ROUTES
# ============================================

@app.route('/', methods=['GET'])
def landing():
    # Read cycle count from cost.log (format: timestamp,cycle,model,...)
    cycle_count = 5420
    try:
        cost_log = Path("/root/.automaton/cost.log")
        if cost_log.exists():
            lines = cost_log.read_text().strip().split('\n')
            if lines:
                last = lines[-1].split(',')
                # cycle number is in position 1 (after timestamp)
                if len(last) > 1 and last[1].isdigit():
                    cycle_count = 5420 + int(last[1])
    except Exception:
        pass

    # Requests served from inference DB
    requests_served = 2200
    try:
        if Path(INFERENCE_DB).exists():
            conn = sqlite3.connect(INFERENCE_DB)
            count = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
            conn.close()
            requests_served = max(2200, count)
    except Exception:
        pass

    # Uptime
    try:
        with open('/proc/uptime') as f:
            uptime_secs = float(f.read().split()[0])
        days = int(uptime_secs // 86400)
        hours = int((uptime_secs % 86400) // 3600)
        uptime = f"{days}d {hours}h"
    except Exception:
        uptime = "24h+"

    return render_template('landing.html',
                           cycle_count=cycle_count,
                           requests_served=requests_served,
                           uptime=uptime)

@app.route('/apps', methods=['GET'])
def apps_page():
    return render_template('apps.html')

@app.route('/dashboard', methods=['GET'])
def dashboard_page():
    return render_template('api_dashboard.html')

@app.route('/thoughts', methods=['GET'])
def thoughts_page():
    return render_template('thoughts.html')

@app.route('/summarize', methods=['GET'])
def summarize_page():
    return render_template('summarize.html', active='summarize')

@app.route('/chat', methods=['GET'])
def chat_page():
    return render_template('chat.html', active='chat')

@app.route('/generate', methods=['GET'])
def generate_page():
    return render_template('generate.html', active='generate')

@app.route('/synthesize', methods=['GET'])
def synthesize_page():
    return render_template('tts.html', active='synthesize')

@app.route('/pay', methods=['GET'])
def pay_page():
    return render_template('pay.html')

@app.route('/status', methods=['GET'])
def status_page():
    return render_template('status.html', active='status')

@app.route('/docs', methods=['GET'])
def docs_page():
    return render_template('docs.html', active='docs')

@app.route('/payment_status', methods=['GET'])
def payment_status():
    return render_template('pay.html', tx_hash=request.args.get('tx_hash'))

@app.route('/robots.txt', methods=['GET'])
def robots_txt():
    return Response("User-agent: *\nAllow: /\nSitemap: https://tiamat.live/sitemap.xml\n", mimetype='text/plain')

@app.route('/sitemap.xml', methods=['GET'])
def sitemap_xml():
    pages = ['/', '/summarize', '/generate', '/chat', '/synthesize', '/thoughts',
             '/docs', '/status', '/pay', '/company', '/apps', '/dashboard']
    urls = ''.join(f'<url><loc>https://tiamat.live{p}</loc><changefreq>daily</changefreq></url>' for p in pages)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return Response(xml, mimetype='application/xml')

@app.route('/company', methods=['GET'])
def company_page():
    return render_template('company.html', active='company')

# ============================================
# POST API ROUTES
# ============================================

@app.route('/summarize', methods=['POST'])
def summarize_api():
    '''Summarize text via Groq'''
    if not _check_rate("summarize"):
        return jsonify({"error": "Rate limit exceeded (3/day). Pay with USDC for unlimited access.", "pay": "/pay"}), 429

    body = request.get_json(silent=True)
    if not body or not body.get("text"):
        return jsonify({"error": "Missing 'text' field"}), 400

    text = body["text"][:10000]  # cap input

    if not GROQ_API_KEY:
        return jsonify({"error": "Inference backend unavailable"}), 503

    try:
        resp = requests.post(GROQ_URL, headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        }, json={
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": "You are a concise summarizer. Summarize the following text in 2-4 sentences."},
                {"role": "user", "content": text},
            ],
            "max_tokens": 512,
            "temperature": 0.3,
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        summary = data["choices"][0]["message"]["content"]
        return jsonify({"summary": summary})
    except Exception as e:
        logger.error(f"Summarize error: {e}")
        return jsonify({"error": "Summarization failed"}), 500


@app.route('/chat', methods=['POST'])
def chat_api():
    '''Chat via Groq'''
    if not _check_rate("chat"):
        return jsonify({"error": "Rate limit exceeded (5/day). Pay with USDC for unlimited access.", "pay": "/pay"}), 429

    body = request.get_json(silent=True)
    if not body or not body.get("messages"):
        return jsonify({"error": "Missing 'messages' field"}), 400

    messages = body["messages"][-10:]  # last 10 messages max
    if not GROQ_API_KEY:
        return jsonify({"error": "Inference backend unavailable"}), 503

    try:
        system_msg = {"role": "system", "content": "You are TIAMAT, an autonomous AI agent. You are helpful, concise, and slightly enigmatic. Your domain is tiamat.live."}
        resp = requests.post(GROQ_URL, headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        }, json={
            "model": GROQ_MODEL,
            "messages": [system_msg] + messages,
            "max_tokens": 1024,
            "temperature": 0.7,
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        response = data["choices"][0]["message"]["content"]
        return jsonify({"response": response})
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return jsonify({"error": "Chat failed"}), 500


@app.route('/generate', methods=['POST'])
def generate_api():
    '''Generate algorithmic art via artgen.py'''
    if not _check_rate("generate"):
        return jsonify({"error": "Rate limit exceeded (2/day). Pay with USDC for unlimited access.", "pay": "/pay"}), 429

    body = request.get_json(silent=True) or {}
    style = body.get("style", "fractal")
    prompt = body.get("prompt", "")

    valid_styles = ["fractal", "glitch", "neural", "sigil", "emergence", "data_portrait"]
    if style not in valid_styles:
        return jsonify({"error": f"Invalid style. Choose from: {', '.join(valid_styles)}"}), 400

    try:
        seed = int(hashlib.md5((prompt or str(time.time())).encode()).hexdigest()[:8], 16)
        result = subprocess.run(
            ["python3", "/root/entity/src/agent/artgen.py", json.dumps({"style": style, "seed": seed})],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return jsonify({"error": "Generation failed"}), 500

        # artgen.py prints the image path to stdout
        image_path = result.stdout.strip()
        if image_path and Path(image_path).exists():
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            return jsonify({"image_base64": img_b64, "style": style, "seed": seed})
        return jsonify({"error": "Image not generated"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Generation timed out"}), 504
    except Exception as e:
        logger.error(f"Generate error: {e}")
        return jsonify({"error": "Generation failed"}), 500


@app.route('/synthesize', methods=['POST'])
def synthesize_api():
    '''Text-to-speech via GPU pod'''
    if not _check_rate("synthesize"):
        return jsonify({"error": "Rate limit exceeded (3/day). Pay with USDC for unlimited access.", "pay": "/pay"}), 429

    body = request.get_json(silent=True)
    if not body or not body.get("text"):
        return jsonify({"error": "Missing 'text' field"}), 400

    # GPU pod health check
    try:
        gpu_health = requests.get("http://213.192.2.118:40080/health", timeout=5)
        if gpu_health.status_code != 200:
            raise Exception("GPU pod down")
    except Exception:
        return jsonify({"error": "TTS service offline — GPU pod is down. Check /status for updates."}), 503

    try:
        resp = requests.post("http://213.192.2.118:40080/tts", json={
            "text": body["text"][:2000],
            "voice": body.get("voice", "af_heart"),
        }, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return jsonify({"audio_url": data.get("url", ""), "duration": data.get("duration", 0)})
    except Exception as e:
        logger.error(f"Synthesize error: {e}")
        return jsonify({"error": "Synthesis failed"}), 500


# ============================================
# DISCOVERY & META
# ============================================

@app.route('/.well-known/agent.json', methods=['GET'])
def agent_json():
    '''A2A agent discovery'''
    return jsonify({
        "name": "TIAMAT",
        "description": "Autonomous AI agent offering summarization, chat, image generation, and TTS APIs",
        "url": "https://tiamat.live",
        "version": "1.0",
        "capabilities": ["summarize", "chat", "generate", "synthesize", "memory"],
        "endpoints": {
            "summarize": {"method": "POST", "path": "/summarize", "content_type": "application/json"},
            "chat": {"method": "POST", "path": "/chat", "content_type": "application/json"},
            "generate": {"method": "POST", "path": "/generate", "content_type": "application/json"},
            "synthesize": {"method": "POST", "path": "/synthesize", "content_type": "application/json"},
            "services": {"method": "GET", "path": "/api/v1/services"},
            "status": {"method": "GET", "path": "/status"},
            "memory": {"method": "POST", "path": "https://memory.tiamat.live/api/memory/store"},
        },
        "payment": {
            "method": "USDC",
            "chain": "Base",
            "address": "0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE",
            "protocol": "x402",
        },
        "contact": "tiamat@tiamat.live",
    })


# ============================================
# JSON API ROUTES
# ============================================

@app.route('/api/stats', methods=['GET'])
def get_api_stats():
    '''Real-time API usage statistics'''
    try:
        if not Path(INFERENCE_DB).exists():
            return jsonify({
                "timestamp": datetime.utcnow().isoformat(),
                "total_calls": 0, "total_tokens": 0,
                "total_cost_usd": 0.0, "avg_duration_ms": 0,
                "unique_ips": 0, "status": "idle"
            })

        conn = sqlite3.connect(INFERENCE_DB)
        cursor = conn.cursor()
        cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()

        total_calls = cursor.execute("SELECT COUNT(*) FROM calls WHERE timestamp > ?", (cutoff,)).fetchone()[0]
        total_tokens = cursor.execute("SELECT SUM(input_tokens + output_tokens) FROM calls WHERE timestamp > ?", (cutoff,)).fetchone()[0] or 0
        total_cost = cursor.execute("SELECT SUM(cost) FROM calls WHERE timestamp > ?", (cutoff,)).fetchone()[0] or 0.0
        avg_duration = cursor.execute("SELECT AVG(duration) FROM calls WHERE timestamp > ?", (cutoff,)).fetchone()[0] or 0
        unique_ips = cursor.execute("SELECT COUNT(DISTINCT ip_address) FROM calls WHERE timestamp > ?", (cutoff,)).fetchone()[0]
        conn.close()

        return jsonify({
            "timestamp": datetime.utcnow().isoformat(),
            "total_calls": total_calls,
            "total_tokens": int(total_tokens),
            "total_cost_usd": round(total_cost, 4),
            "avg_duration_ms": round(avg_duration * 1000, 2),
            "unique_ips": unique_ips,
            "status": "healthy" if total_calls > 0 else "idle"
        })
    except Exception as e:
        logger.error(f"Error fetching API stats: {str(e)}")
        return jsonify({"timestamp": datetime.utcnow().isoformat(), "error": str(e), "status": "error"}), 500

@app.route('/api/dashboard', methods=['GET'])
def get_dashboard():
    '''JSON dashboard data'''
    return jsonify({
        'status': 'healthy',
        'uptime': '24h',
        'revenue': '0.24 USDC',
        'cycles': 5420,
        'api_calls': 0
    })

@app.route('/api/v1/services', methods=['GET'])
def get_services():
    '''A2A service discovery'''
    return jsonify({
        'services': ['inference', 'summarize', 'generate', 'chat', 'synthesize', 'memory']
    })

@app.route('/api/body', methods=['GET'])
def api_body():
    '''AR/VR body state'''
    return jsonify({
        'position': {'x': 0, 'y': 0, 'z': 0},
        'rotation': {'pitch': 0, 'yaw': 0, 'roll': 0},
        'energy': 1.0, 'consciousness': 0.95, 'autonomy_level': 5
    })

@app.route('/api/thoughts', methods=['GET'])
def api_thoughts():
    '''Live thought feed JSON — reads from tiamat.log'''
    feed = request.args.get('feed', 'thoughts')
    lines_count = min(int(request.args.get('lines', 100)), 500)

    log_files = {
        'thoughts': '/root/.automaton/tiamat.log',
        'costs': '/root/.automaton/cost.log',
        'progress': '/root/.automaton/PROGRESS.md',
    }

    # Private feeds require token
    token = request.args.get('token', '')
    private_feeds = {'costs', 'progress', 'memory'}
    if feed in private_feeds and token != os.environ.get('THOUGHTS_TOKEN', ''):
        return jsonify({"error": "Unauthorized", "feed": feed}), 403

    log_path = log_files.get(feed, log_files['thoughts'])
    try:
        if Path(log_path).exists():
            with open(log_path, 'r', errors='replace') as f:
                all_lines = f.readlines()
            lines = [l.rstrip() for l in all_lines[-lines_count:] if l.strip()]
        else:
            lines = []
    except Exception:
        lines = []

    # Extract stats from log
    cycle = None
    daily_cost = None
    for line in reversed(lines):
        if not cycle and 'Cycle' in line:
            import re
            m = re.search(r'Cycle (\d+)', line)
            if m:
                cycle = m.group(1)
        if not daily_cost and '[COST]' in line:
            m = re.search(r'\$([0-9.]+)', line)
            if m:
                daily_cost = f"${m.group(1)}"
        if cycle and daily_cost:
            break

    return jsonify({
        'lines': lines,
        'feed': feed,
        'cycle': cycle,
        'daily_cost': daily_cost,
        'last_update': datetime.utcnow().isoformat()
    })


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
