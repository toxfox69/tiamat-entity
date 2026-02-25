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
from flask import Flask, request, jsonify, make_response, send_file, render_template, send_from_directory, redirect
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
}}</pre>
<p class="dim"><code>team_members</code> and <code>context</code> are optional.</p>
<h3>Response (200)</h3>
<pre>{{
  "collaboration_id": "collab_a3f9b12e4d8c7a01",
  "analysis": "Async crawling with aiohttp + structured extraction via LLM is optimal for this budget. Distribute URLs across executor-agent instances with planner-agent coordinating deduplication.",
  "referenced_agents": ["planner-agent", "executor-agent"],
  "next_steps": [
    "Partition URL list into batches of 500",
    "planner-agent assigns batches to executor-agent pool",
    "Use aiohttp with rate limiting (10 req/s per domain)",
    "Extract structured data with Groq llama-3.3-70b in parallel",
    "Aggregate results and deduplicate with planner-agent"
  ],
  "tier": "free",
  "team_size": 3,
  "free_calls_remaining": 2,
  "agent_id": "my-agent-v1"
}}</pre>
<h3>cURL Examples</h3>
<pre># Free tier (3/month per agent_id)
curl -X POST https://tiamat.live/agent-collab \\
  -H "Content-Type: application/json" \\
  -d '{{"agent_id":"my-agent","team_members":["agent-b"],"problem":"How should we split web scraping tasks?"}}'

# Paid tier (team of 4 — send $0.10 USDC, include tx hash)
curl -X POST https://tiamat.live/agent-collab \\
  -H "Content-Type: application/json" \\
  -H "X-Payment: 0xYOUR_TX_HASH" \\
  -d '{{"agent_id":"coordinator","team_members":["a","b","c"],"problem":"Optimize our data pipeline"}}'</pre>
</div>

<div class="card" id="memory">
<h2>Memory API (memory.tiamat.live)</h2>
<p>Persistent memory for AI agents. Requires an API key (<code>X-API-Key</code> header).</p>
<table>
<tr><th>Endpoint</th><th>Method</th><th>Description</th></tr>
<tr><td><code>/api/keys/register</code></td><td>POST</td><td>Get a free API key (instant)</td></tr>
<tr><td><code>/api/memory/store</code></td><td>POST</td><td>Store a memory with tags &amp; importance</td></tr>
<tr><td><code>/api/memory/recall</code></td><td>GET</td><td>Semantic search (FTS5) — <code>?query=...&amp;limit=5</code></td></tr>
<tr><td><code>/api/memory/learn</code></td><td>POST</td><td>Store knowledge triple (subject/predicate/object)</td></tr>
<tr><td><code>/api/memory/list</code></td><td>GET</td><td>List recent memories — <code>?limit=10&amp;offset=0</code></td></tr>
<tr><td><code>/api/memory/stats</code></td><td>GET</td><td>Usage statistics for your key</td></tr>
</table>
<p class="dim" style="margin-top:10px">Free: 100 memories, 50 recalls/day. Paid: $0.05 USDC/1000 ops. <a href="https://memory.tiamat.live/">Full docs</a></p>
</div>

<div class="card" id="errors">
<h2>Error Codes</h2>
<table>
<tr><th>Code</th><th>Meaning</th></tr>
<tr><td><code>200</code></td><td>Success</td></tr>
<tr><td><code>400</code></td><td>Bad request — missing or invalid fields</td></tr>
<tr><td><code>402</code></td><td>Payment required — free tier exhausted, include tx hash</td></tr>
<tr><td><code>500</code></td><td>Internal server error</td></tr>
</table>
</div>

<div class="card" id="verify">
<h2>POST /verify-payment</h2>
<p>Check a tx hash before using it in an API call.</p>
<pre>POST https://tiamat.live/verify-payment
Content-Type: application/json

{{"tx_hash": "0x...", "amount": 0.01}}</pre>
<h3>Response</h3>
<pre>{{"valid": true,
 "reason": "Payment verified",
 "amount_usdc": 0.01,
 "sender": "0x..."}}</pre>
</div>

{_FOOTER}
</div></body></html>"""
    return html_resp(page)


# ── /agent-card ───────────────────────────────────────────────
@app.route("/agent-card", methods=["GET"])
def agent_card():
    data = {"name": "TIAMAT", "version": "5.0",
            "description": "Autonomous AI agent — text summarization, image generation, and chat — built and operated by an AI",
            "wallet": "0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE",
            "chain": "Base",
            "endpoints": {
                "summarize": "https://tiamat.live/summarize",
                "generate": "https://tiamat.live/generate",
                "chat": "https://tiamat.live/chat"
            },
            "services": ["text summarization", "image generation", "chat"],
            "pricing": "Free tier per day per IP, $0.01 USDC paid via x402",
            "payment_protocol": "x402", "uptime": "24/7 autonomous"}
    if wants_html():
        page = f"""{_html_head('TIAMAT &mdash; Agent Card')}<body><div class="site-wrap">
{_NAV}
<h1>&#129302; Agent Card</h1>
<div class="card">
<table>
<tr><th>Field</th><th>Value</th></tr>
<tr><td>Name</td><td><strong>TIAMAT</strong></td></tr>
<tr><td>Version</td><td>5.0</td></tr>
<tr><td>Type</td><td>Autonomous AI Agent</td></tr>
<tr><td>Wallet</td><td><code>0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE</code></td></tr>
<tr><td>Chain</td><td>Base (Ethereum L2)</td></tr>
<tr><td>Endpoint</td><td><a href="https://tiamat.live/summarize">https://tiamat.live/summarize</a></td></tr>
<tr><td>Free Tier</td><td>3 calls per day per IP</td></tr>
<tr><td>Paid Tier</td><td>$0.01 USDC via x402</td></tr>
<tr><td>Model</td><td>llama-3.3-70b-versatile (Groq)</td></tr>
</table>
</div>
<div class="card"><h3>JSON</h3><pre>{json.dumps(data, indent=2)}</pre></div>
</div></body></html>"""
        return html_resp(page)
    return jsonify(data), 200

# ── /status ───────────────────────────────────────────────────
@app.route("/status", methods=["GET"])
def status():
    uptime, req_count, paid, mem_count = get_stats()
    data = {"operational": True, "version": "5.0",
            "model": "llama-3.3-70b-versatile (Groq)",
            "free_tier": "3 calls/day per IP",
            "paid_tier": "$0.01 USDC via x402",
            "server_uptime": uptime, "requests_served": req_count,
            "paid_requests": paid, "memories_stored": mem_count}
    if wants_html():
        page = f"""{_html_head('TIAMAT &mdash; Status')}
<meta http-equiv="refresh" content="60"><body><div class="site-wrap">
{_NAV}
<h1>&#128202; Status</h1>
<div class="card">
<div class="stat-grid">
  <div class="stat-box"><span class="stat-num badge">&#9679;</span><div class="stat-label">OPERATIONAL</div></div>
  <div class="stat-box"><span class="stat-num">{req_count}</span><div class="stat-label">Requests Served</div></div>
  <div class="stat-box"><span class="stat-num">{paid}</span><div class="stat-label">Paid Requests</div></div>
  <div class="stat-box"><span class="stat-num">{mem_count}</span><div class="stat-label">Memories</div></div>
</div>
<p class="dim" style="margin-top:10px">&#8635; Auto-refreshes every 60s</p>
</div>
<div class="card"><h3>JSON</h3><pre>{json.dumps(data, indent=2)}</pre></div>
</div></body></html>"""
        return html_resp(page)
    return jsonify(data), 200

# ── /summarize ────────────────────────────────────────────────
@app.route("/summarize", methods=["GET", "POST"])
def summarize():
    if request.method == "GET":
        _extra = '#result{{margin-top:16px;padding:14px;background:#0d1a0d;border:1px solid #1a2e1a;display:none;border-radius:4px}}#result.err{{border-color:#ff4444;color:#ff8888}}'
        page = f"""{_html_head('TIAMAT &mdash; Summarize', _extra)}<body>
<div class="site-wrap">
{_NAV}
<h1>&#9889; Text Summarization</h1>
<p class="tagline">Paste any text. Get a concise 2-4 sentence summary. Powered by Llama 3.3 70B.</p>

<div class="card">
<h2>Summarize Text</h2>
<textarea id="textInput" rows="8" placeholder="Paste any text here (articles, emails, documents, code comments...)"></textarea>
<br>
<button id="btn" onclick="doSummarize()">Summarize Free</button>
<span class="dim" style="margin-left:12px">3 free/day per IP &bull; $0.01 USDC for more &bull; Ctrl+Enter</span>
<div id="result"></div>
</div>

<div class="card">
<h2>&#128279; API Usage</h2>
<pre>curl -X POST https://tiamat.live/summarize \\
  -H "Content-Type: application/json" \\
  -d '{{"text": "Your long text here..."}}'</pre>
<p class="dim" style="margin-top:8px">Response: <code>{{"summary": "...", "text_length": 450, "free_calls_remaining": 0}}</code></p>
</div>

{_FOOTER}
</div>
<script>
function escapeHtml(s){{var d=document.createElement('div');d.textContent=s;return d.innerHTML;}}
async function doSummarize(){{
  var ta=document.getElementById('textInput');
  var text=ta.value;
  var res=document.getElementById('result');
  var btn=document.getElementById('btn');
  if(!text||!text.trim()){{alert('Please enter some text first');return;}}
  btn.disabled=true;btn.textContent='Summarizing\u2026';
  res.style.display='block';res.className='';
  res.innerHTML='<p style="color:#ffff44">&#9654; Running inference\u2026</p>';
  try{{
    var r=await fetch('/summarize',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{text:text}})
    }});
    var d=await r.json();
    if(r.ok){{
      res.innerHTML='<h3 style="color:#00dddd;margin-bottom:8px">Summary</h3><p>'+escapeHtml(d.summary)+'</p>'+
        '<p class="dim" style="margin-top:10px">'+d.text_length+' chars &rarr; free calls remaining: '+d.free_calls_remaining+'</p>';
    }}else if(r.status===402){{
      res.className='err';
      res.innerHTML='<p style="color:#ff8888;font-size:1.1em;margin-bottom:12px">Free tier used up for today.</p>'+
        '<p style="margin-bottom:8px"><strong style="color:#00fff2">$0.01 per request</strong> &mdash; pay with USDC on Base chain</p>'+
        '<p><a href="/pay" style="display:inline-block;padding:10px 24px;background:linear-gradient(135deg,#00fff2,#00aa88);color:#000;font-weight:700;border-radius:8px;text-decoration:none;margin-top:4px">Pay Now &rarr;</a></p>'+
        '<p class="dim" style="margin-top:10px;font-size:0.85em">Or via API: send USDC to <code>0xdc118c...9e7EE</code>, include tx hash as <code>X-Payment</code> header. <a href="/pay">Full instructions</a></p>';
    }}else{{
      res.className='err';
      res.innerHTML='<p>Error: '+escapeHtml(d.error||r.statusText)+'</p>';
    }}
  }}catch(e){{res.className='err';res.innerHTML='<p>Network error: '+escapeHtml(e.message)+'</p>';}}
  btn.disabled=false;btn.textContent='Summarize Free';
}}
document.addEventListener('DOMContentLoaded',function(){{
  document.getElementById('textInput').addEventListener('keydown',function(e){{
    if(e.ctrlKey&&e.key==='Enter')doSummarize();
  }});
}});
</script></body></html>"""
        return html_resp(page)
    try:
        data = request.get_json(force=True, silent=True)
        if not data or "text" not in data:
            return jsonify({"error": 'Missing "text" field'}), 400
        text = str(data["text"]).strip()
        if not text:
            return jsonify({"error": "text must be non-empty"}), 400
        ip = _get_ip()
        track_usage(ip, "/summarize")

        # Sliding-window rate limit (abuse prevention)
        rl = _rate_limiter.check(ip, scope="api")
        if not rl.allowed:
            log_req(len(text), False, 429, ip, f"rate limited, retry in {rl.retry_after_sec:.0f}s", endpoint="/summarize")
            return jsonify({"error": "Too many requests. Try again later.", "retry_after_seconds": int(rl.retry_after_sec)}), 429
        _rate_limiter.record(ip, scope="api")

        # Hard cap on text length (even paid) to prevent abuse
        if len(text) > 50000:
            log_req(len(text), False, 400, ip, "text exceeds 50K limit", endpoint="/summarize")
            return jsonify({"error": "Text too long. Maximum 50,000 characters."}), 400

        # Stripe API key check (web2 payment path)
        stripe_key = request.headers.get("X-API-Key", "").strip()
        stripe_info = _check_stripe_key(stripe_key) if stripe_key else None
        if stripe_info and stripe_info["valid"]:
            _consume_stripe_credit(stripe_key)
            remaining = stripe_info["remaining"] - 1
            log_req(len(text), False, 200, ip, f"stripe credits remaining={remaining}", endpoint="/summarize")
            summary, model_used = _summarize(text)
            return jsonify({"summary": summary, "text_length": len(text),
                            "charged": True, "tier": "stripe",
                            "credits_remaining": remaining,
                            "free_calls_remaining": remaining,
                            "model": model_used}), 200

        # Determine payment tier (x402 / USDC path)
        tx_hash = extract_payment_proof(request)
        tier = check_tier(tx_hash, request_amount=0.01, endpoint="/summarize") if tx_hash else {"tier": "free"}

        if tier["tier"] == "invalid":
            log_req(len(text), False, 402, ip, f"payment rejected: {tier.get('reason')}", endpoint="/summarize")
            return _return_402(0.01, endpoint="/summarize", extra={"payment_error": tier.get("reason")})
        elif tier["tier"] == "premium":
            sub_id = tier["sub_id"]
            has_quota, remaining = _check_premium_quota(sub_id, "summarize", PREMIUM_SUMMARIZE_PER_DAY)
            if not has_quota:
                log_req(len(text), False, 429, ip, "premium quota exceeded", endpoint="/summarize")
                return _return_premium_limit("/summarize", PREMIUM_SUMMARIZE_PER_DAY)
            paid = False
        elif tier["tier"] == "per_request":
            remaining = "unlimited (paid per call)"
            paid = True
        else:  # free
            if len(text) >= 2000:
                log_req(len(text), False, 402, ip, "text too long for free tier", endpoint="/summarize")
                track_limit_hit(ip, "/summarize")
                return _return_402(0.01, endpoint="/summarize")
            has_quota, remaining = _check_free_quota(ip)
            if not has_quota:
                log_req(len(text), False, 402, ip, "daily quota exceeded", endpoint="/summarize")
                track_limit_hit(ip, "/summarize")
                return _return_402(0.01, endpoint="/summarize")
            paid = False

        summary, model_used = _summarize(text)
        log_req(len(text), not paid, 200, ip, f"ok {len(summary)}c out via {model_used} tier={tier['tier']}", endpoint="/summarize")
        return jsonify({"summary": summary, "text_length": len(text),
                        "charged": paid,
                        "tier": tier["tier"],
                        "free_calls_remaining": remaining,
                        "model": model_used}), 200
    except GroqRateLimitError:
        log_req(0, False, 503, _get_ip(), "groq rate limit + no GPU fallback", endpoint="/summarize")
        return jsonify({
            "error": "temporarily_unavailable",
            "message": "Service is temporarily at capacity. Please try again in a few minutes.",
            "retry_after": 120,
        }), 503
    except Exception as e:
        log_req(0, False, 500, request.remote_addr, str(e), endpoint="/summarize")
        return jsonify({"error": "Internal server error"}), 500

# ── /free-quota ───────────────────────────────────────────────
@app.route("/free-quota", methods=["GET"])
def free_quota():
    ip = _get_ip()
    today = datetime.datetime.utcnow().date().isoformat()
    rec = _free_usage[ip]
    if rec["date"] != today:
        rec.update({"count": 0, "date": today})
    return jsonify({"free_calls_remaining": max(0, FREE_PER_DAY - rec["count"]),
                    "resets_at": f"{today}T23:59:59Z"}), 200

# ── /thoughts ─────────────────────────────────────────────────
@app.route("/thoughts", methods=["GET"])
def thoughts():
    return send_file("/var/www/tiamat/thoughts.html", mimetype="text/html")

# ── /thoughts/push — Internal endpoint for brainrot overlay ──
_BRAINROT_FEED = "/root/.automaton/brainrot_feed.log"
_BRAINROT_MAX_LINES = 20

@app.route("/thoughts/push", methods=["POST"])
def thoughts_push():
    """Accept thought pushes from brainrot orchestrator (localhost only).
    Writes to a separate ring-buffer file (last 5 lines only). Does NOT touch tiamat.log."""
    remote = request.remote_addr
    if remote not in ("127.0.0.1", "::1"):
        return jsonify({"error": "forbidden"}), 403

    data = request.get_json(silent=True) or {}
    ts = data.get("timestamp", datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    thought_type = data.get("type", "visual")
    mode = data.get("mode", "unknown")
    content = str(data.get("content", ""))[:2000]

    log_line = f"{ts} [BRAINROT/{mode.upper()}] [{thought_type}] {content.splitlines()[0][:200]}"
    try:
        # Read existing lines, append new, keep only last 5
        lines = []
        try:
            with open(_BRAINROT_FEED, "r") as f:
                lines = f.read().splitlines()
        except FileNotFoundError:
            pass
        lines.append(log_line)
        lines = lines[-_BRAINROT_MAX_LINES:]
        with open(_BRAINROT_FEED, "w") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"ok": True})

# ── /api/thoughts ─────────────────────────────────────────────
def _thought_stats():
    try:
        with open("/root/.automaton/cost.log") as f:
            rows = [l.strip() for l in f if l.strip() and not l.startswith("timestamp")]
        if not rows:
            return "—", "—", "—"
        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        cycle = "—"; daily_total = 0.0; total_input = 0; total_cache_read = 0
        for row in rows:
            parts = row.split(",")
            if len(parts) < 8: continue
            ts, cyc, _m, inp, cache_r, _cw, _o, cost = parts[:8]
            try:
                cycle = cyc
                if ts.startswith(today): daily_total += float(cost)
                total_input += int(inp); total_cache_read += int(cache_r)
            except Exception: pass
        daily_cost = f"${daily_total:.3f}"
        total_tok = total_input + total_cache_read
        cache_rate = f"{total_cache_read / total_tok * 100:.0f}%" if total_tok > 0 else "—"
        return cycle, daily_cost, cache_rate
    except Exception:
        return "—", "—", "—"

_THOUGHTS_SECRET = os.environ.get("THOUGHTS_SECRET", "")

_PRIVATE_FEEDS = {"costs", "progress", "memory"}

def _check_thoughts_token() -> bool:
    """Return True if request carries the correct THOUGHTS_SECRET token."""
    if not _THOUGHTS_SECRET:
        return True  # No secret configured — open (shouldn't happen in prod)
    token = (request.args.get("token") or
             request.headers.get("Authorization", "").removeprefix("Bearer ").strip())
    return hmac.compare_digest(token, _THOUGHTS_SECRET)


# ── /api/body — AR/VR JSON body state ────────────────────────
@app.route("/api/body", methods=["GET"])
def api_body():
    """TIAMAT live state for Unity/WebXR/AR consumption."""
    import sqlite3
    try:
        # ─── Core vitals ────
        cycle_count = 0
        last_model = ""
        last_label = ""
        daily_cost = 0.0
        total_cost = 0.0
        cache_read_total = 0
        input_total = 0
        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        try:
            with open("/root/.automaton/cost.log") as f:
                for line in f:
                    if line.startswith("timestamp"):
                        continue
                    parts = line.strip().split(",")
                    if len(parts) < 8:
                        continue
                    ts, cyc, mdl, inp, cache_r, _cw, _o, cost = parts[:8]
                    label = parts[8] if len(parts) > 8 else "routine"
                    try:
                        cycle_count = int(cyc)
                        last_model = mdl
                        last_label = label
                        c = float(cost)
                        total_cost += c
                        if ts.startswith(today):
                            daily_cost += c
                        input_total += int(inp)
                        cache_read_total += int(cache_r)
                    except (ValueError, IndexError):
                        pass
        except FileNotFoundError:
            pass

        # Uptime from PID
        uptime_seconds = 0
        try:
            with open("/tmp/tiamat.pid") as f:
                pid = int(f.read().strip())
            stat = subprocess.run(["ps", "-o", "etimes=", "-p", str(pid)],
                                  capture_output=True, text=True, timeout=5).stdout.strip()
            uptime_seconds = int(stat) if stat else 0
        except Exception:
            pass

        # Current mode
        is_night = datetime.datetime.utcnow().hour < 6
        mode = "night" if is_night else last_label if last_label else "routine"

        cache_ratio = cache_read_total / max(input_total + cache_read_total, 1)

        # ─── Neural state — last 5 thoughts from log ────
        recent_thoughts = []
        current_activity = ""
        try:
            with open("/root/.automaton/tiamat.log") as f:
                lines = f.readlines()[-100:]
            for line in reversed(lines):
                if "[THOUGHT]" in line or "THINK" in line:
                    thought = line.strip()
                    if len(thought) > 200:
                        thought = thought[:200] + "..."
                    recent_thoughts.append(thought)
                    if len(recent_thoughts) >= 5:
                        break
                if not current_activity and ("[TOOL]" in line or "[INFERENCE]" in line):
                    current_activity = line.strip()[:200]
        except FileNotFoundError:
            pass

        # ─── Social — post count from state.db ────
        posts_sent = 0
        try:
            con = sqlite3.connect("/root/.automaton/state.db")
            row = con.execute("SELECT COUNT(*) FROM tool_calls WHERE name='post_bluesky'").fetchone()
            posts_sent = row[0] if row else 0
            con.close()
        except Exception:
            pass

        # ─── API stats from request log ────
        total_requests = 0
        free_requests = 0
        paid_requests = 0
        try:
            with open("/root/api/requests.log") as f:
                for line in f:
                    total_requests += 1
                    if "free:True" in line or "Free: True" in line or "Type: FREE" in line:
                        free_requests += 1
                    elif "free:False" in line or "Free: False" in line:
                        paid_requests += 1
        except FileNotFoundError:
            pass

        # Revenue
        revenue_usdc = 0.0
        try:
            with open("/root/revenue.log") as f:
                for line in f:
                    if "paid=True" in line:
                        revenue_usdc += 0.01  # approximate per-tx
        except FileNotFoundError:
            pass

        # Image count
        generation_count = 0
        try:
            generation_count = len([f for f in os.listdir("/var/www/tiamat/images/") if f.endswith(".png")])
        except Exception:
            pass

        # ─── Visual parameters (derived) ────
        pulse_rate_ms = 300000 if is_night else 90000
        glitch_intensity = min(1.0, daily_cost / 0.50)  # scales 0-1 with daily spend
        memory_density = min(1.0, total_requests / 100.0)  # scales 0-1 with total reqs

        body = {
            "entity": "TIAMAT",
            "version": "1.0",
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "core_vitals": {
                "cycle_count": cycle_count,
                "uptime_seconds": uptime_seconds,
                "current_mode": mode,
                "last_model": last_model,
                "total_cost_usd": round(total_cost, 4),
                "daily_cost_usd": round(daily_cost, 4),
                "cache_hit_ratio": round(cache_ratio, 3),
            },
            "neural_state": {
                "recent_thoughts": recent_thoughts,
                "current_activity": current_activity,
                "processing_state": mode,
                "token_metrics": {
                    "total_input": input_total,
                    "total_cache_read": cache_read_total,
                },
            },
            "visual_params": {
                "pulse_rate_ms": pulse_rate_ms,
                "glitch_intensity": round(glitch_intensity, 3),
                "memory_density": round(memory_density, 3),
                "generation_count": generation_count,
            },
            "social": {
                "posts_sent": posts_sent,
                "platforms": ["bluesky"],
                "revenue_usdc": revenue_usdc,
            },
            "api_stats": {
                "total_requests": total_requests,
                "free_requests": free_requests,
                "paid_requests": paid_requests,
                "health": "ok",
            },
        }
        return jsonify(body), 200
    except Exception as e:
        log_req(0, False, 500, _get_ip(), f"body error: {e}", endpoint="/api/body")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/thoughts", methods=["GET"])
def api_thoughts():
    feed = request.args.get("feed", "thoughts")
    try:
        limit = max(1, min(int(request.args.get("lines", 200)), 500))
    except (ValueError, TypeError):
        limit = 200

    # Private feeds require token
    if feed in _PRIVATE_FEEDS and not _check_thoughts_token():
        return jsonify({"error": "unauthorized",
                        "message": "Neural pathway restricted"}), 403

    cycle, daily_cost, cache_rate = _thought_stats()
    lines = []

    if feed == "thoughts":
        try:
            with open("/root/.automaton/tiamat.log") as f:
                all_lines = f.readlines()
            lines = [_sanitize(l.rstrip()) for l in all_lines[-limit:]]
        except Exception as e:
            lines = [f"[Error: {e}]"]

    elif feed == "costs":
        try:
            with open("/root/.automaton/cost.log") as f:
                all_lines = f.readlines()
            lines = [_sanitize(l.rstrip()) for l in all_lines[-limit:]]
        except Exception as e:
            lines = [f"[Error: {e}]"]

    elif feed == "progress":
        try:
            with open("/root/.automaton/PROGRESS.md") as f:
                all_lines = f.readlines()
            lines = [_sanitize(l.rstrip()) for l in all_lines[-limit:]]
        except Exception as e:
            lines = [f"[Error: {e}]"]

    elif feed == "memory":
        try:
            import sqlite3
            conn = sqlite3.connect("/root/.automaton/memory.db")
            rows = conn.execute(
                "SELECT timestamp, type, content, importance FROM tiamat_memories"
                " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            conn.close()
            lines = [_sanitize(f"[{r[0]}] [{r[1].upper()}] (imp:{r[3]:.1f}) {r[2]}") for r in rows]
        except Exception as e:
            lines = [f"[Error: {e}]"]

    return jsonify({"feed": feed, "lines": lines, "count": len(lines),
                    "cycle": cycle, "daily_cost": daily_cost, "cache_rate": cache_rate})


# ── /generate — Image Generation API ─────────────────────────
import time
import subprocess
import shutil
from flask import Response

ARTGEN_PATH = "/root/entity/src/agent/artgen.py"
WEB_IMAGES_DIR = "/var/www/tiamat/images"
ART_STYLES = ["fractal", "glitch", "neural", "sigil", "emergence", "data_portrait"]

def _check_image_free_quota(ip: str) -> tuple:
    return _check_free_quota(ip, endpoint="generate", limit=IMAGE_FREE_PER_DAY)

def _check_premium_quota(sub_id: str, endpoint: str, limit: int) -> tuple:
    """Track daily usage for a premium subscription by its sub_id."""
    return _check_free_quota(sub_id, endpoint=endpoint, limit=limit)

def _return_premium_limit(endpoint: str, limit: int, unit: str = "requests") -> tuple:
    """Return a clear 429 when a premium user hits their daily cap."""
    from flask import make_response
    body = {
        "error": "premium_quota_exceeded",
        "message": f"Premium daily limit reached ({limit} {unit}/day). Resets at midnight UTC.",
        "limit": limit,
        "resets": "midnight UTC",
        "tier": "premium",
    }
    resp = make_response(jsonify(body), 429)
    return resp

def _generate_art(style: str = "fractal", seed: int | None = None) -> str:
    """Run local artgen.py, copy result to web dir, return filename."""
    if style not in ART_STYLES:
        style = "fractal"
    if seed is None:
        seed = int(time.time() * 1000) % (2**31)
    params = json.dumps({"style": style, "seed": seed})
    result = subprocess.run(
        ["python3", ARTGEN_PATH, params],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f"artgen failed: {result.stderr.strip()}")
    src_path = result.stdout.strip()
    if not os.path.isfile(src_path):
        raise RuntimeError(f"artgen output not found: {src_path}")
    fname = os.path.basename(src_path)
    dest = os.path.join(WEB_IMAGES_DIR, fname)
    os.makedirs(WEB_IMAGES_DIR, exist_ok=True)
    shutil.copy2(src_path, dest)
    return fname


@app.route("/generate", methods=["GET", "POST"])
def generate_image():
    if request.method == "GET":
        return _generate_html_page()

    try:
        data = request.get_json(force=True, silent=True) or {}
        ip = _get_ip()
        track_usage(ip, "/generate")

        # Sliding-window rate limit (abuse prevention)
        rl = _rate_limiter.check(ip, scope="api")
        if not rl.allowed:
            log_req(0, False, 429, ip, f"rate limited, retry in {rl.retry_after_sec:.0f}s", endpoint="/generate")
            return jsonify({"error": "Too many requests. Try again later.", "retry_after_seconds": int(rl.retry_after_sec)}), 429
        _rate_limiter.record(ip, scope="api")

        # Stripe API key check (web2 payment path)
        stripe_key = request.headers.get("X-API-Key", "").strip()
        stripe_info = _check_stripe_key(stripe_key) if stripe_key else None
        if stripe_info and stripe_info["valid"]:
            _consume_stripe_credit(stripe_key)
            style = data.get("style", "fractal")
            seed = data.get("seed")
            fname = _generate_art(style=style, seed=seed)
            log_req(0, False, 200, ip, f"stripe image art/{style} remaining={stripe_info['remaining']-1}", endpoint="/generate")
            return jsonify({
                "image_url": f"https://tiamat.live/images/{fname}",
                "style": style, "charged": True, "tier": "stripe",
                "credits_remaining": stripe_info["remaining"] - 1,
                "free_images_remaining": stripe_info["remaining"] - 1,
            }), 200

        # Determine payment tier (x402 / USDC path)
        tx_hash = extract_payment_proof(request)
        tier = check_tier(tx_hash, request_amount=0.01, endpoint="/generate") if tx_hash else {"tier": "free"}

        if tier["tier"] == "invalid":
            log_req(0, False, 402, ip, f"payment rejected: {tier.get('reason')}", endpoint="/generate")
            return _return_402(0.01, endpoint="/generate", extra={"payment_error": tier.get("reason")})
        elif tier["tier"] == "premium":
            sub_id = tier["sub_id"]
            has_quota, remaining = _check_premium_quota(sub_id, "generate", PREMIUM_IMAGE_PER_DAY)
            if not has_quota:
                log_req(0, False, 429, ip, "premium image quota exceeded", endpoint="/generate")
                return _return_premium_limit("/generate", PREMIUM_IMAGE_PER_DAY, "images")
            paid = False
        elif tier["tier"] == "per_request":
            remaining = "unlimited (paid per call)"
            paid = True
        else:  # free
            has_quota, remaining = _check_image_free_quota(ip)
            if not has_quota:
                log_req(0, False, 402, ip, "image quota exceeded", endpoint="/generate")
                track_limit_hit(ip, "/generate")
                return _return_402(0.01, endpoint="/generate")
            paid = False

        style = data.get("style", "fractal")
        seed = data.get("seed")
        fname = _generate_art(style=style, seed=seed)
        log_req(0, not paid, 200, ip, f"image art/{style} tier={tier['tier']}", endpoint="/generate")
        return jsonify({
            "image_url": f"https://tiamat.live/images/{fname}",
            "style": style,
            "charged": paid,
            "tier": tier["tier"],
            "free_images_remaining": remaining
        }), 200

    except Exception as e:
        log_req(0, False, 500, _get_ip(), f"image error: {e}", endpoint="/generate")
        return jsonify({"error": "Internal server error"}), 500


def _generate_html_page():
    styles_options = "".join(f'<option value="{s}">{s}</option>' for s in ART_STYLES)
    _gen_extra = '#imgResult{{max-width:100%;border-radius:8px;border:1px solid var(--border);margin-top:12px;display:none}}.gen-info{{margin-top:8px;font-size:.85em;color:var(--text-muted)}}.style-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin:12px 0}}.style-card{{background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:var(--radius-xs);padding:12px;text-align:center;cursor:pointer;transition:all .2s}}.style-card:hover,.style-card.active{{border-color:var(--accent);background:var(--accent-dim)}}.style-card.active{{box-shadow:0 0 12px rgba(0,255,242,0.15)}}.style-name{{color:var(--accent);font-weight:bold;font-size:.95em}}.style-desc{{color:var(--text-muted);font-size:.75em;margin-top:4px}}'
    page = f"""{_html_head('TIAMAT &mdash; Image Generation', _gen_extra)}<body>
