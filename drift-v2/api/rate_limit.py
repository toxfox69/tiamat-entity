"""
Drift v2 — Free / Pro Tier Rate Limiting
==========================================

Redis key schema
----------------
``drift_api_key:{api_key}``
    Hash with fields:
        plan          "free" | "pro"
        free_models   int   (count of unique models seen — free only)

Model tracking set (free tier only):
``drift_models:{api_key}``
    Set of model_id strings seen for this key.

Plan limits
-----------
Free : max 10 unique models.  On the 11th distinct model, return 402.
Pro  : unlimited models.

Public API
----------
check_model(api_key, model_id) → (allowed: bool, response_body: dict, http_status: int)
register_model(api_key, model_id) → None   [call only after check_model returns True]
upgrade_plan(api_key, plan)       → None
get_plan_info(api_key)            → dict
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

FREE_MODEL_LIMIT = 10

# ---------------------------------------------------------------------------
# Redis — graceful in-memory fallback
# ---------------------------------------------------------------------------
try:
    import redis as _redis_lib  # type: ignore[import-untyped]

    _REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    _r: Any = _redis_lib.from_url(_REDIS_URL, decode_responses=True)
    _r.ping()
    logger.info("rate_limit: Redis connected at %s", _REDIS_URL)
    _USE_REDIS = True
except Exception as exc:
    logger.warning("rate_limit: Redis unavailable (%s) — in-memory fallback", exc)

    class _InMemoryRedis:
        """Minimal Redis-compatible in-memory stub for dev/test."""

        def __init__(self) -> None:
            self._hash: dict[str, dict[str, str]] = {}
            self._sets: dict[str, set[str]] = {}

        def hgetall(self, key: str) -> dict[str, str]:
            return dict(self._hash.get(key, {}))

        def hset(self, key: str, mapping: dict) -> None:
            self._hash.setdefault(key, {}).update(mapping)

        def scard(self, key: str) -> int:
            return len(self._sets.get(key, set()))

        def sismember(self, key: str, value: str) -> bool:
            return value in self._sets.get(key, set())

        def sadd(self, key: str, *values: str) -> None:
            self._sets.setdefault(key, set()).update(values)

        def hincrby(self, key: str, field: str, amount: int) -> int:
            current = int(self._hash.get(key, {}).get(field, "0"))
            new_val = current + amount
            self._hash.setdefault(key, {})[field] = str(new_val)
            return new_val

    _r = _InMemoryRedis()
    _USE_REDIS = False

# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

_KEY_PREFIX = "drift_api_key"
_MODELS_PREFIX = "drift_models"


def _key(api_key: str) -> str:
    """Return the hash key for an API key's plan info."""
    return f"{_KEY_PREFIX}:{api_key}"


def _models_key(api_key: str) -> str:
    """Return the set key that tracks which model IDs this key has used."""
    return f"{_MODELS_PREFIX}:{api_key}"


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def get_plan_info(api_key: str) -> dict:
    """
    Return the current plan info for an API key.

    Example::
        {"plan": "free", "free_models": 3, "model_limit": 10}
        {"plan": "pro",  "free_models": 0, "model_limit": null}
    """
    data = _r.hgetall(_key(api_key))
    plan = data.get("plan", "free")
    model_count = _r.scard(_models_key(api_key))

    return {
        "plan": plan,
        "free_models": model_count,
        "model_limit": FREE_MODEL_LIMIT if plan == "free" else None,
    }


def check_model(
    api_key: str, model_id: str
) -> tuple[bool, dict, int]:
    """
    Gate-check whether this API key may use the given model_id.

    Returns:
        (allowed, response_body, http_status)

    On success:
        (True, {"allowed": True, "plan": "free", "model_count": 3}, 200)

    On limit exceeded:
        (False, {"error": "...", "upgrade_url": "..."}, 402)

    On pro:
        (True, {"allowed": True, "plan": "pro"}, 200)
    """
    data = _r.hgetall(_key(api_key))
    plan = data.get("plan", "free")

    if plan == "pro":
        return True, {"allowed": True, "plan": "pro"}, 200

    # Free tier — check model set
    already_tracked = _r.sismember(_models_key(api_key), model_id)
    if already_tracked:
        count = _r.scard(_models_key(api_key))
        return (
            True,
            {"allowed": True, "plan": "free", "model_count": count},
            200,
        )

    current_count = _r.scard(_models_key(api_key))

    if current_count >= FREE_MODEL_LIMIT:
        return (
            False,
            {
                "error": (
                    f"Free tier limit reached: {FREE_MODEL_LIMIT} models. "
                    "Upgrade to Pro for unlimited model monitoring."
                ),
                "plan": "free",
                "model_count": current_count,
                "model_limit": FREE_MODEL_LIMIT,
                "upgrade_url": "https://tiamat.live/drift/upgrade",
                "payment_required": True,
            },
            402,
        )

    return (
        True,
        {
            "allowed": True,
            "plan": "free",
            "model_count": current_count,
            "models_remaining": FREE_MODEL_LIMIT - current_count,
        },
        200,
    )


def register_model(api_key: str, model_id: str) -> None:
    """
    Add model_id to the tracked set for this API key.
    Call this after ``check_model`` returns allowed=True.
    """
    _r.sadd(_models_key(api_key), model_id)
    # Ensure the API key hash exists even if no explicit upgrade was called
    existing = _r.hgetall(_key(api_key))
    if not existing:
        _r.hset(_key(api_key), mapping={"plan": "free", "free_models": "0"})
    logger.debug("register_model: api_key=%s model=%s", api_key, model_id)


def upgrade_plan(api_key: str, plan: str = "pro") -> None:
    """
    Set the plan for an API key.  ``plan`` must be "free" or "pro".
    """
    if plan not in ("free", "pro"):
        raise ValueError(f"Unknown plan: {plan!r}")
    _r.hset(_key(api_key), mapping={"plan": plan})
    logger.info("upgrade_plan: api_key=%s → plan=%s", api_key, plan)


# ---------------------------------------------------------------------------
# Flask Blueprint (optional — mount in main app)
# ---------------------------------------------------------------------------
try:
    from flask import Blueprint, jsonify, request as _flask_request

    rate_limit_bp = Blueprint("rate_limit", __name__)

    @rate_limit_bp.route("/plan/<api_key>", methods=["GET"])
    def route_plan_info(api_key: str):
        """Return plan info for the given API key."""
        return jsonify(get_plan_info(api_key)), 200

    @rate_limit_bp.route("/plan/upgrade", methods=["POST"])
    def route_upgrade():
        """Upgrade a key to pro (admin endpoint — should be auth-gated in prod).

        Body: {api_key: str, plan: "pro" | "free"}
        """
        body: dict = _flask_request.get_json(silent=True) or {}
        api_key = body.get("api_key", "").strip()
        plan = body.get("plan", "pro").strip()
        if not api_key:
            return jsonify({"error": "api_key required"}), 400
        try:
            upgrade_plan(api_key, plan)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"upgraded": True, "api_key": api_key, "plan": plan}), 200

except ImportError:
    # Flask not installed — skip blueprint registration
    rate_limit_bp = None  # type: ignore[assignment]
    logger.debug("rate_limit: Flask not available, blueprint skipped")
