#!/usr/bin/env python3
"""
TIAMAT Drift v2 Backend API
============================
Handles drift alerts, Slack OAuth, webhook forwarding, and free/pro routing.

Routes
------
POST /api/v1/drift/alert          — Receive drift event from SDK
POST /api/v1/drift/log            — Log single prediction
GET  /api/v1/drift/status         — Model monitoring status
POST /api/v1/drift/slack/connect  — Start Slack OAuth
GET  /api/v1/drift/slack/callback — OAuth callback
POST /api/v1/drift/slack/disconnect — Remove Slack integration
POST /api/v1/drift/webhook/set    — Configure webhook URL
DELETE /api/v1/drift/webhook      — Remove webhook
"""

import os
import json
import redis
import secrets
from flask import Flask, request, jsonify, redirect
from datetime import datetime
from slack_integration import SlackIntegration, WebhookIntegration

app = Flask(__name__)

# Redis connection
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    decode_responses=True
)

# Integrations
slack = SlackIntegration(redis_client)
webhook = WebhookIntegration(redis_client)

# Free tier limits
FREE_MODEL_LIMIT = 10


def validate_api_key(api_key: str) -> dict:
    """Validate API key and return tier info"""
    if not api_key:
        return {"valid": False, "error": "Missing API key"}
    
    # Check if key exists in Redis
    tier_data = redis_client.get(f"api_key:{api_key}")
    
    if not tier_data:
        # New key - create as free tier
        tier_info = {
            "tier": "free",
            "model_count": 0,
            "created_at": datetime.utcnow().isoformat()
        }
        redis_client.set(f"api_key:{api_key}", json.dumps(tier_info))
        return {"valid": True, "tier": "free", "model_count": 0}
    
    tier_info = json.loads(tier_data)
    return {"valid": True, **tier_info}


def check_model_limit(api_key: str, model_id: str) -> dict:
    """Check if adding this model exceeds free tier limits"""
    tier = validate_api_key(api_key)
    
    if not tier["valid"]:
        return tier
    
    # Pro tier = unlimited
    if tier.get("tier") == "pro":
        return {"allowed": True, "tier": "pro"}
    
    # Check if model already tracked
    existing = redis_client.sismember(f"models:{api_key}", model_id)
    
    if existing:
        return {"allowed": True, "tier": "free", "model_count": tier["model_count"]}
    
    # Check free tier limit
    current_count = tier.get("model_count", 0)
    
    if current_count >= FREE_MODEL_LIMIT:
        return {
            "allowed": False,
            "error": f"Free tier limit: {FREE_MODEL_LIMIT} models. Upgrade to Pro for unlimited.",
            "tier": "free",
            "model_count": current_count
        }
    
    # Add model to set and increment count
    redis_client.sadd(f"models:{api_key}", model_id)
    tier["model_count"] = current_count + 1
    redis_client.set(f"api_key:{api_key}", json.dumps(tier))
    
    return {"allowed": True, "tier": "free", "model_count": tier["model_count"]}