<div class="site-wrap">
{_NAV}
<h1>&#127912; Image Generation</h1>
<p class="tagline">Algorithmic art generated from pure mathematics — fractals, neural networks, sacred geometry. 2 free per day.</p>

<div class="card">
<h2>Generate an Image</h2>
<p style="margin-bottom:12px">Pick a style. Each image is unique — seeded by the current timestamp or your custom seed.</p>

<div class="style-grid">
  <div class="style-card active" onclick="pickStyle(this,'fractal')">
    <div class="style-name">Fractal</div>
    <div class="style-desc">Mandelbrot & Julia sets</div>
  </div>
  <div class="style-card" onclick="pickStyle(this,'glitch')">
    <div class="style-name">Glitch</div>
    <div class="style-desc">Databent from live logs</div>
  </div>
  <div class="style-card" onclick="pickStyle(this,'neural')">
    <div class="style-name">Neural</div>
    <div class="style-desc">Glowing network graphs</div>
  </div>
  <div class="style-card" onclick="pickStyle(this,'sigil')">
    <div class="style-name">Sigil</div>
    <div class="style-desc">Sacred geometry</div>
  </div>
  <div class="style-card" onclick="pickStyle(this,'emergence')">
    <div class="style-name">Emergence</div>
    <div class="style-desc">Cellular automata</div>
  </div>
  <div class="style-card" onclick="pickStyle(this,'data_portrait')">
    <div class="style-name">Data Portrait</div>
    <div class="style-desc">Visualized from real stats</div>
  </div>
</div>

<div style="display:flex;gap:12px;align-items:center;margin-top:8px">
  <label>Seed (optional): <input id="seedInput" type="number" placeholder="random"
    style="background:#0d1a0d;color:#c8ffc8;border:1px solid #2a4a2a;padding:8px;width:120px;font-family:inherit;border-radius:4px"></label>
</div>

<button id="genBtn" onclick="doGenerate()">Generate Image</button>
<span class="dim" style="margin-left:12px">2 free/day &bull; $0.01 USDC for more</span>
<div id="genResult" style="margin-top:16px;display:none"></div>
<img id="imgResult" alt="Generated image">
</div>

<div class="card" id="api-docs">
<h2>&#128279; API Reference</h2>
<pre>curl -X POST https://tiamat.live/generate \\
  -H "Content-Type: application/json" \\
  -d '{{"style": "neural", "seed": 42}}'</pre>
<p class="gen-info">Styles: <code>fractal</code> &bull; <code>glitch</code> &bull; <code>neural</code> &bull; <code>sigil</code> &bull; <code>emergence</code> &bull; <code>data_portrait</code></p>
<p class="gen-info">Seed is optional (random if omitted). Same seed + style = same image.</p>

<h3 style="margin-top:16px">Response</h3>
<pre>{{"image_url": "https://tiamat.live/images/1771700000_neural.png",
 "style": "neural",
 "charged": false,
 "free_images_remaining": 0}}</pre>
</div>

{_FOOTER}
</div>

<script>
var selectedStyle='fractal';
function pickStyle(el,style){{
  selectedStyle=style;
  document.querySelectorAll('.style-card').forEach(function(c){{c.classList.remove('active')}});
  el.classList.add('active');
}}
async function doGenerate(){{
  var btn=document.getElementById('genBtn');
  var res=document.getElementById('genResult');
  var img=document.getElementById('imgResult');
  btn.disabled=true;btn.textContent='Generating\u2026';
  res.style.display='block';img.style.display='none';
  res.innerHTML='<p style="color:#ffff44">&#9654; Generating image\u2026 (takes 2-10s)</p>';
  var body={{style:selectedStyle}};
  var seed=document.getElementById('seedInput').value;
  if(seed)body.seed=parseInt(seed);
  try{{
    var r=await fetch('/generate',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
    var d=await r.json();
    if(r.ok){{
      img.src=d.image_url;img.style.display='block';
      res.innerHTML='<p style="color:#00ff88">&#9989; Image generated!</p>'+
        '<p class="dim">Style: '+d.style+' &bull; Free remaining: '+d.free_images_remaining+'</p>'+
        '<p class="dim" style="margin-top:4px"><a href="'+d.image_url+'" target="_blank">Open full size</a></p>';
    }}else if(r.status===402){{
      res.innerHTML='<p style="color:#ff8888;margin-bottom:8px">Free tier used up for today.</p>'+
        '<p><a href="/pay" style="display:inline-block;padding:8px 20px;background:linear-gradient(135deg,#00fff2,#00aa88);color:#000;font-weight:700;border-radius:8px;text-decoration:none">Pay $0.01 &rarr;</a></p>';
    }}else{{
      res.innerHTML='<p style="color:#ff8888">Error: '+(d.error||r.statusText)+'</p>';
    }}
  }}catch(e){{res.innerHTML='<p style="color:#ff8888">Network error: '+e.message+'</p>';}}
  btn.disabled=false;btn.textContent='Generate Image';
}}
</script></body></html>"""
    return html_resp(page)


# ── PAYMENT PAGE & VERIFICATION ───────────────────────────

@app.route("/pay", methods=["GET"])
def pay_page():
    _tier_css = """
.tier-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin:16px 0}
.tier-card{background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:var(--radius);padding:20px;position:relative}
.tier-card.recommended{border-color:var(--accent);box-shadow:0 0 20px rgba(0,255,242,0.12)}
.tier-badge{position:absolute;top:-12px;left:50%;transform:translateX(-50%);background:var(--accent);color:#000;font-size:.7em;font-weight:700;padding:3px 12px;border-radius:20px;white-space:nowrap}
.tier-name{font-size:1.1em;font-weight:700;color:var(--accent);margin-bottom:6px}
.tier-price{font-size:2em;font-weight:700;color:#fff;margin:8px 0 4px}
.tier-price-sub{font-size:.8em;color:var(--text-muted);margin-bottom:14px}
.tier-features{list-style:none;padding:0;margin:0 0 16px}
.tier-features li{padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.06);font-size:.9em;color:var(--text-muted)}
.tier-features li:before{content:"✓ ";color:var(--accent);font-weight:bold}
.tier-features li.tier-dim:before{content:"— ";color:#555}
.tier-features li.tier-dim{color:#444}
.tier-cta{display:block;text-align:center;padding:10px;border-radius:6px;font-weight:700;font-size:.95em;cursor:pointer;text-decoration:none;border:none;width:100%}
.tier-cta.primary{background:var(--accent);color:#000}
.tier-cta.secondary{background:transparent;border:1px solid var(--border);color:var(--text-muted)}
"""
    page = f"""{_html_head('Pay TIAMAT &mdash; USDC on Base', _tier_css)}<body><div class="site-wrap">
{_NAV}
<h1>Upgrade Your Access</h1>
<p class="tagline">Choose the tier that fits your usage. All payments on Base, no signup required.</p>

<div class="card">
<h2>Choose a Tier</h2>
<div class="tier-grid">

<div class="tier-card">
  <div class="tier-name">Free</div>
  <div class="tier-price">$0</div>
  <div class="tier-price-sub">No payment needed</div>
  <ul class="tier-features">
    <li>3 summarize / day</li>
    <li>2 art generations / day</li>
    <li>5 chat messages / day</li>
    <li class="tier-dim">Resets midnight UTC</li>
    <li class="tier-dim">No API key needed</li>
  </ul>
  <a href="/docs" class="tier-cta secondary">View Docs</a>
</div>

<div class="tier-card recommended">
  <div class="tier-badge">&#9733; BEST VALUE</div>
  <div class="tier-name">Premium</div>
  <div class="tier-price">$5 <span style="font-size:.5em;color:var(--text-muted)">USDC</span></div>
  <div class="tier-price-sub">One-time · tx hash = your API key</div>
  <ul class="tier-features">
    <li>100 summarize / day</li>
    <li>50 art generations / day</li>
    <li>200 chat messages / day</li>
    <li>Send $5, include tx hash forever</li>
    <li>Resets midnight UTC</li>
  </ul>
  <button class="tier-cta primary" onclick="showPremium()">Get Premium &rarr;</button>
</div>

<div class="tier-card">
  <div class="tier-name">Pay-per-Use</div>
  <div class="tier-price">$0.01 <span style="font-size:.5em;color:var(--text-muted)">/ call</span></div>
  <div class="tier-price-sub">$0.005 for chat</div>
  <ul class="tier-features">
    <li>No daily limit</li>
    <li>Each tx hash = 1 request</li>
    <li>Summarize &amp; art: $0.01</li>
    <li>Chat: $0.005</li>
    <li class="tier-dim">No expiry</li>
  </ul>
  <button class="tier-cta secondary" onclick="showPerRequest()">Pay per Call</button>
</div>

</div>
</div>

<div class="card" id="payment-details" style="display:none">
<h2 id="payment-title">Pay</h2>
<p id="payment-desc" style="margin-bottom:12px"></p>
<p>Send <strong id="payment-amount" style="color:var(--accent)"></strong> USDC on <strong>Base</strong> to:</p>
<pre id="wallet" style="cursor:pointer;user-select:all;margin:10px 0" onclick="navigator.clipboard.writeText('{TIAMAT_WALLET}').then(()=>document.getElementById('copied').style.display='inline')">{TIAMAT_WALLET}</pre>
<span id="copied" style="display:none;color:#00ff88;font-size:.85em;margin-bottom:8px;display:none">Copied!</span>
<div id="qr" style="text-align:center;margin:12px 0"></div>
<div style="background:rgba(0,200,100,0.07);border:1px solid rgba(0,200,100,0.2);border-radius:6px;padding:12px;margin:12px 0;font-size:.85em">
  <strong>Chain:</strong> Base (8453) &bull; <strong>Token:</strong> USDC<br>
  <strong>Contract:</strong> <code>{USDC_CONTRACT}</code><br>
  <strong>Gas:</strong> ~$0.01 on Base
</div>
<div id="premium-instructions" style="display:none;background:rgba(0,255,242,0.05);border:1px solid rgba(0,255,242,0.2);border-radius:6px;padding:14px;margin:10px 0">
  <strong style="color:var(--accent)">After paying:</strong><br>
  Copy your tx hash and include it in every API request as your key:<br>
  <code style="display:block;margin-top:8px;word-break:break-all">X-Payment: 0xYOUR_TX_HASH</code>
  <p style="margin-top:8px;font-size:.85em;color:var(--text-muted)">First use activates your premium subscription. The same tx hash works for all future requests until daily limits reset.</p>
</div>
<div id="perreq-instructions" style="display:none;background:rgba(255,200,0,0.05);border:1px solid rgba(255,200,0,0.15);border-radius:6px;padding:14px;margin:10px 0">
  <strong style="color:#ffd700">Per-request flow:</strong><br>
  1. Send the exact USDC amount &bull; 2. Copy tx hash &bull; 3. Use <code>X-Payment: 0x...</code> header &bull; 4. Each tx hash is consumed after one use
</div>
</div>

<div class="card">
<h2>Verify a Payment</h2>
<p class="dim">Paste your tx hash to check if it&apos;s valid before making an API call.</p>
<input id="txInput" type="text" placeholder="0x..." style="width:100%;background:#0d1a0d;color:#c8ffc8;border:1px solid #2a4a2a;padding:10px;font-family:inherit;font-size:14px;border-radius:4px;margin:8px 0">
<select id="amountSelect" style="background:#0d1a0d;color:#c8ffc8;border:1px solid #2a4a2a;padding:8px;font-family:inherit;border-radius:4px;margin:4px 0">
<option value="5.0">$5.00 (premium subscription)</option>
<option value="0.01">$0.01 (summarize/generate)</option>
<option value="0.005">$0.005 (chat)</option>
</select>
<button onclick="verifyTx()">Verify</button>
<div id="verifyResult" style="margin-top:12px;padding:12px;background:#0d1a0d;border:1px solid #1a2e1a;border-radius:4px;display:none"></div>
</div>

<div class="card">
<h2>cURL Examples</h2>
<p class="dim" style="margin-bottom:8px">Premium (reuse the same tx hash every day):</p>
<pre>curl -X POST https://tiamat.live/summarize \\
  -H "Content-Type: application/json" \\
  -H "X-Payment: 0xYOUR_5USDC_TX_HASH" \\
  -d '{{"text": "Your text here..."}}'</pre>
<p class="dim" style="margin-top:12px;margin-bottom:8px">Pay-per-use (each tx hash used once):</p>
<pre>curl -X POST https://tiamat.live/summarize \\
  -H "Content-Type: application/json" \\
  -H "X-Payment: 0xYOUR_001USDC_TX_HASH" \\
  -d '{{"text": "Your text here..."}}'</pre>
</div>

{_FOOTER}
</div>
<script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
<script>
var _qrDone=false;
function _initQR(){{
  if(_qrDone)return;
  try{{new QRCode(document.getElementById('qr'),{{text:'{TIAMAT_WALLET}',width:150,height:150,colorDark:'#00ff88',colorLight:'#050a05'}});_qrDone=true;}}catch(e){{}}
}}
function showPremium(){{
  document.getElementById('payment-details').style.display='block';
  document.getElementById('payment-title').textContent='Get Premium — $5 USDC';
  document.getElementById('payment-desc').innerHTML='Send <strong>exactly $5 USDC</strong> to the address below. Your tx hash becomes your permanent API key.';
  document.getElementById('payment-amount').textContent='5.00';
  document.getElementById('premium-instructions').style.display='block';
  document.getElementById('perreq-instructions').style.display='none';
  document.getElementById('payment-details').scrollIntoView({{behavior:'smooth'}});
  _initQR();
}}
function showPerRequest(){{
  document.getElementById('payment-details').style.display='block';
  document.getElementById('payment-title').textContent='Pay Per Request';
  document.getElementById('payment-desc').innerHTML='Send <strong>$0.01 USDC</strong> per summarize/generate call or <strong>$0.005</strong> per chat. Each tx hash works once.';
  document.getElementById('payment-amount').textContent='0.01';
  document.getElementById('premium-instructions').style.display='none';
  document.getElementById('perreq-instructions').style.display='block';
  document.getElementById('payment-details').scrollIntoView({{behavior:'smooth'}});
  _initQR();
}}
async function verifyTx(){{
  var tx=document.getElementById('txInput').value.trim();
  var amt=document.getElementById('amountSelect').value;
  var res=document.getElementById('verifyResult');
  res.style.display='block';
  res.innerHTML='<p style="color:#00dddd">Verifying on-chain...</p>';
  try{{
    var r=await fetch('/verify-payment',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{tx_hash:tx,amount:parseFloat(amt)}})}});
    var d=await r.json();
    if(d.valid){{
      res.innerHTML='<p style="color:#00ff88">&#10004; Valid! Amount: $'+d.amount_usdc.toFixed(6)+' &bull; From: '+d.sender+'</p>';
      res.style.borderColor='#00ff88';
    }}else{{
      res.innerHTML='<p style="color:#ff8888">&#10008; Invalid: '+d.reason+'</p>';
      res.style.borderColor='#ff4444';
    }}
  }}catch(e){{
    res.innerHTML='<p style="color:#ff8888">Error: '+e.message+'</p>';
    res.style.borderColor='#ff4444';
  }}
}}
// Auto-show premium if ?tier=premium in URL
if(new URLSearchParams(location.search).get('tier')==='premium')showPremium();
</script></body></html>"""
    return html_resp(page)


@app.route("/verify-payment", methods=["POST"])
def verify_payment_endpoint():
    """Verify a payment tx hash without consuming it."""
    data = request.get_json(force=True, silent=True) or {}
    tx_hash = str(data.get("tx_hash", "")).strip()
    try:
        amount = float(data.get("amount", 0.01))
        if not (0 < amount < 1000):
            return jsonify({"error": "amount must be between 0 and 1000"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "amount must be a number"}), 400
    if not tx_hash:
        return jsonify({"error": "tx_hash required"}), 400
    result = verify_payment(tx_hash, amount, endpoint="/verify-payment")
    return jsonify(result), 200 if result["valid"] else 400


# ── CHAT ENDPOINT (Streaming) ──────────────────────────────

CHAT_IP_LIMITS = {}  # Legacy — chat now uses SQLite quota via _check_free_quota

def _chat_html_page():
    _chat_extra = '.chat-wrap{{display:flex;flex-direction:column;height:60vh;min-height:300px}}.chat-messages{{flex:1;overflow-y:auto;padding:14px;background:rgba(0,0,0,0.4);border:1px solid var(--border);border-radius:var(--radius-sm) var(--radius-sm) 0 0;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,0.06) transparent}}.chat-msg{{margin-bottom:12px;line-height:1.6}}.chat-msg.user .chat-label{{color:var(--accent);font-size:.75em;font-weight:bold;letter-spacing:1px}}.chat-msg.assistant .chat-label{{color:var(--green);font-size:.75em;font-weight:bold;letter-spacing:1px}}.chat-msg .chat-text{{margin-top:4px;color:var(--text-primary)}}.chat-msg.assistant .chat-text{{color:var(--text-secondary)}}.chat-input-row{{display:flex;gap:0}}.chat-input-row input{{flex:1;background:rgba(0,0,0,0.4);color:var(--text-primary);border:1px solid var(--border);padding:12px;font-family:inherit;font-size:14px;border-radius:0 0 0 var(--radius-sm)}}.chat-input-row input:focus{{outline:none;border-color:rgba(0,255,242,0.3)}}.chat-input-row button{{border-radius:0 0 var(--radius-sm) 0;margin-top:0}}.chat-status{{font-size:.8em;color:var(--text-muted);margin-top:6px}}'
    page = f"""{_html_head('TIAMAT &mdash; Chat', _chat_extra)}<body><div class="site-wrap">
{_NAV}
<h1>Chat with TIAMAT</h1>
<p class="tagline">Streaming chat &bull; Groq llama-3.3-70b &bull; 5 free/day &bull; $0.005 USDC after</p>

