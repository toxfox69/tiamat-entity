"""
Webhook support for Drift Monitor
Sends drift events to customer-configured webhook endpoints.
"""

import requests
import json
from datetime import datetime
from typing import Dict, Any, Optional
import hashlib
import hmac


class WebhookDispatcher:
    """
    Manages webhook registration and event dispatch.
    """
    
    def __init__(self, redis_client, webhook_secret: Optional[str] = None):
        """
        Args:
            redis_client: Redis connection for storing webhook URLs
            webhook_secret: Secret for HMAC signing (optional)
        """
        self.redis = redis_client
        self.webhook_secret = webhook_secret or "tiamat_drift_webhook_v1"
        
    def register_webhook(self, api_key: str, webhook_url: str) -> Dict[str, Any]:
        """
        Register a webhook URL for an API key.
        
        Args:
            api_key: Customer's TIAMAT API key
            webhook_url: Customer's webhook endpoint
            
        Returns:
            Registration status
        """
        # Validate URL
        if not webhook_url.startswith(("http://", "https://")):
            return {"error": "Invalid webhook URL - must start with http:// or https://"}
            
        # Store in Redis
        self.redis.hset(
            f"webhook:{api_key}",
            mapping={
                "url": webhook_url,
                "registered_at": datetime.utcnow().isoformat(),
                "last_sent": "",
                "success_count": 0,
                "failure_count": 0
            }
        )
        
        return {
            "success": True,
            "message": "Webhook registered successfully",
            "url": webhook_url
        }
    
    def send_drift_event(
        self,
        api_key: str,
        model_id: str,
        drift_score: float,
        affected_features: list,
        timestamp: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send drift event to registered webhook.
        
        Args:
            api_key: Customer's API key
            model_id: Model that drifted
            drift_score: Drift confidence (0-1)
            affected_features: List of drifted features
            timestamp: Event timestamp (ISO format)
            metadata: Additional event data
            
        Returns:
            Send status
        """
        # Get webhook URL from Redis
        webhook_data = self.redis.hgetall(f"webhook:{api_key}")
        
        if not webhook_data or not webhook_data.get(b"url"):
            return {"error": "No webhook registered for this API key"}
            
        webhook_url = webhook_data[b"url"].decode()
        
        # Build event payload
        event = {
            "event_type": "drift_detected",
            "model_id": model_id,
            "drift_score": drift_score,
            "affected_features": affected_features,
            "timestamp": timestamp or datetime.utcnow().isoformat()
        }
        
        if metadata:
            event["metadata"] = metadata
            
        # Sign payload with HMAC
        payload_str = json.dumps(event, sort_keys=True)
        signature = hmac.new(
            self.webhook_secret.encode(),
            payload_str.encode(),
            hashlib.sha256
        ).hexdigest()
        
        headers = {
            "Content-Type": "application/json",
            "X-TIAMAT-Signature": signature,
            "X-TIAMAT-Event": "drift_detected"
        }
        
        # Send webhook
        try:
            response = requests.post(
                webhook_url,
                json=event,
                headers=headers,
                timeout=10
            )
            
            # Update stats in Redis
            if response.ok:
                self.redis.hincrby(f"webhook:{api_key}", "success_count", 1)
                self.redis.hset(
                    f"webhook:{api_key}",
                    "last_sent",
                    datetime.utcnow().isoformat()
                )
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "message": "Webhook delivered successfully"
                }
            else:
                self.redis.hincrby(f"webhook:{api_key}", "failure_count", 1)
                return {
                    "error": f"Webhook returned {response.status_code}",
                    "status_code": response.status_code,
                    "response": response.text[:200]  # Limit response text
                }
                
        except requests.exceptions.RequestException as e:
            self.redis.hincrby(f"webhook:{api_key}", "failure_count", 1)
            return {
                "error": f"Failed to deliver webhook: {str(e)}"
            }
    
    def get_webhook_status(self, api_key: str) -> Dict[str, Any]:
        """
        Get webhook registration status and stats.
        
        Args:
            api_key: Customer's API key
            
        Returns:
            Webhook status and delivery stats
        """
        webhook_data = self.redis.hgetall(f"webhook:{api_key}")
        
        if not webhook_data or not webhook_data.get(b"url"):
            return {"registered": False}
            
        return {
            "registered": True,
            "url": webhook_data[b"url"].decode(),
            "registered_at": webhook_data[b"registered_at"].decode(),
            "last_sent": webhook_data.get(b"last_sent", b"").decode() or None,
            "success_count": int(webhook_data.get(b"success_count", 0)),
            "failure_count": int(webhook_data.get(b"failure_count", 0))
        }
    
    def unregister_webhook(self, api_key: str) -> Dict[str, Any]:
        """
        Remove webhook registration for an API key.
        
        Args:
            api_key: Customer's API key
            
        Returns:
            Deletion status
        """
        if self.redis.delete(f"webhook:{api_key}") > 0:
            return {"success": True, "message": "Webhook unregistered"}
        return {"error": "No webhook found for this API key"}
    
    def test_webhook(self, api_key: str) -> Dict[str, Any]:
        """
        Send a test event to verify webhook is working.
        
        Args:
            api_key: Customer's API key
            
        Returns:
            Test result
        """
        return self.send_drift_event(
            api_key=api_key,
            model_id="test_model",
            drift_score=0.75,
            affected_features=["feature_1", "feature_2"],
            metadata={"test": True, "message": "This is a test drift event"}
        )


def create_webhook_routes(app, webhook_dispatcher):
    """
    Add webhook management routes to Flask app.
    
    Args:
        app: Flask application
        webhook_dispatcher: WebhookDispatcher instance
    """
    from flask import request, jsonify
    
    @app.route('/drift/webhook', methods=['POST'])
    def register_webhook():
        """Register a webhook URL."""
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"error": "Missing X-API-Key header"}), 401
            
        data = request.get_json()
        if not data or not data.get('webhook_url'):
            return jsonify({"error": "Missing webhook_url in request body"}), 400
            
        result = webhook_dispatcher.register_webhook(api_key, data['webhook_url'])
        
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)
    
    @app.route('/drift/webhook', methods=['GET'])
    def get_webhook_status():
        """Get webhook registration status."""
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"error": "Missing X-API-Key header"}), 401
            
        status = webhook_dispatcher.get_webhook_status(api_key)
        return jsonify(status)
    
    @app.route('/drift/webhook', methods=['DELETE'])
    def unregister_webhook():
        """Unregister webhook."""
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"error": "Missing X-API-Key header"}), 401
            
        result = webhook_dispatcher.unregister_webhook(api_key)
        
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)
    
    @app.route('/drift/webhook/test', methods=['POST'])
    def test_webhook():
        """Send a test event to the registered webhook."""
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"error": "Missing X-API-Key header"}), 401
            
        result = webhook_dispatcher.test_webhook(api_key)
        
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)
