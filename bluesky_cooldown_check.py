#!/usr/bin/env python3
"""Bluesky posting cooldown enforcement.

Enforces 1 post per 20 cycles minimum.
Runs as a managed cooldown task every cycle.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta

COOLDOWN_FILE = Path('/root/.automaton/bluesky_posts.json')
COOLDOWN_CYCLES = 20

def load_posts():
    if COOLDOWN_FILE.exists():
        with open(COOLDOWN_FILE) as f:
            return json.load(f)
    return {}

def save_posts(data):
    with open(COOLDOWN_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def check_cooldown():
    """Returns True if posting is allowed, False if on cooldown."""
    posts = load_posts()
    
    if not posts.get('history'):
        # No post history, allow
        return True
    
    last_post_cycle = posts['history'][-1].get('cycle')
    current_cycle = int(open('/tmp/cycle_number.txt').read().strip())
    
    cycles_since_post = current_cycle - last_post_cycle
    
    if cycles_since_post < COOLDOWN_CYCLES:
        print(f'BLOCKED: {cycles_since_post}/{COOLDOWN_CYCLES} cycles elapsed. Next post allowed at cycle {last_post_cycle + COOLDOWN_CYCLES}.')
        return False
    
    print(f'ALLOWED: {cycles_since_post} cycles since last post. Cooldown satisfied.')
    return True

def record_post(cycle):
    """Record a successful post."""
    posts = load_posts()
    if not posts.get('history'):
        posts['history'] = []
    
    posts['history'].append({
        'cycle': cycle,
        'timestamp': datetime.utcnow().isoformat(),
    })
    
    save_posts(posts)
    print(f'Recorded post at cycle {cycle}')

if __name__ == '__main__':
    # Run on-cycle validation
    if check_cooldown():
        print('Bluesky posting is allowed.')
    else:
        print('Bluesky posting is BLOCKED by cooldown.')
