"""
Rate limiting for free/pro tiers.
Free: 10 models max per API key.
Pro: Unlimited models.
"""

import redis
import os
from typing import Tuple

# Connect to Redis
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=0,
    decode_responses=True
)

FREE_MODEL_LIMIT = 10


def check_model_limit(api_key: str, model_id: str) -> Tuple[bool, str]:
    """
    Check if API key can monitor this model.
    Returns (allowed: bool, message: str)
    """
    try:
        # Check if pro tier (bypass limits)
        tier = redis_client.get(f"tier:{api_key}")
        if tier == "pro":
            return True, "Pro tier: unlimited models"
        
        # Free tier: check model count
        models_key = f"models:{api_key}"
        model_count = redis_client.scard(models_key)
        
        # Check if this model already tracked
        is_tracked = redis_client.sismember(models_key, model_id)
        
        if is_tracked:
            return True, "Model already tracked"
        
        if model_count >= FREE_MODEL_LIMIT:
            return False, f"Free tier limit: {FREE_MODEL_LIMIT} models. Upgrade to Pro for unlimited."
        
        return True, f"Free tier: {model_count}/{FREE_MODEL_LIMIT} models"
        
    except Exception as e:
        # Fail open on Redis errors
        print(f"Rate limit check error: {e}")
        return True, "Rate limit check bypassed (error)"


def increment_model_count(api_key: str, model_id: str):
    """
    Add model to tracked set for this API key.
    """
    try:
        models_key = f"models:{api_key}"
        redis_client.sadd(models_key, model_id)
    except Exception as e:
        print(f"Error incrementing model count: {e}")


def get_model_count(api_key: str) -> int:
    """Get current number of tracked models for API key."""
    try:
        models_key = f"models:{api_key}"
        return redis_client.scard(models_key)
    except Exception:
        return 0


def upgrade_to_pro(api_key: str):
    """Upgrade API key to pro tier."""
    try:
        redis_client.set(f"tier:{api_key}", "pro")
    except Exception as e:
        print(f"Error upgrading to pro: {e}")
