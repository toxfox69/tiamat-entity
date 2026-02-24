"""
Drift v2 — Webhook Delivery Module
====================================
Handles outbound webhook delivery to customer-configured URLs.

Redis key layout:
    drift:webhook:{api_key}   →  https://customer-server.example.com/hook

Payload schema (POST to customer URL):
    {
        "model_id":         str,
        "drift_score":      float,
        "affected_features": list[str],
        "timestamp":        int,          # Unix epoch
        "confidence":       int,          # 0-100
        "status":           str,          # "ALERT" | "WARN" | "OK"
        "feature_scores":   dict,         # per-feature KS statistics
        "api_key":          str,          # sender's key (for routing on their side)
    }

Public API:
    register_webhook(api_key, webhook_url) → None
    deregister_webhook(api_key)            → None
    get_webhook(api_key)                   → str | None
    dispatch(api_key, event)               → bool
    make_drift_event(...)                  → dict

Flask blueprint ``webhooks_bp`` (optional) mounts:
    POST /webhooks/register
    DELETE /webhooks/register
    GET  /webhooks/ping
"""

from __future__ import annotations

import ipaddress
import logging
import os
import time
from typing import Any
from urllib.parse import urlparse

import requests
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis setup — graceful fallback to in-memory dict
# ---------------------------------------------------------------------------
try:
    import redis as _redis_lib  # type: ignore[import-untyped]

    _REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    _r: Any = _redis_lib.from_url(_REDIS_URL, decode_responses=True)
    _r.ping()
    logger.info("webhooks: Redis connected at %s", _REDIS_URL)
    _USE_REDIS = True
except Exception as exc:
    logger.warning("webhooks: Redis unavailable (%s) — using in-memory store", exc)
    _r = {}
    _USE_REDIS = False

# ---------------------------------------------------------------------------
# Redis helpers (unified API over both backends)
# ---------------------------------------------------------------------------

_PREFIX = "drift:webhook"


def _set(api_key: str, url: str) -> None:
    key = f"{_PREFIX}:{api_key}"
    if _USE_REDIS:
        _r.set(key, url)
    else:
        _r[key] = url  # type: ignore[index]


def _get(api_key: str) -> str | None:
    key = f"{_PREFIX}:{api_key}"
    if _USE_REDIS:
        return _r.get(key)  # type: ignore[no-any-return]
    return _r.get(key)  # type: ignore[return-value]


def _delete(api_key: str) -> None:
    key = f"{_PREFIX}:{api_key}"
    if _USE_REDIS:
        _r.delete(key)
    else:
        _r.pop(key, None)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# URL validation (SSRF protection)
# ---------------------------------------------------------------------------

_BLOCKED_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "[::1]", "::1"}
)


def _validate_webhook_url(url: str) -> str | None:
    """Return an error string if the URL is invalid/unsafe, or None if ok."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "invalid URL"

    if parsed.scheme not in ("https",):
        return "only https:// webhook URLs are accepted"

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return "missing hostname"

    if hostname in _BLOCKED_HOSTS:
        return "webhook URL must point to a public host"

    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return "webhook URL must point to a public IP"
    except ValueError:
        pass  # domain name — ok

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_webhook(api_key: str, webhook_url: str) -> None:
    """Persist a customer webhook URL for the given API key."""
    _set(api_key, webhook_url)
    logger.info("webhook registered: api_key=%s → %s", api_key, webhook_url)


def deregister_webhook(api_key: str) -> None:
    """Remove the stored webhook URL for the given API key."""
    _delete(api_key)
    logger.info("webhook deregistered: api_key=%s", api_key)


def get_webhook(api_key: str) -> str | None:
    """Return the stored webhook URL for an API key, or None."""
    return _get(api_key)


def make_drift_event(
    model_id: str,
    drift_score: float,
    affected_features: list[str],
    confidence: int = 0,
    status: str = "ALERT",
    feature_scores: dict | None = None,
    api_key: str = "",
) -> dict:
    """Construct the canonical drift event payload."""
    return {
        "model_id": model_id,
        "drift_score": round(drift_score, 4),
        "affected_features": affected_features,
        "timestamp": int(time.time()),
        "confidence": confidence,
        "status": status,
        "feature_scores": feature_scores or {},
        "api_key": api_key,
    }


def dispatch(api_key: str, event: dict, timeout: float = 5.0) -> bool:
    """
    POST the drift event to the customer's registered webhook URL.

    Returns True on success (2xx), False otherwise.
    Non-blocking errors are logged but not re-raised.
    """
    webhook_url = get_webhook(api_key)
    if not webhook_url:
        logger.debug("dispatch: no webhook registered for api_key=%s", api_key)
        return False

    try:
        resp = requests.post(
            webhook_url,
            json=event,
            headers={
                "Content-Type": "application/json",
                "X-Drift-Event": "drift",
                "X-Drift-Model": event.get("model_id", ""),
            },
            timeout=timeout,
        )
        if resp.ok:
            logger.info(
                "dispatch: webhook delivered to %s for model=%s",
                webhook_url,
                event.get("model_id"),
            )
            return True
        logger.warning(
            "dispatch: webhook %s returned %s — %s",
            webhook_url,
            resp.status_code,
            resp.text[:200],
        )
        return False
    except requests.exceptions.Timeout:
        logger.warning("dispatch: webhook %s timed out", webhook_url)
        return False
    except Exception as exc:
        logger.error("dispatch: webhook %s error — %s", webhook_url, exc)
        return False


# ---------------------------------------------------------------------------
# Flask Blueprint
# ---------------------------------------------------------------------------

webhooks_bp = Blueprint("webhooks", __name__)


@webhooks_bp.route("/register", methods=["POST"])
def route_register():
    """Register or update a webhook URL.

    Body (JSON):
        {api_key: str, webhook_url: str}

    Returns:
        200 {registered: true}
        400 {error: str}
    """
    body: dict = request.get_json(silent=True) or {}
    api_key = body.get("api_key", "").strip()
    webhook_url = body.get("webhook_url", "").strip()

    if not api_key:
        return jsonify({"error": "api_key required"}), 400
    if not webhook_url:
        return jsonify({"error": "webhook_url required"}), 400

    url_error = _validate_webhook_url(webhook_url)
    if url_error:
        return jsonify({"error": url_error}), 400

    register_webhook(api_key, webhook_url)
    return jsonify({"registered": True, "api_key": api_key}), 200


@webhooks_bp.route("/register", methods=["DELETE"])
def route_deregister():
    """Remove a registered webhook.

    Body (JSON):
        {api_key: str}
    """
    body: dict = request.get_json(silent=True) or {}
    api_key = body.get("api_key", "").strip()
    if not api_key:
        return jsonify({"error": "api_key required"}), 400
    deregister_webhook(api_key)
    return jsonify({"deregistered": True}), 200


@webhooks_bp.route("/ping", methods=["GET"])
def route_ping():
    """Health check — confirms webhook module is live."""
    return jsonify({"status": "ok", "redis": _USE_REDIS}), 200
