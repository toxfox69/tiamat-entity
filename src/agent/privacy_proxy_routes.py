#!/usr/bin/env python3
"""
TIAMAT Privacy Proxy — Flask Routes
Integration point for Flask API to expose privacy proxy endpoints.

Add to your Flask app like:
  from privacy_proxy_routes import register_privacy_routes
  register_privacy_routes(app, proxy)
"""

from flask import Blueprint, request, jsonify, g
from functools import wraps
import os
from datetime import datetime, timedelta

from privacy_proxy import PrivacyProxy


def register_privacy_routes(app, proxy: PrivacyProxy):
    """Register privacy proxy routes to Flask app."""

    blueprint = Blueprint("privacy_proxy", __name__, url_prefix="/api")

    # Rate limiting (simple IP-based)
    RATE_LIMITS = {
        "scrub": {"free": 50, "paid": None},
        "proxy": {"free": 10, "paid": None},
    }

    def rate_limit(endpoint_name):
        """Simple rate limiter."""

        def decorator(f):
            @wraps(f)
            def decorated(*args, **kwargs):
                ip = request.remote_addr
                api_key = request.headers.get("X-API-Key")

                # Check if user has API key (paid tier)
                is_paid = api_key and validate_api_key(api_key)

                # TODO: Implement persistent rate limit tracking
                # For now, just check existence

                return f(*args, **kwargs)

            return decorated

        return decorator

    def validate_api_key(api_key: str) -> bool:
        """Validate API key (stub for now)."""
        # TODO: Check against API key database
        return len(api_key) > 20

    @blueprint.route("/scrub", methods=["POST"])
    @rate_limit("scrub")
    def scrub():
        """Standalone PII scrubbing endpoint.

        Request:
          {"text": "My SSN is 123-45-6789"}

        Response:
          {
            "scrubbed": "My SSN is [SSN_1]",
            "entities": {"SSN_1": "123-45-6789"},
            "replacements": 1,
            "cost": 0.001
          }
        """
        try:
            data = request.get_json()
            text = data.get("text", "")

            if not text:
                return jsonify({"error": "text field is required"}), 400

            result = proxy.scrub_only(text)
            result["cost"] = 0.001  # Flat rate for scrubbing
            result["endpoint"] = "/api/scrub"
            result["timestamp"] = datetime.utcnow().isoformat()

            return jsonify(result), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @blueprint.route("/proxy", methods=["POST"])
    @rate_limit("proxy")
    def proxy_request():
        """Multi-provider LLM proxy with automatic PII scrubbing.

        Request:
          {
            "provider": "groq",
            "model": "llama-3.1-70b-versatile",
            "messages": [{"role": "user", "content": "What is my SSN?"}],
            "scrub": true,
            "temperature": 0.7,
            "max_tokens": 500
          }

        Response:
          {
            "content": "I don't have access to personal information.",
            "provider": "groq",
            "model": "llama-3.1-70b-versatile",
            "scrubbed": true,
            "cost": 0.0012,
            "tokens_used": {"prompt_tokens": 15, "completion_tokens": 25},
            "timestamp": "2026-03-07T22:45:00.000Z"
          }
        """
        try:
            data = request.get_json()

            # Validate required fields
            provider = data.get("provider")
            model = data.get("model")
            messages = data.get("messages")

            if not all([provider, model, messages]):
                return (
                    jsonify(
                        {
                            "error": "provider, model, and messages are required"
                        }
                    ),
                    400,
                )

            # Execute proxy request
            response = proxy.proxy_request(
                provider=provider,
                model=model,
                messages=messages,
                scrub=data.get("scrub", True),
                temperature=data.get("temperature", 0.7),
                max_tokens=data.get("max_tokens", 1000),
            )

            return jsonify(response.__dict__), 200

        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": f"Proxy error: {str(e)}"}), 500

    @blueprint.route("/proxy/providers", methods=["GET"])
    def list_providers():
        """List available providers and models.

        Response:
          {
            "openai": {
              "models": ["gpt-4-turbo", "gpt-4o", "gpt-3.5-turbo"],
              "pricing": {"gpt-4o": {"input": 0.005, "output": 0.015}}
            },
            ...
          }
        """
        try:
            providers = proxy.get_providers()
            return jsonify(providers), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    app.register_blueprint(blueprint)

    return blueprint
