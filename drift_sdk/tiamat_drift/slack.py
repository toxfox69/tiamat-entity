"""
Slack integration for Drift Monitor
Sends drift alerts to Slack channels with actionable insights.
"""

import requests
import json
from datetime import datetime
from typing import Dict, Any, Optional, List


class SlackIntegration:
    """
    Manages Slack workspace connections and drift alert delivery.
    """
    
    def __init__(self, redis_client):
        """
        Args:
            redis_client: Redis connection for storing OAuth tokens
        """
        self.redis = redis_client
        
    def store_oauth_token(
        self,
        api_key: str,
        access_token: str,
        channel_id: str,
        workspace_name: Optional[str] = None,
        team_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Store Slack OAuth token after successful authorization.
        
        Args:
            api_key: Customer's TIAMAT API key
            access_token: Slack bot access token
            channel_id: Default channel ID for alerts
            workspace_name: Slack workspace name (optional)
            team_id: Slack team ID (optional)
            
        Returns:
            Storage status
        """
        self.redis.hset(
            f"slack:{api_key}",
            mapping={
                "access_token": access_token,
                "channel_id": channel_id,
                "workspace_name": workspace_name or "",
                "team_id": team_id or "",
                "connected_at": datetime.utcnow().isoformat(),
                "alert_count": 0
            }
        )
        
        return {
            "success": True,
            "message": "Slack connected successfully",
            "workspace": workspace_name,
            "channel_id": channel_id
        }
    
    def send_drift_alert(
        self,
        api_key: str,
        model_id: str,
        drift_score: float,
        affected_features: List[str],
        suggestions: Optional[List[str]] = None,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send drift alert to Slack channel.
        
        Args:
            api_key: Customer's API key
            model_id: Model that drifted
            drift_score: Drift confidence (0-1)
            affected_features: List of drifted features
            suggestions: Fix suggestions (optional)
            timestamp: Detection timestamp (ISO format)
            
        Returns:
            Send status
        """
        # Get Slack credentials from Redis
        slack_data = self.redis.hgetall(f"slack:{api_key}")
        
        if not slack_data or not slack_data.get(b"access_token"):
            return {"error": "No Slack workspace connected for this API key"}
            
        access_token = slack_data[b"access_token"].decode()
        channel_id = slack_data[b"channel_id"].decode()
        
        # Build Slack message
        confidence_emoji = "🔴" if drift_score >= 0.9 else "🟠" if drift_score >= 0.7 else "🟡"
        
        message_blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{confidence_emoji} Drift Detected: {model_id}"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Confidence:*\n{int(drift_score * 100)}%"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Time:*\n{timestamp or datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
                    }
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Affected Features:*\n{', '.join(f'`{f}`' for f in affected_features[:10])}"
                }
            }
        ]
        
        # Add fix suggestions if provided
        if suggestions:
            suggestion_text = "\n".join(f"• {s}" for s in suggestions[:5])
            message_blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Suggested Actions:*\n{suggestion_text}"
                }
            })
        
        # Add action buttons
        message_blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "View Details"
                    },
                    "url": f"https://tiamat.live/drift/models/{model_id}",
                    "style": "primary"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Acknowledge"
                    },
                    "value": f"ack_{model_id}"
                }
            ]
        })
        
        # Send to Slack
        try:
            response = requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                json={
                    "channel": channel_id,
                    "blocks": message_blocks,
                    "text": f"Drift detected in {model_id} ({int(drift_score * 100)}% confidence)"
                }
            )
            
            result = response.json()
            
            if result.get("ok"):
                # Increment alert count
                self.redis.hincrby(f"slack:{api_key}", "alert_count", 1)
                return {
                    "success": True,
                    "message": "Alert sent to Slack",
                    "ts": result.get("ts")
                }
            else:
                return {
                    "error": f"Slack API error: {result.get('error', 'Unknown')}",
                    "details": result
                }
                
        except requests.exceptions.RequestException as e:
            return {
                "error": f"Failed to send Slack alert: {str(e)}"
            }
    
    def get_connection_status(self, api_key: str) -> Dict[str, Any]:
        """
        Get Slack connection status and stats.
        
        Args:
            api_key: Customer's API key
            
        Returns:
            Connection status and alert stats
        """
        slack_data = self.redis.hgetall(f"slack:{api_key}")
        
        if not slack_data or not slack_data.get(b"access_token"):
            return {"connected": False}
            
        return {
            "connected": True,
            "workspace": slack_data.get(b"workspace_name", b"").decode() or "Unknown",
            "channel_id": slack_data[b"channel_id"].decode(),
            "connected_at": slack_data[b"connected_at"].decode(),
            "alert_count": int(slack_data.get(b"alert_count", 0))
        }
    
    def disconnect(self, api_key: str) -> Dict[str, Any]:
        """
        Remove Slack connection for an API key.
        
        Args:
            api_key: Customer's API key
            
        Returns:
            Disconnection status
        """
        if self.redis.delete(f"slack:{api_key}") > 0:
            return {"success": True, "message": "Slack disconnected"}
        return {"error": "No Slack connection found for this API key"}
    
    def test_connection(self, api_key: str) -> Dict[str, Any]:
        """
        Send a test alert to verify Slack integration is working.
        
        Args:
            api_key: Customer's API key
            
        Returns:
            Test result
        """
        return self.send_drift_alert(
            api_key=api_key,
            model_id="test_model",
            drift_score=0.75,
            affected_features=["feature_1", "feature_2"],
            suggestions=[
                "Review recent training data for anomalies",
                "Check for changes in upstream data sources",
                "Consider retraining with latest data"
            ]
        )


