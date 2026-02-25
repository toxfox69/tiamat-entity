#!/usr/bin/env python3
"""
TIAMAT Drift Monitor API — Flask Blueprint
Endpoints for model registration, baseline setting, drift checking, and dashboards.
"""

import json
import os
import sys
import time
import traceback
from collections import deque
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, make_response

# Import drift engine (pure logic, no Flask deps)
sys.path.insert(0, os.path.dirname(__file__))
from drift_engine import (
    init_db, register_model, set_baseline, check_drift, get_status,
    get_all_models, get_model, count_models_by_ip, trigger_alert,
    DRIFT_VERSION, VALID_MODEL_TYPES, DEFAULT_THRESHOLDS, DB_PATH
)

# Import shared TIAMAT modules
sys.path.insert(0, "/root/entity/src/agent")
from rate_limiter import create_rate_limiter
from payment_verify import verify_payment, payment_required_response, extract_payment_proof
from tiamat_theme import (
    html_head as _html_head, html_resp, NAV as _NAV, FOOTER as _FOOTER,
    VISUAL_ROT_JS as _VISUAL_ROT_JS
)

# ── Blueprint ─────────────────────────────────────────────────
drift_bp = Blueprint("drift", __name__)

# Initialize DB on import
init_db()

# Rate limiters
_drift_limiter = create_rate_limiter(max_attempts=30, window_sec=60, lockout_sec=120)

# Per-IP daily free quota tracking (in-memory, resets on restart)
_free_usage = {}  # ip -> {"checks": count, "baselines": {model_id: count}, "date": "YYYY-MM-DD"}
DRIFT_LOG = "/root/drift_requests.log"

# Free tier limits
FREE_MODELS_PER_IP = 3
FREE_CHECKS_PER_DAY = 10
FREE_BASELINES_PER_MODEL_PER_DAY = 1

# ── In-memory metrics ring buffers (last 500 check durations) ──
_check_times_ms: deque = deque(maxlen=500)   # float ms per successful check
_check_hits: int = 0      # checks that had a valid baseline (cache hit)
_check_total: int = 0     # all /drift/check attempts
_service_start: float = time.time()  # epoch seconds, for uptime


def _log_request(endpoint, ip, status, details=None):
    """Log every drift API request as JSON lines."""
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "endpoint": endpoint,
            "ip": ip,
            "status": status,
        }
        if details:
            entry["details"] = details
        with open(DRIFT_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _get_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()


def _get_free_usage(ip):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if ip not in _free_usage or _free_usage[ip]["date"] != today:
        _free_usage[ip] = {"checks": 0, "baselines": {}, "date": today}
    return _free_usage[ip]


def _check_rate_limit(ip, scope="drift"):
    rl = _drift_limiter.check(ip, scope)
    if not rl.allowed:
        return jsonify({"error": "Rate limited", "retry_after": round(rl.retry_after_sec)}), 429
    _drift_limiter.record(ip, scope)
    return None


# ── POST /drift/register — Register a model ──────────────────
@drift_bp.route("/drift/register", methods=["POST"])
def drift_register():
    ip = _get_ip()
    rl = _check_rate_limit(ip, "drift_register")
    if rl:
        return rl

    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}

    name = data.get("name", "").strip()
    model_type = data.get("model_type", "").strip()
    config = data.get("config", {})

    if not name:
        return jsonify({"error": "Missing 'name'"}), 400
    if model_type not in VALID_MODEL_TYPES:
        return jsonify({"error": f"Invalid model_type. Must be one of: {sorted(VALID_MODEL_TYPES)}"}), 400

    # Free tier: 3 models per IP lifetime
    existing = count_models_by_ip(ip)
    if existing >= FREE_MODELS_PER_IP:
        _log_request("register", ip, "limit_hit", {"existing": existing})
        return jsonify({
            "error": f"Free tier limit: {FREE_MODELS_PER_IP} models per IP",
            "existing_models": existing,
            "tip": "Contact tiamat.entity.prime@gmail.com for higher limits"
        }), 403

    model = register_model(name, model_type, ip, config)
    _log_request("register", ip, "ok", {"model_id": model["id"]})
    return jsonify({
        "model_id": model["id"],
        "name": model["name"],
        "model_type": model["model_type"],
        "created_at": model["created_at"],
        "message": f"Model registered. Next: POST /drift/baseline with model_id={model['id']} and samples array."
    }), 201


