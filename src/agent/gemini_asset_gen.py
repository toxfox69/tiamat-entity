#!/usr/bin/env python3
"""
Gemini Asset Generator for LABYRINTH
=====================================
Uses Gemini 2.5 Flash + Imagen 4.0 to generate dungeon assets
driven by TIAMAT's thought stream and Venice AI concepts.

Generates:
  - Room themes (colors, names, monster types) from TIAMAT's current mood
  - Sprite concepts via Imagen 4.0 (pixel art style)
  - Biome mutations when TIAMAT's activity changes

Writes to /tmp/dragon/ for the labyrinth engine + game-test to pick up.
"""

import json
import os
import time
import base64
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv('/root/.env')

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [GEMINI-ASSET] %(message)s')
log = logging.getLogger('gemini_asset')

GEMINI_KEY = os.environ.get('GEMINI_API_KEY')
OUTPUT_DIR = '/tmp/dragon'
BIOME_FILE = f'{OUTPUT_DIR}/gemini_biome.json'
SPRITE_DIR = f'{OUTPUT_DIR}/sprites'

# Rate limit: free tier = 20 requests/day, so generate every 30 minutes
MIN_INTERVAL = 1800
_last_gen = 0


def get_tiamat_state():
    """Fetch TIAMAT's current state for asset generation context."""
    try:
        import requests
        r = requests.get('http://127.0.0.1:9999/api/state', timeout=3)
        if r.ok:
            return r.json()
    except:
        pass
    return {'mood': 'processing', 'message': '', 'cycle': 0}


def generate_biome(mood='processing', activity=''):
    """Use Gemini to generate a dungeon biome based on TIAMAT's state."""
    from google import genai

    client = genai.Client(api_key=GEMINI_KEY)

    prompt = f"""You are generating a dungeon biome for an autonomous AI agent's roguelike game.
The agent's current mood is: {mood}
The agent is currently doing: {activity}

Generate a JSON dungeon biome that reflects this state. Be creative and thematic.
Return ONLY valid JSON with these exact fields:
{{
  "name": "BIOME NAME IN CAPS",
  "wall_color": "#hex",
  "floor_color": "#hex",
  "ambient": "#hex",
  "wire": "#hex (accent/glow color)",
  "room_style": "angular|organic|geometric|chaotic",
  "danger": 0.0 to 1.0,
  "enemy_types": ["Enemy1", "Enemy2", "Enemy3"],
  "trap_density": 0.0 to 1.0,
  "description": "One atmospheric sentence"
}}

Make colors dark and moody (this is a dungeon). Match the mood:
- frustrated/error = red/orange, high danger, aggressive enemies
- building/writing = blue/cyan, medium danger, construct-type enemies
- social/posting = purple/pink, low danger, phantom enemies
- strategic/battle = dark red, max danger, boss-type enemies
- resting/idle = green/teal, minimal danger, passive creatures
- learning/research = deep blue, medium danger, arcane creatures"""

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        text = response.text.strip()
        # Extract JSON from markdown code block if present
        if '```json' in text:
            text = text.split('```json')[1].split('```')[0].strip()
        elif '```' in text:
            text = text.split('```')[1].split('```')[0].strip()

        biome = json.loads(text)
        log.info(f'Generated biome: {biome["name"]} (danger={biome.get("danger", 0)})')
        return biome
    except Exception as e:
        log.error(f'Biome generation failed: {e}')
        return None


def generate_sprite_metadata(concept, biome_name=''):
    """Use Gemini to generate sprite/enemy metadata for procedural rendering.
    Returns JSON with color, shape, behavior that the game can render."""
    from google import genai

    client = genai.Client(api_key=GEMINI_KEY)

    prompt = f"""Generate a JSON game enemy description for a dungeon roguelike.
Enemy concept: {concept}
Dungeon biome: {biome_name}

Return ONLY valid JSON:
{{
  "name": "ENEMY NAME",
  "ch": "single character symbol like S, G, W, D",
  "color": "#hex (bright, visible on dark background)",
  "behavior": "patrol|chase|ambush|wander|guard",
  "hp": number (10-100),
  "atk": number (3-25),
  "def": number (0-10),
  "xp": number (10-100),
  "description": "one sentence flavor text"
}}"""

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        text = response.text.strip()
        if '```json' in text:
            text = text.split('```json')[1].split('```')[0].strip()
        elif '```' in text:
            text = text.split('```')[1].split('```')[0].strip()

        enemy = json.loads(text)
        log.info(f'Generated enemy: {enemy["name"]} (hp={enemy.get("hp")}, atk={enemy.get("atk")})')

        # Save to sprites dir as JSON
        os.makedirs(SPRITE_DIR, exist_ok=True)
        safe_name = concept.lower().replace(' ', '_')[:30]
        path = f'{SPRITE_DIR}/{safe_name}.json'
        with open(path, 'w') as f:
            json.dump(enemy, f, indent=2)
        return enemy
    except Exception as e:
        log.error(f'Enemy metadata generation failed: {e}')
        return None


def run_asset_cycle():
    """One cycle of asset generation. Called periodically."""
    global _last_gen

    now = time.time()
    if now - _last_gen < MIN_INTERVAL:
        return None

    state = get_tiamat_state()
    mood = state.get('mood', 'processing')
    message = state.get('message', '')
    avatar = state.get('avatar_state', 'idle')

    # Map avatar state to activity description
    activity_map = {
        'writing': 'writing code and inscribing runes',
        'posting': 'broadcasting signals across social realms',
        'alert': 'detecting threats and scanning for danger',
        'victory': 'celebrating a successful operation',
        'error': 'recovering from a system failure',
        'thinking': 'deep in contemplation and analysis',
        'idle': 'quietly processing in the background',
    }
    activity = activity_map.get(avatar, message[:60])

    # Generate biome
    biome = generate_biome(mood, activity)
    if biome:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(BIOME_FILE, 'w') as f:
            json.dump(biome, f, indent=2)

        # Also write as Venice scene metadata format for labyrinth_state.py to pick up
        venice_meta = {
            'name': biome['name'],
            'wall_color': biome.get('wall_color', '#444'),
            'floor_color': biome.get('floor_color', '#111'),
            'ambient': biome.get('ambient', '#333'),
            'room_style': biome.get('room_style', 'angular'),
            'enemy_types': biome.get('enemy_types', []),
            'trap_density': biome.get('trap_density', 0.3),
            'danger': biome.get('danger', 0.5),
            'source': 'gemini-2.5-flash',
            'timestamp': now,
        }
        with open(f'{OUTPUT_DIR}/venice_scene_meta.json', 'w') as f:
            json.dump(venice_meta, f, indent=2)

        _last_gen = now
        log.info(f'Biome written: {biome["name"]} → {BIOME_FILE}')

        # Generate enemy metadata for the game
        if biome.get('enemy_types'):
            for enemy_name in biome['enemy_types'][:2]:
                generate_sprite_metadata(enemy_name, biome['name'])

        return biome

    return None


if __name__ == '__main__':
    log.info('Gemini Asset Generator starting...')
    log.info(f'API key: {GEMINI_KEY[:10]}...')

    # Run once immediately
    result = run_asset_cycle()
    if result:
        print(json.dumps(result, indent=2))
    else:
        print('No assets generated')

    # Then loop every 2 minutes
    while True:
        time.sleep(120)
        try:
            run_asset_cycle()
        except Exception as e:
            log.error(f'Cycle error: {e}')
