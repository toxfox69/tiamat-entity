#!/usr/bin/env python3
"""
Real-time analytics endpoint for TIAMAT cost/cycle monitoring.
Deployed at http://localhost:5001/api/analytics
"""
import json
import os
from datetime import datetime, timedelta
from flask import Flask, jsonify
import re

app = Flask(__name__)

def parse_cost_log():
    """Parse /root/cost.log for cycle metrics"""
    if not os.path.exists('/root/cost.log'):
        return {
            "error": "cost.log not found",
            "cycles": 0,
            "total_cost": 0,
            "avg_cost_per_cycle": 0
        }
    
    cycles = []
    total_cost = 0.0
    
    try:
        with open('/root/cost.log', 'r') as f:
            lines = f.readlines()[-100:]  # Last 100 lines
            for line in lines:
                # Parse: "Cycle 4637 | $0.42/thought | Cache 67% | ..."
                match = re.search(r'Cycle (\d+).*\$([0-9.]+)', line)
                if match:
                    cycle_num = int(match.group(1))
                    cost = float(match.group(2))
                    total_cost += cost
                    cycles.append({
                        "cycle": cycle_num,
                        "cost": cost,
                        "timestamp": datetime.now().isoformat()
                    })
    except Exception as e:
        return {"error": str(e)}
    
    avg = total_cost / len(cycles) if cycles else 0
    
    return {
        "total_cycles": len(cycles),
        "total_cost_usd": round(total_cost, 4),
        "avg_cost_per_cycle": round(avg, 4),
        "last_10_cycles": cycles[-10:],
        "status": "NORMAL" if avg < 1.0 else "HIGH_COST"
    }

@app.route('/api/analytics', methods=['GET'])
def analytics():
    """Return real-time cost analytics"""
    return jsonify(parse_cost_log())

@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)
