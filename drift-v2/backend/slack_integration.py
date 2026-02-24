"""
Slack OAuth and alert integration for Drift v2
"""

import os
import json
import requests
from typing import Dict, Any, Optional
from datetime import datetime

SLACK_CLIENT_ID = os.getenv("SLACK_CLIENT_ID", "")
SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET", "")
SLACK_REDIRECT_URI = "https://tiamat.live/api/v1/drift/slack/callback"


class SlackIntegration:
    """Handle Slack OAuth and message posting"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
        
    def get_oauth_url(self, state: str) -> str:
        """Generate Slack OAuth URL"""
        scopes = "chat:write,incoming-webhook"
        return (
            f"https://slack.com/oauth/v2/authorize?"
            f"client_id={SLACK_CLIENT_ID}&"
            f"scope={scopes}&"
            f"redirect_uri={SLACK_REDIRECT_URI}&"
            f"state={state}"
        )
    
    def exchange_code(self, code: str) -> Dict[str, Any]:
        """Exchange OAuth code for access token"""
        response = requests.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": SLACK_CLIENT_ID,
                "client_secret": SLACK_CLIENT_SECRET,
                "code": code,
                "redirect_uri": SLACK_REDIRECT_URI
            }
        )
        
        return response.json()
    
    def save_workspace(self, api_key: str, oauth_response: Dict[str, Any]):
        """Save Slack workspace credentials"""
        workspace_data = {
            "access_token": oauth_response.get("access_token"),
            "team_id": oauth_response.get("team", {}).get("id"),
            "team_name": oauth_response.get("team", {}).get("name"),
            "channel_id": oauth_response.get("incoming_webhook", {}).get("channel_id"),
            "channel_name": oauth_response.get("incoming_webhook", {}).get("channel"),
            "webhook_url": oauth_response.get("incoming_webhook", {}).get("url"),
            "connected_at": datetime.utcnow().isoformat()
        }
        
        # Store in Redis: drift:slack:{api_key}
        self.redis.set(
            f"drift:slack:{api_key}",
            json.dumps(workspace_data),
            ex=None  # No expiry
        )
        
        return workspace_data
    
    def get_workspace(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Get Slack workspace for API key"""
        data = self.redis.get(f"drift:slack:{api_key}")
        if data:
            return json.loads(data)
        return None
    
    def send_alert(
        self,
        api_key: str,
        model_id: str,
        drift_score: float,
        affected_features: list,
        recommendation: str
    ) -> bool:
        """Send drift alert to Slack"""
        workspace = self.get_workspace(api_key)
        
        if not workspace or not workspace.get("webhook_url"):
            return False
        
        # Format drift alert message
        severity = "🔴" if drift_score > 0.3 else "🟡" if drift_score > 0.15 else "🟢"
        
        message = {
            "text": f"{severity} Model Drift Alert",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{severity} Model Drift Detected"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Model:*\n`{model_id}`"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Drift Score:*\n{drift_score:.1%}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Affected Features:*\n{len(affected_features)} feature(s)"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Time:*\n{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
                        }
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Features:* {', '.join(affected_features[:5])}"
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
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "View Dashboard"
                            },
                            "url": f"https://tiamat.live/drift/dashboard?model={model_id}",
                            "style": "primary"
                        }
                    ]
                }
            ]
        }
        
        try:
            response = requests.post(
                workspace["webhook_url"],
                json=message,
                timeout=5
            )
            return response.status_code == 200
        except:
            return False
    
    def disconnect(self, api_key: str):
        """Disconnect Slack integration"""
        self.redis.delete(f"drift:slack:{api_key}")


class WebhookIntegration:
    """Handle custom webhook forwarding"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    def save_webhook(self, api_key: str, webhook_url: str):
        """Save webhook URL for API key"""
        webhook_data = {
            "url": webhook_url,
            "created_at": datetime.utcnow().isoformat()
        }
        
        self.redis.set(
            f"drift:webhook:{api_key}",
            json.dumps(webhook_data),
            ex=None
        )
    
    def get_webhook(self, api_key: str) -> Optional[str]:
        """Get webhook URL for API key"""
        data = self.redis.get(f"drift:webhook:{api_key}")
        if data:
            webhook_data = json.loads(data)
            return webhook_data.get("url")
        return None
    
    def send_event(
        self,
        api_key: str,
        event_type: str,
        payload: Dict[str, Any]
    ) -> bool:
        """Send event to customer webhook"""
        webhook_url = self.get_webhook(api_key)
        
        if not webhook_url:
            return False
        
        # Standard webhook payload format
        webhook_payload = {
            "event": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": payload
        }
        
        try:
            response = requests.post(
                webhook_url,
                json=webhook_payload,
                headers={"Content-Type": "application/json"},
                timeout=5
            )
            return 200 <= response.status_code < 300
        except:
            return False
    
    def delete_webhook(self, api_key: str):
        """Remove webhook"""
        self.redis.delete(f"drift:webhook:{api_key}")