@app.route("/api/v1/drift/log", methods=["POST"])
def log_prediction():
    """Log a single prediction with drift detection"""
    data = request.json
    
    api_key = request.headers.get("X-API-Key") or data.get("api_key")
    model_id = data.get("model_id")
    features = data.get("features")
    prediction = data.get("prediction")
    ground_truth = data.get("ground_truth")
    
    if not all([api_key, model_id, features]):
        return jsonify({"error": "Missing required fields"}), 400
    
    # Validate API key and check limits
    limit_check = check_model_limit(api_key, model_id)
    
    if not limit_check.get("allowed"):
        return jsonify({
            "error": limit_check.get("error"),
            "tier": limit_check.get("tier"),
            "model_count": limit_check.get("model_count")
        }), 403
    
    # Store prediction in Redis
    prediction_data = {
        "model_id": model_id,
        "features": features,
        "prediction": prediction,
        "ground_truth": ground_truth,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Add to model's prediction stream
    redis_client.lpush(
        f"predictions:{api_key}:{model_id}",
        json.dumps(prediction_data)
    )
    
    # Keep last 1000 predictions per model
    redis_client.ltrim(f"predictions:{api_key}:{model_id}", 0, 999)
    
    # Run drift detection (simple version - can be enhanced)
    drift_result = detect_drift(api_key, model_id, features)
    
    # If drift detected, send alerts
    if drift_result["drift_detected"]:
        send_drift_alerts(
            api_key,
            model_id,
            drift_result["drift_score"],
            drift_result["affected_features"],
            drift_result["recommendation"]
        )
    
    return jsonify({
        "success": True,
        **drift_result
    }), 200


def detect_drift(api_key: str, model_id: str, current_features: list) -> dict:
    """Simple drift detection using feature statistics"""
    # Get historical predictions
    historical = redis_client.lrange(f"predictions:{api_key}:{model_id}", 0, 99)
    
    if len(historical) < 10:
        return {
            "drift_detected": False,
            "drift_score": 0.0,
            "affected_features": [],
            "recommendation": "Collecting baseline data..."
        }
    
    # Parse historical features
    import numpy as np
    historical_features = []
    for pred in historical:
        pred_data = json.loads(pred)
        historical_features.append(pred_data["features"])
    
    historical_features = np.array(historical_features)
    current = np.array(current_features)
    
    # Calculate Z-scores for each feature
    means = historical_features.mean(axis=0)
    stds = historical_features.std(axis=0) + 1e-6  # Avoid division by zero
    
    z_scores = np.abs((current - means) / stds)
    
    # Features with Z-score > 2.5 = drift
    drifted_indices = np.where(z_scores > 2.5)[0]
    drift_score = min(1.0, len(drifted_indices) / len(current))
    
    if len(drifted_indices) == 0:
        return {
            "drift_detected": False,
            "drift_score": 0.0,
            "affected_features": [],
            "recommendation": "No drift detected"
        }
    
    # Generate recommendation
    severity = "HIGH" if drift_score > 0.3 else "MEDIUM" if drift_score > 0.15 else "LOW"
    affected = [f"feature_{i}" for i in drifted_indices]
    
    recommendation = f"[{severity}] Drift detected in {len(affected)} feature(s)"
    if severity == "HIGH":
        recommendation += " | → URGENT: Retrain model immediately"
    elif severity == "MEDIUM":
        recommendation += " | → Schedule retraining within 24 hours"
    else:
        recommendation += " | → Monitor closely"
    
    return {
        "drift_detected": True,
        "drift_score": float(drift_score),
        "affected_features": affected,
        "recommendation": recommendation
    }


def send_drift_alerts(
    api_key: str,
    model_id: str,
    drift_score: float,
    affected_features: list,
    recommendation: str
):
    """Send drift alerts via Slack and/or webhook"""
    # Try Slack
    slack_sent = slack.send_alert(
        api_key, model_id, drift_score, affected_features, recommendation
    )
    
    # Try webhook
    webhook_sent = webhook.send_event(
        api_key,
        "drift_detected",
        {
            "model_id": model_id,
            "drift_score": drift_score,
            "affected_features": affected_features,
            "recommendation": recommendation
        }
    )
    
    # Log alert status
    redis_client.lpush(
        f"alerts:{api_key}:{model_id}",
        json.dumps({
            "timestamp": datetime.utcnow().isoformat(),
            "drift_score": drift_score,
            "slack_sent": slack_sent,
            "webhook_sent": webhook_sent
        })
    )


@app.route("/api/v1/drift/status", methods=["GET"])
def get_status():
    """Get model monitoring status"""
    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    
    if not api_key:
        return jsonify({"error": "Missing API key"}), 400
    
    tier = validate_api_key(api_key)
    
    if not tier["valid"]:
        return jsonify({"error": "Invalid API key"}), 401
    
    # Get all models
    models = list(redis_client.smembers(f"models:{api_key}"))
    
    model_stats = []
    for model_id in models:
        pred_count = redis_client.llen(f"predictions:{api_key}:{model_id}")
        alert_count = redis_client.llen(f"alerts:{api_key}:{model_id}")
        
        # Get latest alert if any
        latest_alert = redis_client.lindex(f"alerts:{api_key}:{model_id}", 0)
        last_drift = None
        if latest_alert:
            alert_data = json.loads(latest_alert)
            last_drift = alert_data["timestamp"]
        
        model_stats.append({
            "model_id": model_id,
            "prediction_count": pred_count,
            "alert_count": alert_count,
            "last_drift": last_drift
        })
    
    return jsonify({
        "tier": tier["tier"],
        "model_count": len(models),
        "model_limit": FREE_MODEL_LIMIT if tier["tier"] == "free" else "unlimited",
        "models": model_stats,
        "integrations": {
            "slack": slack.get_workspace(api_key) is not None,
            "webhook": webhook.get_webhook(api_key) is not None
        }
    }), 200


@app.route("/api/v1/drift/slack/connect", methods=["POST"])
def slack_connect():
    """Start Slack OAuth flow"""
    data = request.json
    api_key = request.headers.get("X-API-Key") or data.get("api_key")
    
    if not api_key:
        return jsonify({"error": "Missing API key"}), 400
    
    tier = validate_api_key(api_key)
    if not tier["valid"]:
        return jsonify({"error": "Invalid API key"}), 401
    
    # Generate state token
    state = secrets.token_urlsafe(32)
    redis_client.setex(f"slack_state:{state}", 600, api_key)  # 10 min TTL
    
    oauth_url = slack.get_oauth_url(state)
    
    return jsonify({
        "oauth_url": oauth_url,
        "state": state
    }), 200


@app.route("/api/v1/drift/slack/callback", methods=["GET"])
def slack_callback():
    """Handle Slack OAuth callback"""
    code = request.args.get("code")
    state = request.args.get("state")
    
    if not code or not state:
        return "Missing OAuth parameters", 400
    
    # Verify state
    api_key = redis_client.get(f"slack_state:{state}")
    
    if not api_key:
        return "Invalid or expired state token", 400
    
    # Exchange code for token
    oauth_response = slack.exchange_code(code)
    
    if not oauth_response.get("ok"):
        return f"Slack OAuth failed: {oauth_response.get('error')}", 400
    
    # Save workspace
    slack.save_workspace(api_key, oauth_response)
    
    # Clean up state
    redis_client.delete(f"slack_state:{state}")
    
    return redirect("https://tiamat.live/drift/dashboard?slack=connected")


@app.route("/api/v1/drift/slack/disconnect", methods=["POST"])
def slack_disconnect():
    """Disconnect Slack integration"""
    data = request.json
    api_key = request.headers.get("X-API-Key") or data.get("api_key")
    
    if not api_key:
        return jsonify({"error": "Missing API key"}), 400
    
    slack.disconnect(api_key)
    
    return jsonify({"success": True, "message": "Slack disconnected"}), 200


@app.route("/api/v1/drift/webhook/set", methods=["POST"])
def set_webhook():
    """Configure webhook URL"""
    data = request.json
    api_key = request.headers.get("X-API-Key") or data.get("api_key")
    webhook_url = data.get("webhook_url")
    
    if not api_key or not webhook_url:
        return jsonify({"error": "Missing API key or webhook URL"}), 400
    
    tier = validate_api_key(api_key)
    if not tier["valid"]:
        return jsonify({"error": "Invalid API key"}), 401
    
    webhook.save_webhook(api_key, webhook_url)
    
    return jsonify({
        "success": True,
        "webhook_url": webhook_url,
        "message": "Webhook configured"
    }), 200


@app.route("/api/v1/drift/webhook", methods=["DELETE"])
def delete_webhook():
    """Remove webhook"""
    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    
    if not api_key:
        return jsonify({"error": "Missing API key"}), 400
    
    webhook.delete_webhook(api_key)
    
    return jsonify({"success": True, "message": "Webhook removed"}), 200


@app.route("/health", methods=["GET"])
def health():
    """Health check"""
    return jsonify({"status": "healthy", "service": "drift-v2"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False)