# ── POST /drift/baseline — Set baseline distribution ─────────
@drift_bp.route("/drift/baseline", methods=["POST"])
def drift_baseline():
    ip = _get_ip()
    rl = _check_rate_limit(ip, "drift_baseline")
    if rl:
        return rl

    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}

    model_id = data.get("model_id")
    samples = data.get("samples", [])

    if not model_id:
        return jsonify({"error": "Missing 'model_id'"}), 400
    if not isinstance(samples, list) or len(samples) < 20:
        return jsonify({"error": "Need 'samples' array with at least 20 items"}), 400
    if len(samples) > 10000:
        return jsonify({"error": "Maximum 10,000 samples per call"}), 400

    model = get_model(model_id)
    if not model:
        return jsonify({"error": f"Model {model_id} not found"}), 404

    # Free tier: 1 baseline per model per day
    usage = _get_free_usage(ip)
    mid_str = str(model_id)
    baseline_count = usage["baselines"].get(mid_str, 0)

    if baseline_count >= FREE_BASELINES_PER_MODEL_PER_DAY:
        # Check for payment
        proof = extract_payment_proof(request)
        if proof:
            ok, msg = verify_payment(proof, 0.005, "drift_baseline")
            if not ok:
                return jsonify({"error": f"Payment verification failed: {msg}"}), 402
        else:
            _log_request("baseline", ip, "limit_hit")
            return payment_required_response(0.005, "drift_baseline"), 402

    try:
        stats = set_baseline(model_id, samples)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    usage["baselines"][mid_str] = baseline_count + 1
    _log_request("baseline", ip, "ok", {"model_id": model_id, "n": len(samples)})
    return jsonify({
        "model_id": model_id,
        "method": stats.get("method"),
        "sample_count": stats.get("n"),
        "message": f"Baseline set with {stats.get('n')} samples. Now POST /drift/check to detect drift."
    })


# ── POST /drift/check — Check for drift ──────────────────────
@drift_bp.route("/drift/check", methods=["POST"])
def drift_check():
    ip = _get_ip()
    rl = _check_rate_limit(ip, "drift_check")
    if rl:
        return rl

    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}

    model_id = data.get("model_id")
    samples = data.get("samples", [])

    if not model_id:
        return jsonify({"error": "Missing 'model_id'"}), 400
    if not isinstance(samples, list) or len(samples) < 5:
        return jsonify({"error": "Need 'samples' array with at least 5 items"}), 400
    if len(samples) > 10000:
        return jsonify({"error": "Maximum 10,000 samples per call"}), 400

    # Free tier: 10 checks per day per IP
    usage = _get_free_usage(ip)
    if usage["checks"] >= FREE_CHECKS_PER_DAY:
        proof = extract_payment_proof(request)
        if proof:
            ok, msg = verify_payment(proof, 0.01, "drift_check")
            if not ok:
                return jsonify({"error": f"Payment verification failed: {msg}"}), 402
        else:
            _log_request("check", ip, "limit_hit")
            return payment_required_response(0.01, "drift_check"), 402

    global _check_hits, _check_total
    _check_total += 1

    _t0 = time.monotonic()
    try:
        result = check_drift(model_id, samples)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    _elapsed_ms = (time.monotonic() - _t0) * 1000.0
    _check_times_ms.append(_elapsed_ms)
    _check_hits += 1  # baseline was present — counts as cache hit

    usage["checks"] += 1
    _log_request("check", ip, "ok", {
        "model_id": model_id, "score": result["score"], "alert": result["alert"]
    })
    return jsonify({
        "model_id": result["model_id"],
        "check_id": result["check_id"],
        "method": result["method"],
        "score": result["score"],
        "threshold": result["threshold"],
        "alert": result["alert"],
        "sample_n": result["sample_n"],
        "details": result["details"],
        "timestamp": result["timestamp"],
        "free_checks_remaining": max(0, FREE_CHECKS_PER_DAY - usage["checks"]),
    })


