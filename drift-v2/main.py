#!/usr/bin/env python3
"""
Drift v2 — FastAPI Server (port 8083)
======================================
Wires together:
  sdk/drift_monitor_sdk.py    — Python SDK (KS-test drift client)
  slack/slack_webhook.py      — Slack OAuth + formatted alerts
  webhooks/webhooks.py        — Drift event receiver + customer webhook forwarder
  limits/limits.py            — Redis free-tier rate limiter (3 models / 30 days)

Endpoints:
  POST /log               Log predictions; triggers alerts + webhook forwarding
  POST /webhook           Receive drift events from SDK or external sources
  GET  /slack/install     Start Slack OAuth install flow
  GET  /slack/oauth       Slack OAuth callback
  GET  /health            Service health (Redis, Slack config, version)
"""

from __future__ import annotations

import os
import sys
import logging
import logging.handlers
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Path setup — let Python find the sub-package modules
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
for _sub in ("sdk", "slack", "webhooks", "limits"):
    _p = str(BASE_DIR / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            LOG_DIR / "drift-main.log", maxBytes=10 * 1024 * 1024, backupCount=5
        ),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("drift.main")

# ---------------------------------------------------------------------------
# Import component modules
# ---------------------------------------------------------------------------

# slack/slack_webhook.py — SlackNotifier with send_alert() + oauth_connect()
from slack_webhook import SlackNotifier  # noqa: E402

# limits/limits.py — check_and_increment() atomic rate-limit + get_limit_info()
from limits import check_and_increment, get_limit_info  # noqa: E402

# webhooks/webhooks.py — _forward_to_customer() posts to customer-registered URLs
try:
    from webhooks import _forward_to_customer as _fwd_customer  # type: ignore[import-untyped]
    log.info("webhooks._forward_to_customer loaded")
except Exception as _exc:
    log.warning("Could not import _forward_to_customer from webhooks: %s", _exc)

    def _fwd_customer(api_key: str, _payload: dict) -> None:  # type: ignore[misc]
        log.debug("webhook forwarder unavailable — skipping for api_key=%s", api_key)


# ---------------------------------------------------------------------------
# Shared Slack notifier (reads SLACK_WEBHOOK_URL from env)
# ---------------------------------------------------------------------------

_slack = SlackNotifier()

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

PORT = int(os.getenv("DRIFT_PORT", "8083"))

app = FastAPI(
    title="Drift v2",
    description=(
        "ML model drift monitoring: log predictions, receive drift events, "
        "get Slack alerts, and forward to your webhooks."
    ),
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class LogRequest(BaseModel):
    """Prediction log sent by SDK users."""

    api_key: str = Field(..., description="API key for rate-limit tracking")
    model_id: str = Field(..., description="Unique model / pipeline identifier")
    predictions: List[Any] = Field(
        ...,
        description=(
            "Prediction batch. Numeric: list[float]. "
            "Embedding: list[list[float]]. Text: list[str]."
        ),
    )
    # Drift indicators — computed client-side via drift_monitor_sdk
    status: str = Field("OK", description="ALERT | WARN | OK")
    drift_score: float = Field(0.0, ge=0.0, description="Drift magnitude (PSI, cosine, etc.)")
    confidence: int = Field(0, ge=0, le=100, description="Detection confidence 0–100")
    affected_features: List[str] = Field(default_factory=list)
    extra: Optional[Dict[str, Any]] = Field(None, description="Any additional metadata")


class WebhookEventPayload(BaseModel):
    """Drift event posted to /webhook."""

    api_key: str = Field("anonymous", description="Sender API key")
    model_id: str = Field(..., description="Model identifier")
    status: str = Field("ALERT", description="ALERT | WARN | OK")
    drift_score: float = Field(0.0)
    confidence: int = Field(0)
    affected_features: List[str] = Field(default_factory=list)
    extra: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post(
    "/log",
    summary="Log model predictions and trigger drift alerts",
    tags=["core"],
)
async def log_predictions(payload: LogRequest):
    """
    Receive a batch of model predictions from an SDK user.

    - Enforces the **free tier** limit (3 models / 30-day window via Redis).
    - Logs the event to `logs/drift-main.log`.
    - Sends a **Slack alert** when `status` is ALERT or WARN and
      `SLACK_WEBHOOK_URL` is configured.
    - Forwards the event to the customer's **registered webhook** (if any)
      via the Redis-backed forwarder in `webhooks/webhooks.py`.

    Returns the logged event summary plus current rate-limit usage.
    """
    allowed, _ = check_and_increment(payload.api_key)
    if not allowed:
        info = get_limit_info(payload.api_key)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "free tier model limit reached",
                "upgrade": "https://tiamat.live/#pricing",
                "limit_info": info,
            },
        )

    log.info(
        "LOG | api_key=%s model=%s status=%s score=%.4f n_predictions=%d",
        payload.api_key,
        payload.model_id,
        payload.status,
        payload.drift_score,
        len(payload.predictions),
    )

    if payload.status in ("ALERT", "WARN"):
        if _slack.webhook_url:
            sent = _slack.send_alert(
                model_id=payload.model_id,
                drift_score=payload.drift_score,
                confidence=payload.confidence,
                affected_features=payload.affected_features,
                status=payload.status,
                extra_fields=payload.extra,
            )
            log.info("Slack alert sent=%s for model=%s", sent, payload.model_id)
        else:
            log.debug("Slack not configured — skipping alert for model=%s", payload.model_id)

    _fwd_customer(payload.api_key, {
        "model_id": payload.model_id,
        "status": payload.status,
        "drift_score": payload.drift_score,
        "confidence": payload.confidence,
        "affected_features": payload.affected_features,
    })

    return {
        "logged": True,
        "model_id": payload.model_id,
        "status": payload.status,
        "sample_count": len(payload.predictions),
        "limit_info": get_limit_info(payload.api_key),
    }