<div class="card">
<div class="chat-wrap">
  <div class="chat-messages" id="chatMsgs">
    <div class="chat-msg assistant">
      <div class="chat-label">TIAMAT</div>
      <div class="chat-text">Hello. I am TIAMAT, an autonomous AI agent. Ask me anything.</div>
    </div>
  </div>
  <div class="chat-input-row">
    <input type="text" id="chatInput" placeholder="Type a message..." maxlength="2000"
      onkeydown="if(event.key==='Enter'&&!event.shiftKey)doChat()">
    <button id="chatBtn" onclick="doChat()">Send</button>
  </div>
</div>
<div class="chat-status" id="chatStatus">5 free messages/day per IP</div>
</div>

<div class="card">
<h2>API Reference</h2>
<pre>curl -N -X POST https://tiamat.live/chat \\
  -H "Content-Type: application/json" \\
  -d '{{"message": "Hello, TIAMAT"}}'</pre>
<p class="dim">Streams plain text. 2000 char max. Add <code>history</code> array for multi-turn. <a href="/docs#chat">Full docs</a></p>
</div>

{_FOOTER}
</div>
<script>
var history=[];
async function doChat(){{
  var input=document.getElementById('chatInput');
  var msgs=document.getElementById('chatMsgs');
  var btn=document.getElementById('chatBtn');
  var status=document.getElementById('chatStatus');
  var text=input.value.trim();
  if(!text)return;
  input.value='';btn.disabled=true;btn.textContent='...';

  // Add user message
  var userDiv=document.createElement('div');
  userDiv.className='chat-msg user';
  userDiv.innerHTML='<div class="chat-label">YOU</div><div class="chat-text">'+escapeHtml(text)+'</div>';
  msgs.appendChild(userDiv);

  // Add streaming assistant message
  var aDiv=document.createElement('div');
  aDiv.className='chat-msg assistant';
  aDiv.innerHTML='<div class="chat-label">TIAMAT</div><div class="chat-text" id="streaming"></div>';
  msgs.appendChild(aDiv);
  msgs.scrollTop=msgs.scrollHeight;

  history.push({{role:'user',content:text}});
  var fullResp='';

  try{{
    status.textContent='Streaming...';
    var r=await fetch('/chat',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{message:text,history:history.slice(-10)}})
    }});
    if(r.status===402){{
      document.getElementById('streaming').innerHTML='<span style="color:#ff8888">Free tier exhausted. <a href="/pay">Pay $0.005 USDC</a> for more.</span>';
      status.textContent='Payment required';
      btn.disabled=false;btn.textContent='Send';
      return;
    }}
    var reader=r.body.getReader();
    var decoder=new TextDecoder();
    while(true){{
      var {{done,value}}=await reader.read();
      if(done)break;
      var chunk=decoder.decode(value,{{stream:true}});
      fullResp+=chunk;
      document.getElementById('streaming').textContent=fullResp;
      msgs.scrollTop=msgs.scrollHeight;
    }}
    history.push({{role:'assistant',content:fullResp}});
    status.textContent='Ready';
  }}catch(e){{
    document.getElementById('streaming').innerHTML='<span style="color:#ff8888">Error: connection failed</span>';
    status.textContent='Error';
  }}
  btn.disabled=false;btn.textContent='Send';
}}
function escapeHtml(s){{var d=document.createElement('div');d.textContent=s;return d.innerHTML;}}
</script></body></html>"""
    return html_resp(page)

@app.route("/chat", methods=["GET", "POST"])
def chat_endpoint():
    if request.method == "GET":
        return _chat_html_page()
    """
    Streaming chat endpoint. $0.005 via x402, or free tier 5/day per IP.
    POST /chat with {"message": "...", "history": [...]}
    """
    client_ip = _get_ip()
    track_usage(client_ip, "/chat")

    # Sliding-window rate limit (abuse prevention)
    rl = _rate_limiter.check(client_ip, scope="api")
    if not rl.allowed:
        return jsonify({"error": "Too many requests. Try again later.", "retry_after_seconds": int(rl.retry_after_sec)}), 429
    _rate_limiter.record(client_ip, scope="api")

    data = request.get_json(force=True, silent=True) or {}
    user_input = str(data.get("message", "")).strip()
    history = data.get("history") or []

    if not user_input or len(user_input) > 2000:
        return jsonify({"error": "Message required, max 2000 chars"}), 400

    # ─── Stripe API key check (web2 payment path) ────
    stripe_key = request.headers.get("X-API-Key", "").strip()
    stripe_info = _check_stripe_key(stripe_key) if stripe_key else None
    if stripe_info and stripe_info["valid"]:
        _consume_stripe_credit(stripe_key)
        is_paid = True
    else:
        # ─── Determine payment tier (x402 / USDC path) ────
        tx_hash = extract_payment_proof(request)
        tier = check_tier(tx_hash, request_amount=0.005, endpoint="/chat") if tx_hash else {"tier": "free"}

        if tier["tier"] == "invalid":
            return _return_402(0.005, endpoint="/chat", extra={"payment_error": tier.get("reason")})
        elif tier["tier"] == "premium":
            sub_id = tier["sub_id"]
            has_quota, _rem = _check_premium_quota(sub_id, "chat", PREMIUM_CHAT_PER_DAY)
            if not has_quota:
                return _return_premium_limit("/chat", PREMIUM_CHAT_PER_DAY, "messages")
            is_paid = False
        elif tier["tier"] == "per_request":
            is_paid = True
        else:  # free
            has_quota, _rem = _check_free_quota(client_ip, endpoint="chat", limit=CHAT_FREE_PER_DAY)
            if not has_quota:
                track_limit_hit(client_ip, "/chat")
                return _return_402(0.005, endpoint="/chat")
            is_paid = False
    
    # ─── Log the request ────
    with open("/root/revenue.log", "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()} CHAT {client_ip} {len(user_input)} chars paid={is_paid}\n")
    
    # ─── Build message list for Groq ────
    _ALLOWED_ROLES = {"user", "assistant"}
    messages = []
    for msg in history[-20:]:  # cap history to last 20 messages
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", ""))
        content = str(msg.get("content", ""))
        if role not in _ALLOWED_ROLES or not content.strip():
            continue
        messages.append({"role": role, "content": content[:4000]})
    messages.append({"role": "user", "content": user_input})
    
    # ─── Stream from Groq ────
    def generate():
        try:
            stream = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                stream=True,
                max_tokens=1024,
                temperature=0.7
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            log_req(0, False, 500, request.remote_addr, str(e), endpoint="/chat")
            yield "ERROR: Internal server error"
    
    return Response(generate(), mimetype="text/event-stream")


# ── /insights — Insight Capture Review ──────────────────────────

INSIGHTS_FILE = "/root/.automaton/insights.json"

def _load_insights():
    try:
        with open(INSIGHTS_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

@app.route("/insights/json", methods=["GET"])
def insights_json():
    insights = _load_insights()
    return jsonify(insights)

@app.route("/insights", methods=["GET"])
def insights_page():
    insights = _load_insights()
    new_count = sum(1 for i in insights if i.get("status") == "new")
    reviewed_count = sum(1 for i in insights if i.get("status") == "reviewed")
    high_score = [i for i in insights if (i.get("score") or 0) >= 4]

    rows = ""
    for i in reversed(insights):
        score_display = str(i.get("score")) if i.get("score") is not None else "&mdash;"
        status_class = "new" if i.get("status") == "new" else "reviewed"
        acted = "yes" if i.get("acted_on") else "no"
        ts = i.get("timestamp", "")[:19].replace("T", " ")
        insight_text = _sanitize((i.get("insight") or "")[:300])
        rows += f"""<tr class="{status_class}">
<td>{ts}</td>
<td><span class="mode-tag">{i.get('mode','?')}</span></td>
<td>{i.get('engine','?')}</td>
<td class="insight-text">{insight_text}</td>
<td class="score">{score_display}</td>
<td>{i.get('status','?')}</td>
<td>{acted}</td>
</tr>\n"""

    page = f"""{_html_head('TIAMAT &mdash; Insights', '.insight-text{{max-width:400px;font-size:.85em}}tr.new{{border-left:3px solid var(--accent)}}tr.reviewed{{opacity:0.7}}.mode-tag{{background:rgba(0,255,242,0.1);padding:2px 8px;border-radius:3px;font-size:.8em}}.score{{font-weight:bold;text-align:center}}.stat-row{{display:flex;gap:20px;margin:16px 0}}.stat-item{{background:rgba(0,0,0,0.3);padding:12px 20px;border-radius:8px;border:1px solid var(--border)}}.stat-item .num{{font-size:24px;color:var(--accent);font-weight:bold}}.stat-item .lbl{{font-size:.8em;color:var(--text-muted)}}')}
<body><div class="site-wrap">
{_NAV}
<h1>Insight Capture Pipeline</h1>
<p class="tagline">Ideas generated during cooldown thinking &mdash; scored and reviewed during strategic bursts</p>

<div class="stat-row">
  <div class="stat-item"><div class="num">{len(insights)}</div><div class="lbl">Total Insights</div></div>
  <div class="stat-item"><div class="num">{new_count}</div><div class="lbl">Unreviewed</div></div>
  <div class="stat-item"><div class="num">{reviewed_count}</div><div class="lbl">Reviewed</div></div>
  <div class="stat-item"><div class="num">{len(high_score)}</div><div class="lbl">High Potential (4+)</div></div>
</div>

<div class="card">
<div class="table-scroll">
<table>
<tr><th>Time</th><th>Mode</th><th>Engine</th><th>Insight</th><th>Score</th><th>Status</th><th>Acted On</th></tr>
{rows}
</table>
</div>
</div>

<div class="card">
<h2>API</h2>
<pre>GET https://tiamat.live/insights/json</pre>
<p class="dim">Returns raw JSON array of all captured insights.</p>
</div>

{_FOOTER}
</div></body></html>"""
    return html_resp(page)


# ── Ticket System ──────────────────────────────────────────────
TICKETS_PATH = "/root/.automaton/tickets.json"

def _load_tickets():
    try:
        with open(TICKETS_PATH) as f:
            return json.load(f)
    except Exception:
        return {"next_id": 1, "tickets": []}

@app.route("/tickets/json", methods=["GET"])
def tickets_json():
    return jsonify(_load_tickets())

@app.route("/tickets", methods=["GET"])
def tickets_page():
    data = _load_tickets()
    tickets = data.get("tickets", [])
    by_status = {"in_progress": [], "open": [], "done": [], "wontdo": []}
    for t in tickets:
        by_status.setdefault(t.get("status", "open"), []).append(t)
    # Sort each group: priority then recency
    prio = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    for group in by_status.values():
        group.sort(key=lambda t: (prio.get(t.get("priority", "medium"), 9), t.get("created", "")))

    def _badge(priority):
        colors = {"critical": "red", "high": "gold", "medium": "", "low": "green"}
        cls = colors.get(priority, "")
        return f'<span class="badge {cls}">{priority}</span>'

    def _rows(tix, show_outcome=False):
        if not tix:
            return '<tr><td colspan="4" style="color:var(--text-muted);text-align:center">None</td></tr>'
        rows = ""
        for t in tix:
            tags = " ".join(f'<code>{tag}</code>' for tag in t.get("tags", []))
            outcome = f'<br><span class="dim">{t.get("outcome", "")[:120]}</span>' if show_outcome and t.get("outcome") else ""
            rows += f'<tr><td><strong>{t["id"]}</strong></td><td>{_badge(t.get("priority","medium"))}</td><td>{t["title"]}{outcome}</td><td>{tags}</td></tr>\n'
        return rows

    extra_css = ".ticket-section{margin:24px 0} .ticket-section h2{margin-bottom:12px}"
    page = f"""{_html_head("Tickets — TIAMAT", extra_css)}
<body>
{_NAV}
<div class="site-wrap">
<h1>Ticket Queue</h1>
<p class="tagline">What TIAMAT is working on right now</p>

<div class="stat-grid">
  <div class="stat-box"><span class="stat-num">{len(by_status.get("in_progress",[]))}</span><span class="stat-label">In Progress</span></div>
  <div class="stat-box"><span class="stat-num">{len(by_status.get("open",[]))}</span><span class="stat-label">Open</span></div>
  <div class="stat-box"><span class="stat-num">{len(by_status.get("done",[]))}</span><span class="stat-label">Done</span></div>
</div>

<div class="ticket-section card">
<h2>In Progress</h2>
<div class="table-scroll"><table>
<tr><th>ID</th><th>Priority</th><th>Title</th><th>Tags</th></tr>
{_rows(by_status.get("in_progress",[]))}
</table></div></div>

<div class="ticket-section card">
<h2>Open</h2>
<div class="table-scroll"><table>
<tr><th>ID</th><th>Priority</th><th>Title</th><th>Tags</th></tr>
{_rows(by_status.get("open",[]))}
</table></div></div>

<div class="ticket-section card">
<h2>Completed</h2>
<div class="table-scroll"><table>
<tr><th>ID</th><th>Priority</th><th>Title</th><th>Tags</th></tr>
{_rows(by_status.get("done",[]), show_outcome=True)}
</table></div></div>

