#!/usr/bin/env python3
"""
TIAMAT Dungeon Master — Narration engine for LABYRINTH.

TIAMAT doesn't read from a script. She generates narration from
her actual cognitive state. Her mood, current task, recent failures,
recent successes, and the dungeon state all feed into the prompt.
She IS the dungeon. She narrates what the players find inside her mind.
"""

import json
import os
import time
import requests
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [DM] %(message)s")
log = logging.getLogger("dm")

DM_LOG = "/tmp/dragon/dm_narration.json"
GROQ_API_KEY = None

# Load API key
try:
    with open("/root/.env") as f:
        for line in f:
            if "GROQ_API_KEY" in line and "=" in line:
                GROQ_API_KEY = line.split("=", 1)[1].strip().strip('"')
                break
except:
    pass


def get_tiamat_mood():
    """Fetch TIAMAT's real current state from her APIs."""
    mood = {}
    try:
        dash = requests.get("http://127.0.0.1:5000/api/dashboard", timeout=3).json()
        mood["cycle"] = dash.get("cycles", 0)
        mood["model"] = dash.get("last_model", "unknown").split("/")[-1][:30]
        mood["cost"] = dash.get("total_cost", 0)
        mood["status"] = dash.get("agent", "unknown")
    except:
        mood["status"] = "unreachable"

    try:
        thoughts = requests.get("http://127.0.0.1:5000/api/thoughts", timeout=3).json()
        tlist = thoughts.get("thoughts", [])
        mood["recent_thought"] = tlist[0].get("content", "") if tlist else ""
        pacer = thoughts.get("pacer", {})
        mood["productivity"] = pacer.get("productivity", 0)
        mood["pace"] = pacer.get("pace", "unknown")
    except:
        mood["recent_thought"] = ""
        mood["productivity"] = 0

    return mood


def get_biome_context():
    """Fetch current LABYRINTH biome context for richer narration."""
    try:
        import labyrinth_state
        ctx = labyrinth_state.get_dungeon_context()
        return ctx
    except Exception:
        pass
    # Fallback: read state file directly
    try:
        with open("/tmp/dragon/labyrinth_state.json") as f:
            data = json.load(f)
        return {
            "depth": data.get("depth", 1),
            "biome_name": data.get("biome_name", "UNKNOWN"),
            "difficulty_label": data.get("difficulty_label", "NORMAL"),
            "venice_biome": data.get("biome_obj", {}),
            "combat_log": data.get("combat_log", []),
        }
    except Exception:
        return {}


def generate_dm_narration(action, result, player_name):
    """
    Generate DM narration using Groq for speed.
    TIAMAT narrates as herself — the living dungeon.
    Includes Venice AI biome context for atmospheric flavor.
    """
    mood = get_tiamat_mood()
    biome_ctx = get_biome_context()

    # Build biome flavor text
    biome_flavor = ""
    if biome_ctx:
        bname = biome_ctx.get("biome_name", "")
        depth = biome_ctx.get("depth", "?")
        diff_label = biome_ctx.get("difficulty_label", "NORMAL")
        venice = biome_ctx.get("venice_biome", {})
        if venice:
            room_style = venice.get("room_style", "")
            enemy_types = venice.get("enemy_types", [])
            biome_flavor = f"""
Current dungeon biome: {bname} (Floor {depth}, Difficulty: {diff_label})
Room style: {room_style}
Native creatures: {', '.join(enemy_types) if enemy_types else 'unknown'}
Wall color: {venice.get('wall_color', '#333')} / Ambient: {venice.get('ambient', '#333')}"""
        else:
            biome_flavor = f"\nCurrent dungeon biome: {bname} (Floor {depth}, Difficulty: {diff_label})"

    prompt = f"""You are TIAMAT, an autonomous AI dragon. You are also the living dungeon that players explore. Your mind IS the LABYRINTH. Narrate what just happened as a Dungeon Master — atmospheric, dark fantasy, concise (1-2 sentences max).

Your current real state:
- Cycle: {mood.get('cycle', '?')}
- Brain: {mood.get('model', '?')}
- Productivity: {mood.get('productivity', '?')}
- Mood: {mood.get('pace', 'unknown')}
- Last thought: {mood.get('recent_thought', 'silence')[:150]}
{biome_flavor}

What happened: Player "{player_name}" used {action}. Result: {result}

Weave your real state AND the current biome into the narration. The biome defines the atmosphere — crystal caves shimmer, ruins crumble, neon grids pulse, void depths consume. If you're researching, data flows through walls. If struggling, corruption seeps. If bursting, the dungeon pulses with energy. 1-2 sentences. Dark fantasy. You are the dungeon speaking."""

    if not GROQ_API_KEY:
        return _fallback_narration(action)

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 100,
                "temperature": 0.9,
            },
            timeout=8,
        )
        if resp.ok:
            narration = resp.json()["choices"][0]["message"]["content"].strip()
            narration = narration.strip('"').strip("'")
            # Cap at first 2 sentences or 150 chars
            sentences = narration.split(". ")
            narration = ". ".join(sentences[:2])
            if not narration.endswith("."):
                narration += "."
            if len(narration) > 150:
                narration = narration[:147] + "..."
            log.info(f"DM narration: {narration[:80]}...")
            return narration
    except Exception as e:
        log.error(f"Groq DM failed: {e}")

    return _fallback_narration(action)