def create_slack_routes(app, slack_integration):
    """
    Add Slack integration routes to Flask app.
    
    Args:
        app: Flask application
        slack_integration: SlackIntegration instance
    """
    from flask import request, jsonify, redirect
    import os
    
    # Slack OAuth credentials (set via environment)
    SLACK_CLIENT_ID = os.getenv("SLACK_CLIENT_ID", "")
    SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET", "")
    SLACK_REDIRECT_URI = os.getenv("SLACK_REDIRECT_URI", "https://tiamat.live/drift/slack/callback")
    
    @app.route('/drift/slack/connect', methods=['GET'])
    def slack_connect():
        """Initiate Slack OAuth flow."""
        api_key = request.args.get('api_key')
        if not api_key:
            return jsonify({"error": "Missing api_key parameter"}), 400
            
        # Build Slack OAuth URL
        slack_url = (
            f"https://slack.com/oauth/v2/authorize"
            f"?client_id={SLACK_CLIENT_ID}"
            f"&scope=chat:write,channels:read"
            f"&redirect_uri={SLACK_REDIRECT_URI}"
            f"&state={api_key}"
        )
        
        return redirect(slack_url)
    
    @app.route('/drift/slack/callback', methods=['GET'])
    def slack_callback():
        """Handle Slack OAuth callback."""
        code = request.args.get('code')
        api_key = request.args.get('state')
        
        if not code or not api_key:
            return jsonify({"error": "Missing OAuth parameters"}), 400
            
        # Exchange code for access token
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
            
            result = response.json()
            
            if result.get("ok"):
                access_token = result["access_token"]
                team_id = result["team"]["id"]
                team_name = result["team"]["name"]
                
                # Get default channel (first public channel)
                channel_response = requests.post(
                    "https://slack.com/api/conversations.list",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"types": "public_channel", "limit": 1}
                )
                
                channel_result = channel_response.json()
                channel_id = "general"
                
                if channel_result.get("ok") and channel_result.get("channels"):
                    channel_id = channel_result["channels"][0]["id"]
                
                # Store OAuth token
                slack_integration.store_oauth_token(
                    api_key=api_key,
                    access_token=access_token,
                    channel_id=channel_id,
                    workspace_name=team_name,
                    team_id=team_id
                )
                
                return jsonify({
                    "success": True,
                    "message": "Slack connected successfully",
                    "workspace": team_name,
                    "channel_id": channel_id
                })
            else:
                return jsonify({
                    "error": f"Slack OAuth error: {result.get('error', 'Unknown')}"
                }), 400
                
        except Exception as e:
            return jsonify({"error": f"Failed to connect Slack: {str(e)}"}), 500
    
    @app.route('/drift/slack/status', methods=['GET'])
    def slack_status():
        """Get Slack connection status."""
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"error": "Missing X-API-Key header"}), 401
            
        status = slack_integration.get_connection_status(api_key)
        return jsonify(status)
    
    @app.route('/drift/slack/disconnect', methods=['DELETE'])
    def slack_disconnect():
        """Disconnect Slack integration."""
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"error": "Missing X-API-Key header"}), 401
            
        result = slack_integration.disconnect(api_key)
        
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)
    
    @app.route('/drift/slack/test', methods=['POST'])
    def slack_test():
        """Send a test alert to verify Slack integration."""
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"error": "Missing X-API-Key header"}), 401
            
        result = slack_integration.test_connection(api_key)
        
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)
