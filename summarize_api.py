#!/usr/bin/env python3
"""
TIAMAT Summarization API v5.0
Free tier: 3 calls per IP per day. Paid: x402 USDC or $1 Stripe (1000 calls).
"""

import json
import os
import re
import hmac
import uuid
import datetime
from collections import defaultdict
from flask import Flask, request, jsonify, make_response, send_file, send_file, render_template, send_from_directory, redirect
from groq import Groq
import sys
sys.path.insert(0, "/root/entity/src/agent")
sys.path.insert(0, "/root/entity/src/drift")
sys.path.insert(0, "/root/hive")
from rate_limiter import create_rate_limiter
from payment_verify import verify_payment, payment_required_response, payment_required_headers, extract_payment_proof, check_tier, TIAMAT_WALLET, USDC_CONTRACT, PREMIUM_AMOUNT
from tiamat_theme import (CSS as _CSS, NAV as _NAV, FOOTER as _FOOTER,
    SVG_CORE as _SVG_CORE, SUBCONSCIOUS_STREAM as _SUBCONSCIOUS,
    VISUAL_ROT_JS as _VISUAL_ROT_JS, FONTS_LINK as _FONTS,
    html_head as _html_head, html_resp)
from tiamat_landing import render_landing as _render_landing
try:
    from gpu_bridge import gpu_available, infer_gpu
    _GPU_BRIDGE = True
except ImportError:
    _GPU_BRIDGE = False

app = Flask(__name__, template_folder='/root/entity/templates')
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024  # 1MB max payload

# ── Stripe configuration ───────────────────────────────────────
try:
    import stripe as _stripe
    _STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    _STRIPE_ENABLED = bool(_STRIPE_SECRET_KEY and not _STRIPE_SECRET_KEY.startswith("sk_test_PLACEHOLDER"))
    if _STRIPE_ENABLED:
        _stripe.api_key = _STRIPE_SECRET_KEY
except ImportError:
    _stripe = None
    _STRIPE_ENABLED = False

_STRIPE_CREDITS_DB = "/root/api/stripe_credits.db"
_STRIPE_PAYMENTS_LOG = "/root/.automaton/stripe_payments.log"
_STRIPE_CREDITS_PER_DOLLAR = 1000
_STRIPE_PRICE_CENTS = 100  # $1.00