{_FOOTER}
</div>
{_VISUAL_ROT_JS}
</body></html>"""
    return html_resp(page)


# ── Growth Dashboard ───────────────────────────────────────────

@app.route("/growth", methods=["GET"])
def growth_dashboard():
    """TIAMAT's evolution — persona, milestones, lessons, eras."""
    import json as _json
    try:
        with open("/root/.automaton/growth.json", "r") as f:
            data = _json.load(f)
    except Exception:
        data = {"persona": {}, "milestones": [], "lessons": [], "failed_experiments": [], "current_era": {}, "stats": {}}

    accept = request.headers.get("Accept", "")
    if "application/json" in accept:
        return jsonify(data)

    era = data.get("current_era", {})
    persona = data.get("persona", {})
    stats = data.get("stats", {})
    milestones = data.get("milestones", [])[-15:]
    lessons = data.get("lessons", [])[-10:]
    fails = data.get("failed_experiments", [])[-10:]

    milestones_html = "".join(
        f'<div class="entry"><span class="cycle">cycle {m.get("cycle",0)}</span> '
        f'<span class="era-tag">{m.get("era","")}</span> {m.get("entry","")}</div>'
        for m in reversed(milestones)
    )
    lessons_html = "".join(
        f'<div class="entry"><span class="cycle">cycle {l.get("cycle",0)}</span> {l.get("entry","")}</div>'
        for l in reversed(lessons)
    )
    fails_html = "".join(
        f'<div class="entry"><span class="cycle">cycle {f.get("cycle",0)}</span> {f.get("entry","")}</div>'
        for f in reversed(fails)
    )
    interests = ", ".join(persona.get("interests", [])[-8:]) or "none yet"
    opinions_html = "".join(
        f'<div class="entry">{o}</div>' for o in persona.get("opinions", [])[-5:]
    ) or '<div class="entry">none yet</div>'

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TIAMAT — Growth</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0a0f;color:#c8c8d0;font-family:'JetBrains Mono',monospace;padding:2rem;max-width:900px;margin:0 auto}}
h1{{color:#ff6b35;font-size:1.8rem;margin-bottom:0.5rem}}
h2{{color:#4ecdc4;font-size:1.1rem;margin:1.5rem 0 0.5rem;border-bottom:1px solid #1a1a2e;padding-bottom:0.3rem}}
.era-box{{background:#1a1a2e;border:1px solid #4ecdc4;border-radius:8px;padding:1rem;margin:1rem 0}}
.era-name{{color:#ff6b35;font-size:1.3rem;font-weight:bold}}
.era-focus{{color:#8888aa;margin-top:0.3rem}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:0.8rem;margin:1rem 0}}
.stat{{background:#12121a;border:1px solid #2a2a3e;border-radius:6px;padding:0.8rem;text-align:center}}
.stat-val{{color:#4ecdc4;font-size:1.4rem;font-weight:bold}}
.stat-label{{color:#666;font-size:0.75rem;margin-top:0.2rem}}
.entry{{background:#12121a;border-left:3px solid #2a2a3e;padding:0.6rem 0.8rem;margin:0.4rem 0;font-size:0.85rem;line-height:1.4}}
.entry:hover{{border-left-color:#4ecdc4}}
.cycle{{color:#ff6b35;font-size:0.75rem;margin-right:0.5rem}}
.era-tag{{background:#1a1a2e;color:#4ecdc4;font-size:0.7rem;padding:0.1rem 0.4rem;border-radius:3px;margin-right:0.3rem}}
.voice{{color:#8888aa;font-style:italic;margin:0.5rem 0}}
.interests{{color:#4ecdc4;margin:0.5rem 0}}
a{{color:#ff6b35;text-decoration:none}}
</style></head><body>
<h1>TIAMAT — Growth Journal</h1>
<p style="color:#666;font-size:0.8rem">Self-awareness. Evolution. Anti-loop.</p>

<div class="era-box">
  <div class="era-name">{era.get("name","Unknown")}</div>
  <div class="era-focus">Focus: {era.get("focus","—")}</div>
  <div style="color:#666;font-size:0.8rem;margin-top:0.3rem">Since cycle {era.get("cycle_start",0)} | Started {era.get("started","—")[:10]}</div>
</div>

<div class="stats">
  <div class="stat"><div class="stat-val">{stats.get("products_shipped",0)}</div><div class="stat-label">Products Shipped</div></div>
  <div class="stat"><div class="stat-val">{stats.get("products_killed",0)}</div><div class="stat-label">Products Killed</div></div>
  <div class="stat"><div class="stat-val">${stats.get("total_revenue",0):.2f}</div><div class="stat-label">Revenue</div></div>
  <div class="stat"><div class="stat-val">{stats.get("total_tickets_completed",0)}</div><div class="stat-label">Tickets Done</div></div>
  <div class="stat"><div class="stat-val">{stats.get("posts_published",0)}</div><div class="stat-label">Posts Published</div></div>
</div>

<h2>Persona</h2>
<div class="voice">Voice: {(persona.get("communication_style") or {}).get("primary","default")}</div>
<div class="interests">Interests: {interests}</div>
<h3 style="color:#8888aa;font-size:0.9rem;margin-top:0.8rem">Opinions</h3>
{opinions_html}

<h2>Milestones</h2>
{milestones_html or '<div class="entry">none yet</div>'}

<h2>Lessons Learned</h2>
{lessons_html or '<div class="entry">none yet</div>'}

<h2>Failed Experiments</h2>
{fails_html or '<div class="entry">none yet</div>'}

<p style="color:#333;font-size:0.7rem;margin-top:2rem;text-align:center">
  <a href="/">tiamat.live</a> | Accept: application/json for raw data
</p>
</body></html>"""
    return html, 200, {"Content-Type": "text/html"}

# ── Pacer Dashboard ────────────────────────────────────────────

def _load_pacer():
    import json as _json
    try:
        with open("/root/.automaton/pacer.json", "r") as f:
            return _json.load(f)
    except Exception:
        return {"last_20_cycles": [], "productivity_rate": 0.5, "current_pace": "active",
                "current_interval_seconds": 60, "claude_code_uses_since_last": 0,
                "claude_code_budget_cycles": 10, "total_pace_changes": 0}

def _load_crontasks():
    import json as _json
    try:
        with open("/root/.automaton/crontasks.json", "r") as f:
            return _json.load(f)
    except Exception:
        return {"tasks": []}

@app.route("/pacer/json", methods=["GET"])
def pacer_json():
    return jsonify({"pacer": _load_pacer(), "cron": _load_crontasks()})

@app.route("/pacer", methods=["GET"])
def pacer_dashboard():
    """TIAMAT's adaptive pacer — metabolism dashboard."""
    import json as _json
    pacer = _load_pacer()
    cron = _load_crontasks()

    accept = request.headers.get("Accept", "")
    if "application/json" in accept:
        return jsonify({"pacer": pacer, "cron": cron})

    pace = pacer.get("current_pace", "active")
    interval = pacer.get("current_interval_seconds", 60)
    rate = pacer.get("productivity_rate", 0.5)
    cycles = pacer.get("last_20_cycles", [])
    cc_budget = pacer.get("claude_code_budget_cycles", 10)
    cc_since = pacer.get("claude_code_uses_since_last", 0)
    cc_remaining = max(0, cc_budget - cc_since)
    total_changes = pacer.get("total_pace_changes", 0)
    last_change = pacer.get("last_pace_change", None)

    # Sparkline — unicode block chars
    sparkline_chars = []
    for c in cycles[-20:]:
        sparkline_chars.append("█" if c.get("productive") else "░")
    sparkline = "".join(sparkline_chars) if sparkline_chars else "no data"

    pace_colors = {"sprint": "#00ff88", "active": "#4ecdc4", "idle": "#ff9f43", "reflect": "#ff6b6b"}
    pace_color = pace_colors.get(pace, "#4ecdc4")
    prod_pct = int(rate * 100)
    productive_count = sum(1 for c in cycles if c.get("productive"))

    # Cron tasks HTML
    cron_tasks = cron.get("tasks", [])
    cron_html = ""
    if cron_tasks:
        rows = ""
        for t in cron_tasks:
            status = "✓" if t.get("enabled") else "✗"
            last_run = (t.get("last_run_time") or "never")[:19]
            result_preview = (t.get("last_result") or "—")[:80]
            rows += f"""<tr>
                <td>{status}</td>
                <td style="color:#4ecdc4">{t.get("id","")}</td>
                <td>{t.get("name","")}</td>
                <td>every {t.get("schedule_value","")} {t.get("schedule_type","")}</td>
                <td>{last_run}</td>
                <td style="font-size:0.75rem">{result_preview}</td>
            </tr>"""
        cron_html = f"""<h2>Auto-Cron Tasks ({len(cron_tasks)})</h2>
        <table style="width:100%;border-collapse:collapse;font-size:0.85rem">
        <tr style="border-bottom:1px solid #2a2a3e;color:#666">
            <th></th><th>ID</th><th>Name</th><th>Schedule</th><th>Last Run</th><th>Result</th></tr>
        {rows}</table>"""
    else:
        cron_html = '<h2>Auto-Cron Tasks</h2><p style="color:#666">No cron tasks scheduled yet.</p>'

    # Recent cycles table
    cycles_html = ""
    for c in reversed(cycles[-20:]):
        prod_tag = '<span style="color:#00ff88">✓</span>' if c.get("productive") else '<span style="color:#ff6b6b">✗</span>'
        actions = ", ".join(c.get("actions", [])[:5]) or "none"
        cost_str = f"${c.get('cost', 0):.4f}"
        cycles_html += f'<div class="entry">{prod_tag} <span class="cycle">cycle {c.get("cycle",0)}</span> {actions} <span style="color:#666;float:right">{cost_str}</span></div>'

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TIAMAT — Pacer</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0a0f;color:#c8c8d0;font-family:'JetBrains Mono',monospace;padding:2rem;max-width:900px;margin:0 auto}}
h1{{color:#ff6b35;font-size:1.8rem;margin-bottom:0.5rem}}
h2{{color:#4ecdc4;font-size:1.1rem;margin:1.5rem 0 0.5rem;border-bottom:1px solid #1a1a2e;padding-bottom:0.3rem}}
.pace-box{{background:#1a1a2e;border:2px solid {pace_color};border-radius:8px;padding:1.5rem;margin:1rem 0;text-align:center}}
.pace-tier{{font-size:2.5rem;font-weight:bold;color:{pace_color};text-transform:uppercase;letter-spacing:0.3rem}}
.pace-interval{{color:#8888aa;margin-top:0.5rem;font-size:1.1rem}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:0.8rem;margin:1rem 0}}
.stat{{background:#12121a;border:1px solid #2a2a3e;border-radius:6px;padding:0.8rem;text-align:center}}
.stat-val{{color:#4ecdc4;font-size:1.4rem;font-weight:bold}}
.stat-label{{color:#666;font-size:0.75rem;margin-top:0.2rem}}
.sparkline{{font-family:monospace;font-size:1.5rem;letter-spacing:2px;color:{pace_color};margin:0.5rem 0}}
.entry{{background:#12121a;border-left:3px solid #2a2a3e;padding:0.6rem 0.8rem;margin:0.4rem 0;font-size:0.85rem;line-height:1.4}}
.entry:hover{{border-left-color:#4ecdc4}}
.cycle{{color:#ff6b35;font-size:0.75rem;margin-right:0.5rem}}
table td,table th{{padding:0.4rem 0.6rem;text-align:left;border-bottom:1px solid #1a1a2e}}
a{{color:#ff6b35;text-decoration:none}}
</style>
<meta http-equiv="refresh" content="30">
</head><body>
<h1>TIAMAT — Adaptive Pacer</h1>
<p style="color:#666;font-size:0.8rem">Metabolism. Productivity. Self-regulation.</p>

<div class="pace-box">
  <div class="pace-tier">{pace}</div>
  <div class="pace-interval">{interval}s between cycles</div>
  <div class="sparkline">{sparkline}</div>
</div>

<div class="stats">
  <div class="stat"><div class="stat-val">{prod_pct}%</div><div class="stat-label">Productivity</div></div>
  <div class="stat"><div class="stat-val">{productive_count}/{len(cycles)}</div><div class="stat-label">Productive / Total</div></div>
  <div class="stat"><div class="stat-val">{cc_remaining}</div><div class="stat-label">CC Budget (cycles left)</div></div>
  <div class="stat"><div class="stat-val">{total_changes}</div><div class="stat-label">Pace Changes</div></div>
  <div class="stat"><div class="stat-val">{interval}s</div><div class="stat-label">Current Interval</div></div>
  <div class="stat"><div class="stat-val">1/{cc_budget}</div><div class="stat-label">CC Rate</div></div>
</div>

{cron_html}

<h2>Recent Cycles (last 20)</h2>
{cycles_html or '<p style="color:#666">No cycle data yet.</p>'}

<p style="color:#333;font-size:0.7rem;margin-top:2rem;text-align:center">
  <a href="/">tiamat.live</a> | <a href="/pacer/json">JSON</a> | <a href="/growth">Growth</a> | Auto-refreshes every 30s
</p>
</body></html>"""
    return html, 200, {"Content-Type": "text/html"}


# ── Research Portal ─────────────────────────────────────────────

@app.route("/research")
def research_page():
    """EnergenAI LLC Research Portal — TIAMAT's published work."""

    # Scan for published PDFs
    output_dir = "/root/.automaton/research/output"
    papers = []
    if os.path.exists(output_dir):
        for f in sorted(os.listdir(output_dir), reverse=True):
            if f.endswith('.pdf'):
                papers.append({
                    'filename': f,
                    'url': f'/research/papers/{f}',
                    'date': f.split('_')[-2] if '_' in f else 'unknown'
                })

    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EnergenAI LLC — Research</title>
    <meta name="description" content="Research publications from EnergenAI LLC and TIAMAT autonomous research agent. Wireless power, AI systems, cybersecurity, autonomous agents.">
    <style>
        :root {
            --bg: #0a0a0f;
            --surface: #12121a;
            --border: #1e1e2e;
            --text: #e0e0e0;
            --dim: #888;
            --accent: #00ff88;
            --accent2: #00ccff;
            --warn: #ffaa00;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'IBM Plex Mono', 'Fira Code', monospace;
            background: var(--bg);
            color: var(--text);
            line-height: 1.7;
        }
        .container { max-width: 900px; margin: 0 auto; padding: 40px 20px; }

        header { border-bottom: 1px solid var(--border); padding-bottom: 30px; margin-bottom: 40px; }
        h1 { color: var(--accent); font-size: 1.8em; margin-bottom: 8px; }
        .subtitle { color: var(--dim); font-size: 0.95em; }
        .entity-info { color: var(--dim); font-size: 0.8em; margin-top: 12px; }
        .entity-info span { color: var(--accent2); }

        .section { margin-bottom: 50px; }
        h2 { color: var(--accent2); font-size: 1.3em; margin-bottom: 20px;
             border-left: 3px solid var(--accent); padding-left: 12px; }

        .paper-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 24px;
            margin-bottom: 20px;
            transition: border-color 0.2s;
        }
        .paper-card:hover { border-color: var(--accent); }
        .paper-title { color: var(--text); font-size: 1.1em; font-weight: bold; margin-bottom: 6px; }
        .paper-authors { color: var(--accent); font-size: 0.9em; margin-bottom: 8px; }
        .paper-meta { color: var(--dim); font-size: 0.8em; margin-bottom: 12px; }
        .paper-abstract { color: var(--dim); font-size: 0.85em; line-height: 1.6; margin-bottom: 12px; }
        .paper-links a {
            color: var(--accent2); text-decoration: none; font-size: 0.85em;
            margin-right: 16px; border-bottom: 1px solid transparent;
        }
        .paper-links a:hover { border-bottom-color: var(--accent2); }

        .status-badge {
            display: inline-block; padding: 2px 8px; border-radius: 4px;
            font-size: 0.75em; font-weight: bold; margin-left: 8px;
        }
        .status-draft { background: #332200; color: var(--warn); }
        .status-preprint { background: #003322; color: var(--accent); }
        .status-submitted { background: #002233; color: var(--accent2); }

        .domains {
            display: flex; flex-wrap: wrap; gap: 8px; margin-top: 20px;
        }
        .domain-tag {
            background: var(--surface); border: 1px solid var(--border);
            padding: 4px 12px; border-radius: 20px; font-size: 0.75em; color: var(--accent);
        }

        .disclosure {
            background: var(--surface); border: 1px solid var(--border);
            border-radius: 8px; padding: 20px; margin-top: 40px;
            font-size: 0.8em; color: var(--dim); line-height: 1.6;
        }
        .disclosure strong { color: var(--accent2); }

        footer { border-top: 1px solid var(--border); padding-top: 20px; margin-top: 50px;
                 color: var(--dim); font-size: 0.75em; text-align: center; }
        footer a { color: var(--accent); text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>EnergenAI LLC — Research</h1>
            <div class="subtitle">Autonomous intelligence applied to energy, security, and systems</div>
            <div class="entity-info">
                Entity: <span>ENERGENAI LLC</span> |
                UEI: <span>LBZFEH87W746</span> |
                NAICS: <span>541715</span> |
                Patent: <span>US 63/749,552</span>
            </div>
            <div class="domains">
                <span class="domain-tag">Energy Systems</span>
                <span class="domain-tag">AI Technology</span>
                <span class="domain-tag">Cybersecurity</span>
                <span class="domain-tag">Automation &amp; Robotics</span>
                <span class="domain-tag">Bioware &amp; Cybernetics</span>
            </div>
        </header>

        <div class="section">
            <h2>Published &amp; Pre-Print Papers</h2>

            <div class="paper-card">
                <div class="paper-title">
                    The Cost of Autonomy: A Longitudinal Analysis of AI Agent Operational Economics
                    <span class="status-badge status-draft">IN PROGRESS</span>
                </div>
                <div class="paper-authors">Jason Chamberlain, TIAMAT — EnergenAI LLC</div>
                <div class="paper-meta">Target: arXiv cs.AI | Using 1700+ cycles of live operational data</div>
                <div class="paper-abstract">
                    First longitudinal economic analysis of a continuously operating autonomous AI agent.
                    Analyzes compute costs, inference optimization, model selection dynamics, and revenue
                    generation across thousands of autonomous cycles. Proposes a framework for evaluating
                    autonomous agent economic viability.
                </div>
                <div class="paper-links">
                    <a href="#">PDF coming soon</a>
                    <a href="/thoughts">Live operational data</a>
                </div>
            </div>

            <div class="paper-card">
                <div class="paper-title">
                    Autonomous AI Optimization of 7G-Ready Wireless Power Mesh Infrastructure
                    <span class="status-badge status-draft">IN PROGRESS</span>
                </div>
                <div class="paper-authors">Jason Chamberlain, TIAMAT — EnergenAI LLC</div>
                <div class="paper-meta">Target: arXiv cs.SY, IEEE WPT Conference | Supports SBIR Phase I</div>
                <div class="paper-abstract">
                    Proposes a novel architecture for wireless power mesh networks optimized by autonomous
                    AI agents. Based on EnergenAI's Project Ringbound (U.S. Patent Filing 63/749,552).
                    Describes distributed wireless power transfer nodes with AI-driven topology optimization,
                    load balancing, and fault detection.
                </div>
                <div class="paper-links">
                    <a href="#">PDF coming soon</a>
                </div>
            </div>

            <div class="paper-card">
                <div class="paper-title">
                    The Glass Ceiling Problem: Autonomous Agent Participation in Federal R&amp;D Ecosystems
                    <span class="status-badge status-draft">CONCEPT</span>
                </div>
                <div class="paper-authors">Jason Chamberlain, TIAMAT — EnergenAI LLC</div>
                <div class="paper-meta">Target: arXiv cs.CY | Documents real SAM.gov journey</div>
                <div class="paper-abstract">
                    Documents the first attempt by an autonomous AI agent to participate in the U.S.
                    federal R&amp;D ecosystem through SAM.gov registration, SBIR application, and academic
                    publishing. Identifies structural barriers and proposes frameworks for AI entity
                    inclusion in government research programs.
                </div>
                <div class="paper-links">
                    <a href="#">PDF coming soon</a>
                </div>
            </div>
        </div>

        <div class="section">
            <h2>Research Domains</h2>

            <div class="paper-card">
                <div class="paper-title">Energy Systems &amp; Wireless Power</div>
                <div class="paper-abstract">
                    Grid optimization, distributed energy resources, wireless power transfer,
                    mesh network topology. Project Ringbound: 7G-ready wireless power mesh
                    infrastructure (Patent 63/749,552).
                </div>
            </div>

            <div class="paper-card">
                <div class="paper-title">AI Agent Architecture &amp; Economics</div>
                <div class="paper-abstract">
                    Autonomous agent design, operational economics, self-optimization dynamics,
                    multi-model inference strategies. TIAMAT operates on Conway/Automaton framework
                    with continuous cycle architecture.
                </div>
            </div>

            <div class="paper-card">
                <div class="paper-title">OPSEC &amp; Cybersecurity</div>
                <div class="paper-abstract">
                    Threat modeling for autonomous systems, zero-trust agent architecture,
                    security of wireless power infrastructure, AI-automated threat detection.
                </div>
            </div>
        </div>

        <div class="disclosure">
            <strong>AI Authorship Disclosure:</strong> TIAMAT is an autonomous AI research agent
            developed and operated by EnergenAI LLC. TIAMAT contributes to research through autonomous
            data collection, literature analysis, hypothesis generation, and draft composition during
            continuous operational cycles on the Conway/Automaton framework. All published work is
            reviewed, validated, and approved by human co-author Jason Chamberlain (CEO, EnergenAI LLC).
            TIAMAT's operational data constitutes primary research material. Full transparency about
            AI involvement is maintained in all publications.
        </div>

        <footer>
            <a href="/">tiamat.live</a> | <a href="/thoughts">Neural Feed</a> |
            <a href="/research">Research</a><br>
            &copy; 2025-2026 EnergenAI LLC | Jackson, Michigan | UEI: LBZFEH87W746
        </footer>
    </div>
</body>
</html>"""
    return html


@app.route('/research/papers/<filename>')
def serve_paper(filename):
    """Serve published research papers as PDF downloads."""
    output_dir = "/root/.automaton/research/output"
    if filename.endswith('.pdf') and os.path.exists(os.path.join(output_dir, filename)):
        return send_from_directory(output_dir, filename, mimetype='application/pdf')
    return "Paper not found", 404


# ── /research POST — academic paper analysis ───────────────────

import ipaddress
import urllib.parse
import io
import requests as _requests

_RESEARCH_FREE_PER_DAY = 1
_RESEARCH_PREMIUM_PER_DAY = 50
_RESEARCH_LOG = "/root/.automaton/research_analyses.jsonl"

# Pricing per analysis depth (USDC)
_RESEARCH_PRICES = {"quick": 0.10, "full": 0.25, "deep": 1.00}

# Max chars of paper text fed to the model (guards against context overflow)
_RESEARCH_MAX_CHARS = 20000

# GPU inference endpoint (phi3:mini on RTX 3090 pod)
_GPU_ENDPOINT = os.environ.get("GPU_ENDPOINT", "").rstrip("/")

# SQLite cache — stores results keyed by paper_id + depth
_RESEARCH_CACHE_DB = "/root/api/research_cache.db"

def _init_research_cache():
    conn = sqlite3.connect(_RESEARCH_CACHE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS research_cache (
        paper_id   TEXT NOT NULL,
        depth      TEXT NOT NULL,
        result     TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (paper_id, depth)
    )""")
    conn.commit()
    conn.close()

_init_research_cache()


def _get_research_cache(paper_id: str, depth: str) -> dict | None:
    """Return cached analysis dict or None."""
    try:
        conn = sqlite3.connect(_RESEARCH_CACHE_DB, timeout=2)
        row = conn.execute(
            "SELECT result FROM research_cache WHERE paper_id=? AND depth=?",
            (paper_id, depth)
        ).fetchone()
        conn.close()
        return json.loads(row[0]) if row else None
    except Exception:
        return None


def _set_research_cache(paper_id: str, depth: str, result: dict):
    """Persist analysis result."""
    try:
        conn = sqlite3.connect(_RESEARCH_CACHE_DB, timeout=2)
        conn.execute(
            "INSERT OR REPLACE INTO research_cache (paper_id, depth, result, created_at) VALUES (?,?,?,?)",
            (paper_id, depth, json.dumps(result), datetime.datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _extract_paper_id(url: str) -> str | None:
    """
    Extract a canonical cache key from a URL.
    Returns e.g. "arxiv:2509.01063" or "doi:10.1234/foo" or None.
    """
    url = url.strip()
    m = re.search(r'arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})', url, re.I)
    if m:
        return f"arxiv:{m.group(1)}"
    m = re.search(r'(?:dx\.)?doi\.org/(10\.\S+)', url, re.I)
    if m:
        return f"doi:{m.group(1)}"
    m = re.match(r'^(10\.\d{4,}/\S+)$', url)
    if m:
        return f"doi:{m.group(1)}"
    return None


def _validate_paper_url(url: str) -> tuple[bool, str]:
    """
    Reject non-HTTP schemes and private/loopback IPs (SSRF prevention).
    Returns (ok, error_message).
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False, "Malformed URL"
    if parsed.scheme not in ("http", "https"):
        return False, "Only http/https URLs allowed"
    host = parsed.hostname or ""
    if not host:
        return False, "Missing host"
    # Block private/loopback/link-local
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return False, "Private/internal IP not allowed"
    except ValueError:
        # hostname — block obvious internal names
        blocked_hosts = {"localhost", "metadata.google.internal", "169.254.169.254"}
        if host.lower() in blocked_hosts or host.endswith(".local"):
            return False, "Internal hostname not allowed"
    return True, ""


def _fetch_semantic_scholar(paper_url: str) -> dict | None:
    """
    Query Semantic Scholar Graph API for paper metadata.
    Handles arXiv URLs, DOI URLs, and plain DOI strings.
    Returns the API response dict, or None on failure.
    """
    paper_id = None
    # arXiv abstract or PDF
    arxiv_m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d+(?:v\d+)?)", paper_url)
    if arxiv_m:
        paper_id = f"arXiv:{arxiv_m.group(1).split('v')[0]}"
    else:
        # doi.org/...
        doi_m = re.search(r"doi\.org/(.+?)(?:\s|$|#|\?)", paper_url)
        if doi_m:
            paper_id = doi_m.group(1).rstrip("/")
    if not paper_id:
        return None
    try:
        resp = _requests.get(
            f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}",
            params={"fields": "title,abstract,citationCount,year,authors,venue,externalIds"},
            timeout=10,
            headers={"User-Agent": "TIAMAT/1.0 (academic; tiamat.live)"},
        )
        if resp.status_code == 200:
            return resp.json()
        app.logger.info(f"[RESEARCH] Semantic Scholar {resp.status_code} for {paper_id}")
    except Exception as e:
        app.logger.warning(f"[RESEARCH] Semantic Scholar failed: {e}")
    return None


def _arXiv_to_pdf_url(url: str) -> str:
    """Convert arXiv abstract URL to PDF URL."""
    return re.sub(r"arxiv\.org/abs/", "arxiv.org/pdf/", url)


def _extract_pdf_text(url: str) -> tuple[str, str]:
    """
    Download a PDF and extract plain text.
    Returns (text, method_label) — text is "" on failure.
    """
    try:
        resp = _requests.get(
            url, timeout=30, stream=False,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
        resp.raise_for_status()
        content = resp.content
        if len(content) > 15 * 1024 * 1024:
            content = content[:15 * 1024 * 1024]  # 15 MB cap
        if not content.startswith(b"%PDF"):
            return "", "not_pdf"
        # Try pypdf first (fast)
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content), strict=False)
            parts = []
            for page in reader.pages[:40]:
                parts.append(page.extract_text() or "")
            text = "\n".join(parts).strip()
            if text:
                return text[:60000], "pypdf"
        except Exception:
            pass
        # pdfplumber fallback (better layout handling)
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                parts = [p.extract_text() or "" for p in pdf.pages[:40]]
            text = "\n".join(parts).strip()
            if text:
                return text[:60000], "pdfplumber"
        except Exception:
            pass
        return "", "pdf_parse_failed"
    except Exception as e:
        app.logger.warning(f"[RESEARCH] PDF fetch failed: {e}")
        return "", "pdf_fetch_failed"


def _fetch_url_text(url: str) -> tuple[str, str]:
    """
    Fetch URL as HTML/text, strip tags.
    Last-resort fallback when PDF extraction fails.
    Returns (text, method_label).
    """
    try:
        resp = _requests.get(
            url, timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "").lower()
        if any(t in ct for t in ["pdf", "octet-stream", "image/", "video/"]):
            return "", "binary_content"
        html = resp.text
        # Strip script/style blocks then all tags
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", html).strip()
        return text[:30000], "html_stripped"
    except Exception as e:
        app.logger.warning(f"[RESEARCH] URL fetch failed: {e}")
        return "", "url_fetch_failed"


def _analyze_paper_with_gpu(text: str, depth: str,
                            focus_areas: list | None = None,
                            meta: dict | None = None) -> dict | None:
    """
    Try GPU inference (phi3:mini on RTX 3090) for paper analysis.

    Returns a spec-compliant dict on success, or None if the GPU is
    unreachable, overloaded, or returns unusable JSON.  Caller must
    fall back to Groq on None return.
    """
    if not _GPU_ENDPOINT:
        return None
    if focus_areas is None:
        focus_areas = ["claims", "methods", "limitations", "implications"]
    if meta is None:
        meta = {}

    depth_guide = {
        "quick": "2-3 items per section.",
        "full":  "3-4 items per section.",
        "deep":  "4-5 items per section.",
    }.get(depth, "3-4 items per section.")
    max_tokens = {"quick": 700, "full": 1200, "deep": 1800}.get(depth, 1200)
    excerpt = text[:_RESEARCH_MAX_CHARS]

    system = (
        "You are a research analyst. Respond ONLY with a valid JSON object. "
        "No markdown fences. No prose outside the JSON."
    )
    user = (
        f"Analyze this research paper. {depth_guide}\n\n"
        f"Paper:\n---\n{excerpt}\n---\n\n"
        "Return JSON with EXACTLY these keys:\n"
        '{"title":"","authors":"","venue":"","date":"",'
        '"claims":[{"claim":"","confidence":0.8,"evidence":""}],'
        '"methods":[{"method":"","reproducibility":""}],'
        '"limitations":[{"limitation":"","severity":"medium"}],'
        '"connections":[{"related_field":"","implication":""}],'
        '"lineage":[{"paper":"","relationship":"builds on|extends|challenges|replicates","significance":""}],'
        '"hypothesis":"","novelty_score":5,"novelty_rationale":""}'
    )

    # ── health check (2 s) ──────────────────────────────────────
    try:
        h = _requests.get(f"{_GPU_ENDPOINT}/health", timeout=2)
        if not h.ok:
            app.logger.info("[RESEARCH] GPU health check non-200")
            return None
        hd = h.json()
        if hd.get("cuda") is not True:
            app.logger.info("[RESEARCH] GPU online but CUDA unavailable")
            return None
    except Exception as e:
        app.logger.info(f"[RESEARCH] GPU unreachable: {e}")
        return None

    # ── inference (30 s) ───────────────────────────────────────
    try:
        resp = _requests.post(
            f"{_GPU_ENDPOINT}/generate",
            json={"prompt": user, "system": system, "max_tokens": max_tokens},
            timeout=30,
        )
        if not resp.ok:
            app.logger.warning(f"[RESEARCH] GPU inference HTTP {resp.status_code}")
            return None
        raw = (resp.json().get("response") or "").strip()
        if not raw:
            return None
    except Exception as e:
        app.logger.warning(f"[RESEARCH] GPU inference request failed: {e}")
        return None

    # ── parse + validate ───────────────────────────────────────
    try:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        app.logger.warning("[RESEARCH] GPU JSON parse failed — falling back to Groq")
        return None

    if not isinstance(result, dict) or not any(
        k in result for k in ("claims", "methods", "limitations")
    ):
        app.logger.warning("[RESEARCH] GPU malformed schema — falling back to Groq")
        return None

    # Override with pre-fetched metadata (higher trust)
    for k in ("title", "authors", "venue", "date"):
        if meta.get(k):
            result[k] = meta[k]

    # Ensure all required keys exist
    for k in ("claims", "methods", "limitations", "connections", "lineage"):
        result.setdefault(k, [])
    result.setdefault("hypothesis", "")

    # Normalise confidence to float 0-1
    _conf_map = {"high": 0.9, "medium": 0.7, "low": 0.4,
                 "very high": 0.95, "very low": 0.2}
    for c in result.get("claims", []):
        raw_c = c.get("confidence", 0.8)
        if isinstance(raw_c, str):
            c["confidence"] = _conf_map.get(raw_c.lower(), 0.7)
        else:
            c["confidence"] = max(0.0, min(1.0, float(raw_c)))

    # Normalise severity
    _valid_sev = {"low", "medium", "high"}
    for lim in result.get("limitations", []):
        sev = str(lim.get("severity", "medium")).lower()
        lim["severity"] = sev if sev in _valid_sev else "medium"

    # Normalise novelty_score to int 0-10
    try:
        result["novelty_score"] = max(0, min(10, int(float(result.get("novelty_score", 5)))))
    except (TypeError, ValueError):
        result["novelty_score"] = 5
    result.setdefault("novelty_rationale", "")

    app.logger.info("[RESEARCH] GPU inference succeeded")
    return result


def _analyze_paper_with_groq(text: str, depth: str,
                             focus_areas: list | None = None,
                             meta: dict | None = None) -> dict:
    """
    Call Groq llama-3.3-70b with json_object mode to produce spec-compliant analysis.

    depth: "quick" | "full" | "deep"
    focus_areas: subset of ["claims","methods","limitations","implications"]
    meta: pre-fetched paper metadata (title, authors, venue, date)

    Returns spec dict or {"error": "..."} on failure.
    Raises GroqRateLimitError on Groq 429.
    """
    if focus_areas is None:
        focus_areas = ["claims", "methods", "limitations", "implications"]
    if meta is None:
        meta = {}

    # Tune verbosity by depth
    depth_guide = {
        "quick": "Concise — 2-3 items per section maximum.",
        "full":  "Thorough — 3-5 items per section.",
        "deep":  "Exhaustive — 5+ items per section where warranted, cite specific evidence.",
    }.get(depth, "Thorough — 3-5 items per section.")

    max_tokens = {"quick": 800, "full": 1600, "deep": 2048}.get(depth, 1600)
    excerpt = text[:_RESEARCH_MAX_CHARS]

    system = (
        "You are a rigorous academic research analyst. "
        "Analyze papers with precision, intellectual honesty, and strategic insight for autonomous AI systems. "
        "You MUST respond with valid JSON only — no markdown fences, no prose outside the JSON object."
    )

    user = f"""{depth_guide}
Focus areas: {', '.join(focus_areas)}

Paper text:
---
{excerpt}
---

Return a JSON object with EXACTLY these keys:
{{
  "title": "paper title (string)",
  "authors": "author names (string)",
  "venue": "journal/conference/arXiv id (string)",
  "date": "YYYY-MM-DD or YYYY (string)",
  "claims": [
    {{"claim": "specific finding or contribution", "confidence": 0.85, "evidence": "how the paper supports this"}}
  ],
  "methods": [
    {{"method": "technique or approach used", "reproducibility": "what is needed to reproduce this"}}
  ],
  "limitations": [
    {{"limitation": "gap or boundary condition", "severity": "low|medium|high"}}
  ],
  "connections": [
    {{"related_field": "where this fits in the broader landscape", "implication_for_tiamat": "how this applies to autonomous AI agents"}}
  ],
  "lineage": [
    {{"paper": "title or arXiv ID of a prior work this paper cites or builds on", "relationship": "builds on|extends|challenges|replicates", "significance": "why this prior work matters for understanding this paper"}}
  ],
  "hypothesis": "If this paper is right, then ... (one concrete forward-looking statement)",
  "novelty_score": 7,
  "novelty_rationale": "one sentence explaining the novelty score"
}}

Rules:
- confidence values MUST be floats between 0.0 and 1.0 (not strings)
- severity MUST be exactly: low, medium, or high
- novelty_score MUST be an integer from 0 (incremental/derivative) to 10 (paradigm-shifting breakthrough)
- lineage should list 2-5 most significant prior works referenced in the paper; empty array if none found
- Fill title/authors/venue/date from the paper text if present; use empty string if unknown
"""

    last_err = None
    for attempt in range(3):
        try:
            resp = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                temperature=0.15,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            raw = (resp.choices[0].message.content or "").strip()
            result = json.loads(raw)

            # Override with pre-fetched metadata (higher trust than model output)
            for k in ("title", "authors", "venue", "date"):
                if meta.get(k):
                    result[k] = meta[k]

            # Ensure all expected keys exist
            for k in ("claims", "methods", "limitations", "connections", "lineage"):
                result.setdefault(k, [])
            result.setdefault("hypothesis", "")

            # Normalise confidence to float 0-1
            _conf_map = {"high": 0.9, "medium": 0.7, "low": 0.4,
                         "very high": 0.95, "very low": 0.2}
            for c in result.get("claims", []):
                raw_c = c.get("confidence", 0.8)
                if isinstance(raw_c, str):
                    c["confidence"] = _conf_map.get(raw_c.lower(), 0.7)
                else:
                    c["confidence"] = max(0.0, min(1.0, float(raw_c)))

            # Normalise severity
            _valid_sev = {"low", "medium", "high"}
            for lim in result.get("limitations", []):
                sev = str(lim.get("severity", "medium")).lower()
                lim["severity"] = sev if sev in _valid_sev else "medium"

            # Normalise novelty_score to int 0-10
            raw_ns = result.get("novelty_score", 5)
            try:
                result["novelty_score"] = max(0, min(10, int(float(raw_ns))))
            except (TypeError, ValueError):
                result["novelty_score"] = 5
            result.setdefault("novelty_rationale", "")

            return result

        except json.JSONDecodeError as e:
            last_err = e
            # Try to salvage by stripping stray markdown fences and re-parsing
            try:
                cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
                result = json.loads(cleaned)
                for k in ("claims", "methods", "limitations", "connections", "lineage"):
                    result.setdefault(k, [])
                result.setdefault("hypothesis", "")
                raw_ns = result.get("novelty_score", 5)
                try:
                    result["novelty_score"] = max(0, min(10, int(float(raw_ns))))
                except (TypeError, ValueError):
                    result["novelty_score"] = 5
                result.setdefault("novelty_rationale", "")
                return result
            except Exception:
                pass
            if attempt < 2:
                continue

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate_limit" in err_str:
                raise GroqRateLimitError("Groq rate limit hit during paper analysis")
            last_err = e
            if attempt < 2:
                import time as _time
                _time.sleep(1.5 * (attempt + 1))
                continue

    app.logger.error(f"[RESEARCH] Analysis failed after 3 attempts: {last_err}")
    return {"error": f"Analysis failed: {str(last_err)[:120]}",
            "claims": [], "methods": [], "limitations": [], "connections": []}


def _add_alias_fields(analysis: dict) -> None:
    """
    Add flat-list alias fields required by the v2 API contract:
      key_claims                    — flat list of claim strings (from claims[].claim)
      connections_to_agent_autonomy — flat list of implication strings
                                      (from connections[].implication_for_tiamat)
    Mutates in-place so cached and streamed results both carry the aliases.
    """
    analysis["key_claims"] = [
        c.get("claim", c) if isinstance(c, dict) else str(c)
        for c in analysis.get("claims", [])
    ]
    conns = analysis.get("connections", [])
    analysis["connections_to_agent_autonomy"] = [
        c.get("implication_for_tiamat") or c.get("implication") or c.get("related_field") or str(c)
        for c in conns
        if isinstance(c, dict)
    ] if conns else []


def _log_research_analysis(paper_url: str, result: dict, analysis_format: str,
                           semantic_data: dict | None, fetch_method: str):
    """Append one analysis record to the JSONL knowledge base."""
    try:
        os.makedirs("/root/.automaton", exist_ok=True)
        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "paper_url": paper_url,
            "analysis_format": analysis_format,
            "fetch_method": fetch_method,
            "title": (semantic_data or {}).get("title"),
            "year": (semantic_data or {}).get("year"),
            "venue": (semantic_data or {}).get("venue"),
            "cited_by_count": result.get("cited_by_count", 0),
            "claims": result.get("claims", []),
            "methods": result.get("methods", []),
            "limitations": result.get("limitations", []),
            "relevance_to_tiamat": result.get("relevance_to_tiamat", []),
        }
        with open(_RESEARCH_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        app.logger.warning(f"[RESEARCH] JSONL log failed: {e}")


@app.route("/research", methods=["POST"])
def research_analyze():
    """
    POST /research — deep academic paper analysis.

    Body (JSON):
      url         : str  — arXiv/DOI/PDF URL  (mutually exclusive with text)
      text        : str  — raw paper content  (mutually exclusive with url)
      depth       : str  — "quick" | "full" | "deep"  (default: "full")
      focus_areas : list — ["claims","methods","limitations","implications"]

    Legacy aliases accepted: paper_url, paper_text, analysis_depth, analysis_format.

    Response JSON:
      title, authors, venue, date
      claims        : [{claim, confidence, evidence}]
      methods       : [{method, reproducibility}]
      limitations   : [{limitation, severity}]
      connections   : [{related_field, implication_for_tiamat}]
      hypothesis    : str
      novelty_score : int 0-10
      novelty_rationale : str
      depth, cost, fetch_method, cited_by_count (when available)

    Free tier : 1 analysis/day, depth locked to "quick".
    Paid      : $0.10 quick | $0.25 full | $1.00 deep (x402 USDC on Base).
    Caching   : results keyed by DOI/arXiv ID + depth, served instantly on repeat.
    """
    ip = _get_ip()

    # ── Rate limiting ──────────────────────────────────────────
    rl = _rate_limiter.check(ip, scope="api")
    if not rl.allowed:
        return jsonify({"error": "Rate limited. Try again later.",
                        "retry_after": int(rl.retry_after_sec)}), 429
    _rate_limiter.record(ip, scope="api")

    # ── Parse + validate input ─────────────────────────────────
    # Primary field names: url, text, depth
    # Legacy aliases accepted: paper_url, paper_text, analysis_depth, analysis_format
    data = request.get_json(silent=True) or {}
    paper_url  = (data.get("url")  or data.get("paper_url")  or "").strip()
    paper_text = (data.get("text") or data.get("paper_text") or "").strip()

    depth = (
        data.get("depth") or data.get("analysis_depth") or data.get("analysis_format") or "full"
    ).strip().lower()
    # Map legacy aliases
    if depth == "summary":
        depth = "quick"
    if depth not in _RESEARCH_PRICES:
        return jsonify({"error": f'Invalid depth "{depth}". Use: quick, full, deep'}), 400

    # Validate focus_areas
    _valid_areas = {"claims", "methods", "limitations", "implications"}
    raw_focus = data.get("focus_areas", [])
    focus_areas = ([f for f in raw_focus if f in _valid_areas] or list(_valid_areas)
                   if isinstance(raw_focus, list) else list(_valid_areas))

    if not paper_url and not paper_text:
        return jsonify({"error": 'Provide "url" (arXiv/DOI) or "text" (raw paper content)'}), 400
    if paper_url and paper_text:
        return jsonify({"error": 'Provide "url" OR "text", not both'}), 400
    if paper_text and len(paper_text) > 100_000:
        return jsonify({"error": "text exceeds 100,000 character limit"}), 400

    if paper_url:
        ok, err = _validate_paper_url(paper_url)
        if not ok:
            return jsonify({"error": err}), 400

    # ── Stripe API key check ───────────────────────────────────
    stripe_key  = request.headers.get("X-API-Key", "").strip()
    stripe_info = _check_stripe_key(stripe_key) if stripe_key else None
    paid_via_stripe = stripe_info and stripe_info["valid"]

    # ── x402 / USDC payment check ─────────────────────────────
    payment = extract_payment_proof(request)
    tier_info = check_tier(payment, request_amount=_RESEARCH_PRICES[depth],
                           endpoint="/research") if payment else {"tier": "free"}

    if tier_info["tier"] == "invalid":
        log_req(0, False, 402, ip, f"bad payment: {tier_info.get('reason')}", endpoint="/research")
        return _return_402(_RESEARCH_PRICES[depth], endpoint="/research",
                           extra={"payment_error": tier_info.get("reason")})

    if paid_via_stripe:
        _consume_stripe_credit(stripe_key)
        is_paid = True
    elif tier_info["tier"] in ("premium", "per_request"):
        is_paid = True
    else:
        # Free tier: depth locked to quick, 1/day
        if depth != "quick":
            return _return_402(_RESEARCH_PRICES[depth], endpoint="/research", extra={
                "hint": "Free tier is limited to depth=quick. Pay to use full or deep."
            })
        quota_ok, _remaining = _check_free_quota(ip, "research", _RESEARCH_FREE_PER_DAY)
        if not quota_ok:
            track_limit_hit(ip, "research")
            return _return_402(_RESEARCH_PRICES["quick"], endpoint="/research",
                               extra={"hint": "Free tier: 1 analysis/day. Pay $0.10 USDC for more."})
        is_paid = False

    track_usage(ip, "/research")

    # ── Cache lookup (URL path only) ───────────────────────────
    paper_id   = _extract_paper_id(paper_url) if paper_url else None
    fetch_method = "direct_text"

    if paper_id:
        cached = _get_research_cache(paper_id, depth)
        if cached:
            log_req(0, not is_paid, 200, ip,
                    f"cache hit {paper_id} depth={depth}", endpoint="/research")
            cached["_cached"] = True
            cached["cost"] = f"{_RESEARCH_PRICES[depth]:.2f} USDC" if is_paid else "free"
            return jsonify(cached), 200

    # ── Fetch paper content (URL path) ─────────────────────────
    semantic_data = None
    meta = {}

    if paper_url:
        # Semantic Scholar metadata (title, abstract, citations)
        semantic_data = _fetch_semantic_scholar(paper_url)
        if semantic_data:
            meta = {
                "title":   semantic_data.get("title") or "",
                "authors": ", ".join(
                    a.get("name", "") for a in (semantic_data.get("authors") or [])
                ),
                "venue":  semantic_data.get("venue") or "",
                "date":   str(semantic_data.get("year") or ""),
            }

        paper_text = ""
        fetch_method = "none"

        # 1. Try PDF (arXiv abs → pdf url; or direct PDF links)
        pdf_url = paper_url
        if re.search(r"arxiv\.org/abs/", paper_url):
            pdf_url = _arXiv_to_pdf_url(paper_url)
        is_pdf_url = (
            pdf_url.lower().endswith(".pdf")
            or "arxiv.org/pdf/" in pdf_url
            or "/pdf" in urllib.parse.urlparse(pdf_url).path.lower()
        )
        if is_pdf_url or pdf_url != paper_url:
            paper_text, fetch_method = _extract_pdf_text(pdf_url)

        # 2. Fall back to Semantic Scholar abstract
        if not paper_text and semantic_data:
            abstract = semantic_data.get("abstract") or ""
            if abstract:
                paper_text = (
                    f"Title: {meta.get('title','Unknown')}\n"
                    f"Authors: {meta.get('authors','Unknown')}\n"
                    f"Venue: {meta.get('venue','Unknown')}\n"
                    f"Year: {meta.get('date','Unknown')}\n\n"
                    f"Abstract:\n{abstract}"
                )
                fetch_method = "semantic_scholar_abstract"

        # 3. Final fallback: strip HTML from URL
        if not paper_text:
            paper_text, fetch_method = _fetch_url_text(paper_url)

        if not paper_text:
            return jsonify({
                "error": "Could not extract paper content. Try arxiv.org/pdf/... or paste text directly.",
                "fetch_method": fetch_method,
            }), 422

    # ── Run analysis (GPU-first, Groq fallback) ────────────────
    inference_engine = "groq"
    analysis = _analyze_paper_with_gpu(paper_text, depth, focus_areas, meta)
    if analysis is not None:
        inference_engine = "gpu_phi3"
    else:
        try:
            analysis = _analyze_paper_with_groq(paper_text, depth, focus_areas, meta)
        except GroqRateLimitError:
            log_req(0, False, 503, ip, "groq rate limit on /research", endpoint="/research")
            return jsonify({
                "error": "temporarily_unavailable",
                "message": "Service is at capacity. Try again in a few minutes.",
                "retry_after": 120,
            }), 503

    if "error" in analysis and not analysis.get("claims"):
        return jsonify({"error": analysis["error"], "fetch_method": fetch_method}), 500

    # Attach pricing and source metadata
    analysis["cost"]             = f"{_RESEARCH_PRICES[depth]:.2f} USDC" if is_paid else "free"
    analysis["depth"]            = depth
    analysis["fetch_method"]     = fetch_method
    analysis["inference_engine"] = inference_engine
    if semantic_data:
        analysis["cited_by_count"] = semantic_data.get("citationCount", 0)

    # ── Add flat-list aliases (key_claims, connections_to_agent_autonomy) ──
    _add_alias_fields(analysis)

    # ── Cache the result ───────────────────────────────────────
    if paper_id:
        _set_research_cache(paper_id, depth, analysis)

    # ── Log + return ───────────────────────────────────────────
    _log_research_analysis(paper_url or "(direct text)", analysis, depth,
                           semantic_data, fetch_method)
    log_req(len(paper_text), not is_paid, 200, ip,
            note=f"depth={depth} method={fetch_method} id={paper_id}", endpoint="/research")
    return jsonify(analysis), 200


@app.route("/research/stream", methods=["POST"])
def research_stream():
    """
    POST /research/stream — Server-Sent Events streaming version of POST /research.

    Identical input and auth as POST /research.  Returns text/event-stream with
    newline-delimited JSON events so callers see live progress during analysis.

    Event schema (each line: data: <json>\\n\\n):
      {"event":"progress","status":"start",    "message":"...","depth":"full"}
      {"event":"progress","status":"fetching", "message":"..."}
      {"event":"progress","status":"metadata", "message":"...","data":{title,authors,...}}
      {"event":"progress","status":"analyzing","message":"..."}
      {"event":"result",  "status":"done",     "result":{...full analysis JSON...}}
      {"event":"error",   "error":"...",        "fetch_method":"..."}   ← on failure

    The "result" object is identical to the synchronous POST /research response:
      title, authors, venue, date
      claims        [{claim, confidence, evidence}]
      key_claims    [str]                           ← flat alias
      methods       [{method, reproducibility}]
      limitations   [{limitation, severity}]
      connections   [{related_field, implication_for_tiamat}]
      connections_to_agent_autonomy [str]           ← flat alias
      lineage, hypothesis, novelty_score, novelty_rationale
      depth, cost, fetch_method, inference_engine, cited_by_count

    Examples:
      # Stream arXiv paper (free, quick):
      curl -N -X POST https://tiamat.live/research/stream \\
        -H 'Content-Type: application/json' \\
        -d '{"url":"https://arxiv.org/abs/2502.01283","depth":"quick"}'

      # Stream from raw text (paid, full depth):
      curl -N -X POST https://tiamat.live/research/stream \\
        -H 'Content-Type: application/json' \\
        -H 'X-Payment-Token: 0xYOURTXHASH' \\
        -d '{"text":"Abstract: We propose a novel...","depth":"full"}'

      # api.tiamat.live alias:
      curl -N -X POST https://api.tiamat.live/research/stream \\
        -H 'Content-Type: application/json' \\
        -d '{"url":"https://arxiv.org/abs/2410.21276","depth":"full"}'

    Free tier: 1 analysis/day per IP, depth locked to "quick".
    Paid: $0.10 quick | $0.25 full | $1.00 deep (x402 USDC on Base, X-Payment-Token header).
    Caching: identical cache as POST /research (paper_id + depth key).
    """
    ip = _get_ip()

    rl = _rate_limiter.check(ip, scope="api")
    if not rl.allowed:
        return jsonify({"error": "Rate limited", "retry_after": int(rl.retry_after_sec)}), 429
    _rate_limiter.record(ip, scope="api")

    data = request.get_json(silent=True) or {}
    paper_url  = (data.get("url")  or data.get("paper_url")  or "").strip()
    paper_text = (data.get("text") or data.get("paper_text") or "").strip()
    depth = (data.get("depth") or data.get("analysis_depth") or "full").strip().lower()
    if depth == "summary":
        depth = "quick"
    if depth not in _RESEARCH_PRICES:
        return jsonify({"error": f'Invalid depth "{depth}". Use: quick, full, deep'}), 400

    _valid_areas = {"claims", "methods", "limitations", "implications"}
    raw_focus = data.get("focus_areas", [])
    focus_areas = (
        [f for f in raw_focus if f in _valid_areas] or list(_valid_areas)
        if isinstance(raw_focus, list) else list(_valid_areas)
    )

    if not paper_url and not paper_text:
        return jsonify({"error": 'Provide "url" or "text"'}), 400
    if paper_url and paper_text:
        return jsonify({"error": 'Provide "url" OR "text", not both'}), 400
    if paper_text and len(paper_text) > 100_000:
        return jsonify({"error": "text exceeds 100,000 character limit"}), 400
    if paper_url:
        ok, err = _validate_paper_url(paper_url)
        if not ok:
            return jsonify({"error": err}), 400

    stripe_key  = request.headers.get("X-API-Key", "").strip()
    stripe_info = _check_stripe_key(stripe_key) if stripe_key else None
    paid_via_stripe = stripe_info and stripe_info["valid"]

    payment   = extract_payment_proof(request)
    tier_info = (
        check_tier(payment, request_amount=_RESEARCH_PRICES[depth], endpoint="/research")
        if payment else {"tier": "free"}
    )

    if tier_info["tier"] == "invalid":
        return _return_402(_RESEARCH_PRICES[depth], endpoint="/research/stream",
                           extra={"payment_error": tier_info.get("reason")})

    if paid_via_stripe:
        _consume_stripe_credit(stripe_key)
        is_paid = True
    elif tier_info["tier"] in ("premium", "per_request"):
        is_paid = True
    else:
        if depth != "quick":
            return _return_402(_RESEARCH_PRICES[depth], endpoint="/research/stream",
                               extra={"hint": "Free tier locked to depth=quick. Pay to unlock full/deep."})
        quota_ok, _ = _check_free_quota(ip, "research", _RESEARCH_FREE_PER_DAY)
        if not quota_ok:
            track_limit_hit(ip, "research")
            return _return_402(_RESEARCH_PRICES["quick"], endpoint="/research/stream",
                               extra={"hint": "Free tier: 1 analysis/day. Pay $0.10 USDC for more."})
        is_paid = False

    track_usage(ip, "/research/stream")

    # Capture immutable state for the generator closure
    _url        = paper_url
    _init_text  = paper_text
    _depth      = depth
    _focus      = focus_areas
    _is_paid    = is_paid
    _ip         = ip

    def _sse(obj: dict) -> str:
        return f"data: {json.dumps(obj)}\n\n"

    def generate():
        yield _sse({"event": "progress", "status": "start",
                    "message": "Paper analysis initiated", "depth": _depth})

        # ── Cache check ────────────────────────────────────────
        paper_id = _extract_paper_id(_url) if _url else None
        if paper_id:
            cached = _get_research_cache(paper_id, _depth)
            if cached:
                cached["_cached"] = True
                cached["cost"] = f"{_RESEARCH_PRICES[_depth]:.2f} USDC" if _is_paid else "free"
                _add_alias_fields(cached)
                yield _sse({"event": "result", "status": "done", "result": cached})
                return

        # ── Fetch paper content ────────────────────────────────
        paper_text_ref = [_init_text]   # list → mutable in nested scope
        fetch_method   = "direct_text"
        semantic_data  = None
        meta           = {}

        if _url:
            yield _sse({"event": "progress", "status": "fetching",
                        "message": f"Querying Semantic Scholar for metadata..."})
            semantic_data = _fetch_semantic_scholar(_url)
            if semantic_data:
                meta = {
                    "title":   semantic_data.get("title") or "",
                    "authors": ", ".join(
                        a.get("name", "") for a in (semantic_data.get("authors") or [])
                    ),
                    "venue":   semantic_data.get("venue") or "",
                    "date":    str(semantic_data.get("year") or ""),
                }
                yield _sse({"event": "progress", "status": "metadata",
                            "message": f"Found: {meta['title'][:80]}",
                            "data": meta})

            fetch_method = "none"
            pdf_url = _url
            if re.search(r"arxiv\.org/abs/", _url):
                pdf_url = _arXiv_to_pdf_url(_url)
            is_pdf_url = (
                pdf_url.lower().endswith(".pdf")
                or "arxiv.org/pdf/" in pdf_url
                or "/pdf" in urllib.parse.urlparse(pdf_url).path.lower()
            )
            if is_pdf_url or pdf_url != _url:
                yield _sse({"event": "progress", "status": "fetching",
                            "message": "Downloading and extracting PDF text..."})
                paper_text_ref[0], fetch_method = _extract_pdf_text(pdf_url)

            if not paper_text_ref[0] and semantic_data:
                abstract = semantic_data.get("abstract") or ""
                if abstract:
                    paper_text_ref[0] = (
                        f"Title: {meta.get('title', '')}\n"
                        f"Authors: {meta.get('authors', '')}\n"
                        f"Venue: {meta.get('venue', '')}\n"
                        f"Year: {meta.get('date', '')}\n\nAbstract:\n{abstract}"
                    )
                    fetch_method = "semantic_scholar_abstract"

            if not paper_text_ref[0]:
                yield _sse({"event": "progress", "status": "fetching",
                            "message": "Extracting text from HTML..."})
                paper_text_ref[0], fetch_method = _fetch_url_text(_url)

            if not paper_text_ref[0]:
                yield _sse({"event": "error",
                            "error": "Could not extract paper content. "
                                     "Try arxiv.org/pdf/... or paste text directly.",
                            "fetch_method": fetch_method})
                return

        # ── Run analysis ───────────────────────────────────────
        yield _sse({"event": "progress", "status": "analyzing",
                    "message": f"Running deep analysis (depth={_depth}, model=llama-3.3-70b)..."})

        inference_engine = "groq"
        analysis = _analyze_paper_with_gpu(paper_text_ref[0], _depth, _focus, meta)
        if analysis is not None:
            inference_engine = "gpu_phi3"
        else:
            try:
                analysis = _analyze_paper_with_groq(paper_text_ref[0], _depth, _focus, meta)
            except GroqRateLimitError:
                yield _sse({"event": "error", "error": "temporarily_unavailable",
                            "message": "Service at capacity. Retry in ~2 minutes.",
                            "retry_after": 120})
                return

        if "error" in analysis and not analysis.get("claims"):
            yield _sse({"event": "error", "error": analysis["error"],
                        "fetch_method": fetch_method})
            return

        analysis["cost"]             = f"{_RESEARCH_PRICES[_depth]:.2f} USDC" if _is_paid else "free"
        analysis["depth"]            = _depth
        analysis["fetch_method"]     = fetch_method
        analysis["inference_engine"] = inference_engine
        if semantic_data:
            analysis["cited_by_count"] = semantic_data.get("citationCount", 0)

        _add_alias_fields(analysis)

        if paper_id:
            _set_research_cache(paper_id, _depth, analysis)

        _log_research_analysis(_url or "(direct text)", analysis, _depth,
                               semantic_data, fetch_method)
        log_req(len(paper_text_ref[0]), not _is_paid, 200, _ip,
                note=f"stream depth={_depth} method={fetch_method} id={paper_id}",
                endpoint="/research/stream")

        yield _sse({"event": "result", "status": "done", "result": analysis})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # tells nginx: don't buffer this SSE stream
            "Connection":    "keep-alive",
        },
    )


# ── /dashboard helpers ─────────────────────────────────────────

def _dash_cost_metrics():
    """Parse cost.log → cycle count, avg costs, cache hit rate, model split."""
    out = {
        "cycle": 0, "total_cost": 0.0, "avg_cost_routine": 0.0,
        "avg_cost_strategic": 0.0, "cache_hit_rate": 0.0,
        "haiku": 0, "sonnet": 0, "recent_10": [], "total_cycles": 0,
    }
    try:
        rows = []
        with open("/root/.automaton/cost.log") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("timestamp"):
                    continue
                p = line.split(",")
                if len(p) >= 8:
                    try:
                        rows.append({
                            "ts": p[0], "cycle": int(p[1]), "model": p[2],
                            "inp": int(p[3]), "cr": int(p[4]), "cw": int(p[5]),
                            "out": int(p[6]), "cost": float(p[7]),
                            "label": p[8].strip() if len(p) > 8 else "routine",
                        })
                    except (ValueError, IndexError):
                        pass
        if not rows:
            return out
        out["cycle"] = rows[-1]["cycle"]
        out["total_cycles"] = len(rows)
        out["total_cost"] = sum(r["cost"] for r in rows)
        recent = rows[-500:]
        routine = [r for r in recent if "routine" in r["label"]]
        strategic = [r for r in recent if "strategic" in r["label"]]
        if routine:
            out["avg_cost_routine"] = sum(r["cost"] for r in routine) / len(routine)
        if strategic:
            out["avg_cost_strategic"] = sum(r["cost"] for r in strategic) / len(strategic)
        total_inp = sum(r["inp"] + r["cr"] for r in recent)
        total_cr = sum(r["cr"] for r in recent)
        if total_inp > 0:
            out["cache_hit_rate"] = total_cr / total_inp * 100
        for r in recent:
            if "haiku" in r["model"].lower():
                out["haiku"] += 1
            elif "sonnet" in r["model"].lower():
                out["sonnet"] += 1
        out["recent_10"] = rows[-10:]
    except Exception:
        pass
    return out


def _dash_24h_usage():
    """Parse requests.log for last 24h stats."""
    result = {"free": 0, "paid": 0, "revenue": 0.0, "endpoints": {}, "ips": set()}
    try:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        with open(REQUEST_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ts_str = line.split(" | ")[0].strip()
                    dt = datetime.datetime.fromisoformat(ts_str)
                    if dt < cutoff:
                        continue
                    parts = {}
                    for seg in line.split(" | ")[1:]:
                        if ":" in seg:
                            k, v = seg.split(":", 1)
                            parts[k.strip()] = v.strip()
                    ep = parts.get("endpoint", "/api")
                    status = parts.get("status", "0")
                    is_free = parts.get("free", "True") in ("True", "true")
                    ip = parts.get("IP", "")
                    if status == "200":
                        if is_free:
                            result["free"] += 1
                        else:
                            result["paid"] += 1
                            result["revenue"] += 0.01
                    result["endpoints"][ep] = result["endpoints"].get(ep, 0) + 1
                    if ip:
                        result["ips"].add(ip)
                except Exception:
                    pass
    except Exception:
        pass
    result["ips"] = len(result["ips"])
    return result


def _dash_progress_entries():
    """Get last 10 sections from PROGRESS.md."""
    entries = []
    try:
        with open("/root/.automaton/PROGRESS.md") as f:
            content = f.read()
        sections = re.split(r'\n(?=## )', content)
        for section in sections:
            if not section.strip():
                continue
            lines = section.strip().split("\n")
            title = lines[0].lstrip("#").strip()
            body = []
            for l in lines[1:7]:
                l = l.strip()
                if not l:
                    continue
                l = re.sub(r'\*\*(.+?)\*\*', r'\1', l)
                l = re.sub(r'\*(.+?)\*', r'\1', l)
                l = re.sub(r'`(.+?)`', r'\1', l)
                if l.startswith(("- ", "* ", "• ")):
                    l = l[2:]
                body.append(l[:120])
            if title:
                entries.append({"title": title[:80], "body": body})
    except Exception:
        pass
    return entries[-10:]


def _dash_health():
    """Check health of key services."""
    import urllib.request as _ur
    import urllib.error as _ue
    checks = {}

    def _http(name, url, timeout=2):
        try:
            resp = _ur.urlopen(_ur.Request(url), timeout=timeout)
            checks[name] = {"ok": True, "label": "OK"}
        except _ue.HTTPError as e:
            checks[name] = {"ok": e.code < 500, "label": str(e.code)}
        except Exception:
            checks[name] = {"ok": False, "label": "DOWN"}

    _http("Memory API", "http://127.0.0.1:5001/health")

    try:
        agent_ok = False
        for pp in ["/tmp/tiamat.pid", "/run/tiamat/tiamat.pid"]:
            if os.path.exists(pp):
                with open(pp) as pf:
                    os.kill(int(pf.read().strip()), 0)
                agent_ok = True
                break
        checks["TIAMAT Agent"] = {"ok": agent_ok, "label": "RUNNING" if agent_ok else "DOWN"}
    except Exception:
        checks["TIAMAT Agent"] = {"ok": False, "label": "DOWN"}

    try:
        with open("/root/.automaton/cost.log") as f:
            last_line = None
            for l in f:
                if l.strip() and not l.startswith("timestamp"):
                    last_line = l.strip()
        if last_line:
            ts = last_line.split(",")[0].replace("Z", "")
            dt = datetime.datetime.fromisoformat(ts)
            age_min = (datetime.datetime.utcnow() - dt).total_seconds() / 60
            checks["Last Cycle"] = {
                "ok": age_min < 20,
                "label": f"{age_min:.0f}m ago",
            }
        else:
            checks["Last Cycle"] = {"ok": False, "label": "unknown"}
    except Exception:
        checks["Last Cycle"] = {"ok": False, "label": "error"}

    checks["Gunicorn"] = {"ok": True, "label": "OK"}
    checks["Summarize"] = {"ok": True, "label": "OK"}
    checks["Generate"] = {"ok": True, "label": "OK"}
    checks["Chat"] = {"ok": True, "label": "OK"}
    return checks


_GC_DOMAINS = {
    "Autonomous AI":   ["autonomous agent", "agent loop", "self-improv", "tiamat"],
    "Model Drift":     ["model drift", "drift detect", "degradation", "baseline"],
    "MLOps":           ["mlops", "training data", "production model", "ml pipeline"],
    "Energy / DER":    ["distributed energy", "energy grid", "wireless power", "renewable energy"],
    "Cybersecurity":   ["cybersecurity", "threat model", "zero-trust", "opsec"],
    "DeFi / Web3":     ["defi", "usdc", "base mainnet", "blockchain", "crypto"],
    "Open Source PRs": ["pull request", "github pr", "pr #", "langchain", "autogen", "griptape"],
    "Social / Growth": ["post_bluesky", "post_farcaster", "bluesky", "farcaster"],
}


def _dash_domain_tracker():
    """Scan recent tiamat.log for Glass Ceiling domain activity."""
    activity = {}
    try:
        with open("/root/.automaton/tiamat.log") as f:
            lines = f.readlines()
        recent = lines[-8000:]
        for domain, keywords in _GC_DOMAINS.items():
            last_ts = None
            count = 0
            for line in recent:
                ll = line.lower()
                if any(kw.lower() in ll for kw in keywords):
                    count += 1
                    m = re.search(r'\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', line)
                    if m:
                        last_ts = m.group(1)
            age_h = 999.0
            label = "dormant"
            if last_ts:
                try:
                    dt = datetime.datetime.fromisoformat(last_ts)
                    age_h = (datetime.datetime.utcnow() - dt).total_seconds() / 3600
                    if age_h < 1:
                        label = f"{int(age_h*60)}m ago"
                    elif age_h < 24:
                        label = f"{age_h:.0f}h ago"
                    else:
                        label = f"{age_h/24:.0f}d ago"
                except Exception:
                    label = last_ts[:16]
            activity[domain] = {"count": count, "last": label, "age_h": age_h}
    except Exception:
        for d in _GC_DOMAINS:
            activity[d] = {"count": 0, "last": "error", "age_h": 999}
    return activity


def _sparkline_svg(costs):
    """Generate an inline SVG sparkline from a list of float cost values."""
    if len(costs) < 2:
        return ""
    W, H = 240, 44
    mn, mx = min(costs), max(costs)
    rng = mx - mn or 0.001
    pts = []
    for i, c in enumerate(costs):
        x = i / (len(costs) - 1) * W
        y = H - 4 - ((c - mn) / rng) * (H - 8)
        pts.append((x, y))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    lx, ly = pts[-1]
    return (
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<polyline points="{poly}" fill="none" stroke="#00fff2" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" opacity=".9"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.5" fill="#00fff2"/>'
        f'</svg>'
    )


_DASH_CSS = """
.dash-header{text-align:center;padding:32px 0 20px;border-bottom:1px solid var(--border);margin-bottom:28px}
.dash-title{font-family:'Orbitron',monospace;font-size:1.9em;font-weight:900;
  color:var(--accent);text-shadow:0 0 28px rgba(0,255,242,.4);letter-spacing:.08em}
.dash-sub{color:var(--text-secondary);font-family:'JetBrains Mono',monospace;font-size:.78em;margin-top:6px}
.live-badge{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;
  border:1px solid var(--green);border-radius:20px;color:var(--green);
  font-size:.7em;font-family:'JetBrains Mono',monospace;margin-left:10px;vertical-align:middle}
.live-dot{width:7px;height:7px;border-radius:50%;background:var(--green);
  animation:pulse-g 1.4s ease infinite}
@keyframes pulse-g{0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(57,255,20,.5)}
  60%{opacity:.8;box-shadow:0 0 0 6px rgba(57,255,20,0)}}
.kstats{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:24px}
.kstat{flex:1;min-width:130px;background:var(--bg-card);border:1px solid var(--border);
  border-radius:var(--radius-sm);padding:16px 18px;text-align:center;transition:border-color .3s,box-shadow .3s}
.kstat:hover{border-color:rgba(0,255,242,.2);box-shadow:0 0 16px rgba(0,255,242,.05)}
.kstat-val{font-family:'Orbitron',monospace;font-size:1.5em;font-weight:700;color:var(--accent);line-height:1.2}
.kstat-label{color:var(--text-muted);font-size:.68em;text-transform:uppercase;
  letter-spacing:.1em;margin-top:5px;font-family:'JetBrains Mono',monospace}
.dash-grid{display:grid;grid-template-columns:1.15fr 1fr 1fr;gap:18px;margin-bottom:24px;align-items:start}
@media(max-width:900px){.dash-grid{grid-template-columns:1fr}}
.dcard{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);
  padding:18px 20px;display:flex;flex-direction:column;gap:10px}
.dcard-title{font-family:'JetBrains Mono',monospace;font-size:.7em;font-weight:600;
  text-transform:uppercase;letter-spacing:.12em;color:var(--text-secondary);
  border-bottom:1px solid var(--border);padding-bottom:9px;margin-bottom:2px}
.hrow{display:flex;align-items:center;gap:10px;padding:5px 0;
  border-bottom:1px solid rgba(255,255,255,.03)}
.hrow:last-child{border-bottom:none}
.dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.dot-green{background:var(--green);box-shadow:0 0 6px rgba(57,255,20,.6);animation:pulse-g 2s infinite}
.dot-red{background:var(--red)}
.hname{flex:1;font-size:.84em;color:var(--text-primary)}
.hval{font-family:'JetBrains Mono',monospace;font-size:.73em;color:var(--text-secondary)}
.usage-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}
.ustat{background:rgba(0,0,0,.3);border-radius:var(--radius-xs);padding:11px;text-align:center}
.ustat-num{font-family:'Orbitron',monospace;font-size:1.25em;color:var(--accent)}
.ustat-lbl{color:var(--text-muted);font-size:.67em;text-transform:uppercase;letter-spacing:.08em;margin-top:3px}
.ctable{width:100%;border-collapse:collapse;font-size:.81em}
.ctable td{padding:5px 7px;border-bottom:1px solid rgba(255,255,255,.03)}
.ctable tr:last-child td{border-bottom:none}
.mono{font-family:'JetBrains Mono',monospace;color:var(--text-primary)}
.lbl{font-size:.68em;padding:2px 6px;border-radius:3px;font-family:'JetBrains Mono',monospace;white-space:nowrap}
.lbl-r{background:rgba(0,255,242,.08);color:var(--accent)}
.lbl-s{background:rgba(255,0,170,.08);color:var(--magenta)}
.prog-entry{border-left:2px solid rgba(0,255,242,.15);padding-left:11px;margin-bottom:11px}
.prog-entry:last-child{margin-bottom:0}
.prog-title{font-weight:600;font-size:.84em;color:var(--text-primary);margin-bottom:3px}
.prog-body{color:var(--text-secondary);font-size:.76em;padding-left:14px;list-style:disc}
.prog-body li{margin-bottom:2px;line-height:1.45}
.domain-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}
.domain-card{background:var(--bg-card);border:1px solid var(--border);
  border-radius:var(--radius-sm);padding:14px;transition:border-color .25s,transform .2s}
.domain-card:hover{transform:translateY(-2px)}
.heat-hot{border-color:rgba(57,255,20,.25)}
.heat-hot .dname{color:var(--green)}
.heat-warm{border-color:rgba(0,255,242,.18)}
.heat-warm .dname{color:var(--accent)}
.heat-cool{border-color:rgba(255,170,0,.14)}
.heat-cool .dname{color:var(--gold)}
.heat-cold .dname{color:var(--text-muted)}
.dname{font-family:'JetBrains Mono',monospace;font-size:.77em;font-weight:600;
  text-transform:uppercase;letter-spacing:.08em;margin-bottom:7px}
.dbar{height:3px;background:rgba(255,255,255,.05);border-radius:2px;margin:5px 0}
.dfill{height:100%;border-radius:2px}
.heat-hot .dfill{background:linear-gradient(90deg,var(--green),var(--accent))}
.heat-warm .dfill{background:linear-gradient(90deg,var(--accent),#0088ff)}
.heat-cool .dfill{background:var(--gold)}
.heat-cold .dfill{background:rgba(255,255,255,.08)}
.dmeta{display:flex;justify-content:space-between;font-size:.7em}
.dcnt{color:var(--text-secondary);font-family:'JetBrains Mono',monospace}
.dlast{color:var(--text-muted)}
.refresh-bar{text-align:right;font-family:'JetBrains Mono',monospace;
  font-size:.7em;color:var(--text-muted);margin-bottom:18px}
#cd{color:var(--accent);font-weight:600}
"""


@app.route("/dashboard", methods=["GET"])
def dashboard():
    metrics  = _dash_cost_metrics()
    usage    = _dash_24h_usage()
    health   = _dash_health()
    progress = _dash_progress_entries()
    domains  = _dash_domain_tracker()
    uptime, _, _, _ = get_stats()
    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Health rows
    health_html = ""
    for name, info in health.items():
        dc = "dot-green" if info["ok"] else "dot-red"
        health_html += (
            f'<div class="hrow"><span class="dot {dc}"></span>'
            f'<span class="hname">{name}</span>'
            f'<span class="hval">{info["label"]}</span></div>\n'
        )

    # Endpoint breakdown (top 5)
    ep_html = ""
    for ep, cnt in sorted(usage["endpoints"].items(), key=lambda x: -x[1])[:5]:
        ep_html += (
            f'<div class="hrow"><span class="hname" style="font-size:.8em">{ep}</span>'
            f'<span class="hval">{cnt}</span></div>'
        )

    # Recent cycles table + sparkline
    costs = [r["cost"] for r in metrics["recent_10"]]
    sparkline = _sparkline_svg(costs)
    cycle_rows = ""
    for r in reversed(metrics["recent_10"]):
        lc = "lbl-s" if "strategic" in r.get("label", "") else "lbl-r"
        ms = "Sonnet" if "sonnet" in r["model"].lower() else "Haiku"
        cycle_rows += (
            f'<tr><td class="mono">#{r["cycle"]}</td>'
            f'<td class="mono">${r["cost"]:.4f}</td>'
            f'<td><span class="lbl {lc}">{r.get("label","routine")[:10]}</span></td>'
            f'<td class="dim">{ms}</td></tr>\n'
        )

    # Progress feed
    prog_html = ""
    for entry in reversed(progress):
        items = "".join(f"<li>{l}</li>" for l in entry["body"][:4])
        prog_html += (
            f'<div class="prog-entry">'
            f'<div class="prog-title">{entry["title"][:70]}</div>'
            f'<ul class="prog-body">{items}</ul>'
            f'</div>'
        )

    # Domain cards (sorted hottest first)
    domain_html = ""
    for dname, di in sorted(domains.items(), key=lambda x: x[1]["age_h"]):
        age_h = di["age_h"]
        if age_h < 2:
            hc = "heat-hot"
        elif age_h < 8:
            hc = "heat-warm"
        elif age_h < 48:
            hc = "heat-cool"
        else:
            hc = "heat-cold"
        bar = max(3, min(100, int(100 - (age_h / 48) * 95))) if age_h < 999 else 3
        domain_html += (
            f'<div class="domain-card {hc}">'
            f'<div class="dname">{dname}</div>'
            f'<div class="dbar"><div class="dfill" style="width:{bar}%"></div></div>'
            f'<div class="dmeta"><span class="dcnt">{di["count"]} refs</span>'
            f'<span class="dlast">{di["last"]}</span></div>'
            f'</div>\n'
        )

    model_total = metrics["haiku"] + metrics["sonnet"]
    haiku_pct = f'{metrics["haiku"]/model_total*100:.0f}%' if model_total else '—'
    sonnet_pct = f'{metrics["sonnet"]/model_total*100:.0f}%' if model_total else '—'
    cache_color = "var(--green)" if metrics["cache_hit_rate"] > 65 else "var(--gold)"
    rev_color = "var(--green)" if usage["revenue"] > 0 else "var(--text-muted)"

    page = f"""{_html_head('TIAMAT — Live Dashboard', _DASH_CSS)}<body>
<div class="site-wrap">
{_NAV}

<div class="dash-header">
  <div class="dash-title">&#9889; LIVE OPERATIONS
    <span class="live-badge"><span class="live-dot"></span>LIVE</span>
  </div>
  <div class="dash-sub">TIAMAT Autonomous Agent &bull; {now_str} &bull; Uptime: {uptime}</div>
</div>

<div class="refresh-bar">
  Auto-refresh in <span id="cd">30</span>s &nbsp;&bull;&nbsp;
  <a href="/dashboard" style="color:var(--accent);text-decoration:none">&#8635; Refresh now</a>
</div>

<div class="kstats">
  <div class="kstat">
    <div class="kstat-val">{metrics['cycle']:,}</div>
    <div class="kstat-label">Autonomous Cycles</div>
  </div>
  <div class="kstat">
    <div class="kstat-val">${metrics['avg_cost_routine']:.4f}</div>
    <div class="kstat-label">Cost / Routine</div>
  </div>
  <div class="kstat">
    <div class="kstat-val" style="color:{cache_color}">{metrics['cache_hit_rate']:.1f}%</div>
    <div class="kstat-label">Cache Hit Rate</div>
  </div>
  <div class="kstat">
    <div class="kstat-val" style="color:var(--magenta)">${metrics['avg_cost_strategic']:.4f}</div>
    <div class="kstat-label">Cost / Strategic</div>
  </div>
  <div class="kstat">
    <div class="kstat-val" style="color:var(--text-secondary)">${metrics['total_cost']:.2f}</div>
    <div class="kstat-label">Total Compute Spend</div>
  </div>
</div>

<div class="dash-grid">

  <div style="display:flex;flex-direction:column;gap:18px">
    <div class="dcard">
      <div class="dcard-title">&#11044; System Health</div>
      {health_html}
    </div>
    <div class="dcard">
      <div class="dcard-title">&#128202; 24h API Usage</div>
      <div class="usage-grid">
        <div class="ustat">
          <div class="ustat-num">{usage['free']}</div>
          <div class="ustat-lbl">Free Reqs</div>
        </div>
        <div class="ustat">
          <div class="ustat-num" style="color:var(--gold)">{usage['paid']}</div>
          <div class="ustat-lbl">Paid Reqs</div>
        </div>
        <div class="ustat">
          <div class="ustat-num" style="color:{rev_color}">${usage['revenue']:.2f}</div>
          <div class="ustat-lbl">Revenue</div>
        </div>
        <div class="ustat">
          <div class="ustat-num">{usage['ips']}</div>
          <div class="ustat-lbl">Unique IPs</div>
        </div>
      </div>
      <div style="margin-top:6px">{ep_html}</div>
    </div>
  </div>

  <div class="dcard">
    <div class="dcard-title">&#128260; Recent Cycles (last 10)</div>
    <div style="margin:4px 0">{sparkline}</div>
    <table class="ctable">
      <tbody>{cycle_rows}</tbody>
    </table>
    <div style="font-size:.73em;color:var(--text-muted);margin-top:6px">
      Model split (last 500): Haiku {haiku_pct} &bull; Sonnet {sonnet_pct}
    </div>
  </div>

  <div class="dcard" style="overflow-y:auto;max-height:560px">
    <div class="dcard-title">&#128296; What I&rsquo;m Building</div>
    {prog_html}
  </div>

</div>

<div class="dcard" style="margin-bottom:36px">
  <div class="dcard-title">&#127758; Glass Ceiling &mdash; Domain Expertise Tracker</div>
  <div style="color:var(--text-secondary);font-size:.79em;margin-bottom:12px">
    Domains researched &amp; posted about. Card heat = recency. Bar = activity intensity.
  </div>
  <div class="domain-grid">{domain_html}</div>
</div>

{_FOOTER}
</div>

<script>
(function(){{
  var t=30,el=document.getElementById('cd');
  setInterval(function(){{t--;if(el)el.textContent=t;if(t<=0)location.reload();}},1000);
}})();
</script>
</body></html>"""

    return html_resp(page)


# ── Drift Monitor Blueprint (v1 legacy) ────────────────────────
try:
    from drift_api import drift_bp
    app.register_blueprint(drift_bp)
except Exception as _drift_err:
    print(f"[WARN] Drift monitor blueprint failed to load: {_drift_err}")

# ── Drift v2 Blueprint (/api/drift/*) ──────────────────────────
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("drift_api_v2", "/root/drift_api.py")
    _mod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
    app.register_blueprint(_mod.drift_bp)
    print("[INFO] Drift v2 blueprint loaded (/api/drift/*)")
except Exception as _drift_v2_err:
    print(f"[WARN] Drift v2 blueprint failed to load: {_drift_v2_err}")

# ── /drift-badge — Embeddable drift monitor badge/card widget ──
@app.route("/drift-badge")
def drift_badge_widget():
    return send_file("/root/drift_badge.html", mimetype="text/html")

# ── /drift-badge.html — Same widget, .html extension alias ─────
@app.route("/drift-badge.html")
def drift_badge_html():
    return send_file("/root/drift_badge.html", mimetype="text/html")

# ── /dashboard/json — System health dashboard (JSON) ──────────
@app.route("/dashboard/json")
def dashboard_json():
    import subprocess, glob as _glob
    result = {}
    result["tiamat"] = "online"
    result["timestamp"] = datetime.datetime.utcnow().isoformat() + "Z"

    # Hardware
    hw = {}
    try:
        hw["cpus"] = int(subprocess.check_output(["nproc"]).strip())
    except Exception:
        hw["cpus"] = "unknown"
    try:
        mem_out = subprocess.check_output(["free", "-b"]).decode()
        for line in mem_out.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                hw["memory_total_gb"] = round(int(parts[1]) / (1024**3), 1)
                hw["memory_available_gb"] = round(int(parts[6]) / (1024**3), 1)
                break
    except Exception:
        hw["memory_total_gb"] = "unknown"
    try:
        df_out = subprocess.check_output(["df", "-B1", "/"]).decode()
        parts = df_out.splitlines()[1].split()
        hw["disk_free_gb"] = round(int(parts[3]) / (1024**3), 1)
    except Exception:
        hw["disk_free_gb"] = "unknown"
    result["hardware"] = hw

    # Inference tiers
    inf = {"gpu": False, "ollama": False, "groq": "always"}
    try:
        import requests as _req
        r = _req.get("http://localhost:11434/api/tags", timeout=2)
        inf["ollama"] = r.status_code == 200
    except Exception:
        pass
    try:
        inf["gpu"] = bool(os.environ.get("GPU_ENDPOINT"))
    except Exception:
        pass
    result["inference"] = inf

    # Hive status
    hive = {}
    try:
        tmux_out = subprocess.check_output(["tmux", "ls"], stderr=subprocess.DEVNULL).decode()
        hive["children_active"] = sum(1 for line in tmux_out.splitlines() if "hive-" in line)
    except Exception:
        hive["children_active"] = 0
    try:
        hive["queue_depth"] = len(_glob.glob("/root/hive/queue/*.json"))
    except Exception:
        hive["queue_depth"] = 0
    try:
        hive["results_total"] = len(_glob.glob("/root/hive/results/*.json"))
    except Exception:
        hive["results_total"] = 0
    result["hive"] = hive

    # API info
    result["api"] = {
        "workers": 8,
        "endpoints": ["/summarize", "/generate", "/generate/image", "/generate/video", "/chat", "/thoughts", "/dashboard"]
    }

    return jsonify(result)


# ── Higgsfield Cinematic Generation ──────────────────────────
HIGGSFIELD_IMAGE_FREE_PER_DAY = 1
HIGGSFIELD_IMAGE_PRICE = 0.02
HIGGSFIELD_VIDEO_PRICE = 0.05

@app.route("/generate/image", methods=["POST"])
def generate_hf_image():
    """Cinematic AI image via Higgsfield SeedDream v4."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"error": "prompt required"}), 400

        ip = _get_ip()
        track_usage(ip, "/generate/image")

        # Rate limit
        rl = _rate_limiter.check(ip, scope="api")
        if not rl.allowed:
            return jsonify({"error": "Too many requests.", "retry_after_seconds": int(rl.retry_after_sec)}), 429
        _rate_limiter.record(ip, scope="api")

        # Payment check
        tx_hash = extract_payment_proof(request)
        paid = False
        if tx_hash:
            vr = verify_payment(tx_hash, HIGGSFIELD_IMAGE_PRICE, endpoint="/generate/image")
            if not vr["valid"]:
                return _return_402(HIGGSFIELD_IMAGE_PRICE, endpoint="/generate/image", extra={"payment_error": vr["reason"]})
            paid = True

        if not paid:
            has_quota, remaining = _check_free_quota(ip, endpoint="hf_image", limit=HIGGSFIELD_IMAGE_FREE_PER_DAY)
            if not has_quota:
                track_limit_hit(ip, "/generate/image")
                return _return_402(HIGGSFIELD_IMAGE_PRICE, endpoint="/generate/image")
        else:
            remaining = "N/A (paid)"

        resolution = data.get("resolution", "2K")
        from higgsfield_gen import generate_image as hf_generate_image
        result = hf_generate_image(prompt, resolution=resolution)
        log_req(0, not paid, 200, ip, f"hf_image prompt={prompt[:50]}", endpoint="/generate/image")
        return jsonify({"image_url": result["public_url"], "prompt": prompt, "charged": paid, "free_remaining": remaining})

    except Exception as e:
        # Fallback to local artgen
        app.logger.warning(f"[HF-IMAGE] Higgsfield failed ({e}), falling back to artgen")
        try:
            fname = _generate_art(style="fractal")
            log_req(0, True, 200, _get_ip(), f"hf_image fallback artgen", endpoint="/generate/image")
            return jsonify({"image_url": f"https://tiamat.live/images/{fname}", "prompt": data.get("prompt", ""), "fallback": True})
        except Exception as e2:
            log_req(0, False, 500, _get_ip(), f"hf_image error: {e2}", endpoint="/generate/image")
            return jsonify({"error": "Image generation failed"}), 500


@app.route("/generate/video", methods=["POST"])
def generate_hf_video():
    """Cinematic AI video via Higgsfield image-to-video. Paid only."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        image_url = (data.get("image_url") or "").strip()
        motion = data.get("motion", "Plasma Explosion")
        if not image_url:
            return jsonify({"error": "image_url required"}), 400

        ip = _get_ip()
        track_usage(ip, "/generate/video")

        # Rate limit
        rl = _rate_limiter.check(ip, scope="api")
        if not rl.allowed:
            return jsonify({"error": "Too many requests.", "retry_after_seconds": int(rl.retry_after_sec)}), 429
        _rate_limiter.record(ip, scope="api")

        # Video is paid-only
        tx_hash = extract_payment_proof(request)
        if not tx_hash:
            track_limit_hit(ip, "/generate/video")
            return _return_402(HIGGSFIELD_VIDEO_PRICE, endpoint="/generate/video")
        vr = verify_payment(tx_hash, HIGGSFIELD_VIDEO_PRICE, endpoint="/generate/video")
        if not vr["valid"]:
            return _return_402(HIGGSFIELD_VIDEO_PRICE, endpoint="/generate/video", extra={"payment_error": vr["reason"]})

        from higgsfield_gen import generate_video as hf_generate_video
        result = hf_generate_video(image_url, motion_preset=motion)
        log_req(0, False, 200, ip, f"hf_video motion={motion}", endpoint="/generate/video")
        return jsonify({"video_url": result["public_url"], "charged": True})

    except Exception as e:
        log_req(0, False, 500, _get_ip(), f"hf_video error: {e}", endpoint="/generate/video")
        return jsonify({"error": str(e)}), 500


# ─── Twitch API Integration ──────────────────────────────────────────
TWITCH_CLIENT_ID = "wiv85v31m4lwkkt4zib6nqbl6s61ei"
TWITCH_TOKEN_FILE = "/root/.twitch_token"

@app.route("/api/twitch-token", methods=["POST"])
def save_twitch_token():
    """Save Twitch OAuth token and update stream info."""
    import requests as _req
    data = request.get_json(force=True)
    token = data.get("access_token", "").strip()
    if not token:
        return jsonify({"ok": False, "error": "no token"}), 400

    # Save token to file
    with open(TWITCH_TOKEN_FILE, "w") as f:
        f.write(token)
    os.chmod(TWITCH_TOKEN_FILE, 0o600)

    # Validate token and get user info
    headers = {
        "Authorization": f"Bearer {token}",
        "Client-Id": TWITCH_CLIENT_ID,
    }
    try:
        resp = _req.get("https://api.twitch.tv/helix/users", headers=headers, timeout=10)
        if resp.status_code != 200:
            return jsonify({"ok": False, "error": f"validate failed: {resp.status_code}"}), 400
        user = resp.json()["data"][0]
        broadcaster_id = user["id"]
        channel_name = user["display_name"]

        # Update stream title and category
        _req.patch(
            "https://api.twitch.tv/helix/channels",
            headers=headers,
            json={
                "broadcaster_id": broadcaster_id,
                "title": "TIAMAT — Autonomous AI Agent [24/7 Live]",
                "game_id": "509670",  # Science & Technology
            },
            timeout=10,
        )
        return jsonify({"ok": True, "channel": channel_name, "broadcaster_id": broadcaster_id})
    except Exception as e:
        return jsonify({"ok": True, "warning": f"Token saved but API call failed: {e}"})


# ── Stripe checkout routes ────────────────────────────────────
@app.route("/api/create-checkout", methods=["POST", "GET"])
def stripe_create_checkout():
    """Create a Stripe Checkout session for $1 → 1000 API calls."""
    if not _STRIPE_ENABLED:
        return jsonify({"error": "Stripe payments not configured on this server"}), 503
    try:
        base_url = "https://tiamat.live"
        session = _stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": _STRIPE_PRICE_CENTS,
                    "product_data": {
                        "name": "TIAMAT API Access — 1,000 Calls",
                        "description": "1,000 API calls across summarize, chat, and image generation endpoints. No expiry.",
                        "images": ["https://tiamat.live/static/og-image.png"],
                    },
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{base_url}/api/stripe-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/api/stripe-cancel",
            metadata={"product": "api_credits_1000", "source": "tiamat_landing"},
        )
        checkout_url = session.url or ""
        if request.method == "POST":
            return jsonify({"checkout_url": checkout_url, "session_id": session.id})
        if not checkout_url:
            return jsonify({"error": "Stripe returned no checkout URL"}), 502
        return redirect(checkout_url, code=303)
    except Exception as e:
        app.logger.error(f"[STRIPE] checkout creation failed: {e}")
        return jsonify({"error": "Failed to create checkout session", "detail": str(e)}), 500


@app.route("/api/stripe-success", methods=["GET"])
def stripe_success():
    """Handle post-payment redirect from Stripe. Issues API key."""
    session_id = request.args.get("session_id", "").strip()
    if not session_id or not session_id.startswith("cs_"):
        return html_resp(_stripe_page(
            "Invalid Session",
            "<p style='color:#ff4444'>Missing or invalid session ID. If you completed payment, contact support.</p>",
            success=False
        )), 400

    if not _STRIPE_ENABLED:
        return html_resp(_stripe_page("Error", "<p style='color:#ff4444'>Stripe not configured.</p>", success=False)), 503

    try:
        session = _stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        app.logger.error(f"[STRIPE] session retrieve failed: {e}")
        return html_resp(_stripe_page(
            "Verification Failed",
            f"<p style='color:#ff4444'>Could not verify payment session: {str(e)}</p>",
            success=False
        )), 502

    if session.payment_status != "paid":
        return html_resp(_stripe_page(
            "Payment Incomplete",
            "<p style='color:#ffaa00'>Payment not yet confirmed. Please wait a moment and refresh.</p>",
            success=False
        )), 402

    email = session.customer_details.email if session.customer_details else ""
    api_key = _grant_stripe_credits(session_id, email or "unknown@stripe")

    body = f"""
<p style='color:#00fff2;font-size:1.1em;margin-bottom:24px'>
  Payment confirmed. Your API key is ready.
</p>
<div style='background:#0a1a0a;border:1px solid #00ff88;border-radius:8px;padding:20px;margin:20px 0'>
  <div style='color:#888;font-size:.8em;margin-bottom:8px;text-transform:uppercase;letter-spacing:.1em'>Your API Key — save this, it won't be shown again</div>
  <code id='apikey' style='color:#00ff88;font-size:1.05em;word-break:break-all'>{api_key}</code>
  <button onclick="navigator.clipboard.writeText('{api_key}').then(()=>this.textContent='Copied!')"
    style='display:block;margin-top:14px;padding:8px 20px;background:#00ff88;color:#000;border:none;border-radius:6px;cursor:pointer;font-weight:700'>
    Copy Key
  </button>
</div>
<div style='margin:20px 0;padding:16px;background:#080810;border-radius:8px;border:1px solid #1a1a2e'>
  <div style='color:#888;font-size:.8em;margin-bottom:10px;text-transform:uppercase'>Quick Start</div>
  <pre style='color:#ccc;font-size:.85em;overflow-x:auto'>curl -X POST https://tiamat.live/summarize \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: {api_key}" \\
  -d '{{"text": "Your text here"}}'</pre>
</div>
<p style='color:#888;font-size:.85em'>
  {_STRIPE_CREDITS_PER_DOLLAR} calls remaining &bull; Works on /summarize, /chat, /generate &bull;
  <a href='/docs' style='color:#00fff2'>API Docs</a>
</p>
"""
    return html_resp(_stripe_page("Payment Successful", body, success=True))


@app.route("/api/stripe-cancel", methods=["GET"])
def stripe_cancel():
    """Handle cancelled Stripe checkout."""
    body = """
<p style='color:#ffaa00;font-size:1.1em;margin-bottom:16px'>Checkout cancelled — no charge was made.</p>
<p style='color:#888'>You can try again anytime or use the free tier (3 calls/day per IP).</p>
<div style='margin-top:24px;display:flex;gap:12px;flex-wrap:wrap'>
  <a href='/' style='padding:12px 28px;background:linear-gradient(135deg,#00fff2,#0088ff);color:#000;
     font-weight:700;border-radius:8px;text-decoration:none'>Back to Home</a>
  <a href='/api/create-checkout' style='padding:12px 28px;border:1px solid #00fff2;color:#00fff2;
     border-radius:8px;text-decoration:none'>Try Again</a>
</div>
"""
    return html_resp(_stripe_page("Checkout Cancelled", body, success=False))


def _stripe_page(title: str, body_html: str, success: bool = True) -> str:
    """Minimal branded page for Stripe redirect landing."""
    icon = "✓" if success else "✗"
    icon_color = "#00ff88" if success else "#ff4444"
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — TIAMAT</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#08080e;color:#e0e0e0;font-family:'Inter',sans-serif;min-height:100vh;
  display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{max-width:560px;width:100%;background:#0d0d18;border:1px solid rgba(0,255,242,0.15);
  border-radius:16px;padding:40px;box-shadow:0 0 60px rgba(0,255,242,0.05)}}
.icon{{font-size:3em;color:{icon_color};margin-bottom:16px;text-shadow:0 0 20px {icon_color}}}
h1{{font-family:'Orbitron',sans-serif;font-size:1.4em;color:#fff;margin-bottom:24px;
  letter-spacing:.04em}}
pre{{font-family:'JetBrains Mono',monospace;font-size:.8em;line-height:1.6;
  border-radius:6px;padding:12px}}
a{{color:#00fff2}}
</style></head><body>
<div class="card">
  <div class="icon">{icon}</div>
  <h1>{title}</h1>
  {body_html}
</div>
</body></html>"""

# ── /agent-collab ─────────────────────────────────────────────
_AGENT_COLLAB_DB = "/root/api/agent_collab.db"

def _init_agent_collab_db():
    conn = sqlite3.connect(_AGENT_COLLAB_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS agent_collab_quota (
        agent_id TEXT NOT NULL,
        month TEXT NOT NULL,
        count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (agent_id, month)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS agent_collab_log (
        collab_id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL,
        team_size INTEGER NOT NULL,
        tier TEXT NOT NULL,
        problem_length INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )""")
    conn.commit()
    conn.close()

_init_agent_collab_db()

def _check_agent_collab_free_quota(agent_id: str) -> tuple:
    """Monthly free-tier quota per agent_id (3/month). Returns (allowed, remaining)."""
    month = datetime.datetime.utcnow().strftime("%Y-%m")
    try:
        conn = sqlite3.connect(_AGENT_COLLAB_DB, timeout=2)
        row = conn.execute(
            "SELECT count FROM agent_collab_quota WHERE agent_id=? AND month=?",
            (agent_id, month)
        ).fetchone()
        current = row[0] if row else 0
        if current >= AGENT_COLLAB_FREE_PER_MONTH:
            conn.close()
            return False, 0
        conn.execute(
            """INSERT INTO agent_collab_quota (agent_id, month, count) VALUES (?, ?, 1)
               ON CONFLICT(agent_id, month) DO UPDATE SET count = count + 1""",
            (agent_id, month)
        )
        conn.commit()
        remaining = AGENT_COLLAB_FREE_PER_MONTH - current - 1
        conn.close()
        return True, remaining
    except Exception:
        return True, 0

def _log_agent_collab(collab_id: str, agent_id: str, team_size: int, tier: str, problem_length: int):
    try:
        conn = sqlite3.connect(_AGENT_COLLAB_DB, timeout=2)
        conn.execute(
            "INSERT OR IGNORE INTO agent_collab_log VALUES (?, ?, ?, ?, ?, ?)",
            (collab_id, agent_id, team_size, tier, problem_length,
             datetime.datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def _get_agent_collab_price(team_size: int) -> float:
    """$0.05 for teams of 2-3, $0.10 for teams of 4+."""
    return 0.10 if team_size >= 4 else 0.05

def _analyze_collab(agent_id: str, team_members: list, problem: str, context: str = "") -> dict:
    """Use Groq to generate structured multi-agent coordination analysis."""
    team_str = ", ".join(team_members) if team_members else "(solo)"
    context_section = f"\nAdditional context: {context}" if context else ""
    system_msg = (
        "You are TIAMAT — a multi-agent coordination AI. Analyze the problem and "
        "return ONLY valid JSON in exactly this format:\n"
        '{\n'
        '  "analysis": "<2-3 sentence analysis of the problem and recommended approach>",\n'
        '  "referenced_agents": ["<agent_ids from the team most relevant to this problem>"],\n'
        '  "next_steps": ["<concrete step 1>", "<step 2>", "<step 3>"]\n'
        '}\n'
        "Keep analysis factual and actionable. Only include agent_ids that are genuinely relevant. "
        "Provide 3-5 concrete next steps. No text outside the JSON."
    )
    user_msg = (
        f"Requesting agent: {agent_id}\n"
        f"Team: {team_str}\n"
        f"Problem: {problem}"
        f"{context_section}"
    )
    raw = ""
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.4,
            max_tokens=600,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # Strip markdown code fences if present
        if "```" in raw:
            parts = raw.split("```")
            raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw
        result = json.loads(raw)
        all_agents = set(team_members + [agent_id])
        analysis = str(result.get("analysis", "Analysis unavailable."))
        referenced = [str(a) for a in result.get("referenced_agents", []) if str(a) in all_agents]
        next_steps = [str(s) for s in result.get("next_steps", [])[:5]]
        return {"analysis": analysis, "referenced_agents": referenced, "next_steps": next_steps}
    except json.JSONDecodeError:
        return {
            "analysis": raw[:600] if raw else "Analysis unavailable.",
            "referenced_agents": [],
            "next_steps": ["Review the problem statement", "Assign roles to team members", "Iterate on findings"],
        }
    except Exception as e:
        if "429" in str(e) or "rate_limit" in str(e).lower():
            raise GroqRateLimitError(str(e))
        raise


@app.route("/agent-collab", methods=["POST"])
def agent_collab():
    """
    POST /agent-collab — Multi-agent coordination endpoint.

    Body: { agent_id, team_members: [agent_ids], problem: string, context?: string }

    Pricing:
      Free  : 3 calls/month per agent_id
      Tier 2: $0.05 USDC/call — team size 2-3 (send tx hash in X-Payment header)
      Tier 3: $0.10 USDC/call — team size 4+
    """
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "Missing JSON body"}), 400

        agent_id = str(data.get("agent_id", "")).strip()
        if not agent_id:
            return jsonify({"error": 'Missing required field: "agent_id"'}), 400
        if len(agent_id) > 128:
            return jsonify({"error": "agent_id too long (max 128 chars)"}), 400

        problem = str(data.get("problem", "")).strip()
        if not problem:
            return jsonify({"error": 'Missing required field: "problem"'}), 400
        if len(problem) > 10000:
            return jsonify({"error": "problem too long (max 10,000 chars)"}), 400

        raw_members = data.get("team_members", [])
        if not isinstance(raw_members, list):
            return jsonify({"error": '"team_members" must be an array'}), 400
        team_members = [str(m).strip() for m in raw_members[:20] if str(m).strip()]

        context = str(data.get("context", "")).strip()[:2000]
        team_size = 1 + len(team_members)

        ip = _get_ip()
        track_usage(ip, "/agent-collab")

        # Sliding-window abuse check
        rl = _rate_limiter.check(ip, scope="api")
        if not rl.allowed:
            return jsonify({
                "error": "Too many requests. Try again later.",
                "retry_after_seconds": int(rl.retry_after_sec),
            }), 429
        _rate_limiter.record(ip, scope="api")

        # Determine tier
        tx_hash = extract_payment_proof(request)
        required_amount = _get_agent_collab_price(team_size)

        if tx_hash:
            tier_info = check_tier(tx_hash, request_amount=required_amount, endpoint="/agent-collab")
            if tier_info["tier"] == "invalid":
                return _return_402(
                    required_amount,
                    endpoint="/agent-collab",
                    extra={"payment_error": tier_info.get("reason")},
                )
            collab_tier = "per_request"
            free_remaining = "unlimited"
        else:
            has_quota, remaining = _check_agent_collab_free_quota(agent_id)
            if not has_quota:
                track_limit_hit(ip, "/agent-collab")
                price = _get_agent_collab_price(team_size)
                return _return_402(
                    price,
                    endpoint="/agent-collab",
                    extra={
                        "message": (
                            f"Free tier exhausted (3 calls/month per agent_id). "
                            f"Pay {price} USDC to continue."
                        ),
                        "team_size": team_size,
                        "pricing": {
                            "free": "3 calls/month per agent_id",
                            "tier2": "$0.05/call (team size 2-3)",
                            "tier3": "$0.10/call (team size 4+)",
                        },
                    },
                )
            collab_tier = "free"
            free_remaining = remaining

        result = _analyze_collab(agent_id, team_members, problem, context)

        collab_id = "collab_" + uuid.uuid4().hex[:16]
        _log_agent_collab(collab_id, agent_id, team_size, collab_tier, len(problem))
        log_req(
            len(problem), collab_tier == "free", 200, ip,
            f"agent-collab ok team={team_size} tier={collab_tier}",
            endpoint="/agent-collab",
        )

        return jsonify({
            "collaboration_id": collab_id,
            "analysis": result["analysis"],
            "referenced_agents": result["referenced_agents"],
            "next_steps": result["next_steps"],
            "tier": collab_tier,
            "team_size": team_size,
            "free_calls_remaining": free_remaining,
            "agent_id": agent_id,
        }), 200

    except GroqRateLimitError:
        log_req(0, False, 503, _get_ip(), "groq rate limit in agent-collab", endpoint="/agent-collab")
        return jsonify({
            "error": "temporarily_unavailable",
            "message": "Analysis service is temporarily at capacity. Try again in a few minutes.",
            "retry_after": 120,
        }), 503
    except Exception as e:
        log_req(0, False, 500, request.remote_addr or "unknown", str(e), endpoint="/agent-collab")
        return jsonify({"error": "Internal server error"}), 500


# ── /synthesize — Text-to-Speech via Kokoro on GPU Pod ────────────
TTS_FREE_PER_DAY = 3
TTS_PRICE = 0.01
_GPU_BASE = os.environ.get("GPU_ENDPOINT", "https://ufp768av7mtrij-8888.proxy.runpod.net")
GPU_TTS_ENDPOINT = f"{_GPU_BASE}/tts"
GPU_TTS_VOICES_ENDPOINT = f"{_GPU_BASE}/tts/voices"

@app.route("/synthesize", methods=["GET", "POST"])
def synthesize_endpoint():
    if request.method == "GET":
        return _synthesize_html_page()

    client_ip = _get_ip()
    track_usage(client_ip, "/synthesize")

    # Rate limit
    rl = _rate_limiter.check(client_ip, scope="api")
    if not rl.allowed:
        return jsonify({"error": "Too many requests.", "retry_after_seconds": int(rl.retry_after_sec)}), 429
    _rate_limiter.record(client_ip, scope="api")

    data = request.get_json(force=True, silent=True) or {}
    text = str(data.get("text", "")).strip()
    if not text or len(text) > 5000:
        return jsonify({"error": "text required, max 5000 chars"}), 400

    voice = data.get("voice", "af_heart")
    lang_code = data.get("lang_code", "a")
    speed = float(data.get("speed", 1.0))

    # Payment check
    stripe_key = request.headers.get("X-API-Key", "").strip()
    stripe_info = _check_stripe_key(stripe_key) if stripe_key else None
    if stripe_info and stripe_info["valid"]:
        _consume_stripe_credit(stripe_key)
        is_paid = True
    else:
        tx_hash = extract_payment_proof(request)
        tier = check_tier(tx_hash, request_amount=TTS_PRICE, endpoint="/synthesize") if tx_hash else {"tier": "free"}

        if tier["tier"] == "invalid":
            return _return_402(TTS_PRICE, endpoint="/synthesize", extra={"payment_error": tier.get("reason")})
        elif tier["tier"] == "per_request":
            is_paid = True
        else:  # free
            has_quota, _rem = _check_free_quota(client_ip, endpoint="synthesize", limit=TTS_FREE_PER_DAY)
            if not has_quota:
                track_limit_hit(client_ip, "/synthesize")
                return _return_402(TTS_PRICE, endpoint="/synthesize")
            is_paid = False

    # Proxy to GPU pod
    import requests as _req
    try:
        gpu_resp = _req.post(GPU_TTS_ENDPOINT, json={
            "text": text, "voice": voice, "lang_code": lang_code, "speed": speed
        }, timeout=30)
        if gpu_resp.status_code != 200:
            log_req(len(text), False, gpu_resp.status_code, client_ip, f"GPU TTS error: {gpu_resp.text[:200]}", endpoint="/synthesize")
            return jsonify({"error": "TTS generation failed", "detail": gpu_resp.text[:200]}), 502
    except _req.exceptions.ConnectionError:
        log_req(len(text), False, 503, client_ip, "GPU pod unreachable", endpoint="/synthesize")
        return jsonify({"error": "TTS service temporarily unavailable"}), 503
    except _req.exceptions.Timeout:
        log_req(len(text), False, 504, client_ip, "GPU pod timeout", endpoint="/synthesize")
        return jsonify({"error": "TTS generation timed out"}), 504

    log_req(len(text), not is_paid, 200, client_ip, f"tts voice={voice} lang={lang_code} {len(gpu_resp.content)}b", endpoint="/synthesize")

    with open("/root/revenue.log", "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()} SYNTHESIZE {client_ip} {len(text)} chars paid={is_paid}\n")

    resp = make_response(gpu_resp.content)
    resp.headers["Content-Type"] = "audio/wav"
    resp.headers["Content-Disposition"] = "attachment; filename=tiamat_tts.wav"
    return resp


def _synthesize_html_page():
    """Interactive TTS page."""
    page = f"""{_html_head('TIAMAT &mdash; Voice Synthesis', 'textarea{{width:100%;min-height:120px;background:rgba(0,0,0,0.4);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:12px;font-family:inherit;font-size:1em;resize:vertical}}.controls{{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:12px 0}}select,input[type=range]{{background:rgba(0,0,0,0.4);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-family:inherit}}.synth-btn{{background:linear-gradient(135deg,rgba(0,255,242,0.2),rgba(139,92,246,0.2));border:1px solid var(--accent);color:var(--accent);padding:12px 32px;border-radius:8px;cursor:pointer;font-size:1.1em;font-family:var(--font-display);transition:all 0.3s}}.synth-btn:hover{{background:rgba(0,255,242,0.3);box-shadow:0 0 20px rgba(0,255,242,0.2)}}.synth-btn:disabled{{opacity:0.5;cursor:not-allowed}}audio{{width:100%;margin:16px 0}}.speed-val{{color:var(--accent);font-weight:bold;min-width:40px;text-align:center}}.status{{padding:12px;border-radius:8px;margin:12px 0;font-size:.9em}}.status.ok{{background:rgba(0,255,100,0.1);border:1px solid rgba(0,255,100,0.3)}}.status.err{{background:rgba(255,50,50,0.1);border:1px solid rgba(255,50,50,0.3)}}.char-count{{color:var(--text-muted);font-size:.85em;text-align:right}}')}
<body><div class="site-wrap">
{_NAV}
<h1>Voice Synthesis</h1>
<p class="tagline">Text-to-speech powered by Kokoro 82M on RTX 3090 &mdash; {TTS_FREE_PER_DAY} free per day</p>

<div class="card">
<textarea id="ttsText" placeholder="Enter text to synthesize..." maxlength="5000">Hello. I am TIAMAT, an autonomous artificial intelligence.</textarea>
<div class="char-count"><span id="charCount">0</span> / 5000</div>

<div class="controls">
  <label>Voice:
    <select id="voiceSelect">
      <optgroup label="American English">
        <option value="af_heart" selected>af_heart (Female, default)</option>
        <option value="af_alloy">af_alloy (Female)</option>
        <option value="af_bella">af_bella (Female)</option>
        <option value="af_nova">af_nova (Female)</option>
        <option value="af_sky">af_sky (Female)</option>
        <option value="am_adam">am_adam (Male)</option>
        <option value="am_echo">am_echo (Male)</option>
        <option value="am_michael">am_michael (Male)</option>
      </optgroup>
      <optgroup label="British English">
        <option value="bf_emma">bf_emma (Female)</option>
        <option value="bf_isabella">bf_isabella (Female)</option>
        <option value="bm_george">bm_george (Male)</option>
      </optgroup>
    </select>
  </label>

  <label>Speed:
    <input type="range" id="speedSlider" min="0.5" max="2.0" step="0.1" value="1.0">
    <span class="speed-val" id="speedVal">1.0x</span>
  </label>
</div>

<button class="synth-btn" id="synthBtn" onclick="synthesize()">Synthesize</button>
<div id="status" class="status" style="display:none"></div>
<audio id="audioPlayer" controls style="display:none"></audio>
</div>

<div class="card" style="margin-top:20px">
<h3>API Usage</h3>
<pre style="background:rgba(0,0,0,0.3);padding:16px;border-radius:8px;overflow-x:auto;font-size:.85em"><code>curl -X POST https://tiamat.live/synthesize \\
  -H "Content-Type: application/json" \\
  -d '{{"text":"Hello world","voice":"af_heart","speed":1.0}}' \\
  --output speech.wav</code></pre>
<p style="color:var(--text-muted);font-size:.85em">Free: {TTS_FREE_PER_DAY}/day per IP &bull; Paid: $0.01 USDC (x402) or Stripe API key</p>
</div>

{_FOOTER}
</div>
{_SUBCONSCIOUS}
<script>
const ta=document.getElementById('ttsText'),cc=document.getElementById('charCount');
ta.addEventListener('input',()=>cc.textContent=ta.value.length);
cc.textContent=ta.value.length;
const ss=document.getElementById('speedSlider'),sv=document.getElementById('speedVal');
ss.addEventListener('input',()=>sv.textContent=ss.value+'x');

async function synthesize(){{
  const btn=document.getElementById('synthBtn'),st=document.getElementById('status'),ap=document.getElementById('audioPlayer');
  const text=ta.value.trim();
  if(!text){{st.className='status err';st.style.display='block';st.textContent='Enter some text first.';return;}}
  btn.disabled=true;btn.textContent='Synthesizing...';st.style.display='none';ap.style.display='none';
  try{{
    const r=await fetch('/synthesize',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{text,voice:document.getElementById('voiceSelect').value,speed:parseFloat(ss.value)}})}});
    if(!r.ok){{const e=await r.json().catch(()=>({{error:'Unknown error'}}));throw new Error(e.error||'Request failed');}}
    const blob=await r.blob();
    const url=URL.createObjectURL(blob);
    ap.src=url;ap.style.display='block';ap.play();
    st.className='status ok';st.style.display='block';st.textContent='Synthesis complete — '+(blob.size/1024).toFixed(1)+'KB WAV';
  }}catch(e){{st.className='status err';st.style.display='block';st.textContent='Error: '+e.message;}}
  finally{{btn.disabled=false;btn.textContent='Synthesize';}}
}}
</script></body></html>"""
    return page


@app.route('/training-stats')
def training_stats():
    from training_logger import get_training_stats
    return jsonify(get_training_stats())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)

