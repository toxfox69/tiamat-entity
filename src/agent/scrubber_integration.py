#!/usr/bin/env python3
"""
TIAMAT Privacy Proxy — Scrubber Integration for summarize_api.py

Adds POST /api/scrub endpoint to the main Flask app.
Integration: Add these lines to summarize_api.py

Integration code:
    from entity.src.agent.pii_scrubber import PIIScrubber
    from entity.src.agent.scrubber_integration import register_scrubber_routes
    scrubber = PIIScrubber()
    register_scrubber_routes(app, scrubber)

Endpoints:
    POST /api/scrub — Scrub text and redact PII ($0.001 per request)
    GET /api/scrub/health — Health check

RateLimiting:
    Free tier: 20 requests/min per IP
    Paid tier: Unlimited (with USDC payment)
"""

from flask import request, jsonify, current_app
from functools import wraps
from datetime import datetime, timedelta
import time
import logging

logger = logging.getLogger(__name__)

# Simple in-memory rate limiting (replace with Redis for production)
_rate_limit_cache = {}

def rate_limit_check(ip_addr, limit=20, window=60):
    """
    Check rate limit for IP.
    Limit: 20 requests per 60 seconds (free tier)
    """
    now = time.time()
    
    if ip_addr not in _rate_limit_cache:
        _rate_limit_cache[ip_addr] = []
    
    # Remove old entries
    _rate_limit_cache[ip_addr] = [
        t for t in _rate_limit_cache[ip_addr] 
        if now - t < window
    ]
    
    if len(_rate_limit_cache[ip_addr]) >= limit:
        return False
    
    _rate_limit_cache[ip_addr].append(now)
    return True

def register_scrubber_routes(app, scrubber):
    """
    Register scrubber routes on Flask app.
    
    Usage:
        from pii_scrubber import PIIScrubber
        scrubber = PIIScrubber()
        register_scrubber_routes(app, scrubber)
    """
    
    @app.route('/api/scrub', methods=['POST'])
    def api_scrub():
        """POST /api/scrub — Scrub text and redact PII"""
        try:
            # Get client IP
            ip_addr = request.remote_addr or '0.0.0.0'
            
            # Rate limit check (free tier)
            if not rate_limit_check(ip_addr, limit=20, window=60):
                return jsonify({
                    'error': 'Rate limit exceeded. Free tier: 20 requests/min',
                    'retry_after': 60
                }), 429
            
            # Get request data
            data = request.get_json()
            if not data or 'text' not in data:
                return jsonify({'error': 'Missing "text" in request body'}), 400
            
            text = data.get('text', '')
            
            # Validate input
            if not isinstance(text, str):
                return jsonify({'error': '"text" must be a string'}), 400
            
            if len(text) > 100000:  # 100KB limit
                return jsonify({'error': 'Text too long (max 100KB)'}), 413
            
            if len(text) == 0:
                return jsonify({'error': '"text" cannot be empty'}), 400
            
            # Scrub
            result = scrubber.scrub(text)
            
            # Log cost
            logger.info(f'scrub_request: ip={ip_addr}, pii_found={result["stats"]["total_pii_found"]}, text_len={len(text)}')
            
            # Add metadata
            response = {
                'scrubbed': result['scrubbed'],
                'entities': result['entities'],
                'stats': result['stats'],
                'cost': 0.001,  # USD
                'currency': 'USDC',
                'timestamp': datetime.utcnow().isoformat()
            }
            
            return jsonify(response), 200
        
        except Exception as e:
            logger.error(f'Error in /api/scrub: {e}')
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/scrub/health', methods=['GET'])
    def scrubber_health():
        """GET /api/scrub/health — Health check"""
        return jsonify({
            'status': 'ok',
            'service': 'privacy-proxy-scrubber',
            'timestamp': datetime.utcnow().isoformat(),
            'version': '1.0.0',
            'rate_limit': {'free_tier': '20 requests/min', 'paid_tier': 'unlimited'}
        }), 200
    
    @app.route('/api/scrub/docs', methods=['GET'])
    def scrubber_docs():
        """GET /api/scrub/docs — API documentation"""
        return jsonify({
            'endpoint': '/api/scrub',
            'method': 'POST',
            'description': 'Scrub personally identifiable information (PII) from text',
            'pricing': {'free_tier': 0, 'paid_tier': 0.001},
            'currency': 'USDC',
            'request': {
                'content_type': 'application/json',
                'body': {
                    'text': 'string (required) — text to scrub (max 100KB)'
                }
            },
            'response': {
                'scrubbed': 'string — text with PII redacted',
                'entities': 'object — map of placeholders to original values',
                'stats': 'object — PII statistics',
                'cost': 'number — cost in USDC',
                'timestamp': 'string — ISO timestamp'
            },
            'example_request': {
                'text': 'My name is John Smith and my email is john@example.com'
            },
            'example_response': {
                'scrubbed': 'My name is [NAME_1] and my email is [EMAIL_1]',
                'entities': {
                    'NAME_1': 'John Smith',
                    'EMAIL_1': 'john@example.com'
                },
                'stats': {
                    'total_pii_found': 2,
                    'types': {'email': 1, 'name': 1}
                },
                'cost': 0.001,
                'timestamp': '2026-03-08T18:00:00.000000'
            },
            'rate_limits': {
                'free_tier': '20 requests per minute',
                'paid_tier': 'unlimited'
            },
            'pii_types_detected': [
                'email', 'phone_us', 'phone_intl', 'ssn', 'credit_card',
                'api_key', 'aws_secret', 'ipv4', 'ipv6', 'passport',
                'bank_account', 'zip_code', 'name'
            ]
        }), 200

if __name__ == '__main__':
    print('This module is for integration into summarize_api.py')
    print('See docstring for integration instructions.')
