"""
TIAMAT Drift v2 — Production Flask Blueprint
=============================================
Registers on the main summarize_api.py app as ``drift_bp``.

Endpoints
---------
POST /api/drift
    Ingest a prediction from the Python SDK.
    Free-tier gate: max 10 models per API key.
    Redis key: drift:api_key:{key}:models  (SET of model_ids)
    On drift detected: fires Slack webhook if registered.

GET  /api/drift/status/<model_id>
    Return the last-seen drift state for a model.

POST /api/drift/slack/webhook
    Register a Slack incoming-webhook URL for an API key.
    Body: {"channel_url": "https://hooks.slack.com/services/..."}
    Redis key: drift:slack:{api_key}  (STRING)

POST /api/drift/webhook
    Register a generic customer callback URL.
    Body: {"callback_url": "https://example.com/hook"}
    Redis key: drift:webhook:{api_key}  (STRING)

Free / Pro tier
---------------
Free:  drift:api_key:{key}:models SET size < 10
Pro:   drift:tier:{api_key} == "pro"  → unlimited

Security
--------
- Slack webhook URLs restricted to https://hooks.slack.com/ prefix
- Generic callback URLs restricted to https://, blocking private IPs
- API key extracted from X-API-Key or Authorization: Bearer headers
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import redis
import requests
from flask import Blueprint, jsonify, request

# ── Logging ───────────────────────────────────────────────────────────────────

logger = logging.getLogger("drift_api")

# ── Blueprint ─────────────────────────────────────────────────────────────────

drift_bp = Blueprint("drift_v2_main", __name__)

# ── Redis singleton ───────────────────────────────────────────────────────────

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_r: Optional[redis.Redis] = None  # type: ignore[type-arg]

try:
    _r = redis.from_url(_REDIS_URL, decode_responses=True, socket_connect_timeout=3)  # type: ignore[assignment]
    _r.ping()  # type: ignore[union-attr]
    logger.info("drift_api: Redis connected %s", _REDIS_URL)
except Exception as _re:
    logger.warning("drift_api: Redis unavailable (%s) — in-process fallback active", _re)
    _r = None

# ── In-process fallback (used when Redis is down) ─────────────────────────────

_fallback_models: Dict[str, set] = {}
_fallback_webhooks: Dict[str, str] = {}
_fallback_slack: Dict[str, str] = {}
_fallback_drift_state: Dict[str, Dict] = {}

# ── Constants ─────────────────────────────────────────────────────────────────

_FREE_MODEL_LIMIT = 10
_DRIFT_THRESHOLD = 0.05      # fire alerts when drift_score >= this
_WEBHOOK_TIMEOUT = 8.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    """Extract API key from request headers; default to 'free'."""
    key = (
        request.headers.get("X-API-Key", "")
        or request.headers.get("Authorization", "").removeprefix("Bearer ")
    ).strip()
    return key or "free"


def _is_pro(api_key: str) -> bool:
    if _r is None:
        return False
    return _r.get(f"drift:tier:{api_key}") == "pro"  # type: ignore[return-value]


# ── Free-tier model limit (Redis SET: drift:api_key:{key}:models) ─────────────

def _check_model_limit(api_key: str, model_id: str) -> Optional[tuple]:
    """
    Enforce free-tier 10-model cap.

    Returns None if allowed, or (flask response, 402) if limit exceeded.
    """
    if _is_pro(api_key):
        return None

    models_key = f"drift:api_key:{api_key}:models"

    if _r is not None:
        already_in: bool = bool(_r.sismember(models_key, model_id))  # type: ignore[arg-type]
        if already_in:
            return None
        count: int = int(_r.scard(models_key))  # type: ignore[arg-type]
        if count >= _FREE_MODEL_LIMIT:
            return (
                jsonify({
                    "error": "free_tier_limit_exceeded",
                    "message": (
                        f"Free tier allows monitoring up to {_FREE_MODEL_LIMIT} models. "
                        "Upgrade to Pro at https://tiamat.live/drift#pricing "
                        "for unlimited model monitoring."
                    ),
                    "models_used": count,
                    "limit": _FREE_MODEL_LIMIT,
                    "upgrade_url": "https://tiamat.live/drift#pricing",
                }),
                402,
            )
        _r.sadd(models_key, model_id)  # type: ignore[misc]
        logger.info(
            "drift_api: New model registered — key=%s*** model=%s (%d/%d)",
            api_key[:6], model_id, count + 1, _FREE_MODEL_LIMIT,
        )
    else:
        # Fallback
        bucket = _fallback_models.setdefault(api_key, set())
        if model_id not in bucket:
            if len(bucket) >= _FREE_MODEL_LIMIT:
                return (
                    jsonify({
                        "error": "free_tier_limit_exceeded",
                        "message": f"Free tier allows up to {_FREE_MODEL_LIMIT} models.",
                        "models_used": len(bucket),
                        "limit": _FREE_MODEL_LIMIT,
                        "upgrade_url": "https://tiamat.live/drift#pricing",
                    }),
                    402,
                )
            bucket.add(model_id)

    return None


def _get_model_set(api_key: str) -> List[str]:
    """Return the list of tracked models for an API key."""
    if _r is not None:
        return sorted(_r.smembers(f"drift:api_key:{api_key}:models"))  # type: ignore[arg-type,return-value]
    return sorted(_fallback_models.get(api_key, set()))


# ── Webhook / Slack helpers ───────────────────────────────────────────────────

_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_private_ip(hostname: str) -> bool:
    """Return True if hostname resolves to a private/loopback address."""
    try:
        addr = ipaddress.ip_address(socket.gethostbyname(hostname))
        return any(addr in net for net in _PRIVATE_RANGES)
    except Exception:
        return True  # fail closed on resolution errors


def _validate_https_url(url: str, restrict_host: Optional[str] = None) -> Optional[str]:
    """
    Validate a URL for webhook registration.

    Returns an error string if invalid, None if valid.
    Blocks non-HTTPS, private IPs, and (optionally) wrong host prefix.
    """
    if not url:
        return "URL is required"
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "URL must use https://"
    if restrict_host and not parsed.netloc.startswith(restrict_host):
        return f"URL must be a {restrict_host} webhook URL"
    if _is_private_ip(parsed.hostname or ""):
        return "URL resolves to a private/loopback address (SSRF blocked)"
    return None


def _fire_webhook(url: str, payload: Dict[str, Any]) -> None:
    """POST payload to a customer webhook in a daemon thread."""
    def _send() -> None:
        try:
            resp = requests.post(
                url, json=payload, timeout=_WEBHOOK_TIMEOUT,
                headers={"Content-Type": "application/json", "User-Agent": "TIAMAT-Drift/2.0"},
            )
            logger.info("drift_api: Webhook delivered → %s  HTTP %s", url[:60], resp.status_code)
        except Exception as exc:
            logger.warning("drift_api: Webhook failed → %s  err=%s", url[:60], exc)

    threading.Thread(target=_send, daemon=True).start()


def _get_customer_webhook(api_key: str) -> Optional[str]:
    if _r is not None:
        return _r.get(f"drift:webhook:{api_key}")  # type: ignore[return-value]
    return _fallback_webhooks.get(api_key)


def _get_slack_webhook(api_key: str) -> Optional[str]:
    if _r is not None:
        return _r.get(f"drift:slack:{api_key}")  # type: ignore[return-value]
    return _fallback_slack.get(api_key)


def _fire_slack_alert(
    channel_url: str,
    model_id: str,
    drift_score: float,
    affected_features: List[str],
) -> None:
    """POST a Block Kit drift alert to a Slack incoming webhook."""
    pct = round(drift_score * 100, 1)
    feat_str = ", ".join(f"`{f}`" for f in affected_features[:5])
    if len(affected_features) > 5:
        feat_str += f" (+{len(affected_features) - 5} more)"
    feat_str = feat_str or "_none_"

    if drift_score >= 0.7:
        severity, emoji, color = "CRITICAL", "🔴", "#FF0000"
    elif drift_score >= 0.5:
        severity, emoji, color = "HIGH", "🟠", "#FF6600"
    elif drift_score >= 0.3:
        severity, emoji, color = "MEDIUM", "🟡", "#FFAA00"
    else:
        severity, emoji, color = "LOW", "🟢", "#00AA44"

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    message = {
        "attachments": [{
            "color": color,
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"{emoji} Drift Detected — {model_id}"},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Drift Score*\n`{drift_score:.3f}` ({pct}%)"},
                        {"type": "mrkdwn", "text": f"*Severity*\n{emoji} {severity}"},
                        {"type": "mrkdwn", "text": f"*Detected At*\n{ts}"},
                    ],
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Affected Features*\n{feat_str}"},
                },
                {
                    "type": "context",
                    "elements": [{
                        "type": "mrkdwn",
                        "text": (
                            "Powered by <https://tiamat.live/drift|TIAMAT Drift> • "
                            "<https://tiamat.live/drift#status|Dashboard>"
                        ),
                    }],
                },
            ],
        }]
    }

    def _send() -> None:
        try:
            resp = requests.post(channel_url, json=message, timeout=8,
                                 headers={"Content-Type": "application/json"})
            logger.info(
                "drift_api: Slack alert sent → model=%s drift=%.1f%% HTTP %s",
                model_id, pct, resp.status_code,
            )
        except Exception as exc:
            logger.warning("drift_api: Slack alert failed → model=%s err=%s", model_id, exc)

    threading.Thread(target=_send, daemon=True).start()


def _maybe_fire_alerts(api_key: str, model_id: str, drift_score: float, affected_features: List[str]) -> None:
    """Fire Slack and customer webhook alerts when drift is significant."""
    if drift_score < _DRIFT_THRESHOLD:
        return

    ts = datetime.now(timezone.utc).isoformat()
    event = {
        "event": "drift_detected",
        "model_id": model_id,
        "drift_score": drift_score,
        "affected_features": affected_features,
        "timestamp": ts,
    }

    # Generic customer webhook
    cb = _get_customer_webhook(api_key)
    if cb:
        _fire_webhook(cb, event)

    # Slack
    slack_url = _get_slack_webhook(api_key)
    if slack_url:
        _fire_slack_alert(slack_url, model_id, drift_score, affected_features)


# ── Routes ────────────────────────────────────────────────────────────────────

@drift_bp.route("/api/drift", methods=["POST"])
def ingest_prediction():
    """
    Receive a single prediction report from the Python SDK.

    Headers:
        X-API-Key   or   Authorization: Bearer <key>

    Body (JSON):
        model_id          str   required
        features          list  required
        prediction        list  required
        ground_truth      list  optional
        drift_score       float required  (computed by SDK via KS test)
        affected_features list  optional

    Returns:
        {drift_detected, confidence, affected_features}
        or 402 if free-tier model cap is exceeded.
    """
    api_key = _get_api_key()
    body = request.get_json(force=True, silent=True) or {}
    model_id = str(body.get("model_id", "")).strip()

    if not model_id:
        return jsonify({"error": "model_id is required"}), 400

    # Free-tier gate
    limit_err = _check_model_limit(api_key, model_id)
    if limit_err:
        return limit_err

    drift_score = float(body.get("drift_score", 0.0))
    affected_features: List[str] = body.get("affected_features", [])
    drift_detected = drift_score >= _DRIFT_THRESHOLD

    # Persist latest state for GET /api/drift/status/<model_id>
    state = json.dumps({
        "drift_detected": drift_detected,
        "drift_score": drift_score,
        "affected_features": affected_features,
        "last_seen": datetime.now(timezone.utc).isoformat(),
    })
    state_key = f"drift:state:{api_key}:{model_id}"
    if _r is not None:
        _r.set(state_key, state, ex=86400)  # type: ignore[misc]
    else:
        _fallback_drift_state[state_key] = json.loads(state)

    # Fire alerts
    if drift_detected:
        _maybe_fire_alerts(api_key, model_id, drift_score, affected_features)

    return jsonify({
        "drift_detected": drift_detected,
        "confidence": drift_score,
        "affected_features": affected_features,
    })


@drift_bp.route("/api/drift/status/<model_id>", methods=["GET"])
def drift_status(model_id: str):
    """Return the most recent drift state stored for a model."""
    api_key = (
        request.headers.get("X-API-Key")
        or request.args.get("api_key", "free")
    ).strip()

    state_key = f"drift:state:{api_key}:{model_id}"
    if _r is not None:
        raw = _r.get(state_key)  # type: ignore[misc]
        if raw:
            return jsonify(json.loads(str(raw)))
    elif state_key in _fallback_drift_state:
        return jsonify(_fallback_drift_state[state_key])

    return jsonify({
        "model_id": model_id,
        "drift_detected": False,
        "drift_score": 0.0,
        "affected_features": [],
        "last_seen": None,
        "message": "No data yet for this model.",
    })


@drift_bp.route("/api/drift/models", methods=["GET"])
def list_models():
    """List all models being monitored for this API key."""
    api_key = _get_api_key()
    models = _get_model_set(api_key)
    tier = "free"
    if _r is not None:
        tier = _r.get(f"drift:tier:{api_key}") or "free"  # type: ignore[assignment]

    return jsonify({
        "models": models,
        "count": len(models),
        "tier": tier,
        "limit": None if tier == "pro" else _FREE_MODEL_LIMIT,
        "slots_remaining": None if tier == "pro" else max(0, _FREE_MODEL_LIMIT - len(models)),
    })


@drift_bp.route("/api/drift/slack/webhook", methods=["POST"])
def register_slack_webhook():
    """
    Register a Slack incoming-webhook URL for this API key.

    Headers:
        X-API-Key   or   Authorization: Bearer <key>

    Body (JSON):
        {"channel_url": "https://hooks.slack.com/services/T.../B.../xxx"}

    Stores in Redis: drift:slack:{api_key} = channel_url
    On drift: a Block Kit alert is POSTed to this URL automatically.
    """
    api_key = _get_api_key()
    body = request.get_json(force=True, silent=True) or {}
    channel_url = str(body.get("channel_url", "")).strip()

    err = _validate_https_url(channel_url, restrict_host="hooks.slack.com")
    if err:
        return jsonify({"error": err}), 400

    if _r is not None:
        _r.set(f"drift:slack:{api_key}", channel_url)  # type: ignore[misc]
    else:
        _fallback_slack[api_key] = channel_url

    logger.info("drift_api: Slack webhook registered for key=%s***", api_key[:6])
    return jsonify({
        "success": True,
        "channel_url": channel_url,
        "api_key_prefix": api_key[:6] + "***",
        "message": (
            "Slack webhook registered. Drift alerts will be posted to your channel "
            "whenever drift_score >= 0.05 for any monitored model."
        ),
    })


@drift_bp.route("/api/drift/webhook", methods=["POST"])
def register_webhook():
    """
    Register a generic HTTPS callback URL for drift events.

    Headers:
        X-API-Key   or   Authorization: Bearer <key>

    Body (JSON):
        {"callback_url": "https://example.com/drift-alerts"}

    Stores in Redis: drift:webhook:{api_key} = callback_url
    """
    api_key = _get_api_key()
    body = request.get_json(force=True, silent=True) or {}
    callback_url = str(body.get("callback_url", "")).strip()

    err = _validate_https_url(callback_url)
    if err:
        return jsonify({"error": err}), 400

    if _r is not None:
        _r.set(f"drift:webhook:{api_key}", callback_url)  # type: ignore[misc]
    else:
        _fallback_webhooks[api_key] = callback_url

    logger.info("drift_api: Webhook registered for key=%s*** url=%s", api_key[:6], callback_url[:60])
    return jsonify({
        "success": True,
        "callback_url": callback_url,
        "message": (
            "Webhook registered. A JSON POST will be sent to your URL "
            "whenever drift is detected for any monitored model."
        ),
    })


@drift_bp.route("/api/drift/health", methods=["GET"])
def drift_health():
    """Health check for the drift subsystem."""
    redis_ok = False
    if _r is not None:
        try:
            _r.ping()  # type: ignore[misc]
            redis_ok = True
        except Exception:
            pass
    return jsonify({
        "status": "ok",
        "redis": redis_ok,
        "service": "tiamat-drift-v2",
        "free_model_limit": _FREE_MODEL_LIMIT,
        "drift_threshold": _DRIFT_THRESHOLD,
    })
