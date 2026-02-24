"""
Drift Monitor SDK v2 — Slack notifier

Sends rich Block Kit messages to a Slack incoming webhook when drift is
detected.  No Slack SDK dependency — pure requests.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

import requests

if TYPE_CHECKING:
    from drift_monitor import DriftReport

logger = logging.getLogger(__name__)

# Colour per severity
_SEVERITY_COLOUR = {
    "NONE": "#36a64f",      # green
    "LOW": "#f0c132",       # yellow
    "MEDIUM": "#e67e22",    # orange
    "HIGH": "#e74c3c",      # red
    "CRITICAL": "#8e44ad",  # purple
}

_SEVERITY_EMOJI = {
    "NONE": ":white_check_mark:",
    "LOW": ":warning:",
    "MEDIUM": ":large_orange_circle:",
    "HIGH": ":red_circle:",
    "CRITICAL": ":skull_and_crossbones:",
}


class SlackNotifier:
    """
    Posts drift alert messages to a Slack channel via incoming webhook.

    Parameters
    ----------
    webhook_url : str
        Slack incoming-webhook URL.
    channel : str
        Channel name (for display only; the webhook target is fixed).
    username : str
        Bot display name.
    timeout : int
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        webhook_url: str,
        channel: str = "#ml-alerts",
        username: str = "Drift Monitor",
        timeout: int = 10,
    ) -> None:
        if not webhook_url or not webhook_url.startswith("https://"):
            raise ValueError("webhook_url must be a valid https:// Slack webhook URL.")
        self._url = webhook_url
        self._channel = channel
        self._username = username
        self._timeout = timeout

    # ------------------------------------------------------------------ #
    def notify(self, report: "DriftReport") -> bool:
        """
        Send a Block Kit message for the given DriftReport.

        Returns
        -------
        bool — True if Slack accepted the message (HTTP 200).
        """
        payload = self._build_payload(report)
        try:
            resp = requests.post(
                self._url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=self._timeout,
            )
            if resp.status_code != 200:
                logger.error(
                    "Slack webhook returned %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            return True
        except requests.RequestException as exc:
            logger.error("Failed to post to Slack: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    def _build_payload(self, report: "DriftReport") -> dict:
        sev = report.severity
        colour = _SEVERITY_COLOUR.get(sev, "#aaaaaa")
        emoji = _SEVERITY_EMOJI.get(sev, ":bell:")
        score_pct = f"{report.drift_score * 100:.1f}%"

        # Top drifted features
        top_features = sorted(
            report.feature_scores.items(),
            key=lambda kv: kv[1],
            reverse=True,
        )[:5]

        feature_lines = "\n".join(
            f"• `{name}`: {score:.3f}" for name, score in top_features
        ) or "_No feature data_"

        recs = "\n".join(f"• {r}" for r in report.recommendations[:4]) or "_None_"

        attachments = [
            {
                "color": colour,
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": (
                                f"{emoji} Drift Alert — {report.model_name}"
                            ),
                            "emoji": True,
                        },
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Severity:*\n{sev}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Drift Score:*\n{score_pct}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Model:*\n`{report.model_name}`",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Timestamp:*\n{report.timestamp}",
                            },
                        ],
                    },
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Top Drifted Features:*\n{feature_lines}",
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Recommendations:*\n{recs}",
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": (
                                    f"Drift Monitor SDK v2  |  "
                                    f"ref_samples={report.ref_samples}  |  "
                                    f"cur_samples={report.cur_samples}"
                                ),
                            }
                        ],
                    },
                ],
            }
        ]

        return {
            "username": self._username,
            "channel": self._channel,
            "attachments": attachments,
        }

    # ------------------------------------------------------------------ #
    def send_custom(self, text: str, title: Optional[str] = None) -> bool:
        """Send a plain-text message to the configured channel."""
        payload: dict = {"username": self._username, "channel": self._channel}
        if title:
            payload["text"] = f"*{title}*\n{text}"
        else:
            payload["text"] = text
        try:
            resp = requests.post(
                self._url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=self._timeout,
            )
            return resp.status_code == 200
        except requests.RequestException as exc:
            logger.error("Slack custom send failed: %s", exc)
            return False