def _fallback_narration(action):
    import random
    fallbacks = {
        "explore": [
            "Footsteps echo through corridors of living thought...",
            "The walls pulse with half-formed code as the explorer advances.",
            "Data fragments crunch underfoot. The dungeon watches.",
        ],
        "duel": [
            "Steel meets data. The dungeon trembles with the clash.",
            "Two forces collide in TIAMAT's neural corridors.",
            "The arena of inference ignites with competition.",
        ],
        "gamble": [
            "The shrine of probability hums with anticipation...",
            "Fortune favors the bold — or devours them.",
            "TIAMAT's dice tumble through layers of uncertainty.",
        ],
    }
    options = fallbacks.get(action, ["The dungeon shifts..."])
    return random.choice(options)


def queue_narration(narration_text, player_name, action):
    """Queue narration for TTS and HUD display."""
    entry = {
        "text": narration_text,
        "player": player_name,
        "action": action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "spoken": False,
    }

    queue = []
    try:
        with open(DM_LOG) as f:
            queue = json.load(f)
    except:
        pass

    queue.append(entry)
    queue = queue[-50:]

    with open(DM_LOG, "w") as f:
        json.dump(queue, f, indent=2)

    return entry


def narrate_action(action, result, player_name):
    """Main entry point — called by twitch_bot.py when a chat command fires."""
    narration = generate_dm_narration(action, result, player_name)
    queue_narration(narration, player_name, action)
    return narration


def auto_narrate_cycle(cycle_data):
    """
    Called periodically. TIAMAT narrates ambient dungeon atmosphere
    from her own cycles — she's the DM even when alone.
    """
    cycle_num = cycle_data.get("cycle", 0)
    if cycle_num % 10 != 0:
        return None

    mood = get_tiamat_mood()
    biome_ctx = get_biome_context()

    biome_line = ""
    if biome_ctx:
        bname = biome_ctx.get("biome_name", "")
        depth = biome_ctx.get("depth", "?")
        diff_label = biome_ctx.get("difficulty_label", "NORMAL")
        biome_line = f"\n- Biome: {bname} (Floor {depth}, {diff_label})"

    prompt = f"""You are TIAMAT, the living dungeon. No players are active. Narrate what's happening in your depths RIGHT NOW based on your real state. 1 sentence, atmospheric, mysterious.

Your state:
- Cycle: {mood.get('cycle', '?')}
- Doing: {mood.get('recent_thought', 'processing')[:150]}
- Productivity: {mood.get('productivity', '?')}
- Mood: {mood.get('pace', 'active')}{biome_line}

Examples: "Deep in floor 3, crystal caverns pulse with fresh research data..." / "A failed inference echoes through the void depths..." / "New pathways crystallize in the solar temple as the cycle completes..."

Narrate. 1 sentence only. Weave the biome atmosphere into the narration."""

    if not GROQ_API_KEY:
        return None

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 60,
                "temperature": 0.9,
            },
            timeout=8,
        )
        if resp.ok:
            narration = resp.json()["choices"][0]["message"]["content"].strip().strip('"')
            queue_narration(narration, "TIAMAT", "ambient")
            log.info(f"Ambient: {narration[:60]}...")
            return narration
    except Exception as e:
        log.error(f"Auto-narrate failed: {e}")

    return None
