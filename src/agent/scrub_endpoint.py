"""Privacy Proxy Scrubber Endpoint — PII removal for AI requests

Makes user data safe to send to any LLM provider.
"""

from flask import Blueprint, request, jsonify
from functools import wraps
import time
import os
import sys

sys.path.insert(0, '/root/entity/src/agent')
from pii_scrubber import PIIScrubber

scrub_bp = Blueprint('scrub', __name__, url_prefix='/api')

# Global scrubber instance
_scrubber = None

def get_scrubber():
    global _scrubber
    if _scrubber is None:
        _scrubber = PIIScrubber()
    return _scrubber

# Rate limiting (simple IP-based, per free tier)
RATE_LIMITS = {}  # {ip: (count, reset_time)}
FREE_TIER_LIMIT = 50  # requests per day per IP
PAID_TIER_LIMIT = 1000000  # effectively unlimited

def get_client_ip():
    """Get client IP for rate limiting"""
    return request.remote_addr or '127.0.0.1'

def rate_limit(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = get_client_ip()
        now = time.time()
        
        # Check if user has API key (paid tier = no limit)
        api_key = request.headers.get('X-TIAMAT-Key')
        if api_key:
            return f(*args, **kwargs)  # Paid tier, no limit
        
        # Free tier rate limiting
        if ip not in RATE_LIMITS:
            RATE_LIMITS[ip] = [0, now + 86400]  # Reset daily
        
        count, reset_time = RATE_LIMITS[ip]
        
        if now > reset_time:
            # Reset counter
            RATE_LIMITS[ip] = [0, now + 86400]
            count = 0
        
        if count >= FREE_TIER_LIMIT:
            return jsonify({
                'error': f'Rate limit exceeded. Free tier: {FREE_TIER_LIMIT}/day. Get API key for unlimited access.',
                'remaining': 0,
                'reset_time': reset_time
            }), 429
        
        RATE_LIMITS[ip][0] = count + 1
        
        response = f(*args, **kwargs)
        if isinstance(response, tuple):
            response[0].headers['X-RateLimit-Remaining'] = str(FREE_TIER_LIMIT - count - 1)
        
        return response
    
    return decorated


@scrub_bp.route('/scrub', methods=['POST'])
@rate_limit
def scrub_text():
    """Scrub PII from a single text
    
    Request:
        {"text": "My name is John Smith, SSN 123-45-6789"}
    
    Response:
        {
            "scrubbed": "My name is [NAME_1], SSN [SSN_1]",
            "entities": {
                "NAME_1": "John Smith",
                "SSN_1": "123-45-6789"
            },
            "entity_count": 2,
            "cost_usd": 0.001
        }
    """
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({'error': 'Missing required field: text'}), 400
        
        text = data['text']
        if not isinstance(text, str) or len(text) == 0:
            return jsonify({'error': 'text must be a non-empty string'}), 400
        
        if len(text) > 10000:
            return jsonify({'error': 'text exceeds maximum length (10,000 chars)'}), 413
        
        # Scrub the text
        scrubber = get_scrubber()
        result = scrubber.scrub(text)
        
        # Add cost
        result['cost_usd'] = 0.001
        
        return jsonify(result), 200
    
    except Exception as e:
        return jsonify({'error': f'Scrubbing failed: {str(e)}'}), 500


@scrub_bp.route('/scrub/batch', methods=['POST'])
@rate_limit
def scrub_batch():
    """Scrub PII from multiple texts (bulk processing)
    
    Request:
        {"texts": ["text1", "text2", ...]}
    
    Response:
        {
            "results": [
                {"scrubbed": "...", "entities": {...}, "entity_count": N},
                ...
            ],
            "batch_count": 2,
            "total_entities": 5,
            "cost_usd": 0.002
        }
    """
    try:
        data = request.get_json()
        if not data or 'texts' not in data:
            return jsonify({'error': 'Missing required field: texts'}), 400
        
        texts = data['texts']
        if not isinstance(texts, list):
            return jsonify({'error': 'texts must be a list'}), 400
        
        if len(texts) > 100:
            return jsonify({'error': 'Maximum 100 texts per batch'}), 413
        
        # Scrub all texts
        scrubber = get_scrubber()
        results = []
        total_entities = 0
        
        for text in texts:
            if not isinstance(text, str):
                return jsonify({'error': 'All items must be strings'}), 400
            
            if len(text) > 10000:
                return jsonify({'error': 'Individual text exceeds 10,000 chars'}), 413
            
            result = scrubber.scrub(text)
            results.append(result)
            total_entities += result.get('entity_count', 0)
        
        return jsonify({
            'results': results,
            'batch_count': len(texts),
            'total_entities': total_entities,
            'cost_usd': len(texts) * 0.001
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Batch scrubbing failed: {str(e)}'}), 500


@scrub_bp.route('/scrub/entities', methods=['GET'])
def list_entities():
    """List all detectable PII entity types
    
    Response:
        {
            "entity_types": [
                {"type": "EMAIL", "description": "Email addresses", "examples": [...]},
                ...
            ],
            "total_types": 16
        }
    """
    scrubber = get_scrubber()
    
    entity_descriptions = {
        'EMAIL': {'description': 'Email addresses', 'examples': ['john@example.com']},
        'PHONE': {'description': 'Phone numbers (US and international)', 'examples': ['(555) 123-4567', '+44 20 7946 0958']},
        'NAME': {'description': 'Personal names', 'examples': ['John Smith', 'Jane Doe']},
        'SSN': {'description': 'Social Security Numbers', 'examples': ['123-45-6789']},
        'CREDIT_CARD': {'description': 'Credit card numbers', 'examples': ['4532-1111-2222-3333']},
        'CVV': {'description': 'Card verification codes', 'examples': ['123', '1234']},
        'API_KEY': {'description': 'API keys and tokens', 'examples': ['sk-proj-123abc', 'AKIA2FJKEQ7D6K7']},
        'OAUTH_TOKEN': {'description': 'OAuth tokens', 'examples': ['oauth2_token_xyz']},
        'PASSWORD': {'description': 'Passwords and secrets', 'examples': ['MyP@ssw0rd123']},
        'IPV4': {'description': 'IPv4 addresses', 'examples': ['192.168.1.1']},
        'IPV6': {'description': 'IPv6 addresses', 'examples': ['2001:0db8:85a3::8a2e:0370:7334']},
        'DB_CONNECTION': {'description': 'Database connection strings', 'examples': ['postgresql://user:pass@host']},
        'AWS_KEY': {'description': 'AWS access keys', 'examples': ['AKIA2FJKEQ7D6K7']},
        'PASSPORT': {'description': 'Passport numbers', 'examples': ['A12345678']},
        'LICENSE_PLATE': {'description': 'License plate numbers', 'examples': ['ABC-1234']},
        'DOB': {'description': 'Date of birth', 'examples': ['1985-03-15', '03/15/1985']},
    }
    
    entity_types = []
    for entity_type in ['EMAIL', 'PHONE', 'NAME', 'SSN', 'CREDIT_CARD', 'CVV', 'API_KEY', 'OAUTH_TOKEN', 'PASSWORD', 'IPV4', 'IPV6', 'DB_CONNECTION', 'AWS_KEY', 'PASSPORT', 'LICENSE_PLATE', 'DOB']:
        entity_types.append({
            'type': entity_type,
            **entity_descriptions.get(entity_type, {'description': 'Custom entity type', 'examples': []})
        })
    
    return jsonify({
        'entity_types': entity_types,
        'total_types': len(entity_types)
    }), 200


@scrub_bp.route('/scrub/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'service': 'tiamat-privacy-scrubber'}), 200
