#!/usr/bin/env python3
"""
Personal Data Removal Scanner Routes
Integrate into main Flask app with:
  from entity.src.agent.tools.scanner_routes import register_scanner_routes
  register_scanner_routes(app)
"""

from flask import request, jsonify
import subprocess
import json
import uuid
import os
from datetime import datetime

BROKER_CONFIGS = [
    {"name": "Spokeo", "url": "https://www.spokeo.com", "removal_script": "/root/sandbox/removers/spokeo_remover.py"},
    {"name": "WhitePages", "url": "https://www.whitepages.com", "removal_script": "/root/sandbox/removers/whitepages_remover.py"},
    {"name": "BeenVerified", "url": "https://www.beenverified.com", "removal_script": "/root/sandbox/removers/beenverified_remover.py"},
]

def validate_input(data):
    """Validate required fields."""
    required = ['first_name', 'last_name', 'city', 'state']
    for field in required:
        if field not in data or not data[field]:
            return {"error": f"Missing required field: {field}", "status": "error", "code": 400}
    return None

def register_scanner_routes(app):
    """Register all scanner routes with Flask app."""
    
    @app.route('/api/scan', methods=['POST'])
    def scan():
        """Scan brokers for a person's data."""
        try:
            data = request.get_json()
            validation_error = validate_input(data)
            if validation_error:
                return jsonify(validation_error), 400
            
            first_name = data.get('first_name', '').strip()
            last_name = data.get('last_name', '').strip()
            city = data.get('city', '').strip()
            state = data.get('state', '').strip()
            
            results = []
            for broker in BROKER_CONFIGS:
                result = {
                    "broker": broker['name'],
                    "url": broker['url'],
                    "search_url": f"{broker['url']}?name={first_name}+{last_name}&city={city}&state={state}",
                    "status": "pending_removal",
                    "removal_script": broker['removal_script']
                }
                results.append(result)
            
            return jsonify({
                "status": "success",
                "person": f"{first_name} {last_name}, {city}, {state}",
                "brokers_found": len(results),
                "brokers": results,
                "scan_id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat()
            }), 200
            
        except Exception as e:
            return jsonify({"error": str(e), "status": "error"}), 500
    
    @app.route('/api/remove', methods=['POST'])
    def trigger_removal():
        """Trigger automatic removal for a specific broker."""
        try:
            data = request.get_json()
            validation_error = validate_input(data)
            if validation_error:
                return jsonify(validation_error), 400
            
            broker_name = data.get('broker_name')
            if not broker_name:
                return jsonify({"error": "Missing broker_name"}), 400
            
            broker_config = None
            for broker in BROKER_CONFIGS:
                if broker['name'].lower() == broker_name.lower():
                    broker_config = broker
                    break
            
            if not broker_config:
                return jsonify({"error": f"Broker {broker_name} not found"}), 404
            
            removal_script = broker_config['removal_script']
            if not os.path.exists(removal_script):
                return jsonify({"error": f"Removal script not found: {removal_script}"}), 404
            
            try:
                result = subprocess.run(
                    ['python3', removal_script],
                    capture_output=True,
                    timeout=30,
                    text=True
                )
                
                try:
                    removal_result = json.loads(result.stdout)
                except:
                    removal_result = {"stdout": result.stdout, "stderr": result.stderr}
                
                return jsonify({
                    "status": "success",
                    "broker": broker_name,
                    "removal_result": removal_result,
                    "timestamp": datetime.utcnow().isoformat()
                }), 200
                
            except subprocess.TimeoutExpired:
                return jsonify({"error": "Removal script timeout"}), 408
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        except Exception as e:
            return jsonify({"error": str(e), "status": "error"}), 500
    
    @app.route('/api/removal-status', methods=['GET'])
    def removal_status():
        """Get scanner service status."""
        return jsonify({
            "status": "online",
            "service": "Personal Data Removal Scanner",
            "phase": 4,
            "brokers_configured": len(BROKER_CONFIGS),
            "brokers": [b['name'] for b in BROKER_CONFIGS]
        }), 200
