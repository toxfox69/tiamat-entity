#!/usr/bin/env python3
"""
TIAMAT Drift v2 Slack Integration
OAuth flow for one-click Slack connect.
"""

import os
import json
import time
import logging
from flask import Flask, request, redirect, render_template_string
import redis
import requests

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Slack OAuth credentials
SLACK_CLIENT_ID = os.environ.get("SLACK_CLIENT_ID", "")
SLACK_CLIENT_SECRET = os.environ.get("SLACK_CLIENT_SECRET", "")
SLACK_REDIRECT_URI = os.environ.get("SLACK_REDIRECT_URI", "https://tiamat.live/slack/oauth/callback")

# Redis connection
redis_client = redis.Redis(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
    db=0,
    decode_responses=True
)


# Landing page with "Add to Slack" button
LANDING_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>TIAMAT Drift v2 - Slack Integration</title>
    <style>
        body {
            font-family: 'Courier New', monospace;
            background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
            color: #00ffcc;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }
        .container {
            text-align: center;
            background: rgba(0, 0, 0, 0.5);
            padding: 40px;
            border-radius: 10px;
            border: 2px solid #00ffcc;
        }
        h1 {
            font-size: 2.5em;
            margin-bottom: 20px;
            text-shadow: 0 0 10px #00ffcc;
        }
        p {
            font-size: 1.2em;
            margin-bottom: 30px;
        }
        .slack-button {
            display: inline-block;
            background: #4A154B;
            color: white;
            padding: 15px 30px;
            border-radius: 5px;
            text-decoration: none;
            font-weight: bold;
            transition: all 0.3s;
        }
        .slack-button:hover {
            background: #611f69;
            box-shadow: 0 0 20px rgba(74, 21, 75, 0.5);
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🌊 TIAMAT Drift v2</h1>
        <p>Get real-time drift alerts in Slack</p>
        <a href="{{ slack_auth_url }}" class="slack-button">
            <img src="https://api.slack.com/img/sign_in_with_slack.png" alt="Add to Slack" style="vertical-align: middle;">
        </a>
        <p style="margin-top: 30px; font-size: 0.9em; opacity: 0.7;">
            One-click setup. No code required.
        </p>
    </div>
</body>
</html>
"""

SUCCESS_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>TIAMAT Drift v2 - Connected</title>
    <style>
        body {
            font-family: 'Courier New', monospace;
            background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
            color: #00ffcc;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }
        .container {
            text-align: center;
            background: rgba(0, 0, 0, 0.5);
            padding: 40px;
            border-radius: 10px;
            border: 2px solid #00ffcc;
        }
        h1 {
            font-size: 2.5em;
            margin-bottom: 20px;
            text-shadow: 0 0 10px #00ffcc;
        }
        .success {
            font-size: 4em;
            margin-bottom: 20px;
        }
        .code {
            background: rgba(0, 255, 204, 0.1);
            padding: 10px;
            border-radius: 5px;
            margin: 20px 0;
            font-family: monospace;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="success">✅</div>
        <h1>Slack Connected!</h1>
        <p>Your API Key:</p>
        <div class="code">{{ api_key }}</div>
        <p style="margin-top: 30px;">
            Use this key in your Python code:<br>
            <code>client = DriftClient(api_key="{{ api_key }}")</code>
        </p>
        <p style="margin-top: 30px; font-size: 0.9em; opacity: 0.7;">
            Drift alerts will be sent to <strong>{{ channel }}</strong>
        </p>
    </div>
</body>
</html>
"""


@app.route("/slack/connect")
def slack_connect():
    """Landing page with 'Add to Slack' button."""
    slack_auth_url = (
        f"https://slack.com/oauth/v2/authorize?"
        f"client_id={SLACK_CLIENT_ID}&"
        f"scope=incoming-webhook&"
        f"redirect_uri={SLACK_REDIRECT_URI}"
    )
    
    return render_template_string(LANDING_PAGE, slack_auth_url=slack_auth_url)


@app.route("/slack/oauth/callback")
def slack_oauth_callback():
    """Handle Slack OAuth callback."""
    code = request.args.get("code")
    
    if not code:
        return "Error: Missing OAuth code", 400
    
    # Exchange code for access token
    try:
        resp = requests.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": SLACK_CLIENT_ID,
                "client_secret": SLACK_CLIENT_SECRET,
                "code": code,
                "redirect_uri": SLACK_REDIRECT_URI
            }
        )
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get("ok"):
            logger.error(f"Slack OAuth error: {data}")
            return f"Error: {data.get('error', 'Unknown error')}", 500
        
        # Extract webhook URL
        webhook_url = data["incoming_webhook"]["url"]
        channel = data["incoming_webhook"]["channel"]
        team_id = data["team"]["id"]
        
        # Generate API key
        import hashlib
        import secrets
        api_key = f"drift_{secrets.token_urlsafe(32)}"
        
        # Store in Redis
        redis_client.hset(f"api_key:{api_key}", mapping={
            "slack_webhook": webhook_url,
            "slack_channel": channel,
            "slack_team": team_id,
            "free_models": "10",
            "tier": "free",
            "created_at": str(int(time.time()))
        })
        
        logger.info(f"New Slack integration: team={team_id}, channel={channel}, api_key={api_key[:20]}...")
        
        return render_template_string(SUCCESS_PAGE, api_key=api_key, channel=channel)
    
    except Exception as e:
        logger.error(f"Slack OAuth error: {e}")
        return f"Error: {str(e)}", 500


@app.route("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "tiamat-drift-slack"}


if __name__ == "__main__":
    if not SLACK_CLIENT_ID or not SLACK_CLIENT_SECRET:
        logger.warning("SLACK_CLIENT_ID and SLACK_CLIENT_SECRET not set. OAuth will not work.")
    
    app.run(host="0.0.0.0", port=5003, debug=False)
