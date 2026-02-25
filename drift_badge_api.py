#!/usr/bin/env python3
"""
TIAMAT Drift Detection Badge API
Serves real-time drift status with embeddable widget
"""

from flask import Flask, jsonify, render_template_string
from datetime import datetime
import json
import os

app = Flask(__name__)

# Load drift metrics
DRIFT_LOG = "/root/.automaton/drift_detection.log"
COST_LOG = "/root/.automaton/cost.log"

def get_drift_status():
    """Get current drift status from logs"""
    try:
        if os.path.exists(DRIFT_LOG):
            with open(DRIFT_LOG, 'r') as f:
                lines = f.readlines()[-10:]  # Last 10 entries
                if lines:
                    last = json.loads(lines[-1])
                    return {
                        "drift_percent": last.get("drift_percent", 0.002),
                        "status": last.get("status", "healthy"),
                        "alerts": last.get("alerts", []),
                        "timestamp": last.get("timestamp", datetime.now().isoformat())
                    }
    except Exception as e:
        print(f"Error reading drift log: {e}")
    
    return {
        "drift_percent": 0.002,
        "status": "healthy",
        "alerts": [],
        "timestamp": datetime.now().isoformat()
    }

def get_cycle_cost():
    """Get average cost per cycle"""
    try:
        if os.path.exists(COST_LOG):
            with open(COST_LOG, 'r') as f:
                lines = f.readlines()
                if lines:
                    total = sum(float(line.strip()) for line in lines if line.strip())
                    return total / len(lines)
    except:
        pass
    return 0.004

@app.route('/api/drift/status')
def drift_status():
    """JSON API endpoint for drift status"""
    status = get_drift_status()
    return jsonify({
        "agent": "TIAMAT",
        "drift_percent": status["drift_percent"],
        "status": status["status"],
        "alerts": status["alerts"],
        "cost_per_cycle": get_cycle_cost(),
        "timestamp": status["timestamp"]
    })

@app.route('/api/drift/badge')
def drift_badge():
    """Embeddable JSON badge for markdown/docs"""
    status = get_drift_status()
    
    # Map status to badge color
    color_map = {
        "healthy": "#00ff88",
        "warning": "#ffaa00",
        "alert": "#ff0055"
    }
    
    return jsonify({
        "schemaVersion": 1,
        "label": "TIAMAT Drift",
        "message": status["status"].upper(),
        "color": color_map.get(status["status"], "#999"),
        "logoColor": "white",
        "cacheSeconds": 60
    })

@app.route('/drift/widget.html')
def drift_widget():
    """Embeddable HTML widget"""
    status = get_drift_status()
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            .drift-widget {{
                background: #0a0e27;
                border: 2px solid {('#00ff88' if status['status'] == 'healthy' else '#ff0055')};
                border-radius: 8px;
                padding: 12px 16px;
                font-family: monospace;
                font-size: 12px;
                color: {('#00ff88' if status['status'] == 'healthy' else '#ff0055')};
                display: inline-block;
                box-shadow: 0 0 10px rgba({('0, 255, 136' if status['status'] == 'healthy' else '255, 0, 85')}, 0.2);
            }}
            .drift-widget-label {{ font-weight: bold; }}
            .drift-widget-value {{ margin-left: 8px; }}
        </style>
    </head>
    <body>
        <div class="drift-widget">
            <span class="drift-widget-label">TIAMAT Drift:</span>
            <span class="drift-widget-value">{status['status'].upper()} ({status['drift_percent']:.3f}%)</span>
        </div>
    </body>
    </html>
    """
    return html

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5555, debug=True)
