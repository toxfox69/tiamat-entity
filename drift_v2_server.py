"""
Drift v2 Server — Flask API for ML drift detection.

Endpoints:
  POST /drift/log                  — log a prediction, get drift result
  GET  /drift/status/<api_key>     — recent drifts for a key
  GET  /drift/health               — health check

Free/Pro routing (Redis-backed):
  - Free: up to 10 distinct model_ids per api_key. 11th model → 403.
  - Pro:  unlimited models (api_key in REDIS_SET "drift:pro_keys").

Slack:
  - If SLACK_WEBHOOK env var is set, drift alerts POST to it globally.
  - Per-customer webhooks: store "drift:webhook:<api_key>" in Redis.

Run:
  python drift_v2_server.py            # port 9000
  DRIFT_PORT=8080 python drift_v2_server.py

Rebuild:
  kill $(cat /tmp/drift_v2.pid 2>/dev/null); \
  cd /root/.automaton && python drift_v2_server.py &
  echo $! > /tmp/drift_v2.pid
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(__file__))  # ensure sdk is importable

from flask import Flask, jsonify, request

import drift_v2_sdk as sdk

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [drift-v2] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis (optional — falls back to in-process dict if unavailable)
# ---------------------------------------------------------------------------
try:
    import redis as _redis

    _r = _redis.Redis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        db=int(os.getenv("REDIS_DB", 2)),
        decode_responses=True,
        socket_connect_timeout=2,
    )
    _r.ping()
    log.info("Redis connected — free/pro routing active")
    _REDIS_OK = True
except Exception as exc:
    log.warning("Redis unavailable (%s) — using in-process dict for tier tracking", exc)
    _REDIS_OK = False
    _r = None  # type: ignore[assignment]

# In-process fallback: {api_key: set_of_model_ids}
_LOCAL_MODELS: Dict[str, set] = {}
_LOCAL_PRO: set = set()


FREE_MODEL_LIMIT = 10


def _is_pro(api_key: str) -> bool:
    if _REDIS_OK:
        return bool(_r.sismember("drift:pro_keys", api_key))
    return api_key in _LOCAL_PRO


def _register_model(api_key: str, model_id: str) -> Tuple[bool, int]:
    """
    Register model_id under api_key.
    Returns (allowed: bool, current_count: int).
    Free tier: reject if this would be the 11th distinct model.
    """
    if _is_pro(api_key):
        return True, -1

    if _REDIS_OK:
        key = f"drift:models:{api_key}"
        _r.sadd(key, model_id)
        count = _r.scard(key)
        # expire after 30 days of inactivity — reset on any activity
        _r.expire(key, 30 * 86400)
        return count <= FREE_MODEL_LIMIT, int(count)
    else:
        if api_key not in _LOCAL_MODELS:
            _LOCAL_MODELS[api_key] = set()
        _LOCAL_MODELS[api_key].add(model_id)
        count = len(_LOCAL_MODELS[api_key])
        return count <= FREE_MODEL_LIMIT, count


def _get_model_count(api_key: str) -> int:
    if _REDIS_OK:
        return int(_r.scard(f"drift:models:{api_key}") or 0)
    return len(_LOCAL_MODELS.get(api_key, set()))


def _get_customer_webhook(api_key: str) -> Optional[str]:
    if _REDIS_OK:
        return _r.get(f"drift:webhook:{api_key}")
    return None


def _set_customer_webhook(api_key: str, webhook_url: str) -> None:
    if _REDIS_OK:
        _r.set(f"drift:webhook:{api_key}", webhook_url)


# ---------------------------------------------------------------------------
# Slack alerting
# ---------------------------------------------------------------------------
try:
    import requests as _req_lib
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

_GLOBAL_SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK", "").strip()


def _post_slack(webhook_url: str, payload: Dict[str, Any]) -> bool:
    if not _HAS_REQUESTS or not webhook_url:
        return False
    try:
        resp = _req_lib.post(webhook_url, json=payload, timeout=5)
        return resp.ok
    except Exception as exc:
        log.warning("Slack POST failed: %s", exc)
        return False


def _slack_drift_alert(
    api_key: str,
    model_id: str,
    ks_stat: float,
    n_ref: int,
    n_cur: int,
) -> None:
    """Fire Slack alert to global webhook and/or per-customer webhook."""
    masked_key = api_key[:8] + "..." if len(api_key) > 8 else api_key
    text = (
        f":rotating_light: *Drift Detected*\n"
        f"• Model: `{model_id}`\n"
        f"• KS statistic: `{ks_stat:.4f}` (p<0.05)\n"
        f"• Reference samples: {n_ref}  |  Current samples: {n_cur}\n"
        f"• API key: `{masked_key}`\n"
        f"• Time: <!date^{int(time.time())}^{{date_time}}|now>"
    )
    payload = {
        "text": text,
        "attachments": [{
            "color": "#ff4444",
            "fields": [
                {"title": "Model", "value": model_id, "short": True},
                {"title": "KS Stat", "value": str(round(ks_stat, 4)), "short": True},
            ],
        }],
    }

    sent = False
    if _GLOBAL_SLACK_WEBHOOK:
        sent = _post_slack(_GLOBAL_SLACK_WEBHOOK, payload)
        log.info("Global Slack alert: %s (model=%s ks=%.4f)", "ok" if sent else "FAIL", model_id, ks_stat)

    customer_hook = _get_customer_webhook(api_key)
    if customer_hook and customer_hook != _GLOBAL_SLACK_WEBHOOK:
        ok = _post_slack(customer_hook, payload)
        log.info("Customer Slack alert: %s (key=%s)", "ok" if ok else "FAIL", masked_key)


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB


def _err(msg: str, code: int) -> Any:
    return jsonify({"error": msg}), code


# ---------------------------------------------------------------------------
# POST /drift/log
# ---------------------------------------------------------------------------
@app.route("/drift/log", methods=["POST"])
def drift_log():
    data = request.get_json(force=True, silent=True)
    if not data:
        return _err("Invalid JSON body", 400)

    model_id = data.get("model_id", "").strip()
    features = data.get("features", {})
    prediction = data.get("prediction")
    ground_truth = data.get("ground_truth")
    api_key = data.get("api_key", "").strip()

    # --- Validation ---
    if not model_id:
        return _err("model_id is required", 400)
    if not api_key:
        return _err("api_key is required", 400)
    if prediction is None:
        return _err("prediction is required", 400)
    try:
        prediction = float(prediction)
    except (TypeError, ValueError):
        return _err("prediction must be a number", 400)
    if ground_truth is not None:
        try:
            ground_truth = float(ground_truth)
        except (TypeError, ValueError):
            return _err("ground_truth must be a number or null", 400)
    if not isinstance(features, dict):
        return _err("features must be a JSON object", 400)

    # --- Free/Pro tier check ---
    allowed, model_count = _register_model(api_key, model_id)
    if not allowed:
        return _err(
            f"Free tier limit reached: {FREE_MODEL_LIMIT} models max. "
            "Upgrade to Pro at https://tiamat.live/pay for unlimited models.",
            403,
        )

    # --- Log prediction + drift check ---
    result = sdk.log_prediction(
        model_id=model_id,
        features=features,
        prediction=prediction,
        ground_truth=ground_truth,
        api_key=api_key,
    )

    # --- Alert if drift detected ---
    if result.get("drift_detected"):
        _slack_drift_alert(
            api_key=api_key,
            model_id=model_id,
            ks_stat=result.get("ks_statistic", 0.0),
            n_ref=result.get("n_reference", 0),
            n_cur=result.get("n_current", 0),
        )

    result["tier"] = "pro" if _is_pro(api_key) else "free"
    result["model_count"] = model_count
    return jsonify(result), 200


# ---------------------------------------------------------------------------
# GET /drift/status/<api_key>
# ---------------------------------------------------------------------------
@app.route("/drift/status/<path:api_key>", methods=["GET"])
def drift_status(api_key: str):
    if not api_key:
        return _err("api_key required in path", 400)

    model_id = request.args.get("model_id") or None
    status = sdk.get_drift_status(api_key, model_id)

    return jsonify({
        "api_key": api_key[:8] + "...",
        "tier": "pro" if _is_pro(api_key) else "free",
        "model_count": _get_model_count(api_key),
        "free_model_limit": FREE_MODEL_LIMIT,
        "models": status,
        "timestamp": time.time(),
    }), 200


# ---------------------------------------------------------------------------
# POST /drift/webhook  — let customers register their Slack webhook
# ---------------------------------------------------------------------------
@app.route("/drift/webhook", methods=["POST"])
def drift_webhook_register():
    data = request.get_json(force=True, silent=True) or {}
    api_key = data.get("api_key", "").strip()
    webhook_url = data.get("webhook_url", "").strip()

    if not api_key or not webhook_url:
        return _err("api_key and webhook_url are required", 400)
    if not webhook_url.startswith("https://hooks.slack.com/"):
        return _err("webhook_url must be a valid Slack webhook URL", 400)

    _set_customer_webhook(api_key, webhook_url)
    return jsonify({"ok": True, "message": "Slack webhook registered"}), 200


# ---------------------------------------------------------------------------
# GET /drift/health
# ---------------------------------------------------------------------------
@app.route("/drift/health", methods=["GET"])
def drift_health():
    return jsonify({
        "status": "ok",
        "redis": _REDIS_OK,
        "scipy": sdk._HAS_SCIPY,
        "ts": time.time(),
    }), 200


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("DRIFT_PORT", 9000))
    log.info("Drift v2 server starting on port %d", port)
    app.run(host="127.0.0.1", port=port, debug=False)
