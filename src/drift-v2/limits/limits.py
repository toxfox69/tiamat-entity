"""
Drift v2 — Redis Rate Limiter
Free-tier: up to 3 models per API key per 30-day window.
"""

import os
import logging
from datetime import timedelta

import redis
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_FREE_MODEL_LIMIT = int(os.getenv("FREE_MODEL_LIMIT", "3"))
_WINDOW_DAYS = int(os.getenv("RATE_WINDOW_DAYS", "30"))
_WINDOW_SECONDS = int(timedelta(days=_WINDOW_DAYS).total_seconds())

# Module-level singleton — reuses connection pool
_redis_client: redis.Redis | None = None  # type: ignore[type-arg]
try:
    _redis_client = redis.from_url(_REDIS_URL, decode_responses=True)  # type: ignore[assignment]
    _redis_client.ping()
except Exception as exc:
    logger.warning("Redis unavailable for rate limiter: %s", exc)
    _redis_client = None


def _model_count_key(api_key: str) -> str:
    return f"drift:free:model_count:{api_key}"


# Atomic check-and-increment via Lua script.
# Returns new count if within limit, -1 if over limit.
# Only sets TTL on first write (NX-style) so the window doesn't reset.
_ATOMIC_INCREMENT_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])

local current = tonumber(redis.call('GET', key) or '0') or 0
if current >= limit then
    return -1
end

local new_count = redis.call('INCR', key)

-- Only set TTL if this is the first write (TTL == -1 means no expiry set)
if redis.call('TTL', key) == -1 then
    redis.call('EXPIRE', key, window)
end

return new_count
"""


def check_and_increment(api_key: str) -> tuple[bool, int]:
    """
    Atomically check free tier limit and increment if allowed.
    Returns (allowed: bool, new_count: int).
    Fails open if Redis is unreachable.
    """
    if _redis_client is None:
        return True, 0
    try:
        result = _redis_client.eval(  # type: ignore[union-attr]
            _ATOMIC_INCREMENT_LUA, 1, _model_count_key(api_key),
            _FREE_MODEL_LIMIT, _WINDOW_SECONDS,
        )
        result = int(result)
        if result == -1:
            count = get_model_count(api_key)
            logger.info("check_and_increment api_key=%s DENIED (count=%d, limit=%d)", api_key, count, _FREE_MODEL_LIMIT)
            return False, count
        logger.info("check_and_increment api_key=%s ALLOWED → %d", api_key, result)
        return True, result
    except redis.RedisError as exc:
        logger.warning("Redis error in check_and_increment (fail open): %s", exc)
        return True, 0


def check_free_tier(api_key: str) -> bool:
    """
    Return True if this api_key is still within the free tier limit.
    Read-only check — does not increment. Fails open if Redis unreachable.
    """
    if _redis_client is None:
        return True
    try:
        count_str = _redis_client.get(_model_count_key(api_key))  # type: ignore[union-attr]
        count = int(count_str) if count_str else 0
        allowed = count < _FREE_MODEL_LIMIT
        logger.debug("check_free_tier api_key=%s count=%d limit=%d → %s", api_key, count, _FREE_MODEL_LIMIT, allowed)
        return allowed
    except redis.RedisError as exc:
        logger.warning("Redis error in check_free_tier (fail open): %s", exc)
        return True


def get_model_count(api_key: str) -> int:
    """
    Return current 30-day model count for api_key.
    Returns 0 if key absent or Redis unavailable.
    """
    if _redis_client is None:
        return 0
    try:
        val = _redis_client.get(_model_count_key(api_key))  # type: ignore[union-attr]
        return int(val) if val else 0
    except redis.RedisError as exc:
        logger.warning("Redis error in get_model_count: %s", exc)
        return 0


def reset_model_count(api_key: str) -> bool:
    """Delete the rate-limit key (admin use / testing)."""
    if _redis_client is None:
        return False
    try:
        _redis_client.delete(_model_count_key(api_key))  # type: ignore[union-attr]
        logger.info("reset_model_count api_key=%s", api_key)
        return True
    except redis.RedisError as exc:
        logger.warning("Redis error in reset_model_count: %s", exc)
        return False


def get_limit_info(api_key: str) -> dict:
    """Return a summary dict for API responses."""
    count = get_model_count(api_key)
    remaining = max(0, _FREE_MODEL_LIMIT - count)
    return {
        "api_key": api_key,
        "free_tier_limit": _FREE_MODEL_LIMIT,
        "models_used": count,
        "models_remaining": remaining,
        "window_days": _WINDOW_DAYS,
        "within_limit": count < _FREE_MODEL_LIMIT,
    }
