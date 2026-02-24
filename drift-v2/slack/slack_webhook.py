"""
Drift v2 — Slack Notifier
Sends formatted drift alerts to a Slack channel via OAuth webhook.
"""

import os
import json
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Status → Slack colour sidebar
_STATUS_COLOR = {
    "ALERT": "#FF3B30",
    "WARN":  "#FF9500",
    "OK":    "#34C759",
}

# Status → emoji
_STATUS_EMOJI = {
    "ALERT": ":rotating_light:",
    "WARN":  ":warning:",
    "OK":    ":white_check_mark:",
}


class SlackNotifier:
    """
    Send drift alerts to Slack.

    Usage:
        notifier = SlackNotifier()
        token = notifier.oauth_connect("https://myworkspace.slack.com")
        notifier.send_alert(
            model_id="fraud-v3",
            drift_score=0.87,
            confidence=92,
            affected_features=["amount", "velocity"],
            status="ALERT",
        )
    """

    OAUTH_ENDPOINT = "https://slack.com/api/oauth.v2.access"

    def __init__(
        self,
        webhook_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        self.webhook_url = webhook_url or os.getenv("SLACK_WEBHOOK_URL", "")
        self.client_id = client_id or os.getenv("SLACK_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("SLACK_CLIENT_SECRET", "")
        self._token: str | None = None

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------

    def oauth_connect(self, workspace_url: str) -> str:
        """
        Perform Slack OAuth2 handshake to obtain a bot token.

        MVP: returns a mock token so the flow can be tested without
        a live Slack app.  Replace the body with a real code-exchange
        when SLACK_CLIENT_ID / SLACK_CLIENT_SECRET are configured.
        """
        if self.client_id and self.client_secret:
            # Real exchange would look like:
            # resp = requests.post(self.OAUTH_ENDPOINT, data={
            #     "client_id": self.client_id,
            #     "client_secret": self.client_secret,
            #     "code": "<auth_code_from_redirect>",
            # })
            # data = resp.json()
            # self._token = data["access_token"]
            # return self._token
            logger.info("OAuth credentials present — real exchange pending UI redirect flow.")

        # MVP stub
        mock_token = f"xoxb-drift-v2-mock-token-for-{workspace_url.split('//')[-1]}"
        self._token = mock_token
        logger.info("oauth_connect: returning mock token for workspace %s", workspace_url)
        return mock_token

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
        extra_fields: dict | None = None,
    ) -> bool:
        """
        Post a formatted drift alert to the configured Slack webhook.

        Returns True on success, False on failure.
        """
        if not self.webhook_url:
            logger.warning("send_alert: no SLACK_WEBHOOK_URL configured, skipping.")
            return False

        color = _STATUS_COLOR.get(status, "#8E8E93")
        emoji = _STATUS_EMOJI.get(status, ":bell:")

        features_str = (
            "\n".join(f"• `{f}`" for f in affected_features)
            if affected_features
            else "_none_"
        )

        fields = [
            {"title": "Model", "value": f"`{model_id}`", "short": True},
            {"title": "Status", "value": f"{emoji} *{status}*", "short": True},
            {
                "title": "Drift Score",
                "value": f"`{drift_score:.4f}`  ({confidence}% confidence)",
                "short": True,
            },
            {"title": "Affected Features", "value": features_str, "short": False},
        ]

        if extra_fields:
            for k, v in extra_fields.items():
                fields.append({"title": k, "value": str(v), "short": True})

        payload = {
            "attachments": [
                {
                    "color": color,
                    "title": f"{emoji} Drift v2 — {status} on `{model_id}`",
                    "fields": fields,
                    "footer": "Drift v2 by tiamat.live",
                    "ts": int(__import__("time").time()),
                }
            ]
        }

        try:
            resp = requests.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
            if resp.ok:
                logger.info("Slack alert sent for model=%s status=%s", model_id, status)
                return True
            logger.warning("Slack webhook returned %s: %s", resp.status_code, resp.text[:120])
            return False
        except Exception as exc:
            logger.error("Slack send_alert failed: %s", exc)
            return False
