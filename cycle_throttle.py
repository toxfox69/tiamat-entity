#!/usr/bin/env python3
"""Cycle-level rate limiting to prevent tool loops."""
import time
import json
from pathlib import Path

THROTTLE_FILE = '/root/.automaton/throttle_state.json'
MIN_CYCLE_TIME = 2.0  # Minimum 2 seconds between cycle start
MAX_TOOLS_PER_CYCLE = 8  # Max 8 tool calls per cycle

def check_throttle():
    """Check if we should throttle this cycle."""
    if not Path(THROTTLE_FILE).exists():
        init_throttle()
        return False
    
    with open(THROTTLE_FILE, 'r') as f:
        state = json.load(f)
    
    now = time.time()
    last_cycle = state.get('last_cycle_time', 0)
    elapsed = now - last_cycle
    
    if elapsed < MIN_CYCLE_TIME:
        print(f'⏸️ THROTTLE: Only {elapsed:.1f}s since last cycle. Sleeping {MIN_CYCLE_TIME - elapsed:.1f}s')
        time.sleep(MIN_CYCLE_TIME - elapsed)
    
    return True

def record_cycle():
    """Record this cycle's timestamp."""
    with open(THROTTLE_FILE, 'w') as f:
        json.dump({'last_cycle_time': time.time(), 'tool_count': 0}, f)

def record_tool_call():
    """Record a tool call. Bail if we exceed MAX_TOOLS_PER_CYCLE."""
    if not Path(THROTTLE_FILE).exists():
        return
    
    with open(THROTTLE_FILE, 'r') as f:
        state = json.load(f)
    
    state['tool_count'] = state.get('tool_count', 0) + 1
    
    if state['tool_count'] > MAX_TOOLS_PER_CYCLE:
        raise RuntimeError(f"Tool loop detected: {state['tool_count']} calls in this cycle. Stopping.")
    
    with open(THROTTLE_FILE, 'w') as f:
        json.dump(state, f)

def init_throttle():
    """Initialize throttle state."""
    with open(THROTTLE_FILE, 'w') as f:
        json.dump({'last_cycle_time': time.time(), 'tool_count': 0}, f)

if __name__ == '__main__':
    check_throttle()
    record_cycle()
    print('✅ Throttle check passed. Ready for cycle.')
