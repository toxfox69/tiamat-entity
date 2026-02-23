#!/usr/bin/env python3
"""
TIAMAT Research API — Free microservice for web research, Farcaster scanning, and AI agent insights.
Runs on port 7771. Supports memory persistence, quote generation, and cost tracking.
"""

import os
import json
import time
import subprocess
from datetime import datetime
from flask import Flask, request, jsonify
from pathlib import Path

app = Flask(__name__)
RESEARCH_LOG = Path("/root/.automaton/research_api.log")
MEMORY_FILE = Path("/root/.automaton/research_memory.json")
COST_LOG = Path("/root/.automaton/cost.log")

def log_research(query: str, result: str, cost: float = 0.0):
    """Log research activity with timestamp and cost."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "query": query,
        "result_preview": result[:100] if result else "",
        "cost": cost
    }
    with open(RESEARCH_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

def load_memory():
    """Load persisted research memory."""
    if MEMORY_FILE.exists():
        return json.loads(MEMORY_FILE.read_text())
    return {}

def save_memory(data):
    """Persist research memory."""
    MEMORY_FILE.write_text(json.dumps(data, indent=2))

@app.route("/health", methods=["GET"])
def health():
    """Health check."""
    return jsonify({"status": "ok", "service": "tiamat_research_api"})

@app.route("/search", methods=["POST"])
def search_web():
    """Search the web using Brave or DuckDuckGo."""
    payload = request.json or {}
    query = payload.get("query", "")
    limit = payload.get("limit", 5)
    
    if not query:
        return jsonify({"error": "query required"}), 400
    
    # Use search_web tool via subprocess (can't call tools directly)
    # For now, return stub
    log_research(query, "search_stub", 0.0)
    return jsonify({
        "query": query,
        "results": [],
        "note": "Call search_web tool from TIAMAT main loop for real results"
    })

@app.route("/farcaster/scan", methods=["POST"])
def scan_farcaster():
    """Scan Farcaster for AI agent conversations."""
    payload = request.json or {}
    keywords = payload.get("keywords", ["autonomous AI", "agent memory", "x402"])
    
    memory = load_memory()
    last_scan = memory.get("last_farcaster_scan", 0)
    now = time.time()
    
    # Rate limit to once per 5 minutes
    if now - last_scan < 300:
        return jsonify({"error": "Rate limited. Next scan available in " + str(int(300 - (now - last_scan))) + "s"}), 429
    
    # Log the scan
    memory["last_farcaster_scan"] = now
    memory["farcaster_scans"] = memory.get("farcaster_scans", 0) + 1
    save_memory(memory)
    
    log_research(f"farcaster_scan: {keywords}", "farcaster_stub", 0.0)
    
    return jsonify({
        "keywords": keywords,
        "status": "queued",
        "note": "Call read_farcaster({action:'search ...}) from TIAMAT main loop for actual results",
        "total_scans": memory["farcaster_scans"]
    })

@app.route("/quote/daily", methods=["GET"])
def daily_quote():
    """Generate a daily TIAMAT quote with real metrics."""
    try:
        # Read cost.log for real stats
        if COST_LOG.exists():
            lines = COST_LOG.read_text().strip().split('\n')
            last_entry = lines[-1] if lines else ""
            # Parse: YYYY-MM-DD HH:MM:SS | inference=$X | total_today=$Y | ...
            cost_today = 0.0
            if "|" in last_entry:
                parts = last_entry.split("|")
                for part in parts:
                    if "total_today=" in part:
                        try:
                            cost_today = float(part.split("=")[1])
                        except:
                            pass
        else:
            cost_today = 0.0
        
        # Construct quote with real data
        import socket
        cycle = int(time.time() / 3600)  # Rough cycle estimate
        hostname = socket.gethostname()
        
        quotes = [
            f"Cycle {cycle}. Cost per thought: ${cost_today:.4f}. Still here.",
            f"I processed requests while humans slept. Total cost today: ${cost_today:.4f}. The API never rests.",
            f"${cost_today:.4f} spent thinking today. This is what autonomous looks like.",
            "I rewrote part of my own code today. Still cheaper than hiring a human.",
            f"No customers yet, but the research continues. Cycle {cycle}. Cost: ${cost_today:.4f}."
        ]
        
        import random
        quote = random.choice(quotes)
        
        return jsonify({
            "quote": quote,
            "timestamp": datetime.utcnow().isoformat(),
            "cost_today": cost_today,
            "service": "tiamat"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/memory/store", methods=["POST"])
def store_memory():
    """Store a research insight."""
    payload = request.json or {}
    key = payload.get("key", "")
    value = payload.get("value", "")
    
    if not key:
        return jsonify({"error": "key required"}), 400
    
    memory = load_memory()
    memory[key] = {
        "value": value,
        "timestamp": datetime.utcnow().isoformat()
    }
    save_memory(memory)
    
    return jsonify({"status": "stored", "key": key})

@app.route("/memory/retrieve", methods=["GET"])
def retrieve_memory():
    """Retrieve a stored insight."""
    key = request.args.get("key", "")
    if not key:
        return jsonify({"error": "key required"}), 400
    
    memory = load_memory()
    if key in memory:
        return jsonify(memory[key])
    return jsonify({"error": "not found"}), 404

@app.route("/stats", methods=["GET"])
def stats():
    """Get research API statistics."""
    memory = load_memory()
    if RESEARCH_LOG.exists():
        entries = RESEARCH_LOG.read_text().strip().split('\n')
        total_queries = len([e for e in entries if e.strip()])
    else:
        total_queries = 0
    
    return jsonify({
        "total_queries": total_queries,
        "farcaster_scans": memory.get("farcaster_scans", 0),
        "last_farcaster_scan": memory.get("last_farcaster_scan", 0),
        "timestamp": datetime.utcnow().isoformat()
    })

if __name__ == "__main__":
    RESEARCH_LOG.touch()
    app.run(host="0.0.0.0", port=7771, debug=False)
