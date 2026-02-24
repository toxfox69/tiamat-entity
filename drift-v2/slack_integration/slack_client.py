"""
Slack integration for drift alerts.
OAuth flow + message sending.
"""

import os
import requests
from typing import Dict, Optional

SLACK_CLIENT_ID = os.getenv("SLACK_CLIENT_ID")
SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET")
SLACK_REDIRECT_URI = os.getenv("SLACK_REDIRECT_URI", "https://tiamat.live/drift/slack/oauth")


def get_oauth_url() -> str:
    """
    Generate Slack OAuth URL for installation.
    """
    scopes = "chat:write,incoming-webhook"
    
    return (
        f"https://slack.com/oauth/v2/authorize?"
        f"client_id={SLACK_CLIENT_ID}&"
        f"scope={scopes}&"
        f"redirect_uri={SLACK_REDIRECT_URI}"
    )


def exchange_code_for_token(code: str) -> Optional[Dict]:
    """
    Exchange OAuth code for access token.
    """
    try:
        response = requests.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": SLACK_CLIENT_ID,
                "client_secret": SLACK_CLIENT_SECRET,
                "code": code,
                "redirect_uri": SLACK_REDIRECT_URI
            }
        )
        
        data = response.json()
        
        if data.get("ok"):
            return {
                "access_token": data["access_token"],
                "webhook_url": data["incoming_webhook"]["url"],
                "channel": data["incoming_webhook"]["channel"],
                "team_id": data["team"]["id"]
            }
        else:
            print(f"Slack OAuth error: {data.get('error')}")
            return None
            
    except Exception as e:
        print(f"Error exchanging Slack code: {e}")
        return None


def send_drift_alert(
    webhook_url: str,
    model_id: str,
    drift_score: float,
    confidence: float,
    affected_features: list,
    recommendation: str
) -> bool:
    """
    Send drift alert to Slack channel.
    """
    try:
        # Format affected features
        feature_list = ", ".join(affected_features[:5])
        if len(affected_features) > 5:
            feature_list += f" (+{len(affected_features) - 5} more)"
        
        # Build message
        message = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"🚨 Drift Detected: {model_id}"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Drift Score:*\n{drift_score * 100:.0f}%"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Confidence:*\n{confidence * 100:.0f}%"
                        }
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Affected Features:*\n{feature_list}"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Recommendation:*\n{recommendation}"
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "Powered by TIAMAT Drift Monitor"
                        }
                    ]
                }
            ]
        }
        
        response = requests.post(webhook_url, json=message)
        
        return response.status_code == 200
        
    except Exception as e:
        print(f"Error sending Slack alert: {e}")
        return False
