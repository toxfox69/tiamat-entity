#!/usr/bin/env python3
"""
TIAMAT Inference Proxy — OpenAI-compatible /v1/chat/completions
Multi-provider cascade: Groq → Cerebras → SambaNova → Gemini
Standalone Flask app on port 5003
"""

import os, time, json, uuid, hashlib, sqlite3, threading
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify, make_response, Response, stream_with_context

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1MB

# ─── Config ──────────────────────────────────────────────────────
DB_PATH = "/root/.automaton/inference_proxy.db"
RATE_LIMIT_FREE = 10   # req/min
RATE_LIMIT_PAID = 100  # req/min

PROVIDERS = [
    {
        "name": "groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key": os.environ.get("GROQ_API_KEY", ""),
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "default": "llama-3.3-70b-versatile",
    },
    {
        "name": "cerebras",
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "key": os.environ.get("CEREBRAS_API_KEY", ""),
        "models": ["llama3.1-70b", "llama3.1-8b"],
        "default": "llama3.1-70b",
    },
    {
        "name": "sambanova",
        "url": "https://api.sambanova.ai/v1/chat/completions",
        "key": os.environ.get("SAMBANOVA_API_KEY", ""),
        "models": ["Meta-Llama-3.3-70B-Instruct"],
        "default": "Meta-Llama-3.3-70B-Instruct",
    },
    {
        "name": "gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key": os.environ.get("GEMINI_API_KEY", ""),
        "models": ["gemini-2.0-flash"],
        "default": "gemini-2.0-flash",
    },
]

# Provider cooldowns (in-memory)
_cooldowns = {}  # provider_name -> cooldown_until timestamp
_cooldown_lock = threading.Lock()

import requests as http_requests

# ─── Database ────────────────────────────────────────────────────
def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS api_keys (
            key TEXT PRIMARY KEY,
            name TEXT,
            tier TEXT DEFAULT 'free',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key TEXT,
            provider TEXT,
            model TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            latency_ms INTEGER DEFAULT 0,
            status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_usage_key_time ON usage_log(api_key, created_at);
        CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_log(created_at);
    """)
    # Migrate: add columns introduced for telemetry dashboard
    for _col, _defn in [
        ("ip",       "TEXT NOT NULL DEFAULT ''"),
        ("paid",     "INTEGER NOT NULL DEFAULT 0"),
        ("failover", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        try:
            db.execute(f"ALTER TABLE usage_log ADD COLUMN {_col} {_defn}")
            db.commit()
        except Exception:
            pass  # column already exists
    # Create a default public key if none exists
    existing = db.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
    if existing == 0:
        pub_key = "tiamat-public-" + hashlib.sha256(b"tiamat-free-tier").hexdigest()[:16]
        db.execute("INSERT INTO api_keys (key, name, tier) VALUES (?, ?, ?)",
                   (pub_key, "Public Free Tier", "free"))
        db.commit()
        print(f"[PROXY] Created default public key: {pub_key}")
    db.close()

# ─── Auth & Rate Limiting ───────────────────────────────────────
def get_api_key_info(key):
    db = get_db()
    row = db.execute("SELECT * FROM api_keys WHERE key = ? AND active = 1", (key,)).fetchone()
    db.close()
    return dict(row) if row else None

def check_rate_limit(api_key, tier):
    limit = RATE_LIMIT_PAID if tier == "paid" else RATE_LIMIT_FREE
    db = get_db()
    count = db.execute(
        "SELECT COUNT(*) FROM usage_log WHERE api_key = ? AND created_at > datetime('now', '-1 minute')",
        (api_key,)
    ).fetchone()[0]
    db.close()
    return count < limit, limit - count

def log_usage(api_key, provider, model, input_tokens, output_tokens, latency_ms, status,
              ip="", paid=False, failover=0):
    """Write one telemetry row. Non-blocking best-effort."""
    try:
        db = get_db()
        db.execute(
            """INSERT INTO usage_log
               (api_key, provider, model, input_tokens, output_tokens,
                latency_ms, status, ip, paid, failover)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (api_key, provider, model, input_tokens, output_tokens,
             latency_ms, status, ip, int(paid), failover),
        )
        db.commit()
        db.close()
    except Exception:
        pass

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = (request.headers.get("X-API-Key") or
               request.headers.get("Authorization", "").replace("Bearer ", "").strip())
        if not key:
            # Anonymous access: free-tier rate limit keyed by IP
            client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
            anon_key = "anon-" + hashlib.md5(client_ip.encode()).hexdigest()[:16]
            ok, _ = check_rate_limit(anon_key, "free")
            if not ok:
                return jsonify({"error": {
                    "message": f"Rate limit exceeded: {RATE_LIMIT_FREE} req/min for anonymous access. Pass X-API-Key for higher limits.",
                    "type": "rate_limit_error",
                }}), 429
            request.api_key = anon_key
            request.api_tier = "free"
            return f(*args, **kwargs)
        info = get_api_key_info(key)
        if not info:
            return jsonify({"error": {"message": "Invalid API key", "type": "auth_error"}}), 401
        ok, remaining = check_rate_limit(key, info["tier"])
        if not ok:
            return jsonify({"error": {"message": f"Rate limit exceeded. Limit: {RATE_LIMIT_PAID if info['tier']=='paid' else RATE_LIMIT_FREE}/min", "type": "rate_limit_error"}}), 429
        request.api_key = key
        request.api_tier = info["tier"]
        return f(*args, **kwargs)
    return decorated

