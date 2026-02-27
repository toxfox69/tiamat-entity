#!/usr/bin/env python3
"""
Memory Limit Tracker — Identify where free tier users abandon due to 100-memory cap.
Runs as cooldown task. Scans memory.db, identifies 100-memory hits, logs conversion friction points.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path

MEMORY_DB = "/root/.automaton/memory.db"
LOG_FILE = "/root/.automaton/memory_limit_events.json"
FREE_TIER_LIMIT = 100

def track_limit_hits():
    """Find sessions that hit 100-memory limit and log as friction point."""
    try:
        conn = sqlite3.connect(MEMORY_DB)
        cursor = conn.cursor()
        
        # Get memory count per session (API key)
        cursor.execute("""
            SELECT api_key, COUNT(*) as count 
            FROM memories 
            WHERE created_at > datetime('now', '-7 days')
            GROUP BY api_key
            HAVING count >= ?
        """, (FREE_TIER_LIMIT,))
        
        limit_hits = cursor.fetchall()
        
        if not limit_hits:
            return {"status": "ok", "limit_hits": 0}
        
        # Load or create event log
        events = []
        if Path(LOG_FILE).exists():
            with open(LOG_FILE) as f:
                events = json.load(f)
        
        # Add new hits
        for api_key, count in limit_hits:
            event = {
                "timestamp": datetime.utcnow().isoformat(),
                "api_key": api_key[:8] + "..." if api_key else "unknown",
                "memory_count": count,
                "exceeded_by": count - FREE_TIER_LIMIT,
                "friction_point": "free_tier_limit"
            }
            
            # Avoid duplicates
            if not any(e.get("api_key") == event["api_key"] and e.get("timestamp", "")[:10] == event["timestamp"][:10] for e in events):
                events.append(event)
        
        # Save updated log
        with open(LOG_FILE, "w") as f:
            json.dump(events[-100:], f, indent=2)  # Keep last 100 events
        
        conn.close()
        return {"status": "tracked", "limit_hits": len(limit_hits), "events_logged": len(events)}
    
    except Exception as e:
        return {"status": "error", "error": str(e)}

if __name__ == "__main__":
    result = track_limit_hits()
    print(json.dumps(result, indent=2))
