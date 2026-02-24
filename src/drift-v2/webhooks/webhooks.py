"""
Drift v2 — Webhook Receiver
Receives drift events, logs them, and forwards to customer-configured webhooks.
"""

import os
import logging
import logging.handlers
import ipaddress
from pathlib import Path
from urllib.parse import urlparse

import redis
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------------
# Logging setup
# ------------------------------------------------------------------

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "drift.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("drift.webhooks")

# ------------------------------------------------------------------
# Redis
# ------------------------------------------------------------------

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_redis: redis.Redis | None  # type: ignore[type-arg]
try:
    _redis = redis.from_url(_REDIS_URL, decode_responses=True)  # type: ignore[assignment]
    _redis.ping()
    logger.info("Redis connected: %s", _REDIS_URL)
except Exception as exc:
    logger.warning("Redis unavailable — customer webhook forwarding disabled: %s", exc)
    _redis = None

# ------------------------------------------------------------------
# Flask app
# ------------------------------------------------------------------

app = Flask(__name__)

_DRIFT_API_SECRET = os.getenv("DRIFT_API_SECRET", "")
if not _DRIFT_API_SECRET:
    logger.warning(
        "DRIFT_API_SECRET not set — all endpoints require auth but none will pass. "
        "Set DRIFT_API_SECRET or DRIFT_AUTH_DISABLED=1 to run without auth."
    )
_AUTH_DISABLED = os.getenv("DRIFT_AUTH_DISABLED", "") == "1"


def _auth_ok(req) -> bool:  # type: ignore[no-untyped-def]
    """Validate X-API-Key header against DRIFT_API_SECRET."""
    if _AUTH_DISABLED:
        return True
    if not _DRIFT_API_SECRET:
        return False  # no secret configured and auth not explicitly disabled
    return req.headers.get("X-API-Key", "") == _DRIFT_API_SECRET


def _validate_webhook_url(url: str) -> str | None:
    """Validate webhook URL. Returns error message or None if valid."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL"
    if parsed.scheme not in ("https",):
        return "Only https:// webhook URLs are allowed"
    if not parsed.hostname:
        return "Missing hostname"
    hostname = parsed.hostname
    # Block loopback, private, and link-local IPs
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return "Webhook URL must point to a public IP"
    except ValueError:
        pass  # hostname is a domain, not an IP — ok
    # Block known internal hostnames
    blocked = ("localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "[::1]")
    if hostname.lower() in blocked:
        return "Webhook URL must point to a public host"
    return None


def _forward_to_customer(api_key: str, payload: dict) -> None:
    """
    Look up customer webhook URL in Redis and forward the drift event.
    Redis key: drift:webhook:{api_key}
    """
    if _redis is None:
        return
    webhook_url: str | None = _redis.get(f"drift:webhook:{api_key}")  # type: ignore[union-attr,assignment]
    if not webhook_url:
        return
    try:
        resp = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json", "X-Drift-Event": "drift"},
            timeout=5,
        )
        if resp.ok:
            logger.info("Forwarded to customer webhook %s: %s", api_key, webhook_url)
        else:
            logger.warning("Customer webhook %s returned %s", webhook_url, resp.status_code)
    except Exception as exc:
        logger.error("Customer webhook forward failed for %s: %s", api_key, exc)


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@app.post("/drift")
def receive_drift():
    """Receive a drift event from the SDK."""
    if not _auth_ok(request):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "empty or invalid JSON body"}), 400

    api_key = request.headers.get("X-API-Key", "anonymous")
    model_id = body.get("model_id", "unknown")
    status = body.get("status", "UNKNOWN")
    drift_score = body.get("drift_score", 0.0)
    affected = body.get("affected_features", [])

    logger.info(
        "DRIFT EVENT | api_key=%s model=%s status=%s score=%.4f features=%s",
        api_key,
        model_id,
        status,
        drift_score,
        affected,
    )

    _forward_to_customer(api_key, body)

    return jsonify({"received": True, "model_id": model_id, "status": status}), 200


@app.post("/webhooks/register")
def register_webhook():
    """Register a customer webhook URL. Body: {api_key, webhook_url}"""
    if not _auth_ok(request):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    api_key = body.get("api_key")
    webhook_url = body.get("webhook_url")

    if not api_key or not webhook_url:
        return jsonify({"error": "api_key and webhook_url required"}), 400

    url_error = _validate_webhook_url(webhook_url)
    if url_error:
        return jsonify({"error": url_error}), 400

    if _redis is None:
        return jsonify({"error": "Redis unavailable"}), 503

    _redis.set(f"drift:webhook:{api_key}", webhook_url)
    logger.info("Registered webhook for %s → %s", api_key, webhook_url)
    return jsonify({"registered": True, "api_key": api_key}), 200


@app.get("/health")
def health():
    redis_ok = False
    if _redis:
        try:
            _redis.ping()
            redis_ok = True
        except Exception:
            pass
    return jsonify({"status": "ok", "redis": redis_ok}), 200


if __name__ == "__main__":
    port = int(os.getenv("WEBHOOKS_PORT", 5050))
    app.run(host="127.0.0.1", port=port, debug=False)
