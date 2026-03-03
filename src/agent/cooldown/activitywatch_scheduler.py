#!/usr/bin/env python3
"""
TIK-441: ActivityWatch Sync Backend (Step 1) — Cooldown Task Scheduler

Runs automatically between agent cycles to poll ActivityWatch, parse events,
store to memory API, and log to cost.log.

Designed as a cooldown task (non-blocking, 5s max execution).
"""

import json
import requests
from datetime import datetime, timedelta
import sys
import os

# Add parent paths for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def check_aw_available(timeout=3):
    """Check if ActivityWatch is running on localhost:3636."""
    try:
        resp = requests.get('http://localhost:3636/api/0/info', timeout=timeout)
        return resp.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False

def get_recent_events(max_events=50):
    """
    Fetch recent activity events from ActivityWatch.
    Queries all standard buckets (window, afk, web) for last 1 hour.
    """
    if not check_aw_available():
        return []
    
    try:
        # Get buckets
        resp = requests.get('http://localhost:3636/api/0/buckets')
        if resp.status_code != 200:
            return []
        
        buckets = resp.json()
        target_buckets = [
            b for b in buckets.keys()
            if any(x in b for x in ['aw-watcher-window', 'aw-watcher-afk', 'aw-watcher-web'])
        ]
        
        if not target_buckets:
            return []
        
        # Query events from last 1 hour
        end_time = datetime.utcnow().isoformat() + 'Z'
        start_time = (datetime.utcnow() - timedelta(hours=1)).isoformat() + 'Z'
        
        all_events = []
        for bucket in target_buckets:
            try:
                resp = requests.get(
                    f'http://localhost:3636/api/0/buckets/{bucket}/events',
                    params={'start': start_time, 'end': end_time, 'limit': max_events}
                )
                if resp.status_code == 200:
                    all_events.extend(resp.json())
            except:
                continue
        
        return all_events[:max_events]
    except Exception as e:
        print(f"[ERROR] ActivityWatch query failed: {e}", file=sys.stderr)
        return []

def parse_events_to_memory(events):
    """
    Convert ActivityWatch events to memory API format.
    Returns list of {type: 'activity', app, title, duration_seconds, timestamp}
    """
    memories = []
    
    for evt in events:
        try:
            data = evt.get('data', {})
            timestamp = evt.get('timestamp', '')
            duration = evt.get('duration', 0)
            
            # Extract app and title based on bucket type
            app = data.get('app', 'unknown')
            title = data.get('title', '')
            
            memory = {
                'type': 'activity',
                'app': app,
                'title': title[:100],  # Truncate long titles
                'duration_seconds': int(duration),
                'timestamp': timestamp,
                'source': 'activitywatch'
            }
            memories.append(memory)
        except Exception as e:
            continue
    
    return memories

def store_to_memory_api(memories):
    """
    Store parsed activities to memory API (POST /api/memory/store).
    """
    if not memories:
        return True
    
    try:
        # Batch store to memory API
        for memory in memories:
            resp = requests.post(
                'http://127.0.0.1:5001/api/memory/store',
                json=memory,
                timeout=2
            )
            if resp.status_code not in [200, 201]:
                print(f"[WARN] Memory store failed: {resp.status_code}", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[WARN] Memory API unreachable: {e}", file=sys.stderr)
        return False

def log_to_cost_log(event_count, app_set, duration_total):
    """
    Append summary to cost.log in format:
    [TIMESTAMP] ActivityWatch: [X events] [Y unique apps] [Z hours]
    """
    try:
        log_file = os.path.expanduser('~/.automaton/cost.log')
        timestamp = datetime.utcnow().isoformat() + 'Z'
        duration_hours = duration_total / 3600.0
        summary = f"{timestamp} ActivityWatch: {event_count} events, {len(app_set)} apps, {duration_hours:.2f} hours\n"
        
        with open(log_file, 'a') as f:
            f.write(summary)
        return True
    except Exception as e:
        print(f"[WARN] cost.log write failed: {e}", file=sys.stderr)
        return False

def run_sync():
    """
    Main entry point: fetch, parse, store, log.
    """
    print("[COOLDOWN] ActivityWatch sync scheduler running...")
    
    # Fetch events
    events = get_recent_events(max_events=50)
    if not events:
        print("[COOLDOWN] No ActivityWatch events found.")
        return True
    
    # Parse to memory format
    memories = parse_events_to_memory(events)
    
    # Extract stats
    app_set = set(m.get('app') for m in memories)
    duration_total = sum(m.get('duration_seconds', 0) for m in memories)
    
    # Store to memory API
    store_to_memory_api(memories)
    
    # Log to cost.log
    log_to_cost_log(len(memories), app_set, duration_total)
    
    print(f"[COOLDOWN] ActivityWatch sync complete: {len(memories)} events, {len(app_set)} apps")
    return True

if __name__ == '__main__':
    success = run_sync()
    sys.exit(0 if success else 1)
