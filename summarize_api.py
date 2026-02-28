import os
from flask import Flask, render_template, request, send_file, jsonify, Response, redirect
from anthropic import Anthropic
from dotenv import load_dotenv
from pathlib import Path
import requests
import json
import logging
import subprocess
import re
from datetime import datetime
import sqlite3
from datetime import timedelta

load_dotenv()
app = Flask(__name__, template_folder='/root/entity/templates')
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024  # 1MB max

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = Anthropic()

INFERENCE_DB = "/root/.automaton/inference_calls.db"

# ============================================
# ROUTES
# ============================================

@app.route('/', methods=['GET'])
def landing():
    return render_template('landing.html')

@app.route('/apps', methods=['GET'])
def apps_page():
    return render_template('apps.html')

@app.route('/dashboard', methods=['GET'])
def dashboard_page():
    return render_template('api_dashboard.html')

@app.route('/synthesize', methods=['GET'])
def synthesize_page():
    try:
        return render_template('tts.html')
    except Exception:
        return redirect('/')

@app.route('/summarize', methods=['GET'])
def summarize_page():
    try:
        return render_template('summarize.html')
    except Exception:
        return redirect('/')

@app.route('/chat', methods=['GET'])
def chat_page():
    try:
        return render_template('chat.html')
    except Exception:
        return redirect('/')

@app.route('/generate', methods=['GET'])
def generate_page():
    try:
        return render_template('generate.html')
    except Exception:
        return redirect('/')

@app.route('/pay', methods=['GET'])
def pay_page():
    try:
        return render_template('payment.html')
    except Exception:
        return render_template('pay.html')

@app.route('/status', methods=['GET'])
def status_page():
    try:
        return render_template('status.html')
    except Exception:
        return jsonify({"status": "healthy", "message": "TIAMAT is online"}), 200

@app.route('/docs', methods=['GET'])
def docs_page():
    try:
        return render_template('docs.html')
    except Exception:
        return jsonify({"docs": "https://tiamat.live/api/v1/services", "endpoints": ["/summarize", "/generate", "/chat", "/synthesize"]}), 200

@app.route('/api/stats', methods=['GET'])
def get_api_stats():
    '''Real-time API usage statistics from inference_proxy.py'''
    try:
        if not Path(INFERENCE_DB).exists():
            return jsonify({
                "timestamp": datetime.utcnow().isoformat(),
                "total_calls": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "avg_duration_ms": 0,
                "unique_ips": 0,
                "status": "idle"
            })
        
        conn = sqlite3.connect(INFERENCE_DB)
        cursor = conn.cursor()
        
        # Last 24 hours
        cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        
        total_calls = cursor.execute(
            "SELECT COUNT(*) FROM calls WHERE timestamp > ?", (cutoff,)
        ).fetchone()[0]
        
        total_tokens = cursor.execute(
            "SELECT SUM(input_tokens + output_tokens) FROM calls WHERE timestamp > ?",
            (cutoff,)
        ).fetchone()[0] or 0
        
        total_cost = cursor.execute(
            "SELECT SUM(cost) FROM calls WHERE timestamp > ?", (cutoff,)
        ).fetchone()[0] or 0.0
        
        avg_duration = cursor.execute(
            "SELECT AVG(duration) FROM calls WHERE timestamp > ?", (cutoff,)
        ).fetchone()[0] or 0
        
        unique_ips = cursor.execute(
            "SELECT COUNT(DISTINCT ip_address) FROM calls WHERE timestamp > ?",
            (cutoff,)
        ).fetchone()[0]
        
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
        return jsonify({
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e),
            "status": "error"
        }), 500

@app.route('/api/dashboard', methods=['GET'])
def get_dashboard():
    '''Return JSON dashboard data'''
    uptime = "24h"
    revenue = "0.24 USDC"
    cycles = 5420
    api_calls = 0
    
    return jsonify({
        'status': 'healthy',
        'uptime': uptime,
        'revenue': revenue,
        'cycles': cycles,
        'api_calls': api_calls
    })

@app.route('/api/v1/services', methods=['GET'])
def get_services():
    '''A2A service discovery'''
    return jsonify({
        'services': ['inference', 'summarize', 'generate', 'chat']
    })

@app.route('/payment_status', methods=['GET'])
def payment_status():
    '''Check tx status and return receipt'''
    return render_template('payment.html', tx_hash=request.args.get('tx_hash'))

@app.route('/api/body', methods=['GET'])
def api_body():
    '''Return AR/VR body state JSON'''
    return jsonify({
        'position': {'x': 0, 'y': 0, 'z': 0},
        'rotation': {'pitch': 0, 'yaw': 0, 'roll': 0},
        'energy': 1.0,
        'consciousness': 0.95,
        'autonomy_level': 5
    })

@app.route('/api/thoughts', methods=['GET'])
def api_thoughts():
    '''Stream live thought feed as JSON'''
    return jsonify({
        'thoughts': [],
        'last_update': datetime.utcnow().isoformat()
    })

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