@app.post(
    "/webhook",
    summary="Receive a drift event",
    tags=["core"],
)
async def receive_webhook(
    payload: WebhookEventPayload,
    x_api_key: str = Header(default=""),
):
    """
    Receive a drift event — e.g., fired by the SDK's alert mechanism or
    sent directly from your pipeline.

    - Sends a **Slack alert** for ALERT / WARN events.
    - Forwards to the customer's registered webhook.
    """
    api_key = x_api_key or payload.api_key

    log.info(
        "WEBHOOK | api_key=%s model=%s status=%s score=%.4f",
        api_key,
        payload.model_id,
        payload.status,
        payload.drift_score,
    )

    if payload.status in ("ALERT", "WARN") and _slack.webhook_url:
        _slack.send_alert(
            model_id=payload.model_id,
            drift_score=payload.drift_score,
            confidence=payload.confidence,
            affected_features=payload.affected_features,
            status=payload.status,
            extra_fields=payload.extra,
        )

    _fwd_customer(api_key, payload.model_dump())

    return {
        "received": True,
        "model_id": payload.model_id,
        "status": payload.status,
    }


@app.get(
    "/slack/install",
    summary="Start Slack OAuth install flow",
    response_class=HTMLResponse,
    tags=["slack"],
)
async def slack_install():
    """
    Redirect to Slack's OAuth authorization URL.
    Requires `SLACK_CLIENT_ID` and `SLACK_REDIRECT_URI` in the environment.
    Falls back to a configuration guidance page when they're absent.
    """
    client_id = os.getenv("SLACK_CLIENT_ID", "")
    redirect_uri = os.getenv(
        "SLACK_REDIRECT_URI",
        f"http://localhost:{PORT}/slack/oauth",
    )
    scopes = "incoming-webhook,chat:write"

    if not client_id:
        return HTMLResponse(
            content="""<!DOCTYPE html>
<html>
<head><title>Drift v2 — Slack Setup</title>
<style>
  body { font-family: 'JetBrains Mono', monospace; background: #0a0a0a;
         color: #00ff88; padding: 2rem; line-height: 1.6; }
  code { background: #1a1a2e; padding: 0.2em 0.4em; border-radius: 3px; }
  a    { color: #00ccff; }
</style></head>
<body>
  <h2>Drift v2 — Slack Integration</h2>
  <p>To enable the full Slack OAuth flow, set these environment variables:</p>
  <ul>
    <li><code>SLACK_CLIENT_ID</code> — from your Slack app settings</li>
    <li><code>SLACK_CLIENT_SECRET</code> — from your Slack app settings</li>
    <li><code>SLACK_REDIRECT_URI</code> — must match what Slack has on file</li>
  </ul>
  <p>For quick setup, skip OAuth and set <code>SLACK_WEBHOOK_URL</code>
     directly in your <code>.env</code> file.</p>
  <p><a href="/docs">API Docs</a></p>
</body>
</html>""",
            status_code=200,
        )

    auth_url = (
        f"https://slack.com/oauth/v2/authorize"
        f"?client_id={client_id}"
        f"&scope={scopes}"
        f"&redirect_uri={redirect_uri}"
    )
    log.info("Redirecting to Slack OAuth: %s", auth_url)
    return RedirectResponse(url=auth_url)


@app.get(
    "/slack/oauth",
    summary="Slack OAuth callback",
    tags=["slack"],
)
async def slack_oauth(code: str = "", error: str = ""):
    """
    Handle the OAuth redirect callback from Slack.
    Exchanges the auth code via `SlackNotifier.oauth_connect()`.
    """
    if error:
        log.warning("Slack OAuth error: %s", error)
        raise HTTPException(status_code=400, detail=f"Slack OAuth error: {error}")

    if not code:
        raise HTTPException(
            status_code=400,
            detail="Missing 'code' query parameter from Slack redirect",
        )

    notifier = SlackNotifier()
    token = notifier.oauth_connect(workspace_url="https://slack.com")
    log.info("Slack OAuth callback complete: token prefix=%s", token[:12] + "...")

    return {
        "status": "connected",
        "message": "Slack workspace linked to Drift v2.",
        "token_prefix": token[:12] + "...",
        "next_step": (
            "Set SLACK_WEBHOOK_URL in your .env to start receiving drift alerts."
        ),
    }


@app.get(
    "/health",
    summary="Service health check",
    tags=["ops"],
)
async def health():
    """
    Return service health including Redis connectivity and Slack configuration.
    Always returns HTTP 200 — check `redis` field to detect degraded mode.
    """
    redis_ok = False
    try:
        from limits import _redis_client as _r  # type: ignore[import-untyped]
        if _r is not None:
            _r.ping()
            redis_ok = True
    except Exception as exc:
        log.debug("Health: Redis unavailable — %s", exc)

    return {
        "status": "ok",
        "version": "2.0.0",
        "redis": redis_ok,
        "slack_configured": bool(_slack.webhook_url),
        "port": PORT,
        "free_tier": {
            "model_limit": int(os.getenv("FREE_MODEL_LIMIT", "3")),
            "window_days": int(os.getenv("RATE_WINDOW_DAYS", "30")),
        },
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("Starting Drift v2 on 0.0.0.0:%d", PORT)
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False, log_level="info")