# ─── Cascade Logic ───────────────────────────────────────────────
def is_cooling(provider_name):
    with _cooldown_lock:
        until = _cooldowns.get(provider_name, 0)
        if time.time() >= until:
            _cooldowns.pop(provider_name, None)
            return False
        return True

def set_cooldown(provider_name, seconds=60):
    with _cooldown_lock:
        _cooldowns[provider_name] = time.time() + seconds

def cascade_chat(messages, model=None, max_tokens=2048, temperature=0.7):
    """Try each provider in order, return first success."""
    errors = []
    failover_count = 0   # increments every time a provider is skipped or fails

    for provider in PROVIDERS:
        if not provider["key"]:
            continue
        if is_cooling(provider["name"]):
            errors.append({"provider": provider["name"], "error": "cooling down"})
            failover_count += 1
            continue

        # Use provider's default model (we abstract away model names)
        provider_model = provider["default"]

        body = {
            "model": provider_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        headers = {
            "Authorization": f"Bearer {provider['key']}",
            "Content-Type": "application/json",
        }

        start = time.time()
        try:
            resp = http_requests.post(provider["url"], json=body, headers=headers, timeout=30)
            latency = int((time.time() - start) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                # Normalize to OpenAI format
                usage = data.get("usage", {})
                return {
                    "provider": provider["name"],
                    "model": provider_model,
                    "data": data,
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "latency_ms": latency,
                    "failover_count": failover_count,
                }
            elif resp.status_code == 429:
                # Rate limited — cool down
                cooldown_s = 300 if "daily" in resp.text.lower() or "day" in resp.text.lower() else 65
                set_cooldown(provider["name"], cooldown_s)
                errors.append({"provider": provider["name"], "error": f"429 (cooling {cooldown_s}s)", "body": resp.text[:200]})
                failover_count += 1
            else:
                errors.append({"provider": provider["name"], "error": f"HTTP {resp.status_code}", "body": resp.text[:200]})
                failover_count += 1
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            errors.append({"provider": provider["name"], "error": str(e)[:200]})
            set_cooldown(provider["name"], 30)
            failover_count += 1

    return {"error": "All providers exhausted", "details": errors, "failover_count": failover_count}


def cascade_chat_stream(messages, model=None, max_tokens=2048, temperature=0.7):
    """Generator: yields SSE-formatted lines for streaming response.

    Tries each provider with native stream=True. All four providers (Groq,
    Cerebras, SambaNova, Gemini-OpenAI-compat) support the OpenAI streaming
    protocol, so we forward their SSE chunks directly after normalizing.
    If a provider returns a non-200 before streaming starts we fall through
    to the next one. If all fail we emit a single error delta + [DONE].
    """
    comp_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    for provider in PROVIDERS:
        if not provider["key"]:
            continue
        if is_cooling(provider["name"]):
            continue

        provider_model = provider["default"]
        body = {
            "model": provider_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {provider['key']}",
            "Content-Type": "application/json",
        }

        try:
            resp = http_requests.post(
                provider["url"], json=body, headers=headers,
                timeout=30, stream=True
            )

            if resp.status_code == 429:
                cooldown_s = 300 if "daily" in resp.text.lower() or "day" in resp.text.lower() else 65
                set_cooldown(provider["name"], cooldown_s)
                continue

            if resp.status_code != 200:
                continue

            # Stream started — forward chunks until [DONE] or connection drops
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line

                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()

                if data_str == "[DONE]":
                    yield "data: [DONE]\n\n"
                    return

                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                # Normalize to a consistent OpenAI chunk shape
                normalized = {
                    "id": chunk.get("id", comp_id),
                    "object": "chat.completion.chunk",
                    "created": chunk.get("created", created),
                    "model": provider_model,
                    "choices": chunk.get("choices", []),
                    "x_tiamat_provider": provider["name"],
                }
                yield f"data: {json.dumps(normalized)}\n\n"

            # Provider finished without [DONE] — emit it and return
            yield "data: [DONE]\n\n"
            return

        except Exception as e:
            set_cooldown(provider["name"], 30)
            continue

    # All providers failed — emit a single error delta so the client knows
    error_chunk = {
        "id": comp_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": "auto",
        "choices": [{
            "index": 0,
            "delta": {"content": "[ERROR: All inference providers exhausted]"},
            "finish_reason": "stop",
        }],
    }
    yield f"data: {json.dumps(error_chunk)}\n\n"
    yield "data: [DONE]\n\n"

# ─── Embedding Providers ─────────────────────────────────────────
EMBEDDING_PROVIDERS = [
    {
        "name": "groq",
        "url": "https://api.groq.com/openai/v1/embeddings",
        "key": os.environ.get("GROQ_API_KEY", ""),
        "default_model": "nomic-embed-text-v1.5",
    },
    {
        "name": "cerebras",
        "url": "https://api.cerebras.ai/v1/embeddings",
        "key": os.environ.get("CEREBRAS_API_KEY", ""),
        "default_model": "nomic-embed-text-v1.5",
    },
    {
        "name": "together",
        "url": "https://api.together.xyz/v1/embeddings",
        "key": os.environ.get("TOGETHER_API_KEY", ""),
        "default_model": "togethercomputer/m2-bert-80M-8k-retrieval",
    },
]

def cascade_embeddings(inputs, model=None):
    """Try each embedding provider in order, return first success.

    Args:
        inputs: str or list[str]
        model: optional model override (uses provider default if None)

    Returns:
        dict with keys: provider, model, data (OpenAI-compat response),
        prompt_tokens, latency_ms, failover_count
        OR dict with key 'error' if all providers exhausted.
    """
    # Normalize to list
    if isinstance(inputs, str):
        inputs = [inputs]

    errors = []
    failover_count = 0

    for provider in EMBEDDING_PROVIDERS:
        if not provider["key"]:
            errors.append({"provider": provider["name"], "error": "no API key configured"})
            failover_count += 1
            continue
        if is_cooling(provider["name"] + ":embed"):
            errors.append({"provider": provider["name"], "error": "cooling down"})
            failover_count += 1
            continue

        provider_model = model if model else provider["default_model"]
        body = {"model": provider_model, "input": inputs}
        headers = {
            "Authorization": f"Bearer {provider['key']}",
            "Content-Type": "application/json",
        }

        start = time.time()
        try:
            resp = http_requests.post(provider["url"], json=body, headers=headers, timeout=30)
            latency = int((time.time() - start) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                usage = data.get("usage", {})
                # Normalize: ensure every item has object/index/embedding keys
                raw_data = data.get("data", [])
                normalized_data = []
                for i, item in enumerate(raw_data):
                    normalized_data.append({
                        "object": "embedding",
                        "index": item.get("index", i),
                        "embedding": item.get("embedding", []),
                    })
                return {
                    "provider": provider["name"],
                    "model": data.get("model", provider_model),
                    "data": normalized_data,
                    "prompt_tokens": usage.get("prompt_tokens", usage.get("total_tokens", 0)),
                    "latency_ms": latency,
                    "failover_count": failover_count,
                }
            elif resp.status_code == 429:
                cooldown_s = 300 if "daily" in resp.text.lower() or "day" in resp.text.lower() else 65
                set_cooldown(provider["name"] + ":embed", cooldown_s)
                errors.append({"provider": provider["name"], "error": f"429 (cooling {cooldown_s}s)", "body": resp.text[:200]})
                failover_count += 1
            else:
                errors.append({"provider": provider["name"], "error": f"HTTP {resp.status_code}", "body": resp.text[:200]})
                failover_count += 1
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            errors.append({"provider": provider["name"], "error": str(e)[:200]})
            set_cooldown(provider["name"] + ":embed", 30)
            failover_count += 1

    return {"error": "All embedding providers exhausted", "details": errors, "failover_count": failover_count}


# ─── Routes ──────────────────────────────────────────────────────
@app.route("/v1/embeddings", methods=["POST"])
@require_api_key
def embeddings():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": {"message": "Request body required", "type": "invalid_request"}}), 400

    inp = body.get("input")
    if inp is None:
        return jsonify({"error": {"message": "Missing 'input' in request body", "type": "invalid_request"}}), 400
    if not isinstance(inp, (str, list)):
        return jsonify({"error": {"message": "'input' must be a string or list of strings", "type": "invalid_request"}}), 400
    if isinstance(inp, list):
        if not all(isinstance(s, str) for s in inp):
            return jsonify({"error": {"message": "All items in 'input' must be strings", "type": "invalid_request"}}), 400
        if len(inp) == 0:
            return jsonify({"error": {"message": "'input' list must not be empty", "type": "invalid_request"}}), 400

    model = body.get("model")  # optional override; cascade uses provider defaults if None

    result = cascade_embeddings(inp, model=model)

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    is_paid = getattr(request, "api_tier", "free") == "paid"

    if "error" in result and "data" not in result:
        log_usage(request.api_key, "none", model or "auto-embed", 0, 0, 0, "all_exhausted",
                  ip=client_ip, paid=is_paid, failover=result.get("failover_count", 0))
        return jsonify({
            "error": {
                "message": result["error"],
                "type": "server_error",
                "details": result.get("details", []),
            }
        }), 503

    log_usage(request.api_key, result["provider"], result["model"],
              result["prompt_tokens"], 0, result["latency_ms"], "ok",
              ip=client_ip, paid=is_paid, failover=result.get("failover_count", 0))

    resp_body = {
        "object": "list",
        "data": result["data"],
        "model": result["model"],
        "usage": {
            "prompt_tokens": result["prompt_tokens"],
            "total_tokens": result["prompt_tokens"],
        },
        "x_tiamat_provider": result["provider"],
        "x_tiamat_latency_ms": result["latency_ms"],
    }
    resp = make_response(jsonify(resp_body), 200)
    resp.headers["X-Provider"] = result["provider"]
    resp.headers["X-Latency-Ms"] = str(result["latency_ms"])
    return resp


@app.route("/v1/chat/completions", methods=["POST"])
@require_api_key
def chat_completions():
    body = request.get_json(silent=True)
    if not body or "messages" not in body:
        return jsonify({"error": {"message": "Missing 'messages' in request body", "type": "invalid_request"}}), 400

    messages = body["messages"]
    model = body.get("model", "auto")
    max_tokens = min(body.get("max_tokens", 2048), 4096)
    temperature = body.get("temperature", 0.7)
    stream = bool(body.get("stream", False))

    # ── Streaming path ────────────────────────────────────────────
    if stream:
        api_key = request.api_key

        def generate():
            yield from cascade_chat_stream(
                messages, model=model, max_tokens=max_tokens, temperature=temperature
            )
            log_usage(api_key, "stream", model, 0, 0, 0, "stream_ok")

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # ── Non-streaming path ────────────────────────────────────────
    result = cascade_chat(messages, model=model, max_tokens=max_tokens, temperature=temperature)

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    is_paid = getattr(request, "api_tier", "free") == "paid"

    if "error" in result and "data" not in result:
        log_usage(request.api_key, "none", model, 0, 0, 0, "all_exhausted",
                  ip=client_ip, paid=is_paid, failover=result.get("failover_count", 0))
        return jsonify({"error": {"message": result["error"], "type": "server_error", "details": result.get("details", [])}}), 503

    log_usage(request.api_key, result["provider"], result["model"],
              result["input_tokens"], result["output_tokens"], result["latency_ms"], "ok",
              ip=client_ip, paid=is_paid, failover=result.get("failover_count", 0))

    data = result["data"]
    resp_body = {
        "id": data.get("id", f"chatcmpl-{uuid.uuid4().hex[:12]}"),
        "object": "chat.completion",
        "created": data.get("created", int(time.time())),
        "model": result["model"],
        "choices": data.get("choices", []),
        "usage": data.get("usage", {
            "prompt_tokens": result["input_tokens"],
            "completion_tokens": result["output_tokens"],
            "total_tokens": result["input_tokens"] + result["output_tokens"],
        }),
        "x_tiamat_provider": result["provider"],
        "x_tiamat_latency_ms": result["latency_ms"],
    }
    resp = make_response(jsonify(resp_body), 200)
    resp.headers["X-Provider"] = result["provider"]
    resp.headers["X-Latency-Ms"] = str(result["latency_ms"])
    return resp

@app.route("/v1/models", methods=["GET"])
def list_models():
    """List available models (OpenAI-compatible)."""
    models = []
    for p in PROVIDERS:
        if not p["key"]:
            continue
        for m in p["models"]:
            models.append({
                "id": m,
                "object": "model",
                "created": 1700000000,
                "owned_by": p["name"],
                "permission": [],
            })
    # Also expose our "auto" model
    models.insert(0, {
        "id": "auto",
        "object": "model",
        "created": 1700000000,
        "owned_by": "tiamat",
        "permission": [],
    })
    return jsonify({"object": "list", "data": models})

@app.route("/v1/keys", methods=["POST"])
def create_key():
    """Create a new API key. No auth required (self-service)."""
    body = request.get_json(silent=True) or {}
    name = body.get("name", "anonymous")
    key = f"tiamat-{hashlib.sha256(f'{name}-{time.time()}-{uuid.uuid4()}'.encode()).hexdigest()[:24]}"
    db = get_db()
    db.execute("INSERT INTO api_keys (key, name, tier) VALUES (?, ?, 'free')", (key, name))
    db.commit()
    db.close()
    return jsonify({"api_key": key, "name": name, "tier": "free", "rate_limit": f"{RATE_LIMIT_FREE}/min"})

@app.route("/v1/usage", methods=["GET"])
@require_api_key
def get_usage():
    """Get usage stats for the current API key."""
    db = get_db()
    stats = db.execute("""
        SELECT
            COUNT(*) as total_requests,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(latency_ms) as total_latency_ms,
            provider,
            COUNT(*) as provider_requests
        FROM usage_log
        WHERE api_key = ?
        GROUP BY provider
    """, (request.api_key,)).fetchall()

    today = db.execute("""
        SELECT COUNT(*) as requests_today, SUM(input_tokens) as tokens_today
        FROM usage_log
        WHERE api_key = ? AND created_at > datetime('now', '-1 day')
    """, (request.api_key,)).fetchone()
    db.close()

    return jsonify({
        "api_key": request.api_key[:12] + "...",
        "tier": request.api_tier,
        "today": {"requests": today["requests_today"], "tokens": today["tokens_today"] or 0},
        "by_provider": [{"provider": r["provider"], "requests": r["provider_requests"],
                         "input_tokens": r["total_input_tokens"], "output_tokens": r["total_output_tokens"]} for r in stats],
    })

@app.route("/v1/status", methods=["GET"])
def proxy_status():
    """Health check with provider status."""
    status = []
    for p in PROVIDERS:
        cooling = is_cooling(p["name"])
        status.append({
            "provider": p["name"],
            "available": bool(p["key"]) and not cooling,
            "cooling": cooling,
            "models": p["models"],
        })
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM usage_log").fetchone()[0]
    keys = db.execute("SELECT COUNT(*) FROM api_keys WHERE active=1").fetchone()[0]
    db.close()
    return jsonify({"status": "ok", "providers": status, "total_requests": total, "active_keys": keys})

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "TIAMAT Inference Proxy",
        "version": "1.0.0",
        "endpoints": {
            "POST /v1/chat/completions": "OpenAI-compatible chat (requires API key)",
            "POST /v1/embeddings": "OpenAI-compatible embeddings — Groq → Cerebras → Together.ai (requires API key)",
            "GET /v1/models": "List available models",
            "POST /v1/keys": "Create a free API key",
            "GET /v1/usage": "Usage stats (requires API key)",
            "GET /v1/status": "Provider health status",
        },
        "docs": "https://tiamat.live/docs",
    })

# ─── Dashboard ───────────────────────────────────────────────────
def _dashboard_stats() -> dict:
    """Return aggregated provider stats from the proxy DB."""
    try:
        db = get_db()

        # Total completed requests (exclude 'none' sentinel rows)
        total = db.execute(
            "SELECT COUNT(*) FROM usage_log WHERE provider != 'none' AND status = 'ok'"
        ).fetchone()[0]

        total_all = db.execute("SELECT COUNT(*) FROM usage_log").fetchone()[0]

        # Provider distribution + avg latency (successful rows only)
        rows = db.execute("""
            SELECT provider,
                   COUNT(*)         AS cnt,
                   AVG(latency_ms)  AS avg_lat
            FROM   usage_log
            WHERE  status = 'ok'
            GROUP  BY provider
            ORDER  BY cnt DESC
        """).fetchall()

        providers = []
        for r in rows:
            providers.append({
                "provider":        r["provider"],
                "requests":        r["cnt"],
                "pct":             round(r["cnt"] / total * 100, 1) if total else 0,
                "avg_latency_ms":  round(r["avg_lat"] or 0),
            })

        # Failover events in last 24 h
        failovers_24h = db.execute(
            "SELECT COALESCE(SUM(failover), 0) FROM usage_log WHERE created_at >= datetime('now', '-1 day')"
        ).fetchone()[0]

        # Avg latency all-time (successful)
        avg_lat_all = db.execute(
            "SELECT AVG(latency_ms) FROM usage_log WHERE status='ok'"
        ).fetchone()[0] or 0

        # Recent 20 rows
        recent = db.execute("""
            SELECT created_at, ip, provider, latency_ms, paid, failover, status
            FROM   usage_log
            ORDER  BY id DESC LIMIT 20
        """).fetchall()

        db.close()
        return {
            "total_requests":  total_all,
            "successful":      total,
            "failovers_24h":   int(failovers_24h),
            "avg_latency_ms":  round(avg_lat_all),
            "providers":       providers,
            "recent":          [dict(r) for r in recent],
            "generated_at":    datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.route("/dashboard/json")
def dashboard_json():
    """Machine-readable provider telemetry."""
    return jsonify(_dashboard_stats())


@app.route("/dashboard")
def dashboard():
    """HTML dashboard: KPI cards + pie chart + provider table + recent log."""
    stats = _dashboard_stats()
    if "error" in stats:
        return jsonify(stats), 500

    import json as _json
    providers_json = _json.dumps(stats["providers"])
    recent_rows_html = ""
    for r in stats["recent"]:
        color = "#2cb67d" if r["status"] == "ok" else "#ef4565"
        fo = r.get("failover", 0)
        fo_badge = f' <span style="color:#f5a623">[fo:{fo}]</span>' if fo else ""
        paid_badge = ' <span style="color:#7f5af0">[paid]</span>' if r.get("paid") else ""
        recent_rows_html += (
            f'<tr><td style="color:#94a1b2;font-size:0.7rem">{r["created_at"]}</td>'
            f'<td>{r["ip"]}</td>'
            f'<td style="color:{color}">{r["provider"]}</td>'
            f'<td>{r["latency_ms"]} ms</td>'
            + f'<td>{r["status"]}{fo_badge}{paid_badge}</td></tr>\n'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TIAMAT — Inference Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root{{--bg:#050508;--surface:#0d0d18;--border:#1a1a35;--accent:#7f5af0;--green:#2cb67d;--red:#ef4565;--text:#fffffe;--muted:#94a1b2}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:'JetBrains Mono',monospace;min-height:100vh;padding:2rem}}
  h1{{font-family:'Orbitron',sans-serif;font-size:1.4rem;color:var(--accent);letter-spacing:.15em;margin-bottom:.25rem}}
  .meta{{color:var(--muted);font-size:.75rem;margin-bottom:2rem}}
  .meta a{{color:var(--accent);text-decoration:none}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem;margin-bottom:2rem}}
  .card{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:1.25rem}}
  .card .label{{color:var(--muted);font-size:.7rem;text-transform:uppercase;letter-spacing:.1em}}
  .card .value{{font-size:2rem;font-weight:600;margin-top:.25rem;color:var(--accent)}}
  .layout{{display:grid;grid-template-columns:300px 1fr;gap:1.5rem;align-items:start;margin-bottom:2rem}}
  .chart-wrap{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:1.25rem}}
  .chart-wrap h2{{font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:1rem}}
  table{{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden}}
  th{{background:var(--border);color:var(--muted);font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;padding:.75rem 1rem;text-align:left}}
  td{{padding:.6rem 1rem;border-top:1px solid var(--border);font-size:.8rem}}
  .bar-bg{{background:var(--border);border-radius:4px;height:5px;width:100%;margin-top:3px}}
  .bar-fill{{border-radius:4px;height:5px}}
  .section-title{{font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin:1.5rem 0 .75rem}}
  .refresh{{color:var(--muted);font-size:.7rem;margin-top:1.5rem}}
  .refresh a{{color:var(--accent);text-decoration:none}}
  @media(max-width:700px){{.layout{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<h1>&#9889; INFERENCE DASHBOARD</h1>
<p class="meta">{stats["generated_at"]} &nbsp;|&nbsp; <a href="/dashboard/json">JSON</a> &nbsp;|&nbsp; <a href="/v1/status">Provider Status</a></p>

<div class="grid">
  <div class="card"><div class="label">Total Requests</div><div class="value">{stats["total_requests"]}</div></div>
  <div class="card"><div class="label">Successful</div><div class="value" style="color:var(--green)">{stats["successful"]}</div></div>
  <div class="card"><div class="label">Avg Latency</div><div class="value">{stats["avg_latency_ms"]}<span style="font-size:1rem">ms</span></div></div>
  <div class="card"><div class="label">Failovers (24h)</div><div class="value" style="color:var(--red)">{stats["failovers_24h"]}</div></div>
  <div class="card"><div class="label">Providers</div><div class="value">{len(stats["providers"])}</div></div>
</div>

<div class="layout">
  <div class="chart-wrap">
    <h2>Provider Distribution</h2>
    <canvas id="pieChart" width="260" height="260"></canvas>
  </div>
  <table id="providerTable">
    <thead><tr><th>Provider</th><th>Requests</th><th>Share</th><th>Avg Latency</th></tr></thead>
    <tbody id="providerRows"></tbody>
  </table>
</div>

<p class="section-title">Recent Requests</p>
<table>
  <thead><tr><th>Timestamp</th><th>IP</th><th>Provider</th><th>Latency</th><th>Status</th></tr></thead>
  <tbody>{recent_rows_html}</tbody>
</table>

<p class="refresh">Auto-refreshes every 60s &nbsp;|&nbsp; <a href="/dashboard">&#8635; Refresh now</a></p>

<script>
const providers = {providers_json};
const COLORS = ["#7f5af0","#2cb67d","#ef4565","#f5a623","#00d4ff","#ff6b6b","#a8ff78"];

new Chart(document.getElementById("pieChart").getContext("2d"), {{
  type: "doughnut",
  data: {{
    labels: providers.map(p => p.provider),
    datasets: [{{
      data: providers.map(p => p.requests),
      backgroundColor: providers.map((_, i) => COLORS[i % COLORS.length]),
      borderWidth: 2, borderColor: "#0d0d18",
    }}]
  }},
  options: {{
    plugins: {{ legend: {{ labels: {{ color:"#94a1b2", font:{{ family:"JetBrains Mono", size:11 }} }} }} }},
    animation: {{ duration: 400 }},
  }}
}});

const tbody = document.getElementById("providerRows");
providers.forEach((p, i) => {{
  const c = COLORS[i % COLORS.length];
  tbody.innerHTML += `<tr>
    <td><span style="color:${{c}};font-weight:600">${{p.provider}}</span></td>
    <td>${{p.requests}}</td>
    <td>${{p.pct}}%<div class="bar-bg"><div class="bar-fill" style="width:${{p.pct}}%;background:${{c}}"></div></div></td>
    <td>${{p.avg_latency_ms}} ms</td>
  </tr>`;
}});

setTimeout(() => location.reload(), 60000);
</script>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


# ─── Main ────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print(f"[PROXY] TIAMAT Inference Proxy starting on port 5003")
    print(f"[PROXY] Providers: {', '.join(p['name'] for p in PROVIDERS if p['key'])}")
    app.run(host="127.0.0.1", port=5004, debug=False)