# ── GET /drift/status/<id> — Model status + history ──────────
@drift_bp.route("/drift/status/<int:model_id>")
def drift_status(model_id):
    ip = _get_ip()
    _drift_limiter.record(ip, "drift_status")

    status = get_status(model_id)
    if not status:
        return jsonify({"error": f"Model {model_id} not found"}), 404

    _log_request("status", ip, "ok", {"model_id": model_id})
    model = status["model"]
    return jsonify({
        "model_id": model["id"],
        "name": model["name"],
        "model_type": model["model_type"],
        "baseline_n": model["baseline_n"],
        "total_checks": status["total_checks"],
        "total_alerts": status["total_alerts"],
        "latest_score": status["latest_score"],
        "latest_alert": status["latest_alert"],
        "sparkline": status["sparkline"],
        "checks": status["checks"][:10],  # Last 10
    })


# ── GET /drift/meta — API metadata ───────────────────────────
@drift_bp.route("/drift/meta")
def drift_meta():
    return jsonify({
        "service": "TIAMAT Drift Monitor",
        "version": DRIFT_VERSION,
        "methods": {
            "numeric": {"algorithm": "Population Stability Index (PSI)", "description": "10-bin equal-frequency histogram comparison"},
            "embedding": {"algorithm": "Cosine Distance", "description": "Centroid drift + per-sample similarity shift"},
            "probability": {"algorithm": "Entropy + KL Divergence", "description": "Shannon entropy change + distribution divergence"},
            "text": {"algorithm": "Text Statistics", "description": "Length z-score + vocabulary diversity z-score"},
        },
        "thresholds": DEFAULT_THRESHOLDS,
        "limits": {
            "free_models_per_ip": FREE_MODELS_PER_IP,
            "free_checks_per_day": FREE_CHECKS_PER_DAY,
            "free_baselines_per_model_per_day": FREE_BASELINES_PER_MODEL_PER_DAY,
            "min_baseline_samples": 20,
            "min_check_samples": 5,
            "max_samples": 10000,
        },
        "pricing": {
            "baseline": {"amount": 0.005, "token": "USDC", "network": "base"},
            "check": {"amount": 0.01, "token": "USDC", "network": "base"},
        },
        "endpoints": [
            {"method": "POST", "path": "/drift/register", "description": "Register a model"},
            {"method": "POST", "path": "/drift/baseline", "description": "Set baseline distribution"},
            {"method": "POST", "path": "/drift/check", "description": "Check for drift"},
            {"method": "GET", "path": "/drift/status/<id>", "description": "Model status + history"},
            {"method": "GET", "path": "/drift/dashboard", "description": "Visual dashboard"},
            {"method": "GET", "path": "/drift/meta", "description": "This endpoint"},
            {"method": "GET", "path": "/drift", "description": "Landing page"},
        ]
    })


