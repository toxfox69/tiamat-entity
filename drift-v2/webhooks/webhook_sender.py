"""
Webhook sender for drift events.
POST drift events to customer backend.
"""

import requests
import redis
import os
from typing import Dict, Optional

# Connect to Redis
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=0,
    decode_responses=True
)


def register_webhook(api_key: str, webhook_url: str):
    """
    Register webhook URL for API key.
    """
    try:
        redis_client.set(f"webhook:{api_key}", webhook_url)
    except Exception as e:
        print(f"Error registering webhook: {e}")


def get_webhook(api_key: str) -> Optional[str]:
    """
    Get registered webhook URL for API key.
    """
    try:
        return redis_client.get(f"webhook:{api_key}")
    except Exception:
        return None


def send_webhook(
    webhook_url: str,
    model_id: str,
    drift_score: float,
    confidence: float,
    affected_features: list,
    recommendation: str,
    details: Dict
) -> bool:
    """
    POST drift event to customer webhook.
    """
    try:
        payload = {
            "event": "drift_detected",
            "model_id": model_id,
            "drift_score": drift_score,
            "confidence": confidence,
            "affected_features": affected_features,
            "recommendation": recommendation,
            "details": details,
            "timestamp": details.get("timestamp")
        }
        
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        return response.status_code in [200, 201, 202]
        
    except Exception as e:
        print(f"Error sending webhook to {webhook_url}: {e}")
        return False
