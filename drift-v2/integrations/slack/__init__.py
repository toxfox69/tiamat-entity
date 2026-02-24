"""
Drift v2 — Slack Integration
=============================
Provides:
  * Flask blueprint (slack_bp) with OAuth install/callback routes
  * SlackAlerter: send formatted drift alerts with fix suggestions
  * Token persistence to tokens.json

Mount the blueprint in your Flask app:
    from integrations.slack import slack_bp
    app.register_blueprint(slack_bp, url_prefix="/slack")

Then the following routes are available:
    GET  /slack/install   → redirect to Slack OAuth page
    GET  /slack/oauth     → OAuth callback, exchanges code for token
    POST /slack/test      → send a test alert (internal use only)
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from flask import Blueprint, jsonify, redirect, request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token storage path
# ---------------------------------------------------------------------------
_TOKENS_FILE = Path(__file__).parent / "tokens.json"


def _load_tokens() -> dict:
    try:
        return json.loads(_TOKENS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_tokens(tokens: dict) -> None:
    _TOKENS_FILE.write_text(json.dumps(tokens, indent=2))


# ---------------------------------------------------------------------------
# Fix suggestions — indexed by feature characteristics
# ---------------------------------------------------------------------------

_FIX_SUGGESTIONS = {
    "ALERT": [
        "Retrain model on recent data — distribution shift is significant.",
        "Investigate upstream data pipeline for schema changes.",
        "Activate a fallback model or rule-based override until retrain completes.",
        "Enable shadow deployment of a freshly trained candidate model.",
    ],
    "WARN": [
        "Monitor affected features closely over the next 24 hours.",
        "Review recent data ingestion logs for anomalies.",
        "Consider scheduling a retrain if drift continues to grow.",
        "Compare feature distributions between last week and today.",
    ],
    "OK": [
        "No action required — model is operating within baseline distribution.",
    ],
}

_STATUS_COLOR = {"ALERT": "#FF3B30", "WARN": "#FF9500", "OK": "#34C759"}
_STATUS_EMOJI = {"ALERT": ":rotating_light:", "WARN": ":warning:", "OK": ":white_check_mark:"}

# ---------------------------------------------------------------------------
# SlackAlerter
# ---------------------------------------------------------------------------


class SlackAlerter:
    """Send formatted drift alerts to a Slack channel.

    Tokens are stored in ``integrations/slack/tokens.json`` keyed by
    ``team_id``.  Pass ``webhook_url`` to send to a static incoming webhook,
    or rely on stored per-workspace bot tokens.

    Args:
        webhook_url:   Slack incoming webhook URL (optional — takes priority
                       if provided, bypasses token lookup).
        client_id:     Slack app Client ID (for OAuth).
        client_secret: Slack app Client Secret (for OAuth).
        redirect_uri:  OAuth redirect URI (e.g. https://tiamat.live/slack/oauth).
    """

    OAUTH_ENDPOINT = "https://slack.com/api/oauth.v2.access"
    CHAT_POST_URL = "https://slack.com/api/chat.postMessage"

    SCOPES = "incoming-webhook,chat:write"

    def __init__(
        self,
        webhook_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
    ):
        self.webhook_url = webhook_url or os.getenv("SLACK_WEBHOOK_URL", "")
        self.client_id = client_id or os.getenv("SLACK_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("SLACK_CLIENT_SECRET", "")
        self.redirect_uri = redirect_uri or os.getenv(
            "SLACK_REDIRECT_URI", "https://tiamat.live/slack/oauth"
        )

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------

    def get_install_url(self, state: str = "") -> str:
        """Return the Slack app install URL for the OAuth flow."""
        params: dict[str, str] = {
            "client_id": self.client_id,
            "scope": self.SCOPES,
            "redirect_uri": self.redirect_uri,
        }
        if state:
            params["state"] = state
        return "https://slack.com/oauth/v2/authorize?" + urlencode(params)

    def exchange_code(self, code: str) -> dict:
        """Exchange an OAuth code for a bot token.  Saves token to tokens.json.

        Returns the Slack API response dict.  On success, ``ok=True`` and
        ``access_token`` is present.
        """
        if not self.client_id or not self.client_secret:
            return {"ok": False, "error": "missing_credentials"}

        try:
            resp = requests.post(
                self.OAUTH_ENDPOINT,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                },
                timeout=10,
            )
            data = resp.json()
        except Exception as exc:
            logger.error("Slack OAuth exchange failed: %s", exc)
            return {"ok": False, "error": str(exc)}

        if data.get("ok"):
            team_id = data.get("team", {}).get("id", "unknown")
            tokens = _load_tokens()
            tokens[team_id] = {
                "access_token": data["access_token"],
                "team_name": data.get("team", {}).get("name", ""),
                "webhook_url": data.get("incoming_webhook", {}).get("url", ""),
                "channel": data.get("incoming_webhook", {}).get("channel", ""),
                "installed_at": int(time.time()),
            }
            _save_tokens(tokens)
            logger.info("Slack token saved for team_id=%s", team_id)

        return data

    # ------------------------------------------------------------------
    # Alert delivery
    # ------------------------------------------------------------------

    def send_alert(
        self,
        model_id: str,
        drift_score: float,
        confidence: int,
        affected_features: list[str],
        status: str = "ALERT",
        team_id: str | None = None,
    ) -> bool:
        """Send a formatted drift alert.

        Uses ``webhook_url`` if set; otherwise looks up the stored webhook
        for ``team_id``.

        Alert format::
            [fraud-v3] Drift detected at 87% confidence
            • amount  • velocity
            Fix: Retrain model on recent data…

        Returns True on success.
        """
        target_url = self.webhook_url
        if not target_url and team_id:
            tokens = _load_tokens()
            target_url = tokens.get(team_id, {}).get("webhook_url", "")

        if not target_url:
            logger.warning("send_alert: no webhook URL available")
            return False

        color = _STATUS_COLOR.get(status, "#8E8E93")
        emoji = _STATUS_EMOJI.get(status, ":bell:")
        suggestions = _FIX_SUGGESTIONS.get(status, _FIX_SUGGESTIONS["WARN"])

        features_str = (
            "  ".join(f"`{f}`" for f in affected_features)
            if affected_features
            else "_none detected_"
        )
        fix_str = "\n".join(f"• {s}" for s in suggestions[:2])

        payload = {
            "attachments": [
                {
                    "color": color,
                    "title": f"{emoji} [{model_id}] Drift detected at {confidence}% confidence",
                    "fields": [
                        {
                            "title": "Status",
                            "value": f"{emoji} *{status}*",
                            "short": True,
                        },
                        {
                            "title": "Drift Score",
                            "value": f"`{drift_score:.4f}`",
                            "short": True,
                        },
                        {
                            "title": "Affected Features",
                            "value": features_str,
                            "short": False,
                        },
                        {
                            "title": "Suggested Fix",
                            "value": fix_str,
                            "short": False,
                        },
                    ],
                    "footer": "Drift v2 · tiamat.live",
                    "ts": int(time.time()),
                }
            ]
        }

        try:
            resp = requests.post(
                target_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
            if resp.ok and resp.text != "invalid_token":
                logger.info("Slack alert sent model=%s status=%s", model_id, status)
                return True
            logger.warning("Slack webhook %s: %s", resp.status_code, resp.text[:120])
            return False
        except Exception as exc:
            logger.error("Slack send_alert failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Flask Blueprint
# ---------------------------------------------------------------------------

slack_bp = Blueprint("slack", __name__)
_alerter = SlackAlerter()


@slack_bp.route("/install")
def slack_install():
    """Redirect browser to Slack OAuth install page."""
    if not _alerter.client_id:
        return (
            jsonify({"error": "SLACK_CLIENT_ID not configured"}),
            501,
        )
    state = request.args.get("state", "")
    install_url = _alerter.get_install_url(state=state)
    return redirect(install_url)


@slack_bp.route("/oauth")
def slack_oauth_callback():
    """Slack OAuth callback — exchanges code for bot token and saves it."""
    error = request.args.get("error")
    if error:
        logger.warning("Slack OAuth denied: %s", error)
        return jsonify({"error": error, "message": "OAuth was denied or failed."}), 400

    code = request.args.get("code", "")
    if not code:
        return jsonify({"error": "missing_code"}), 400

    result = _alerter.exchange_code(code)
    if result.get("ok"):
        team = result.get("team", {}).get("name", "your workspace")
        channel = result.get("incoming_webhook", {}).get("channel", "")
        return jsonify(
            {
                "success": True,
                "message": f"Drift v2 connected to {team}",
                "channel": channel,
            }
        )

    return jsonify({"error": result.get("error", "unknown")}), 400


@slack_bp.route("/test", methods=["POST"])
def slack_test_alert():
    """POST a test drift alert to the configured webhook. Internal use only."""
    body: dict[str, Any] = request.get_json(silent=True) or {}
    team_id = body.get("team_id")

    ok = _alerter.send_alert(
        model_id=body.get("model_id", "test-model"),
        drift_score=float(body.get("drift_score", 0.42)),
        confidence=int(body.get("confidence", 87)),
        affected_features=body.get("affected_features", ["amount", "velocity"]),
        status=body.get("status", "ALERT"),
        team_id=team_id,
    )
    return jsonify({"sent": ok})


@slack_bp.route("/tokens", methods=["GET"])
def list_tokens():
    """Return list of connected workspaces (no secrets exposed)."""
    tokens = _load_tokens()
    safe = {
        tid: {"team_name": v.get("team_name"), "channel": v.get("channel")}
        for tid, v in tokens.items()
    }
    return jsonify({"workspaces": safe, "count": len(safe)})