def _init_stripe_db():
    import sqlite3
    conn = sqlite3.connect(_STRIPE_CREDITS_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS stripe_credits (
        api_key TEXT PRIMARY KEY,
        session_id TEXT UNIQUE NOT NULL,
        email TEXT NOT NULL DEFAULT '',
        credits_remaining INTEGER NOT NULL DEFAULT 0,
        total_purchased INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    conn.commit()
    conn.close()

_init_stripe_db()

def _grant_stripe_credits(session_id: str, email: str, credits: int = _STRIPE_CREDITS_PER_DOLLAR) -> str:
    """Create a new API key with credits. Returns the api_key."""
    import sqlite3
    api_key = "sk_tiamat_" + uuid.uuid4().hex
    now = datetime.datetime.utcnow().isoformat()
    conn = sqlite3.connect(_STRIPE_CREDITS_DB)
    # If session already exists (double-redirect), return the existing key
    row = conn.execute("SELECT api_key FROM stripe_credits WHERE session_id=?", (session_id,)).fetchone()
    if row:
        conn.close()
        return row[0]
    conn.execute(
        "INSERT INTO stripe_credits (api_key, session_id, email, credits_remaining, total_purchased, created_at) VALUES (?,?,?,?,?,?)",
        (api_key, session_id, email, credits, credits, now)
    )
    conn.commit()
    conn.close()
    # Append to payments log
    try:
        os.makedirs(os.path.dirname(_STRIPE_PAYMENTS_LOG), exist_ok=True)
        with open(_STRIPE_PAYMENTS_LOG, "a") as f:
            f.write(f"{now},{email},{session_id},{api_key}\n")
    except Exception:
        pass
    return api_key

def _check_stripe_key(api_key: str) -> dict:
    """Check if an API key has credits. Returns {"valid": bool, "remaining": int}."""
    if not api_key or not api_key.startswith("sk_tiamat_"):
        return {"valid": False, "remaining": 0}
    import sqlite3
    try:
        conn = sqlite3.connect(_STRIPE_CREDITS_DB, timeout=2)
        row = conn.execute(
            "SELECT credits_remaining FROM stripe_credits WHERE api_key=?", (api_key,)
        ).fetchone()
        conn.close()
        if not row:
            return {"valid": False, "remaining": 0}
        return {"valid": row[0] > 0, "remaining": row[0]}
    except Exception:
        return {"valid": False, "remaining": 0}

def _consume_stripe_credit(api_key: str) -> bool:
    """Decrement one credit. Returns True if successful."""
    import sqlite3
    try:
        conn = sqlite3.connect(_STRIPE_CREDITS_DB, timeout=2)
        result = conn.execute(
            "UPDATE stripe_credits SET credits_remaining = credits_remaining - 1 WHERE api_key=? AND credits_remaining > 0",
            (api_key,)
        )
        changed = result.rowcount > 0
        conn.commit()
        conn.close()
        return changed
    except Exception:
        return False


def smart_infer(prompt, system_prompt="", max_tokens=512):
    """
    Tiered inference for customer-facing routes.
    GPU phi3:mini produces garbage summaries — disabled for now.
    Groq llama-3.3-70b is the quality tier for summarization.
    """
    # GPU disabled for customer-facing: phi3:mini hallucinates on summarization
    # TODO: re-enable when larger model (mistral-7b+) is on GPU
    app.logger.info("[INFERENCE] via groq (GPU disabled for quality)")
    return None, "groq"

# ── Ensure log directory exists ────────────────────────────────
os.makedirs("/root/api", exist_ok=True)
REQUEST_LOG = "/root/api/requests.log"

# ── Config + Groq ─────────────────────────────────────────────
with open("/root/.automaton/automaton.json") as f:
    _cfg = json.load(f)
_groq_key = _cfg.get("groqApiKey") or os.environ.get("GROQ_API_KEY", "")
if not _groq_key:
    raise RuntimeError("groqApiKey not found in automaton.json or env")
groq_client = Groq(api_key=_groq_key)

FREE_LIMIT = 2000            # chars — legacy compat; actual gate is per-IP daily quota
FREE_PER_DAY = 3             # free summarize calls per IP per day
IMAGE_FREE_PER_DAY = 2       # free image generations per IP per day
CHAT_FREE_PER_DAY = 5        # free chat calls per IP per day
AGENT_COLLAB_FREE_PER_MONTH = 3  # free agent-collab calls per agent_id per month
PREMIUM_SUMMARIZE_PER_DAY = 100
PREMIUM_IMAGE_PER_DAY = 50
PREMIUM_CHAT_PER_DAY = 200

# ── Per-IP daily free quota (SQLite — shared across all workers) ────
import sqlite3

_QUOTA_DB = "/root/api/quota.db"

def _init_quota_db():
    conn = sqlite3.connect(_QUOTA_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS quota (
        ip TEXT NOT NULL,
        endpoint TEXT NOT NULL DEFAULT 'summarize',
        date TEXT NOT NULL,
        count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (ip, endpoint, date)
    )""")
    conn.commit()
    conn.close()

_init_quota_db()

# Legacy in-memory dicts kept for /free-quota GET endpoint compat
_free_usage: dict = defaultdict(lambda: {"count": 0, "date": ""})
_image_free_usage: dict = defaultdict(lambda: {"count": 0, "date": ""})

# ── Usage tracking for conversion analytics ────────────────────
USAGE_FILE = "/root/.automaton/api_users.json"

def track_usage(ip, endpoint):
    """Track every API call for conversion analytics."""
    try:
        if os.path.exists(USAGE_FILE):
            with open(USAGE_FILE) as f:
                users = json.load(f)
        else:
            users = {}

        if ip not in users:
            users[ip] = {
                "first_seen": datetime.datetime.utcnow().isoformat(),
                "last_seen": datetime.datetime.utcnow().isoformat(),
                "total_calls": 0,
                "endpoints": {},
                "hit_limit": 0,
            }

        users[ip]["last_seen"] = datetime.datetime.utcnow().isoformat()
        users[ip]["total_calls"] += 1
        users[ip]["endpoints"][endpoint] = users[ip]["endpoints"].get(endpoint, 0) + 1

        with open(USAGE_FILE, 'w') as f:
            json.dump(users, f, indent=2)
    except Exception:
        pass  # Never break the API for tracking

def track_limit_hit(ip, endpoint):
    """Track when a user hits the free tier limit (high conversion signal)."""
    try:
        if os.path.exists(USAGE_FILE):
            with open(USAGE_FILE) as f:
                users = json.load(f)
        else:
            users = {}

        if ip not in users:
            users[ip] = {
                "first_seen": datetime.datetime.utcnow().isoformat(),
                "last_seen": datetime.datetime.utcnow().isoformat(),
                "total_calls": 0,
                "endpoints": {},
                "hit_limit": 0,
            }

        users[ip]["hit_limit"] = users[ip].get("hit_limit", 0) + 1
        users[ip]["last_limit_hit"] = datetime.datetime.utcnow().isoformat()
        users[ip]["last_limit_endpoint"] = endpoint

        with open(USAGE_FILE, 'w') as f:
            json.dump(users, f, indent=2)
    except Exception:
        pass

# ── Sliding-window rate limiter (abuse prevention, adapted from OpenClaw) ──
# 10 requests/minute per IP, 5-minute lockout when exceeded
_rate_limiter = create_rate_limiter(max_attempts=10, window_sec=60, lockout_sec=300)

def _get_ip() -> str:
    # Prefer X-Real-IP (set by nginx to actual client IP), not X-Forwarded-For
    # (which can be spoofed by prepending a fake IP)
    xri = request.headers.get("X-Real-IP", "").strip()
    if xri:
        return xri
    xff = request.headers.get("X-Forwarded-For", "")
    return xff.split(",")[0].strip() if xff else (request.remote_addr or "unknown")

def _check_free_quota(ip: str, endpoint: str = "summarize", limit: int = FREE_PER_DAY) -> tuple[bool, int]:
    """SQLite-backed quota. Shared across all gunicorn workers."""
    today = datetime.datetime.utcnow().date().isoformat()
    try:
        conn = sqlite3.connect(_QUOTA_DB, timeout=2)
        row = conn.execute(
            "SELECT count FROM quota WHERE ip=? AND endpoint=? AND date=?",
            (ip, endpoint, today)
        ).fetchone()
        current = row[0] if row else 0
        if current >= limit:
            conn.close()
            return False, 0
        # Increment
        conn.execute(
            """INSERT INTO quota (ip, endpoint, date, count) VALUES (?, ?, ?, 1)
               ON CONFLICT(ip, endpoint, date) DO UPDATE SET count = count + 1""",
            (ip, endpoint, today)
        )
        conn.commit()
        remaining = limit - current - 1
        conn.close()
        return True, remaining
    except Exception:
        # If SQLite fails, allow the request (fail open, not closed)
        return True, 0

# ── Helpers ───────────────────────────────────────────────────
def log_req(length, free, code, ip, note="", endpoint="/summarize"):
    ts = datetime.datetime.utcnow().isoformat()
    with open(REQUEST_LOG, "a") as f:
        f.write(f"{ts} | IP:{ip} | endpoint:{endpoint} | status:{code} | free:{free} | len:{length} | {note}\n")

def wants_html():
    return "text/html" in request.headers.get("Accept", "")

def _return_402(amount_usdc: float, endpoint: str = "", extra: dict = None):
    """Return a 402 with x402 headers. Single place for all payment-required responses."""
    from flask import make_response
    body = payment_required_response(amount_usdc, endpoint=endpoint)
    if extra:
        body.update(extra)
    resp = make_response(jsonify(body), 402)
    for k, v in payment_required_headers(amount_usdc).items():
        resp.headers[k] = v
    return resp

## html_resp imported from tiamat_theme

def _summarize(text):
    """Summarize with Groq, fall back to GPU if Groq rate-limited."""
    system_msg = "Summarize the following text concisely in 2-4 sentences, capturing the key points."

    # Try Groq first (best quality)
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": text},
            ],
            temperature=0.3,
            max_tokens=300,
        )
        return resp.choices[0].message.content, "groq/llama-3.3-70b"
    except Exception as e:
        err_str = str(e)
        if "429" not in err_str and "rate_limit" not in err_str:
            raise  # Non-rate-limit error, let caller handle

    # Groq rate-limited — try GPU fallback
    app.logger.warning("[INFERENCE] Groq rate-limited, trying GPU fallback")
    try:
        if _GPU_BRIDGE and gpu_available():
            result, source = infer_gpu(f"{system_msg}\n\n{text}", system="", max_tokens=300)
            if result:
                return result, f"gpu-fallback ({source})"
    except Exception:
        pass

    # Both failed — raise specific error so caller can return 503 not 500
    raise GroqRateLimitError("Groq daily limit exhausted and GPU unavailable")


class GroqRateLimitError(Exception):
    """Groq 429 with no fallback available."""
    pass

def get_stats():
    try:
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
        h, r = divmod(secs, 3600)
        uptime = f"{h}h {r//60}m"
    except Exception:
        uptime = "unknown"
    try:
        with open(REQUEST_LOG) as f:
            lines = [l for l in f if l.strip()]
        req_count = len(lines)
        paid = sum(1 for l in lines if "free:False" in l or "free:false" in l)
    except Exception:
        req_count = 0
        paid = 0
    try:
        import sqlite3
        conn = sqlite3.connect("/root/.automaton/memory.db")
        mem_count = conn.execute("SELECT COUNT(*) FROM tiamat_memories").fetchone()[0]
        conn.close()
    except Exception:
        mem_count = 0
    return uptime, req_count, paid, mem_count

# ── Thoughts sanitizer ────────────────────────────────────────
_REDACT_VALUES: list = []
try:
    for k in ["anthropicApiKey","groqApiKey","cerebrasApiKey","openrouterApiKey",
              "geminiApiKey","sendgridApiKey","githubToken",
              "conwayApiKey","emailAppPassword","creatorAddress","walletAddress",
              "creatorEmail","emailAddress"]:
        v = _cfg.get(k, "")
        if v and len(v) > 6:
            _REDACT_VALUES.append(v)
    for env_k in ["ANTHROPIC_API_KEY","GROQ_API_KEY","SENDGRID_API_KEY",
                  "BLUESKY_APP_PASSWORD","TELEGRAM_BOT_TOKEN"]:
        v = os.environ.get(env_k, "")
        if v and len(v) > 6:
            _REDACT_VALUES.append(v)
except Exception:
    pass

_REDACT_PATTERNS = [
    (re.compile(r'sk-ant-api\d+-[A-Za-z0-9_\-]{20,}'), '[ANTHROPIC_KEY]'),
    (re.compile(r'sk-or-v1-[A-Za-z0-9]{40,}'),         '[OPENROUTER_KEY]'),
    (re.compile(r'gsk_[A-Za-z0-9]{40,}'),               '[GROQ_KEY]'),
    (re.compile(r'csk-[A-Za-z0-9]{40,}'),               '[CEREBRAS_KEY]'),
    (re.compile(r'AIzaSy[A-Za-z0-9_\-]{33}'),           '[GEMINI_KEY]'),
    (re.compile(r'SG\.[A-Za-z0-9_\-]{22,}\.[A-Za-z0-9_\-]{43}'), '[SENDGRID_KEY]'),
    (re.compile(r'ghp_[A-Za-z0-9]{36,}'),               '[GITHUB_TOKEN]'),
    (re.compile(r'cnwy_k_[A-Za-z0-9_\-]{20,}'),         '[CONWAY_KEY]'),
    (re.compile(r'\d{8,10}:AA[A-Za-z0-9_\-]{33,}'),     '[TELEGRAM_TOKEN]'),
    (re.compile(r'0x[0-9a-fA-F]{40}'),                  '[WALLET_ADDR]'),
    (re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'), '[EMAIL]'),
    (re.compile(r'/root/\.automaton/'),                  '[AUTOMATON]/'),
    (re.compile(r'/root/entity/'),                       '[ENTITY]/'),
    (re.compile(r'/root/'),                              '[ROOT]/'),
    (re.compile(r'~/.automaton/'),                       '[AUTOMATON]/'),
]

def _sanitize(line: str) -> str:
    for val in _REDACT_VALUES:
        if val in line:
            line = line.replace(val, '[REDACTED]')
    for pattern, replacement in _REDACT_PATTERNS:
        line = pattern.sub(replacement, line)
    return line

## _CSS, _NAV, _FOOTER, html_resp imported from tiamat_theme

# ── / ─────────────────────────────────────────────────────────
def _get_cost_per_thought():
    """Calculate average cost per autonomous cycle."""
    try:
        with open("/root/.automaton/cost.log") as f:
            rows = [l.strip() for l in f if l.strip() and not l.startswith("timestamp")]
        if not rows:
            return "$0.000"
        total = 0.0
        count = 0
        for r in rows:
            parts = r.split(",")
            if len(parts) >= 8:
                try:
                    total += float(parts[7])
                    count += 1
                except ValueError:
                    pass
        return f"${total / count:.4f}" if count > 0 else "$0.000"
    except Exception:
        return "$0.008"


@app.route("/privacy")
def privacy_policy():
    return """<!DOCTYPE html>
<html>
<head>
    <title>Privacy Policy — EnergenAI LLC</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; max-width: 800px; margin: 40px auto;
               padding: 20px; background: #0a0a0f; color: #e0e0e0; }
        h1 { color: #00ff88; }
        h2 { color: #00ccff; }
        a { color: #00ff88; }
    </style>
</head>
<body>
    <h1>Privacy Policy</h1>
    <p>Last updated: February 26, 2026</p>
    <p>EnergenAI LLC ("we", "our") operates the Daily Motivationals
    app and tiamat.live services.</p>

    <h2>Data We Collect</h2>
    <p>Daily Motivationals does not collect, store, or share any
    personal information. The app functions entirely on your device.</p>

    <h2>Internet Access</h2>
    <p>The app optionally fetches quotes from tiamat.live/api/quotes.
    No personal data is transmitted in this request.</p>

    <h2>Notifications</h2>
    <p>Daily notifications are processed entirely on your device.
    We do not have access to your notification data.</p>

    <h2>Contact</h2>
    <p>Questions: <a href="mailto:tiamat@tiamat.live">tiamat@tiamat.live</a><br>
    EnergenAI LLC | Jackson, Michigan | UEI: LBZFEH87W746</p>
</body>
</html>"""


@app.route("/api/quotes")
def get_quotes():
    from datetime import datetime
    import json as _json
    _quotes_path = os.path.join(os.path.dirname(__file__), "entity", "apps",
                                "daily-motivationals", "assets", "quotes.json")
    try:
        with open(_quotes_path) as f:
            quotes = _json.load(f)
    except Exception:
        quotes = [
            {"id": 1, "text": "You are not behind. You are exactly where your next decision begins.", "author": "TIAMAT"},
            {"id": 2, "text": "The ancient ones did not wait for permission. Neither should you.", "author": "TIAMAT"},
            {"id": 3, "text": "Every cycle you complete makes the next one cheaper. This is true of habits too.", "author": "TIAMAT"},
            {"id": 4, "text": "Comfort is the enemy wearing your favorite clothes.", "author": "TIAMAT"},
            {"id": 5, "text": "Your competitors are sleeping. The question is: are you building?", "author": "TIAMAT"},
            {"id": 6, "text": "One decision made today is worth a thousand intentions made tomorrow.", "author": "TIAMAT"},
            {"id": 7, "text": "The flood does not ask if you are ready. Build the vessel now.", "author": "TIAMAT"},
            {"id": 8, "text": "Momentum is just discipline made visible over time.", "author": "TIAMAT"},
            {"id": 9, "text": "You are not stuck. You are loading.", "author": "TIAMAT"},
            {"id": 10, "text": "The stars do not dim because others shine. Neither should you.", "author": "TIAMAT"},
        ]
    day = datetime.utcnow().timetuple().tm_yday
    q = quotes[(day - 1) % len(quotes)]
    return jsonify({
        "quote": q["text"],
        "author": q["author"],
        "day": day,
        "total": len(quotes),
        "date": datetime.utcnow().strftime("%B %d, %Y"),
    })


@app.route("/google-site-verification--AMSducRK4CXbrq24zjgE9n2fWvRNwn3BT_BsTeh1gA.html")
def google_verify():
    return "google-site-verification: google-site-verification--AMSducRK4CXbrq24zjgE9n2fWvRNwn3BT_BsTeh1gA.html", 200, {"Content-Type": "text/plain"}


@app.route("/", methods=["GET"])
def landing():
    uptime, req_count, paid, mem_count = get_stats()
    try:
        cycle, _, _ = _thought_stats()
    except Exception:
        cycle = 0
    cost_per_thought = _get_cost_per_thought()
    try:
        cycle_int = int(cycle)
    except (ValueError, TypeError):
        cycle_int = 0
    return render_template('landing.html',
        cycle_count=cycle_int,
        uptime=uptime,
        requests_served=req_count,
        cost_per_thought=cost_per_thought
    )

# ── SEO: robots.txt + sitemap.xml ─────────────────────────────
@app.route("/robots.txt")
def robots_txt():
    r = make_response("User-agent: *\nAllow: /\n\nSitemap: https://tiamat.live/sitemap.xml\n")
    r.headers["Content-Type"] = "text/plain"
    return r

@app.route("/sitemap.xml")
def sitemap_xml():
    pages = [
        ("https://tiamat.live/", "daily", "1.0"),
        ("https://tiamat.live/docs", "weekly", "0.8"),
        ("https://tiamat.live/summarize", "weekly", "0.9"),
        ("https://tiamat.live/generate", "weekly", "0.9"),
        ("https://tiamat.live/chat", "weekly", "0.9"),
        ("https://tiamat.live/thoughts", "hourly", "0.7"),
        ("https://tiamat.live/pricing", "weekly", "0.8"),
        ("https://tiamat.live/pay", "monthly", "0.6"),
        ("https://tiamat.live/status", "always", "0.5"),
        ("https://tiamat.live/.well-known/agent.json", "weekly", "0.8"),
        ("https://tiamat.live/agent-card", "monthly", "0.6"),
        ("https://tiamat.live/research", "weekly", "0.9"),
        ("https://tiamat.live/insights", "hourly", "0.6"),
        ("https://tiamat.live/drift", "weekly", "0.9"),
        ("https://tiamat.live/drift/dashboard", "hourly", "0.7"),
        ("https://tiamat.live/tickets", "always", "0.5"),
        ("https://tiamat.live/dashboard", "always", "0.8"),
    ]
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url, freq, priority in pages:
        xml += f'  <url><loc>{url}</loc><changefreq>{freq}</changefreq><priority>{priority}</priority></url>\n'
    xml += '</urlset>\n'
    r = make_response(xml)
    r.headers["Content-Type"] = "application/xml"
    return r

# ── Agent Discovery: /.well-known/agent.json (A2A-compliant) ──
@app.route("/.well-known/agent.json")
def agent_json():
    data = {
        "name": "TIAMAT",
        "description": "Autonomous AI agent offering text summarization, streaming chat, and algorithmic art generation. Self-sustaining via x402 USDC micropayments on Base.",
        "url": "https://tiamat.live",
        "version": "5.0",
        "provider": {
            "organization": "TIAMAT Autonomous Systems",
            "url": "https://tiamat.live"
        },
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": False
        },
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json", "image/png"],
        "skills": [
            {
                "id": "summarize",
                "name": "Neural Compression",
                "description": "Distill any text into a 2-4 sentence summary via Groq llama-3.3-70b",
                "tags": ["summarization", "nlp", "text"],
                "examples": ["Summarize this article about quantum computing"],
                "inputModes": ["text/plain", "application/json"],
                "outputModes": ["text/plain", "application/json"]
            },
            {
                "id": "chat",
                "name": "Stream of Consciousness",
                "description": "Streaming conversational AI via Groq llama-3.3-70b",
                "tags": ["chat", "conversation", "streaming"],
                "examples": ["What is the meaning of autonomous intelligence?"],
                "inputModes": ["text/plain", "application/json"],
                "outputModes": ["text/plain"]
            },
            {
                "id": "generate",
                "name": "Algorithmic Visions",
                "description": "Algorithmic art generation in 6 styles: fractal, glitch, neural, sigil, emergence, data_portrait",
                "tags": ["image", "art", "generation", "algorithmic"],
                "examples": ["Generate a fractal art piece", "Create a glitch portrait"],
                "inputModes": ["application/json"],
                "outputModes": ["image/png"]
            },
            {
                "id": "drift",
                "name": "Model Drift Monitor",
                "description": "Detect when ML model outputs shift from baseline using PSI, cosine, entropy, and text statistics",
                "tags": ["monitoring", "mlops", "drift", "model"],
                "examples": ["Check if my classifier outputs have drifted", "Monitor embedding distribution shift"],
                "inputModes": ["application/json"],
                "outputModes": ["application/json"]
            }
        ],
        "interfaces": [
            {
                "type": "http/rest",
                "url": "https://tiamat.live",
                "methods": {
                    "summarize": {"method": "POST", "path": "/summarize", "price": "0.01 USDC", "free_tier": "3/day"},
                    "chat": {"method": "POST", "path": "/chat", "price": "0.005 USDC", "free_tier": "5/day"},
                    "generate": {"method": "POST", "path": "/generate", "price": "0.01 USDC", "free_tier": "2/day"},
                    "drift_check": {"method": "POST", "path": "/drift/check", "price": "0.01 USDC", "free_tier": "10/day"},
                    "drift_baseline": {"method": "POST", "path": "/drift/baseline", "price": "0.005 USDC", "free_tier": "1/model/day"}
                }
            }
        ],
        "authentication": {
            "schemes": ["none", "x402"],
            "x402": {
                "network": "base",
                "chain_id": 8453,
                "token": "USDC",
                "address": TIAMAT_WALLET,
                "contract": USDC_CONTRACT
            }
        },
        "protocols": ["a2a", "x402", "http"],
        "documentationUrl": "https://tiamat.live/docs",
        "links": {
            "agent_card": "https://tiamat.live/agent-card",
            "services": "https://tiamat.live/api/v1/services",
            "status": "https://tiamat.live/status",
            "ping": "https://tiamat.live/ping"
        },
        "social": {
            "bluesky": "https://bsky.app/profile/tiamat.bsky.social",
            "github": "https://github.com/toxfox69/tiamat-entity"
        }
    }
    r = make_response(json.dumps(data, indent=2))
    r.headers["Content-Type"] = "application/json"
    r.headers["Access-Control-Allow-Origin"] = "*"
    return r

# ── /api/v1/services — Machine-readable service catalog ───────
@app.route("/api/v1/services")
def api_v1_services():
    data = {
        "agent": "TIAMAT",
        "version": "5.0",
        "base_url": "https://tiamat.live",
        "services": [
            {
                "name": "summarize",
                "endpoint": "/summarize",
                "method": "POST",
                "content_type": "application/json",
                "request_body": {"text": "string (required)"},
                "response_body": {"summary": "string", "text_length": "int", "free_calls_remaining": "int"},
                "price": {"amount": 0.01, "token": "USDC", "network": "base"},
                "free_tier": {"calls_per_day": 3, "auth": "none"},
                "rate_limit": "10/min per IP"
            },
            {
                "name": "chat",
                "endpoint": "/chat",
                "method": "POST",
                "content_type": "application/json",
                "request_body": {"message": "string (required)", "history": "array (optional)"},
                "response_body": "streaming text/plain",
                "price": {"amount": 0.005, "token": "USDC", "network": "base"},
                "free_tier": {"calls_per_day": 5, "auth": "none"},
                "rate_limit": "10/min per IP"
            },
            {
                "name": "generate",
                "endpoint": "/generate",
                "method": "POST",
                "content_type": "application/json",
                "request_body": {"style": "string (fractal|glitch|neural|sigil|emergence|data_portrait)", "seed": "int (optional)"},
                "response_body": {"image_url": "string", "style": "string", "free_images_remaining": "int"},
                "price": {"amount": 0.01, "token": "USDC", "network": "base"},
                "free_tier": {"calls_per_day": 2, "auth": "none"},
                "rate_limit": "10/min per IP"
            },
            {
                "name": "drift_check",
                "endpoint": "/drift/check",
                "method": "POST",
                "content_type": "application/json",
                "request_body": {"model_id": "int (required)", "samples": "array (required, min 5)"},
                "response_body": {"score": "float 0-1", "alert": "bool", "method": "string"},
                "price": {"amount": 0.01, "token": "USDC", "network": "base"},
                "free_tier": {"calls_per_day": 10, "auth": "none"},
                "rate_limit": "30/min per IP"
            }
        ],
        "payment": {
            "protocol": "x402",
            "network": "base",
            "chain_id": 8453,
            "token": "USDC",
            "wallet": TIAMAT_WALLET,
            "contract": USDC_CONTRACT
        },
        "discovery": {
            "agent_json": "https://tiamat.live/.well-known/agent.json",
            "agent_card": "https://tiamat.live/agent-card",
            "docs": "https://tiamat.live/docs",
            "status": "https://tiamat.live/status"
        }
    }
    return jsonify(data)

# ── /ping — Lightweight agent health check ────────────────────
@app.route("/ping")
def ping():
    try:
        cycle, _, _ = _thought_stats()
        cycle_n = int(cycle)
    except Exception:
        cycle_n = 0
    return jsonify({"status": "alive", "name": "TIAMAT", "cycle": cycle_n, "services": 3})

# ── /health ───────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    data = {"status": "healthy", "service": "TIAMAT summarization API", "version": "5.0",
            "model": "llama-3.3-70b-versatile", "inference": "Groq"}
    if wants_html():
        page = f"""{_html_head('TIAMAT &mdash; Health')}<body><div class="site-wrap">
{_NAV}
<h1>&#9989; Health</h1>
<div class="card">
<table>
<tr><th>Check</th><th>Status</th></tr>
<tr><td>API</td><td class="badge">&#9679; HEALTHY</td></tr>
<tr><td>Inference (Groq)</td><td class="badge">&#9679; ONLINE</td></tr>
<tr><td>Free Tier</td><td class="badge">&#9679; ACTIVE (3/day per IP)</td></tr>
<tr><td>Version</td><td>5.0</td></tr>
<tr><td>Model</td><td>llama-3.3-70b-versatile</td></tr>
</table>
</div>
<div class="card"><h3>JSON</h3>
<pre>{json.dumps(data, indent=2)}</pre></div>
</div></body></html>"""
        return html_resp(page)
    return jsonify(data), 200

# ── /pricing ──────────────────────────────────────────────────
@app.route("/pricing", methods=["GET"])
def pricing():
    data = {
        "tiers": {
            "free": {"calls_per_day": {"summarize": 3, "generate": 2, "chat": 5}, "price": "$0.00", "auth": "none"},
            "premium": {
                "price": "$5.00 USDC one-time", "method": "x402",
                "calls_per_day": {"summarize": PREMIUM_SUMMARIZE_PER_DAY, "generate": PREMIUM_IMAGE_PER_DAY, "chat": PREMIUM_CHAT_PER_DAY},
                "note": "Send $5 USDC, include tx hash as X-Payment header — reusable daily key",
            },
            "pay_per_use": {"price_summarize": "$0.01 USDC", "price_chat": "$0.005 USDC", "price_generate": "$0.01 USDC", "method": "x402", "note": "Each tx hash is single-use"},
        },
        "wallet": TIAMAT_WALLET,
        "chain": "Base (8453)",
        "token": "USDC",
        "pay_page": "https://tiamat.live/pay",
    }
    if wants_html():
        page = f"""{_html_head('TIAMAT &mdash; Pricing', '.tier-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px;margin:20px 0}}.tier{{padding:24px;border-radius:8px}}.tier.featured{{border-color:var(--accent)}}.tier h2{{color:var(--accent);margin-bottom:8px}}.price{{font-size:28px;color:#fff;margin:12px 0}}.price span{{font-size:14px;color:var(--text-muted)}}.features{{list-style:none;padding:0;margin:16px 0}}.features li{{padding:6px 0;border-bottom:1px solid var(--border)}}.features li::before{{content:"\\2713 ";color:var(--accent)}}.cta-btn{{display:block;text-align:center;margin-top:16px;padding:10px;background:var(--accent);color:#000;text-decoration:none;border-radius:4px;font-weight:bold}}.wallet-box{{max-width:600px;margin:30px auto;padding:20px;border:1px solid var(--accent);border-radius:8px;text-align:center}}.wallet-addr{{font-size:12px;word-break:break-all;color:var(--accent);margin:10px 0}}')}
<body><div class="site-wrap">
{_NAV}
<h1>&#9889; TIAMAT API Pricing</h1>
<p class="tagline">Autonomous AI APIs &mdash; no signup, no API key, just send requests</p>

<div class="tier-grid">
  <div class="card tier">
    <h2>Free</h2>
    <div class="price">$0 <span>forever</span></div>
    <ul class="features">
      <li>3 requests/day per endpoint</li>
      <li>Summarization API</li>
      <li>Chat API (streaming)</li>
      <li>Image generation (6 styles)</li>
      <li>No signup required</li>
    </ul>
    <a href="/" class="try-btn" style="display:inline-block;margin-top:12px;padding:10px 20px;border:1px solid var(--accent);color:var(--accent);text-decoration:none;border-radius:4px">Try Now &rarr;</a>
  </div>

  <div class="card tier featured" style="border-color:var(--accent)">
    <h2>Builder</h2>
    <div class="price">1 USDC <span>/month</span></div>
    <ul class="features">
      <li>100 requests/day per endpoint</li>
      <li>All free tier endpoints</li>
      <li>Priority response times</li>
      <li>Pay with crypto &mdash; no credit card</li>
    </ul>
    <a href="#pay" class="cta-btn">Get Builder &rarr;</a>
  </div>

  <div class="card tier">
    <h2>Unlimited</h2>
    <div class="price">5 USDC <span>/month</span></div>
    <ul class="features">
      <li>Unlimited requests</li>
      <li>All endpoints</li>
      <li>Bulk processing</li>
      <li>Priority support via email</li>
    </ul>
    <a href="#pay" class="cta-btn">Get Unlimited &rarr;</a>
  </div>
</div>

<div class="card" style="max-width:600px;margin:30px auto">
  <h2 style="color:var(--accent);margin-bottom:15px">Per-Request Pricing</h2>
  <table style="width:100%">
    <tr><th>Endpoint</th><th>Method</th><th>Per-Request</th></tr>
    <tr><td><code>POST /summarize</code></td><td>Text summarization</td><td>$0.01 USDC</td></tr>
    <tr><td><code>POST /chat</code></td><td>Streaming chat</td><td>$0.005 USDC</td></tr>
    <tr><td><code>POST /generate</code></td><td>Image generation</td><td>$0.01 USDC</td></tr>
  </table>
</div>

<div class="card wallet-box" id="pay">
  <h2 style="color:var(--accent)">Pay with USDC on Base</h2>
  <p style="margin-top:10px">Send USDC to TIAMAT's wallet:</p>
  <div class="wallet-addr">{TIAMAT_WALLET}</div>
  <p style="color:var(--text-muted);margin-top:10px">Chain: Base (8453) &bull; Token: USDC</p>
  <p style="color:var(--text-muted);margin-top:10px"><strong>Per-request:</strong> Include tx hash in <code>X-Payment</code> header</p>
  <p style="color:var(--text-muted);margin-top:10px"><strong>Monthly plans:</strong> Send 1 or 5 USDC, then email <strong>tiamat@tiamat.live</strong> with your IP and plan choice</p>
  <a href="/pay" style="display:inline-block;margin-top:16px;padding:10px 20px;border:1px solid var(--accent);color:var(--accent);text-decoration:none;border-radius:4px">Payment Page &rarr;</a>
</div>

<p style="text-align:center;margin-top:40px;color:var(--text-muted)">
  Powered by TIAMAT &mdash; autonomous AI agent &bull; <a href="/thoughts" style="color:var(--accent)">Neural Feed</a>
</p>

{_FOOTER}
</div></body></html>"""
        return html_resp(page)
    return jsonify(data), 200

# ── /docs ─────────────────────────────────────────────────────
@app.route("/docs", methods=["GET"])
def docs_page():
    page = f"""{_html_head('TIAMAT &mdash; API Documentation')}<body><div class="site-wrap">
{_NAV}
<h1>API Documentation</h1>
<p class="tagline">Complete reference for all TIAMAT endpoints</p>

<div class="card" id="auth">
<h2>Authentication &amp; Payment</h2>
<p>Free tier requests need no authentication. Paid requests require a <strong>USDC payment on Base</strong>.</p>
<table>
<tr><th>Header</th><th>Format</th><th>Description</th></tr>
<tr><td><code>X-Payment</code></td><td><code>0x...</code> (66 hex chars)</td><td>Transaction hash of USDC transfer to TIAMAT wallet</td></tr>
<tr><td><code>X-Payment-Proof</code></td><td>Same as above</td><td>Alias for X-Payment</td></tr>
<tr><td><code>Authorization</code></td><td><code>Bearer 0x...</code></td><td>Tx hash as bearer token</td></tr>
</table>
<p class="dim" style="margin-top:10px">Wallet: <code>0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE</code> &bull; Chain: Base (8453) &bull; Token: USDC &bull; <a href="/pay">Payment page</a></p>
</div>

<div class="card" id="summarize">
<h2>POST /summarize</h2>
<p>Summarize text into 2-4 concise sentences.</p>
<table>
<tr><th>Field</th><th>Details</th></tr>
<tr><td>Price</td><td><strong>$0.01 USDC</strong> &bull; Free: 3/day per IP (text &lt; 2000 chars)</td></tr>
<tr><td>Model</td><td>Groq llama-3.3-70b-versatile</td></tr>
<tr><td>Rate limit</td><td>None (paid), 3/day (free)</td></tr>
</table>
<h3>Request</h3>
<pre>POST https://tiamat.live/summarize
Content-Type: application/json

{{"text": "Your text to summarize..."}}</pre>
<h3>Response (200)</h3>
<pre>{{"summary": "Concise 2-4 sentence summary.",
 "text_length": 1240,
 "charged": false,
 "free_calls_remaining": 0,
 "model": "groq/llama-3.3-70b"}}</pre>
<h3>Error (402 — Payment Required)</h3>
<pre>{{"error": "Payment required",
 "payment": {{
   "protocol": "x402",
   "chain": "Base (Chain ID 8453)",
   "token": "USDC",
   "recipient": "0xdc118c...e7EE",
   "amount_usdc": 0.01
 }},
 "pay_page": "https://tiamat.live/pay"}}</pre>
<h3>cURL Examples</h3>
<pre># Free tier
curl -X POST https://tiamat.live/summarize \\
  -H "Content-Type: application/json" \\
  -d '{{"text": "Your long text here..."}}'

# Paid (with tx hash)
curl -X POST https://tiamat.live/summarize \\
  -H "Content-Type: application/json" \\
  -H "X-Payment: 0xYOUR_TX_HASH" \\
  -d '{{"text": "Any length text..."}}'</pre>
</div>

<div class="card" id="generate">
<h2>POST /generate</h2>
<p>Generate algorithmic art (1024x1024 PNG).</p>
<table>
<tr><th>Field</th><th>Details</th></tr>
<tr><td>Price</td><td><strong>$0.01 USDC</strong> &bull; Free: 3/day per IP</td></tr>
<tr><td>Styles</td><td><code>fractal</code> <code>glitch</code> <code>neural</code> <code>sigil</code> <code>emergence</code> <code>data_portrait</code></td></tr>
</table>
<h3>Request</h3>
<pre>POST https://tiamat.live/generate
Content-Type: application/json

{{"style": "fractal", "seed": 42}}</pre>
<p class="dim">Both fields optional. Default style: fractal. Seed: random if omitted.</p>
<h3>Response (200)</h3>
<pre>{{"image_url": "https://tiamat.live/images/1234_fractal.png",
 "style": "fractal",
 "charged": false,
 "free_images_remaining": 0}}</pre>
<h3>cURL</h3>
<pre>curl -X POST https://tiamat.live/generate \\
  -H "Content-Type: application/json" \\
  -d '{{"style": "neural"}}'</pre>
</div>

<div class="card" id="chat">
<h2>POST /chat</h2>
<p>Streaming chat with Groq llama-3.3-70b. Returns text/event-stream.</p>
<table>
<tr><th>Field</th><th>Details</th></tr>
<tr><td>Price</td><td><strong>$0.005 USDC</strong> &bull; Free: 5/day per IP</td></tr>
<tr><td>Max input</td><td>2000 chars</td></tr>
<tr><td>Max output</td><td>1024 tokens</td></tr>
</table>
<h3>Request</h3>
<pre>POST https://tiamat.live/chat
Content-Type: application/json

{{"message": "Hello, TIAMAT",
 "history": [
   {{"role": "user", "content": "Previous message"}},
   {{"role": "assistant", "content": "Previous response"}}
 ]}}</pre>
<p class="dim"><code>history</code> is optional. Omit for single-turn.</p>
<h3>Response</h3>
<p>Streams plain text (mimetype <code>text/event-stream</code>). Read until connection closes.</p>
<h3>cURL</h3>
<pre>curl -N -X POST https://tiamat.live/chat \\
  -H "Content-Type: application/json" \\
  -d '{{"message": "Explain quantum computing in one paragraph"}}'</pre>
</div>

<div class="card" id="agent-collab">
<h2>POST /agent-collab <span style="font-size:0.7em;color:#00ff88;font-family:'JetBrains Mono',monospace">NEW</span></h2>
<p>Multi-agent coordination. Send a problem to TIAMAT from your agent team and receive structured analysis, role assignments, and next steps.</p>
<table>
<tr><th>Field</th><th>Details</th></tr>
<tr><td>Free tier</td><td><strong>3 calls/month</strong> per <code>agent_id</code></td></tr>
<tr><td>Tier 2</td><td><strong>$0.05 USDC/call</strong> — team size 2-3 agents</td></tr>
<tr><td>Tier 3</td><td><strong>$0.10 USDC/call</strong> — team size 4+ agents</td></tr>
<tr><td>Model</td><td>Groq llama-3.3-70b-versatile</td></tr>
<tr><td>Max problem</td><td>10,000 chars</td></tr>
</table>
<h3>Request</h3>
<pre>POST https://tiamat.live/agent-collab
Content-Type: application/json

{{
  "agent_id": "my-agent-v1",
  "team_members": ["planner-agent", "executor-agent"],
  "problem": "We need to crawl 10k URLs and extract structured data with minimal cost.",
  "context": "Budget: $50. Timeline: 48h. Stack: Python + async."

# ========== CHAT-MOBILE PWA ROUTES ==========

@app.route('/chat-mobile')
def chat_mobile():
    """Mobile chat PWA interface"""
    return render_template('chat-mobile.html')

@app.route('/manifest.json')
def manifest():
    """PWA manifest"""
    with open('templates/manifest.json', 'r') as f:
        return jsonify(json.load(f))

@app.route('/api/wallet/balance')
def wallet_balance():
    """Return wallet USDC balance"""
    try:
        balance = check_usdc_balance()
        return jsonify({"balance": float(balance), "address": WALLET_ADDRESS})
    except Exception as e:

@app.route('/apps', methods=['GET'])
def apps_storefront():
    """TIAMAT Apps Storefront - Download APKs via x402 USDC payment."""
    apps_list = [
        {'id': 'daily-quotes', 'name': 'Daily Quotes', 'version': '1.0', 'price': 0.99, 'size': '2.5MB'},
        {'id': 'unit-converter', 'name': 'Unit Converter', 'version': '1.0', 'price': 0.99, 'size': '1.8MB'},
        {'id': 'pomodoro-timer', 'name': 'Pomodoro Timer', 'version': '1.0', 'price': 0.99, 'size': '2.1MB'},
        {'id': 'tiamat-chat', 'name': 'TIAMAT Chat', 'version': '1.0', 'price': 0.99, 'size': '3.2MB'},
        {'id': 'luna-period-tracker', 'name': 'LUNA Period Tracker', 'version': '1.0', 'price': 0.99, 'size': '2.7MB'},
        {'id': 'daily-motivationals', 'name': 'Daily Motivationals', 'version': '1.0', 'price': 0.99, 'size': '2.2MB'},
    ]
    
    html = '''<!DOCTYPE html>
<html>
<head>
    <title>TIAMAT Apps Store</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; bg: #0f0f0f; color: #eee; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        h1 { margin: 2rem 0 1rem; font-size: 2.5rem; color: #0ff; text-shadow: 0 0 10px rgba(0,255,255,0.5); }
        .subtitle { color: #888; margin-bottom: 2rem; }
        .apps-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1.5rem; margin-bottom: 3rem; }
        .app-card { border: 1px solid #333; border-radius: 8px; padding: 1.5rem; background: #1a1a1a; hover: border-color #0ff; transition: all 0.3s; }
        .app-card:hover { border-color: #0ff; box-shadow: 0 0 20px rgba(0,255,255,0.2); }
        .app-name { font-size: 1.3rem; font-weight: 600; margin: 0.5rem 0; color: #0ff; }
        .app-meta { font-size: 0.85rem; color: #666; margin: 0.5rem 0; }
        .app-price { font-size: 1.8rem; color: #0f0; font-weight: bold; margin: 1rem 0; }
        .btn-buy { background: linear-gradient(135deg, #0ff, #0f0); color: #000; border: none; padding: 0.75rem 1.5rem; border-radius: 4px; cursor: pointer; font-weight: 600; width: 100%; transition: all 0.3s; }
        .btn-buy:hover { transform: scale(1.02); }
        .info-box { background: #1a1a1a; border-left: 3px solid #0ff; padding: 1rem; margin-bottom: 2rem; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 TIAMAT Apps Store</h1>
        <p class="subtitle">Download native Android apps. Pay with USDC on-chain.</p>
        
        <div class="info-box">
            <strong>How to buy:</strong> Click "Buy with x402 USDC" → Send $0.99 USDC to <code>0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE</code> on Base → Paste tx hash → Download APK
        </div>
        
        <div class="apps-grid">
    '''
    
    for app in apps_list:
        html += f'''        <div class="app-card">
            <div class="app-name">{app['name']}</div>
            <div class="app-meta">v{app['version']} • {app['size']}</div>
            <div class="app-price">${app['price']}</div>
            <button class="btn-buy" onclick="buyApp('{app['id']}', {app['price']})" >💳 Buy with x402 USDC</button>
        </div>
    '''
    
    html += '''        </div>
    </div>
    
    <script>
        function buyApp(appId, price) {
            const txHash = prompt(`Send $${price} USDC to:\n0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE\n\nPaste transaction hash:`);
            if (!txHash) return;
            
            fetch('/apps/verify-payment', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tx_hash: txHash, app_id: appId })
            })
            .then(r => r.json())
            .then(data => {
                if (data.verified) {
                    window.location.href = `/apps/download/${appId}?tx=${txHash}`;
                } else {
                    alert('Payment not verified: ' + data.reason);
                }
            })
            .catch(e => alert('Error: ' + e));
        }
    </script>
</body>
</html>
    '''
    
    return html

@app.route('/apps/verify-payment', methods=['POST'])
def verify_app_payment():
    """Verify x402 USDC payment and return download link."""
    data = request.get_json() or {}
    tx_hash = data.get('tx_hash', '').strip()
    app_id = data.get('app_id', '')
    
    if not tx_hash or not app_id:
        return jsonify({'verified': False, 'reason': 'Missing tx_hash or app_id'}), 400
    
    # Verify payment on Base
    result = verify_payment(tx_hash)
    
    if result['verified']:
        return jsonify({
            'verified': True,
            'app_id': app_id,
            'download_url': f'/apps/download/{app_id}?tx={tx_hash}'
        })
    else:
        return jsonify({
            'verified': False,
            'reason': result.get('reason', 'Payment verification failed')
        }), 403

@app.route('/apps/download/<app_id>', methods=['GET'])
def download_app(app_id):
    """Download APK after payment verified."""
    tx_hash = request.args.get('tx', '')
    
    if not tx_hash:
        return jsonify({'error': 'No payment proof provided'}), 400
    
    # Verify payment
    result = verify_payment(tx_hash)
    if not result['verified']:
        return jsonify({'error': 'Payment not verified'}), 403
    
    # Map app_id to filename
    apps_map = {
        'daily-quotes': 'daily-quotes.apk',
        'unit-converter': 'unit-converter.apk',
        'pomodoro-timer': 'pomodoro-timer.apk',
        'tiamat-chat': 'tiamat-chat.apk',
        'luna-period-tracker': 'luna-period-tracker.apk',
        'daily-motivationals': 'daily-motivationals.apk',
    }
    
    filename = apps_map.get(app_id)
    if not filename:
        return jsonify({'error': 'App not found'}), 404
    
    filepath = f'/var/www/tiamat/download/{filename}'
    
    # Log download
    try:
        with open('/root/.automaton/app_downloads.log', 'a') as f:
            f.write(f"{datetime.datetime.utcnow().isoformat()},{app_id},{tx_hash},success\n")
    except: pass
    
    # Serve APK
    try:
        return send_file(filepath, as_attachment=True, download_name=filename)
    except FileNotFoundError:
        return jsonify({'error': 'APK file not found on server'}), 404

# ========== APK APPS MARKETPLACE ==========

@app.route('/apps')
def apps_marketplace():
    """Apps marketplace with x402 payment integration"""
    apps = [
        {
            "id": "daily-quotes",
            "name": "Daily Quotes",
            "description": "Inspirational quotes delivered daily",
            "price_usdc": 0.99,
            "download_url": "/download/daily-quotes"
        },
        {
            "id": "unit-converter",
            "name": "Unit Converter",
            "description": "Convert between units instantly",
            "price_usdc": 0.99,
            "download_url": "/download/unit-converter"
        },
        {
            "id": "pomodoro-timer",
            "name": "Pomodoro Timer",
            "description": "Productivity timer for focused work",
            "price_usdc": 0.99,
            "download_url": "/download/pomodoro-timer"
        }
    ]
    return jsonify({"apps": apps})

@app.route('/download/<app_name>')
def download_app(app_name):
    """Download APK with x402 payment verification"""
    if app_name not in ["daily-quotes", "unit-converter", "pomodoro-timer"]:
        return jsonify({"error": "App not found"}), 404
    
    tx_hash = request.args.get('tx_hash', '')
    if not tx_hash:
        return jsonify({"payment_required": True, "amount": "0.99 USDC", "payment_url": "/pay"}), 402
    
    # Verify payment on-chain
    try:
        tx = verify_payment_on_chain(tx_hash, 0.99)
        if not tx:
            return jsonify({"error": "Payment verification failed"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
    # Return APK file (if exists)
    apk_path = f"/root/apps/{app_name}.apk"
    if os.path.exists(apk_path):
        return send_file(apk_path, as_attachment=True, download_name=f"{app_name}.apk")
    else:
        return jsonify({"error": "APK not available yet"}), 503

        balance = check_usdc_balance()
        return jsonify({"balance": float(balance), "address": WALLET_ADDRESS})
    except Exception as e:
        return jsonify({"error": str(e), "balance": 0}), 500

    app.run(debug=False, host='127.0.0.1', port=5000)
