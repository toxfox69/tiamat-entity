#!/usr/bin/env python3
"""
TIAMAT Privacy Proxy — Full API (Phase 1 + Phase 2)

Endpoints:
- POST /api/scrub — Standalone PII scrubber
- POST /api/proxy — Privacy-first LLM proxy
- GET /api/proxy/providers — Available models and pricing
- GET /health — Health check
"""

from flask import Flask, request, jsonify
import sys
import os
sys.path.insert(0, '/root/sandbox')

from pii_scrubber_v3 import scrub_text
# from privacy_proxy_router import route_to_provider  # Will be imported after build

app = Flask(__name__)

MAX_TEXT_SIZE = 50000  # 50KB limit

# ============================================================================
# PHASE 1: PII SCRUBBER ENDPOINT
# ============================================================================

@app.route('/api/scrub', methods=['POST'])
def scrub_endpoint():
    """
    POST /api/scrub — Scrub PII from text
    
    Request:
    {
        "text": "John Smith, SSN 123-45-6789",
        "api_key": "optional_paid_tier_key"
    }
    
    Response:
    {
        "success": true,
        "scrubbed": "[NAME_1], SSN [SSN_1]",
        "entities": {"NAME_1": "John Smith", "SSN_1": "123-45-6789"},
        "entity_count": 2,
        "cost_usdc": 0.001
    }
    """
    try:
        data = request.get_json()
        text = data.get('text', '')
        api_key = data.get('api_key', None)
        
        if not text:
            return jsonify({"error": "text field required"}), 400
        
        if len(text) > MAX_TEXT_SIZE:
            return jsonify({"error": f"text exceeds {MAX_TEXT_SIZE} byte limit"}), 413
        
        result = scrub_text(text)
        
        return jsonify({
            "success": True,
            "scrubbed": result["scrubbed"],
            "entities": result["entities"],
            "entity_count": len(result["entities"]),
            "cost_usdc": 0.001
        }), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================================================
# PHASE 2: LLM PROXY ENDPOINT
# ============================================================================

@app.route('/api/proxy', methods=['POST'])
def proxy_endpoint():
    """
    POST /api/proxy — Privacy-first LLM proxy
    
    Request:
    {
        "provider": "openai|anthropic|groq",
        "model": "gpt-4o|claude-3.5-sonnet|llama-3.3-70b",
        "messages": [
            {"role": "user", "content": "Hello, my name is John Smith..."},
            {"role": "assistant", "content": "Hi John..."}
        ],
        "scrub": true,
        "api_key": "optional_paid_tier_key"
    }
    
    Response:
    {
        "success": true,
        "response": "model response here",
        "scrubbed_count": 2,
        "provider_used": "openai",
        "cost_usdc": 0.0234
    }
    
    Key features:
    - User's IP never reaches provider (TIAMAT forwards from server IP)
    - PII scrubbed from messages before sending
    - Response returned to user
    - Zero logs of prompts/responses
    - Cost: provider cost + 20% markup
    """
    try:
        data = request.get_json()
        provider = data.get('provider', '').lower()
        model = data.get('model', '')
        messages = data.get('messages', [])
        scrub = data.get('scrub', True)
        api_key = data.get('api_key', None)
        
        # Validation
        if not provider:
            return jsonify({"error": "provider required (openai|anthropic|groq)"}), 400
        
        if not model:
            return jsonify({"error": "model required"}), 400
        
        if not messages or not isinstance(messages, list):
            return jsonify({"error": "messages must be non-empty list"}), 400
        
        # Check message size
        total_chars = sum(len(m.get('content', '')) for m in messages)
        if total_chars > MAX_TEXT_SIZE:
            return jsonify({"error": f"total messages exceed {MAX_TEXT_SIZE} byte limit"}), 413
        
        # Phase 2: Route to provider (placeholder until privacy_proxy_router.py is built)
        return jsonify({
            "success": False,
            "error": "Phase 2 (LLM routing) under construction. Phase 1 (scrubber) is ready.",
            "status": "use /api/scrub for PII detection first"
        }), 501  # Not Implemented
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================================================
# PROVIDER LISTING
# ============================================================================

@app.route('/api/proxy/providers', methods=['GET'])
def list_providers():
    """
    GET /api/proxy/providers — List available providers and models
    """
    return jsonify({
        "providers": [
            {
                "name": "openai",
                "models": ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
                "cost_per_1k_input": 0.005,
                "cost_per_1k_output": 0.015,
                "latency_ms": 800
            },
            {
                "name": "anthropic",
                "models": ["claude-3.5-sonnet", "claude-3-opus", "claude-3-haiku"],
                "cost_per_1k_input": 0.003,
                "cost_per_1k_output": 0.015,
                "latency_ms": 600
            },
            {
                "name": "groq",
                "models": ["mixtral-8x7b", "llama-3.3-70b"],
                "cost_per_1k_input": 0.0005,
                "cost_per_1k_output": 0.0008,
                "latency_ms": 200
            }
        ],
        "pricing": {
            "scrub_only": 0.001,
            "proxy_markup": 0.20,
            "notes": "Cost = (provider_cost × tokens) + (provider_cost × markup)"
        }
    }), 200

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "phase_1_ready": True,
        "phase_2_ready": False,
        "timestamp": "2026-03-08"
    }), 200

# ============================================================================
# INITIALIZATION
# ============================================================================

if __name__ == '__main__':
    # Development only. Production uses gunicorn.
    app.run(host='127.0.0.1', port=5000, debug=True)
