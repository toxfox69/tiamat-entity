"""Minimal PII scrubber Flask endpoint"""

from flask import Blueprint, request, jsonify
from pii_scrubber_v1 import scrub_pii

scrub_bp = Blueprint('scrub', __name__, url_prefix='/api')

@scrub_bp.route('/scrub', methods=['POST'])
def scrub():
    """POST /api/scrub — Scrub PII from text"""
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({'error': 'Missing text field'}), 400
        
        result = scrub_pii(data['text'])
        return jsonify({
            'scrubbed': result.scrubbed_text,
            'entities': result.entities,
            'entity_count': result.entity_count,
            'cost_usd': 0.001
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@scrub_bp.route('/scrub/entities', methods=['GET'])
def list_entities():
    """GET /api/scrub/entities — List detectable types"""
    return jsonify({
        'entities': {
            'contact': ['email', 'phone'],
            'identity': ['ssn'],
            'financial': ['credit_card'],
            'technical': ['api_key', 'password'],
            'network': ['ipv4']
        }
    }), 200