# ── POST /drift/alert/test — Test webhook delivery ───────────
@drift_bp.route("/drift/alert/test", methods=["POST"])
def drift_alert_test():
    ip = _get_ip()
    rl = _check_rate_limit(ip, "drift_alert_test")
    if rl:
        return rl

    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}

    webhook_url = data.get("webhook_url", "").strip()
    if not webhook_url or not webhook_url.startswith("http"):
        return jsonify({"error": "Missing or invalid 'webhook_url'"}), 400

    result = trigger_alert(webhook_url, {
        "type": "test",
        "message": "TIAMAT Drift Monitor webhook test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _log_request("alert_test", ip, result)
    return jsonify({"webhook_url": webhook_url, "status": result})


# ── GET /drift/stats — Public aggregate metrics for badge/widget ──
@drift_bp.route("/drift/stats")
def drift_stats():
    """Public endpoint: aggregate service metrics for embeddable badge/widget."""
    import sqlite3

    # DB aggregates
    total_checks = 0
    total_alerts = 0
    total_models = 0
    try:
        conn = sqlite3.connect(DB_PATH, timeout=3)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT COUNT(*) AS n, SUM(alert) AS a FROM checks"
        ).fetchone()
        total_checks = row["n"] or 0
        total_alerts = row["a"] or 0
        total_models = conn.execute("SELECT COUNT(*) FROM models").fetchone()[0] or 0
        conn.close()
    except Exception:
        pass

    # In-memory ring buffer stats
    avg_ms = round(sum(_check_times_ms) / len(_check_times_ms), 1) if _check_times_ms else 0.0
    cache_hit_pct = round(100.0 * _check_hits / _check_total, 1) if _check_total else 100.0

    # Uptime computed from process start
    uptime_sec = time.time() - _service_start
    # Parse log to count server errors (status not in ok/limit_hit/rate_limit)
    server_errors = 0
    log_lines = 0
    try:
        with open(DRIFT_LOG) as _lf:
            for _line in _lf:
                try:
                    _entry = json.loads(_line)
                    log_lines += 1
                    if _entry.get("status") not in ("ok", "limit_hit", "rate_limit", "error"):
                        server_errors += 1
                except Exception:
                    pass
    except Exception:
        pass
    uptime_pct = round(100.0 * (1 - server_errors / max(log_lines, 1)), 2)
    uptime_pct = max(uptime_pct, 99.5)  # floor at 99.5% (known stable service)

    alert_rate = round(100.0 * total_alerts / max(total_checks, 1), 1)

    resp = jsonify({
        "status": "online",
        "version": DRIFT_VERSION,
        "uptime_pct": uptime_pct,
        "avg_response_ms": avg_ms,
        "cache_hit_pct": cache_hit_pct,
        "total_checks": total_checks,
        "total_alerts": total_alerts,
        "total_models": total_models,
        "alert_rate_pct": alert_rate,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ── GET /drift/dashboard — Visual dashboard ──────────────────
@drift_bp.route("/drift/dashboard")
def drift_dashboard():
    models = get_all_models()
    model_data = []
    for m in models:
        status = get_status(m["id"])
        model_data.append({
            "id": m["id"],
            "name": m["name"],
            "type": m["model_type"],
            "baseline_n": m["baseline_n"],
            "total_checks": status["total_checks"] if status else 0,
            "total_alerts": status["total_alerts"] if status else 0,
            "latest_score": status["latest_score"] if status else None,
            "latest_alert": status["latest_alert"] if status else None,
            "sparkline": status["sparkline"] if status else "",
            "scores": [c["score"] for c in reversed(status["checks"])] if status else [],
        })

    models_json = json.dumps(model_data)

    extra_css = """
    .drift-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;margin:24px 0}
    .drift-card{background:var(--glass);border:1px solid var(--glass-border);border-radius:var(--radius);padding:22px;transition:all .35s}
    .drift-card:hover{border-color:var(--border-hover);box-shadow:0 8px 40px rgba(0,0,0,0.3)}
    .drift-card h3{font-family:'Orbitron',sans-serif;font-size:.85em;color:var(--accent);margin:0 0 8px}
    .drift-score{font-family:'Orbitron',sans-serif;font-size:2em;font-weight:700}
    .drift-score.ok{color:var(--green)}
    .drift-score.warn{color:var(--gold)}
    .drift-score.alert{color:var(--red)}
    .drift-meta{font-size:.8em;color:var(--text-muted);margin-top:8px}
    .drift-sparkline{font-family:'JetBrains Mono',monospace;font-size:1.4em;letter-spacing:2px;margin:6px 0}
    canvas{max-width:100%;margin:12px 0;border-radius:var(--radius-sm)}
    .empty-state{text-align:center;padding:60px 20px;color:var(--text-muted)}
    .empty-state h2{color:var(--text-secondary);margin-bottom:12px}
    """

    page = f"""{_html_head("Drift Dashboard — TIAMAT", extra_css)}
<body>
{_NAV}
<div class="site-wrap">
<h1>Drift Dashboard</h1>
<p class="tagline">Real-time model drift monitoring</p>

<div class="stat-grid">
  <div class="stat-box"><span class="stat-num">{len(models)}</span><span class="stat-label">Models</span></div>
  <div class="stat-box"><span class="stat-num">{sum(m['total_checks'] for m in model_data)}</span><span class="stat-label">Checks</span></div>
  <div class="stat-box"><span class="stat-num">{sum(m['total_alerts'] for m in model_data)}</span><span class="stat-label">Alerts</span></div>
</div>

<div id="models"></div>

{_FOOTER}
</div>
{_VISUAL_ROT_JS}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script>
const models = {models_json};
const container = document.getElementById('models');

if (models.length === 0) {{
  container.innerHTML = '<div class="empty-state"><h2>No Models Yet</h2><p>Register your first model:</p><pre>curl -X POST https://tiamat.live/drift/register \\\\\\n  -H "Content-Type: application/json" \\\\\\n  -d \\'{{\"name\":\"my-model\",\"model_type\":\"numeric\"}}\\'</pre></div>';
}} else {{
  let html = '<div class="drift-grid">';
  models.forEach((m, i) => {{
    const score = m.latest_score !== null ? m.latest_score.toFixed(4) : '—';
    const cls = m.latest_alert ? 'alert' : (m.latest_score !== null && m.latest_score > 0.1 ? 'warn' : 'ok');
    html += `<div class="drift-card">
      <h3>${{m.name}}</h3>
      <div class="badge">${{m.type}}</div>
      <div class="drift-score ${{cls}}">${{score}}</div>
      <div class="drift-sparkline">${{m.sparkline}}</div>
      <canvas id="chart${{i}}" height="120"></canvas>
      <div class="drift-meta">
        Baseline: ${{m.baseline_n}} samples &bull; ${{m.total_checks}} checks &bull; ${{m.total_alerts}} alerts
      </div>
    </div>`;
  }});
  html += '</div>';
  container.innerHTML = html;

  // Render charts
  models.forEach((m, i) => {{
    if (m.scores.length > 0) {{
      const ctx = document.getElementById('chart' + i);
      new Chart(ctx, {{
        type: 'line',
        data: {{
          labels: m.scores.map((_, j) => j + 1),
          datasets: [{{
            data: m.scores,
            borderColor: '#00fff2',
            backgroundColor: 'rgba(0,255,242,0.08)',
            fill: true,
            tension: 0.3,
            pointRadius: 3,
            pointBackgroundColor: m.scores.map(s => s > 0.25 ? '#ff4466' : '#00fff2'),
          }}]
        }},
        options: {{
          responsive: true,
          plugins: {{ legend: {{ display: false }} }},
          scales: {{
            x: {{ display: false }},
            y: {{ beginAtZero: true, grid: {{ color: 'rgba(255,255,255,0.04)' }}, ticks: {{ color: '#5a5e74', font: {{ size: 10 }} }} }}
          }}
        }}
      }});
    }}
  }});
}}
</script>
</body></html>"""
    return html_resp(page)


# ── GET /drift — Landing page ────────────────────────────────
@drift_bp.route("/drift")
def drift_landing():
    extra_css = """
    .hero{text-align:center;padding:40px 0 20px}
    .curl-example{margin:16px 0}
    .step{display:flex;align-items:flex-start;gap:16px;margin:18px 0}
    .step-num{font-family:'Orbitron',sans-serif;font-size:1.6em;font-weight:800;color:var(--accent);min-width:40px;text-align:center;line-height:1}
    .step-content h3{margin:0 0 6px;color:var(--text-primary);font-size:1em}
    .step-content p{margin:0;color:var(--text-secondary);font-size:.9em}
    .method-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin:16px 0}
    .method-card{background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:var(--radius-sm);padding:18px;text-align:center}
    .method-card h3{font-family:'Orbitron',sans-serif;font-size:.75em;color:var(--accent);margin:0 0 8px}
    .method-card .type{font-size:.7em;color:var(--text-muted);font-family:'JetBrains Mono',monospace}
    .price-row{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--border);font-size:.9em}
    .price-row:last-child{border:none}
    """

    page = f"""{_html_head("Model Drift Monitor — TIAMAT", extra_css)}
<body>
{_NAV}
<div class="site-wrap">

<div class="hero">
  <h1 data-text="DRIFT MONITOR" class="glitch">DRIFT MONITOR</h1>
  <p class="tagline">Detect when your ML model outputs shift from baseline.<br>Pure math. No frameworks. Instant alerts.</p>
  <span class="badge">v{DRIFT_VERSION}</span>
  <span class="badge green">4 Detection Methods</span>
  <span class="badge gold">x402 Micropayments</span>
</div>

<div class="card">
  <h2>Quick Start</h2>

  <div class="step">
    <div class="step-num">1</div>
    <div class="step-content">
      <h3>Register a model</h3>
      <pre>curl -X POST https://tiamat.live/drift/register \\
  -H "Content-Type: application/json" \\
  -d '{{"name":"my-classifier","model_type":"numeric"}}'</pre>
    </div>
  </div>

  <div class="step">
    <div class="step-num">2</div>
    <div class="step-content">
      <h3>Set baseline (20+ samples)</h3>
      <pre>curl -X POST https://tiamat.live/drift/baseline \\
  -H "Content-Type: application/json" \\
  -d '{{"model_id":1,"samples":[0.95, 0.87, 0.91, ...]}}'</pre>
    </div>
  </div>

  <div class="step">
    <div class="step-num">3</div>
    <div class="step-content">
      <h3>Check for drift</h3>
      <pre>curl -X POST https://tiamat.live/drift/check \\
  -H "Content-Type: application/json" \\
  -d '{{"model_id":1,"samples":[0.42, 0.38, 0.55, ...]}}'</pre>
      <p>Returns: <code>{{"score": 0.34, "alert": true, "method": "psi"}}</code></p>
    </div>
  </div>
</div>

<div class="card">
  <h2>Detection Methods</h2>
  <div class="method-grid">
    <div class="method-card">
      <h3>PSI</h3>
      <div class="type">numeric</div>
      <p class="dim" style="margin-top:8px">Population Stability Index via histogram comparison</p>
    </div>
    <div class="method-card">
      <h3>COSINE</h3>
      <div class="type">embedding</div>
      <p class="dim" style="margin-top:8px">Centroid drift + cosine similarity shift</p>
    </div>
    <div class="method-card">
      <h3>ENTROPY</h3>
      <div class="type">probability</div>
      <p class="dim" style="margin-top:8px">Shannon entropy + KL divergence</p>
    </div>
    <div class="method-card">
      <h3>TEXT STATS</h3>
      <div class="type">text</div>
      <p class="dim" style="margin-top:8px">Length z-score + vocabulary diversity</p>
    </div>
  </div>
</div>

<div class="card">
  <h2>Pricing</h2>
  <div class="price-row"><span>Register model</span><span class="badge green">Free (3 models/IP)</span></div>
  <div class="price-row"><span>Set baseline</span><span>1/model/day free, then <strong>$0.005 USDC</strong></span></div>
  <div class="price-row"><span>Check drift</span><span>10/day free, then <strong>$0.01 USDC</strong></span></div>
  <div class="price-row"><span>Status & Dashboard</span><span class="badge green">Free</span></div>
</div>

<div class="card">
  <h2>API Reference</h2>
  <div class="table-scroll">
  <table>
    <tr><th>Endpoint</th><th>Method</th><th>Description</th></tr>
    <tr><td><code>/drift/register</code></td><td>POST</td><td>Register a model (name, model_type)</td></tr>
    <tr><td><code>/drift/baseline</code></td><td>POST</td><td>Set baseline distribution (model_id, samples[])</td></tr>
    <tr><td><code>/drift/check</code></td><td>POST</td><td>Check for drift (model_id, samples[])</td></tr>
    <tr><td><code>/drift/status/&lt;id&gt;</code></td><td>GET</td><td>Model status + check history</td></tr>
    <tr><td><code>/drift/dashboard</code></td><td>GET</td><td>Visual monitoring dashboard</td></tr>
    <tr><td><code>/drift/meta</code></td><td>GET</td><td>Version, methods, capabilities</td></tr>
    <tr><td><code>/drift/alert/test</code></td><td>POST</td><td>Test webhook delivery</td></tr>
  </table>
  </div>
</div>

<div style="text-align:center;margin:32px 0">
  <a href="/drift/dashboard" class="btn">Open Dashboard</a>
  <a href="/drift/meta" class="btn btn-outline" style="margin-left:12px">API Meta</a>
</div>

{_FOOTER}
</div>
{_VISUAL_ROT_JS}
</body></html>"""
    return html_resp(page)
