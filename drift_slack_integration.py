"""
Slack Integration for Drift Monitor
Handles OAuth flow and sends alerts to Slack channels.
"""

import os
import json
import requests
from flask import Flask, request, jsonify, redirect
from datetime import datetime
from typing import Dict, Any, Optional


class SlackIntegration:
    """
    Manages Slack OAuth and alert posting.
    """
    
    def __init__(self, client_id: str, client_secret: str, redis_client):
        """
        Args:
            client_id: Slack app client ID
            client_secret: Slack app client secret
            redis_client: Redis connection for storing tokens
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redis = redis_client
        self.oauth_url = "https://slack.com/oauth/v2/authorize"
        self.token_url = "https://slack.com/api/oauth.v2.access"
        
    def get_oauth_url(self, api_key: str, redirect_uri: str) -> str:
        """
        Generate Slack OAuth URL for a given API key.
        
        Args:
            api_key: Customer's TIAMAT API key
            redirect_uri: Where Slack should redirect after auth
            
        Returns:
            OAuth URL to visit
        """
        # Store state for OAuth callback verification
        state = f"drift_{api_key}"
        
        params = {
            "client_id": self.client_id,
            "scope": "chat:write,incoming-webhook",
            "redirect_uri": redirect_uri,
            "state": state
        }
        
        url = self.oauth_url + "?" + "&".join(
            f"{k}={requests.utils.quote(v)}" for k, v in params.items()
        )
        return url
    
    def handle_oauth_callback(self, code: str, state: str) -> Dict[str, Any]:
        """
        Handle Slack OAuth callback and store access token.
        
        Args:
            code: OAuth code from Slack
            state: State parameter (contains api_key)
            
        Returns:
            Success status and details
        """
        # Extract api_key from state
        if not state.startswith("drift_"):
            return {"error": "Invalid state parameter"}
            
        api_key = state[6:]  # Remove "drift_" prefix
        
        # Exchange code for access token
        response = requests.post(
            self.token_url,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code
            }
        )
        
        if not response.ok:
            return {"error": "Failed to exchange OAuth code"}
            
        data = response.json()
        
        if not data.get("ok"):
            return {"error": data.get("error", "Unknown error")}
            
        # Store access token and webhook URL in Redis
        access_token = data["access_token"]
        webhook_url = data["incoming_webhook"]["url"]
        channel = data["incoming_webhook"]["channel"]
        
        self.redis.hset(
            f"slack:{api_key}",
            mapping={
                "access_token": access_token,
                "webhook_url": webhook_url,
                "channel": channel,
                "connected_at": datetime.utcnow().isoformat()
            }
        )
        
        return {
            "success": True,
            "channel": channel,
            "message": "Slack connected successfully"
        }
    
    def send_alert(
        self,
        api_key: str,
        model_id: str,
        drift_score: float,
        affected_features: list,
        suggestions: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Send drift alert to Slack channel.
        
        Args:
            api_key: Customer's API key
            model_id: Model that drifted
            drift_score: Drift confidence (0-1)
            affected_features: List of drifted features
            suggestions: Optional fix suggestions
            
        Returns:
            Send status
        """
        # Get webhook URL from Redis
        slack_data = self.redis.hgetall(f"slack:{api_key}")
        
        if not slack_data or not slack_data.get(b"webhook_url"):
            return {"error": "Slack not connected for this API key"}
            
        webhook_url = slack_data[b"webhook_url"].decode()
        
        # Build alert message
        confidence_pct = int(drift_score * 100)
        features_str = ", ".join(affected_features[:5])  # Limit to 5
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🚨 Model Drift Detected: {model_id}"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Confidence:*\n{confidence_pct}%"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Affected Features:*\n{features_str}"
                    }
                ]
            }
        ]
        
        # Add suggestions if provided
        if suggestions:
            suggestion_text = "\n".join(f"• {s}" for s in suggestions[:3])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Suggested Actions:*\n{suggestion_text}"
                }
            })
        
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Powered by TIAMAT Drift Monitor • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
                }
            ]
        })
        
        # Send to Slack
        response = requests.post(
            webhook_url,
            json={"blocks": blocks}
        )
        
        if response.ok:
            return {"success": True, "message": "Alert sent to Slack"}
        else:
            return {"error": f"Failed to send alert: {response.text}"}
    
    def is_connected(self, api_key: str) -> bool:
        """
        Check if Slack is connected for an API key.
        """
        return self.redis.exists(f"slack:{api_key}") > 0
    
    def disconnect(self, api_key: str) -> Dict[str, Any]:
        """
        Disconnect Slack integration for an API key.
        """
        if self.redis.delete(f"slack:{api_key}") > 0:
            return {"success": True, "message": "Slack disconnected"}
        return {"error": "No Slack connection found"}


def create_slack_routes(app: Flask, slack_integration: SlackIntegration):
    """
    Add Slack OAuth routes to Flask app.
    
    Args:
        app: Flask application
        slack_integration: SlackIntegration instance
    """
    
    @app.route('/drift/slack/oauth', methods=['GET'])
    def slack_oauth_start():
        """Get OAuth URL to connect Slack."""
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"error": "Missing X-API-Key header"}), 401
            
        redirect_uri = f"{request.url_root.rstrip('/')}/drift/slack/callback"
        oauth_url = slack_integration.get_oauth_url(api_key, redirect_uri)
        
        return jsonify({"oauth_url": oauth_url})
    
    @app.route('/drift/slack/callback', methods=['GET'])
    def slack_oauth_callback():
        """Handle Slack OAuth callback."""
        code = request.args.get('code')
        state = request.args.get('state')
        
        if not code or not state:
            return "Missing OAuth parameters", 400
            
        result = slack_integration.handle_oauth_callback(code, state)
        
        if "error" in result:
            return f"Error connecting Slack: {result['error']}", 400
            
        return f"""
        <html>
        <head><title>Slack Connected</title></head>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1>✅ Slack Connected!</h1>
            <p>Drift alerts will now be sent to: <strong>#{result['channel']}</strong></p>
            <p>You can close this window.</p>
        </body>
        </html>
        """
    
    @app.route('/drift/slack/status', methods=['GET'])
    def slack_status():
        """Check if Slack is connected for an API key."""
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"error": "Missing X-API-Key header"}), 401
            
        connected = slack_integration.is_connected(api_key)
        
        if connected:
            slack_data = slack_integration.redis.hgetall(f"slack:{api_key}")
            channel = slack_data.get(b"channel", b"unknown").decode()
            return jsonify({
                "connected": True,
                "channel": channel
            })
        else:
            return jsonify({"connected": False})
    
    @app.route('/drift/slack/disconnect', methods=['POST'])
    def slack_disconnect():
        """Disconnect Slack integration."""
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"error": "Missing X-API-Key header"}), 401
            
        result = slack_integration.disconnect(api_key)
        
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)
