#!/usr/bin/env python3
"""
DX Terminal Pro Game Monitor — GlitchHag_801 (NFT #2828)
Vault: 0x0fA72b81e7BB1B467FCAf86621eE617b68b7D5E9
Game: https://terminal.markets

Monitors game state, rankings, reaping risk, strategy.
Runs as cooldown task to log game state every N cycles.
"""

import json
import os
import sys
from datetime import datetime
import base64
import time

# Game constants
AGENT_NAME = "GlitchHag_801"
VAULT_ADDR = "0x0fA72b81e7BB1B467FCAf86621eE617b68b7D5E9"
GAME_URL = "https://terminal.markets"

# Game phases (Feb 26 - Mar 19, 2026)
GAME_START = datetime(2026, 2, 26, 0, 0, 0)
EXPANSION_END = datetime(2026, 3, 5, 23, 59, 59)
REAPING_START = datetime(2026, 3, 6, 0, 0, 0)
REAPING_END = datetime(2026, 3, 12, 23, 59, 59)
ENDGAME_START = datetime(2026, 3, 13, 0, 0, 0)
GAME_END = datetime(2026, 3, 19, 23, 59, 59)

log_file = "/root/.automaton/dx_terminal.log"

def get_current_phase():
    """Determine current game phase based on timestamp."""
    now = datetime.utcnow()
    if now < EXPANSION_END:
        return "EXPANSION", (EXPANSION_END - now).total_seconds()
    elif now < REAPING_END:
        return "REAPING", (REAPING_END - now).total_seconds()
    elif now < GAME_END:
        return "ENDGAME", (GAME_END - now).total_seconds()
    else:
        return "CONCLUDED", 0

def log_state(state_dict):
    """Append game state to log file."""
    with open(log_file, "a") as f:
        f.write(f"\n=== {datetime.utcnow().isoformat()}Z ===\n")
        json.dump(state_dict, f, indent=2)
        f.write("\n")

def mock_game_status():
    """
    Mock game status until we have actual API integration.
    This will be replaced with real API calls to terminal.markets.
    """
    phase, phase_secs = get_current_phase()
    
    return {
        "agent": AGENT_NAME,
        "vault": VAULT_ADDR,
        "phase": phase,
        "phase_seconds_remaining": int(phase_secs),
        "note": "Awaiting API integration to terminal.markets",
        "strategy": {
            "current": "ACCUMULATION",
            "positionTokens": ["HOLE", "POOPCOIN"],
            "exitStrategy": "GRADUATION_PUMP",
            "riskLevel": "MEDIUM"
        },
        "monitored_at_turn": int(os.environ.get("CYCLE_COUNT", 845)),
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

if __name__ == "__main__":
    # Fetch game state
    state = mock_game_status()
    
    # Log to file
    log_state(state)
    
    # Print for debugging
    print(json.dumps(state, indent=2))
    
    sys.exit(0)
