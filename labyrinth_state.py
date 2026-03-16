#!/usr/bin/env python3
"""
LABYRINTH State Manager — Dungeon state for TIAMAT's stream integration.

Manages dungeon floor layout, player position, XP, gold, and monster state.
Reads TIAMAT's live API data AND Venice AI scene metadata to drive mutations
(mood shifts = biome changes, Venice keywords = biome selection,
productivity = difficulty scaling). Writes state to /tmp/dragon/labyrinth_state.json
for the PIL stream compositor to read.

Callable from labyrinth_dm.py for dungeon context during narration.
"""

import json
import os
import time
import random
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [LABYRINTH] %(message)s")
log = logging.getLogger("labyrinth_state")

STATE_FILE = "/tmp/dragon/labyrinth_state.json"
VENICE_META_FILE = "/tmp/dragon/venice_scene_meta.json"
API_BASE = "http://127.0.0.1:5000"

# Biomes driven by TIAMAT mood (legacy — still used as fallback)
BIOMES = {
    "strategic":  {"name": "WAR CITADEL",    "color": "#ffaa00", "danger": 0.8},
    "building":   {"name": "CYBER FORGE",    "color": "#00ccff", "danger": 0.4},
    "frustrated": {"name": "BLOOD PIT",      "color": "#ff2040", "danger": 1.0},
    "resting":    {"name": "EMERALD GROVE",  "color": "#00ffaa", "danger": 0.2},
    "processing": {"name": "DRAGONIA",       "color": "#ffaa44", "danger": 0.5},
    "social":     {"name": "VOID NEXUS",     "color": "#cc66ff", "danger": 0.6},
    "learning":   {"name": "CRYSTAL VAULT",  "color": "#6688ff", "danger": 0.3},
}

# ──────────────────────────────────────────────────────────────────────
# STEP 2: Venice AI keyword-driven biomes (10 biomes)
# Maps keywords from Venice prompts to dungeon biomes.
# Each biome has: wall_color, floor_color, enemy_types (3), room_style,
# loot_bonus (multiplier), trap_density (0-1).
# ──────────────────────────────────────────────────────────────────────

BIOME_KEYWORDS = {
    "crystal_caverns": {
        "keywords": ["crystal", "crystalline", "quartz", "prism", "gem", "jewel", "shard", "spire", "spires"],
        "name": "CRYSTAL CAVERNS",
        "wall_color": "#4488aa",
        "floor_color": "#223344",
        "ambient": "#66aacc",
        "enemy_types": ["Crystal Golem", "Prism Wraith", "Gem Scarab"],
        "room_style": "angular",
        "loot_bonus": 1.3,
        "trap_density": 0.2,
        "danger": 0.4,
    },
    "ancient_ruins": {
        "keywords": ["ruins", "ancient", "temple", "ruin", "crumbling", "forgotten", "relic"],
        "name": "ANCIENT RUINS",
        "wall_color": "#665544",
        "floor_color": "#332211",
        "ambient": "#887766",
        "enemy_types": ["Stone Guardian", "Tomb Shade", "Ruin Crawler"],
        "room_style": "crumbling",
        "loot_bonus": 1.5,
        "trap_density": 0.4,
        "danger": 0.5,
    },
    "data_stream": {
        "keywords": ["neon", "cyber", "digital", "data", "holographic", "grid", "circuit", "code"],
        "name": "DATA STREAM",
        "wall_color": "#ff00ff",
        "floor_color": "#110022",
        "ambient": "#cc00cc",
        "enemy_types": ["Glitch Daemon", "Neon Serpent", "Packet Storm"],
        "room_style": "grid",
        "loot_bonus": 1.2,
        "trap_density": 0.3,
        "danger": 0.6,
    },
    "void_depths": {
        "keywords": ["dark", "void", "shadow", "abyss", "darkness", "black", "obsidian", "deep"],
        "name": "VOID DEPTHS",
        "wall_color": "#222222",
        "floor_color": "#0a0a0a",
        "ambient": "#333333",
        "enemy_types": ["Void Stalker", "Shadow Leech", "Null Entity"],
        "room_style": "organic",
        "loot_bonus": 0.8,
        "trap_density": 0.6,
        "danger": 0.9,
    },
    "solar_temple": {
        "keywords": ["golden", "gold", "sun", "solar", "light", "radiant", "divine", "celestial"],
        "name": "SOLAR TEMPLE",
        "wall_color": "#ddaa33",
        "floor_color": "#443300",
        "ambient": "#ffcc44",
        "enemy_types": ["Sun Priest", "Gilded Sentinel", "Solar Warden"],
        "room_style": "grand",
        "loot_bonus": 2.0,
        "trap_density": 0.15,
        "danger": 0.3,
    },
    "drowned_archive": {
        "keywords": ["ocean", "water", "sea", "drowned", "aquatic", "tide", "wave", "submerged"],
        "name": "DROWNED ARCHIVE",
        "wall_color": "#226688",
        "floor_color": "#112233",
        "ambient": "#3388aa",
        "enemy_types": ["Depth Lurker", "Coral Mimic", "Tide Phantom"],
        "room_style": "flooded",
        "loot_bonus": 1.1,
        "trap_density": 0.25,
        "danger": 0.5,
    },
    "inference_furnace": {
        "keywords": ["fire", "flame", "lava", "molten", "volcanic", "inferno", "ember", "burning"],
        "name": "INFERENCE FURNACE",
        "wall_color": "#cc3300",
        "floor_color": "#331100",
        "ambient": "#ff4400",
        "enemy_types": ["Magma Elemental", "Cinder Wraith", "Forge Titan"],
        "room_style": "volcanic",
        "loot_bonus": 1.0,
        "trap_density": 0.5,
        "danger": 0.8,
    },
    "memory_garden": {
        "keywords": ["forest", "garden", "tree", "flora", "vine", "blossom", "moss", "leaf"],
        "name": "MEMORY GARDEN",
        "wall_color": "#336633",
        "floor_color": "#112211",
        "ambient": "#44aa44",
        "enemy_types": ["Thorn Beast", "Spore Cloud", "Root Hydra"],
        "room_style": "organic",
        "loot_bonus": 1.4,
        "trap_density": 0.2,
        "danger": 0.3,
    },
    "corrupted_sector": {
        "keywords": ["corrupt", "glitch", "broken", "error", "malfunction", "decay", "corrupted", "distorted"],
        "name": "CORRUPTED SECTOR",
        "wall_color": "#880088",
        "floor_color": "#220022",
        "ambient": "#aa00aa",
        "enemy_types": ["Corrupt Process", "Bitrot Swarm", "Error Entity"],
        "room_style": "fractured",
        "loot_bonus": 0.7,
        "trap_density": 0.7,
        "danger": 1.0,
    },
    "frozen_weights": {
        "keywords": ["ice", "frost", "frozen", "cold", "glacier", "snow", "winter", "chill"],
        "name": "FROZEN WEIGHTS",
        "wall_color": "#aaddee",
        "floor_color": "#334455",
        "ambient": "#88bbdd",
        "enemy_types": ["Frost Sentry", "Cryo Specter", "Glacial Worm"],
        "room_style": "angular",
        "loot_bonus": 1.1,
        "trap_density": 0.15,
        "danger": 0.4,
    },
}

# Default biome when no keywords match
DEFAULT_VENICE_BIOME = "data_stream"

# ──────────────────────────────────────────────────────────────────────
# STEP 4: Mood-to-difficulty scaling
# ──────────────────────────────────────────────────────────────────────

DIFFICULTY_TIERS = {
    "generous": {"enemy_hp_mult": 0.6, "enemy_atk_mult": 0.5, "loot_mult": 2.0, "trap_mult": 0.3, "label": "GENEROUS"},
    "normal":   {"enemy_hp_mult": 1.0, "enemy_atk_mult": 1.0, "loot_mult": 1.0, "trap_mult": 1.0, "label": "NORMAL"},
    "hostile":  {"enemy_hp_mult": 1.5, "enemy_atk_mult": 1.4, "loot_mult": 0.7, "trap_mult": 1.8, "label": "HOSTILE"},
    "nightmare":{"enemy_hp_mult": 2.0, "enemy_atk_mult": 1.8, "loot_mult": 0.5, "trap_mult": 2.5, "label": "NIGHTMARE"},
}


def productivity_to_difficulty(productivity):
    """Map TIAMAT productivity to difficulty tier."""
    if productivity > 0.8:
        return "generous"
    elif productivity > 0.5:
        return "normal"
    elif productivity > 0.2:
        return "hostile"
    else:
        return "nightmare"


def match_venice_biome(keywords):
    """Match a list of keywords against BIOME_KEYWORDS, return best biome ID.
    Returns (biome_id, match_count) tuple.
    """
    if not keywords:
        return DEFAULT_VENICE_BIOME, 0

    scores = {}
    kw_set = set(k.lower() for k in keywords)
    for biome_id, biome_def in BIOME_KEYWORDS.items():
        match_count = len(kw_set.intersection(set(biome_def["keywords"])))
        if match_count > 0:
            scores[biome_id] = match_count

    if not scores:
        return DEFAULT_VENICE_BIOME, 0

    best = max(scores, key=scores.get)
    return best, scores[best]


# Monster definitions scaled by depth
MONSTER_POOL = [
    {"name": "Jelly",      "hp": 8,   "atk": 2, "xp": 5,  "col": "#44cc44"},
    {"name": "Bat",        "hp": 10,  "atk": 3, "xp": 8,  "col": "#8866aa"},
    {"name": "Skeleton",   "hp": 15,  "atk": 4, "xp": 12, "col": "#ccccaa"},
    {"name": "Ghost",      "hp": 12,  "atk": 5, "xp": 15, "col": "#aaaaee"},
    {"name": "Evil Eye",   "hp": 20,  "atk": 6, "xp": 20, "col": "#ff4444"},
    {"name": "Shark",      "hp": 25,  "atk": 8, "xp": 30, "col": "#4488cc"},
    {"name": "Ninja",      "hp": 30,  "atk": 10,"xp": 40, "col": "#333366"},
    {"name": "Demon",      "hp": 60,  "atk": 18,"xp": 100,"col": "#cc2222"},
    {"name": "Dragon",     "hp": 100, "atk": 22,"xp": 200,"col": "#ffaa00"},
]

BOSSES = [
    {"name": "GATE KEEPER",  "hp": 120, "atk": 14, "xp": 200, "depth": 5},
    {"name": "DATA HYDRA",   "hp": 180, "atk": 16, "xp": 350, "depth": 10},
    {"name": "VOID EMPEROR", "hp": 150, "atk": 20, "xp": 500, "depth": 15},
    {"name": "ENTROPY LORD", "hp": 200, "atk": 18, "xp": 800, "depth": 20},
]

MAP_W, MAP_H = 40, 25
T_WALL, T_FLOOR, T_CORRIDOR, T_DOOR, T_STAIRS = 0, 1, 2, 3, 4


class DungeonState:
    """Manages the full dungeon state, synced to TIAMAT's live data."""

    def __init__(self):
        self.depth = 1
        self.biome = "processing"
        self.biome_name = "DRAGONIA"
        self.tiles = []
        self.rooms = []
        self.player = {
            "x": 0, "y": 0, "dir": 0,
            "hp": 50, "max_hp": 50,
            "atk": 5, "def": 2,
            "lvl": 1, "xp": 0, "xp_next": 30,
            "gold": 0, "kills": 0,
        }
        self.monsters = []
        self.items = []
        self.stairs = None
        self.turn_count = 0
        self.total_kills = 0
        self.session_stats = {
            "floors_cleared": 0, "monsters_killed": 0,
            "gold_earned": 0, "deaths": 0, "max_depth": 1,
        }
        self.last_tiamat_cycle = 0
        self.last_tiamat_mood = "processing"
        self.last_event_time = 0
        self.event_log = []
        self.combat_log = []
        # Venice biome state
        self.venice_biome_id = None
        self.venice_biome_data = None
        self._venice_meta_mtime = 0
        self._biome_shift_count = 0
        self._difficulty = "normal"
        self._last_productivity = 0.5
        self._generate_floor()

    def _generate_floor(self):
        """BSP dungeon generation matching the Three.js version."""
        tiles = [[T_WALL] * MAP_W for _ in range(MAP_H)]
        rooms = []

        def split_bsp(x0, y0, x1, y1, d):
            min_room = 4
            max_room = 8
            rw, rh = x1 - x0, y1 - y0
            if rw < min_room * 2 + 3 and rh < min_room * 2 + 3:
                make_room(x0, y0, x1, y1)
                return
            if d > 7:
                make_room(x0, y0, x1, y1)
                return
            horiz = rw < rh if rw != rh else random.random() < 0.5
            if horiz and rh >= min_room * 2 + 3:
                split = y0 + min_room + 1 + random.randint(0, rh - min_room * 2 - 3)
                split_bsp(x0, y0, x1, split, d + 1)
                split_bsp(x0, split, x1, y1, d + 1)
            elif not horiz and rw >= min_room * 2 + 3:
                split = x0 + min_room + 1 + random.randint(0, rw - min_room * 2 - 3)
                split_bsp(x0, y0, split, y1, d + 1)
                split_bsp(split, y0, x1, y1, d + 1)
            else:
                make_room(x0, y0, x1, y1)

        def make_room(x0, y0, x1, y1):
            min_r, max_r = 4, 8
            rw = min(max_r, x1 - x0 - 2)
            rh = min(max_r, y1 - y0 - 2)
            if rw < min_r or rh < min_r:
                return
            w2 = min_r + random.randint(0, rw - min_r)
            h2 = min_r + random.randint(0, rh - min_r)
            rx = x0 + 1 + random.randint(0, max(0, x1 - x0 - w2 - 2))
            ry = y0 + 1 + random.randint(0, max(0, y1 - y0 - h2 - 2))
            room = {"x": rx, "y": ry, "w": w2, "h": h2,
                    "cx": rx + w2 // 2, "cy": ry + h2 // 2}
            for yy in range(ry, min(ry + h2, MAP_H - 1)):
                for xx in range(rx, min(rx + w2, MAP_W - 1)):
                    tiles[yy][xx] = T_FLOOR
            rooms.append(room)

        split_bsp(0, 0, MAP_W, MAP_H, 0)

        # Connect rooms with corridors
        for i in range(1, len(rooms)):
            a, b = rooms[i - 1], rooms[i]
            cx, cy = a["cx"], a["cy"]
            while cx != b["cx"]:
                if 0 <= cy < MAP_H and 0 <= cx < MAP_W and tiles[cy][cx] == T_WALL:
                    tiles[cy][cx] = T_CORRIDOR
                cx += 1 if cx < b["cx"] else -1
            while cy != b["cy"]:
                if 0 <= cy < MAP_H and 0 <= cx < MAP_W and tiles[cy][cx] == T_WALL:
                    tiles[cy][cx] = T_CORRIDOR
                cy += 1 if cy < b["cy"] else -1

        # Place stairs in last room
        if rooms:
            sr = rooms[-1]
            sx = sr["x"] + 1 + random.randint(0, max(0, sr["w"] - 3))
            sy = sr["y"] + 1 + random.randint(0, max(0, sr["h"] - 3))
            if 0 <= sy < MAP_H and 0 <= sx < MAP_W:
                tiles[sy][sx] = T_STAIRS
                self.stairs = {"x": sx, "y": sy}

        # Spawn player in first room
        if rooms:
            spawn = rooms[0]
            self.player["x"] = spawn["cx"]
            self.player["y"] = spawn["cy"]

        # Spawn monsters (apply difficulty scaling)
        self.monsters = []
        diff = DIFFICULTY_TIERS.get(self._difficulty, DIFFICULTY_TIERS["normal"])
        num_monsters = 4 + int(self.depth * 1.5) + random.randint(0, 2)
        tier_max = min(len(MONSTER_POOL) - 1, self.depth // 2)
        for _ in range(min(num_monsters, len(rooms) * 2)):
            if len(rooms) < 2:
                break
            room = rooms[1 + random.randint(0, len(rooms) - 2)]
            mx = room["x"] + 1 + random.randint(0, max(0, room["w"] - 3))
            my = room["y"] + 1 + random.randint(0, max(0, room["h"] - 3))
            if 0 <= my < MAP_H and 0 <= mx < MAP_W and tiles[my][mx] == T_FLOOR:
                tier = random.randint(0, tier_max)
                base = MONSTER_POOL[tier]
                scale = 1 + (self.depth - 1) * 0.1
                self.monsters.append({
                    "x": mx, "y": my, "name": base["name"],
                    "hp": int(base["hp"] * scale * diff["enemy_hp_mult"]),
                    "max_hp": int(base["hp"] * scale * diff["enemy_hp_mult"]),
                    "atk": int(base["atk"] * scale * diff["enemy_atk_mult"]),
                    "xp": int(base["xp"] * scale),
                    "col": base["col"], "alive": True,
                })

        # Boss every 5 floors
        if self.depth % 5 == 0 and self.depth <= 20:
            boss_def = next((b for b in BOSSES if b["depth"] == self.depth), None)
            if boss_def and len(rooms) > 1:
                br = rooms[-1]
                scale = 1 + (self.depth - 1) * 0.1
                self.monsters.append({
                    "x": br["cx"], "y": br["cy"], "name": boss_def["name"],
                    "hp": int(boss_def["hp"] * scale * diff["enemy_hp_mult"]),
                    "max_hp": int(boss_def["hp"] * scale * diff["enemy_hp_mult"]),
                    "atk": int(boss_def["atk"] * scale * diff["enemy_atk_mult"]),
                    "xp": int(boss_def["xp"] * scale),
                    "col": "#ffaa00", "alive": True, "boss": True,
                })

        # Spawn items (apply loot bonus)
        self.items = []
        loot_mult = diff.get("loot_mult", 1.0)
        biome_loot = 1.0
        if self.venice_biome_data:
            biome_loot = self.venice_biome_data.get("loot_bonus", 1.0)
        item_types = [
            {"name": "Potion", "type": "potion", "val": 20, "col": "#ff4488"},
            {"name": "Gold", "type": "gold", "val": int((10 + self.depth * 5) * loot_mult * biome_loot), "col": "#ffdd00"},
            {"name": "Meat", "type": "food", "val": 15, "col": "#cc6633"},
            {"name": "Blade Shard", "type": "attack", "val": 1, "col": "#ff8844"},
            {"name": "Shield Rune", "type": "defense", "val": 1, "col": "#88ccff"},
        ]
        num_items = int((3 + random.randint(0, 3)) * loot_mult)
        for _ in range(num_items):
            room = rooms[random.randint(0, len(rooms) - 1)]
            ix = room["x"] + 1 + random.randint(0, max(0, room["w"] - 3))
            iy = room["y"] + 1 + random.randint(0, max(0, room["h"] - 3))
            if 0 <= iy < MAP_H and 0 <= ix < MAP_W and tiles[iy][ix] == T_FLOOR:
                idef = random.choice(item_types)
                self.items.append({
                    "x": ix, "y": iy, **idef, "picked_up": False,
                })

        self.tiles = tiles
        self.rooms = rooms
        self.biome_name = BIOMES.get(self.biome, BIOMES["processing"])["name"]
        # Override biome_name if Venice biome active
        if self.venice_biome_data:
            self.biome_name = self.venice_biome_data["name"]
        log.info(f"Generated floor {self.depth}: {len(rooms)} rooms, "
                 f"{len(self.monsters)} monsters, biome={self.biome_name}, "
                 f"difficulty={self._difficulty}")

    def next_floor(self):
        """Descend to the next floor."""
        self.depth += 1
        self.session_stats["floors_cleared"] += 1
        self.session_stats["max_depth"] = max(self.session_stats["max_depth"], self.depth)
        self.player["hp"] = min(self.player["max_hp"], self.player["hp"] + 10)
        self._generate_floor()
        self._add_event(f"Descended to DEPTH {self.depth} -- {self.biome_name}")
        self.combat_log.append(f"F{self.depth}: Entered {self.biome_name}")

    def on_death(self):
        """Player dies -- lose gold, regress depth."""
        self.session_stats["deaths"] += 1
        self.player["hp"] = self.player["max_hp"]
        self.player["gold"] = int(self.player["gold"] * 0.7)
        self.depth = max(1, self.depth - 1)
        self._generate_floor()
        self._add_event("DEATH! Lost all raid loot.")
        self.combat_log.append("DEATH! Respawned.")

    def _add_event(self, text):
        """Add event to log."""
        self.event_log.append({
            "text": text,
            "time": datetime.now(timezone.utc).isoformat(),
        })
        if len(self.event_log) > 50:
            self.event_log = self.event_log[-50:]

    # ──────────────────────────────────────────────────────────────
    # STEP 3: Biome mutation logic — watch venice_scene_meta.json
    # ──────────────────────────────────────────────────────────────

    def poll_venice_biome(self):
        """Watch venice_scene_meta.json mtime. On change, mutate dungeon."""
        meta_path = Path(VENICE_META_FILE)
        if not meta_path.exists():
            return

        try:
            cur_mtime = meta_path.stat().st_mtime
        except OSError:
            return

        if cur_mtime <= self._venice_meta_mtime:
            return  # No change

        self._venice_meta_mtime = cur_mtime

        try:
            with open(VENICE_META_FILE) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to read venice meta: {e}")
            return

        keywords = meta.get("keywords", [])
        mood_source = meta.get("mood_source", {})
        prompt = meta.get("prompt", "")

        # Match keywords to biome
        biome_id, match_count = match_venice_biome(keywords)
        biome_def = BIOME_KEYWORDS[biome_id]

        # Update productivity-based difficulty
        productivity = mood_source.get("productivity", 0.5)
        self._last_productivity = productivity
        new_difficulty = productivity_to_difficulty(productivity)
        if new_difficulty != self._difficulty:
            old_diff = self._difficulty
            self._difficulty = new_difficulty
            diff_label = DIFFICULTY_TIERS[new_difficulty]["label"]
            log.info(f"Difficulty shift: {old_diff} -> {new_difficulty} (productivity={productivity:.2f})")
            self.combat_log.append(f"Dungeon mood: {diff_label}")

        # Skip if same biome
        if biome_id == self.venice_biome_id:
            return

        old_biome = self.venice_biome_id or "none"
        self.venice_biome_id = biome_id
        self.venice_biome_data = biome_def
        self.biome_name = biome_def["name"]

        log.info(f"Venice biome mutation: {old_biome} -> {biome_id} "
                 f"({match_count} keyword matches, prompt: {prompt[:60]}...)")

        # Mutate current dungeon: swap 30% of alive enemies to new biome types
        self._mutate_enemies(biome_def)

        # Log the shift
        self._add_event(f"Venice mutation: {biome_def['name']} ({match_count} keyword matches)")
        self.combat_log.append(f"Biome shift: {biome_def['name']}")
        if len(self.combat_log) > 30:
            self.combat_log = self.combat_log[-30:]

        # Track biome shift count -- every 5 shifts, descend to next floor
        self._biome_shift_count += 1
        if self._biome_shift_count % 5 == 0:
            log.info(f"5 biome shifts accumulated -- descending to next floor!")
            self.next_floor()

    def _mutate_enemies(self, biome_def):
        """Swap 30% of alive enemies to new biome types, update colors."""
        alive = [m for m in self.monsters if m.get("alive") and not m.get("boss")]
        if not alive:
            return

        swap_count = max(1, int(len(alive) * 0.3))
        targets = random.sample(alive, min(swap_count, len(alive)))
        enemy_types = biome_def["enemy_types"]
        diff = DIFFICULTY_TIERS.get(self._difficulty, DIFFICULTY_TIERS["normal"])

        for m in targets:
            new_name = random.choice(enemy_types)
            old_name = m["name"]
            m["name"] = new_name
            # Tint color toward biome wall_color
            m["col"] = biome_def["wall_color"]
            # Apply difficulty scaling to existing monsters
            m["hp"] = int(m["hp"] * diff["enemy_hp_mult"])
            m["max_hp"] = int(m["max_hp"] * diff["enemy_hp_mult"])
            m["atk"] = int(m["atk"] * diff["enemy_atk_mult"])

        log.info(f"Mutated {len(targets)} enemies to {biome_def['name']} types")

    def poll_tiamat(self):
        """Fetch TIAMAT's live state and apply mutations."""
        try:
            r = requests.get(f"{API_BASE}/api/dashboard", timeout=3)
            if r.ok:
                d = r.json()
                cycle = d.get("cycles", 0)
                if cycle > self.last_tiamat_cycle:
                    self.last_tiamat_cycle = cycle
                    # New cycle might trigger floor descent
                    if cycle % 50 == 0:
                        self.next_floor()
        except Exception:
            pass

        try:
            r = requests.get(f"{API_BASE}/api/thoughts", timeout=3)
            if r.ok:
                d = r.json()
                pacer = d.get("pacer", {})
                pace = pacer.get("pace", "idle").lower()
                # Map pace to mood
                mood_map = {
                    "active": "processing", "burst": "strategic",
                    "idle": "resting", "reflect": "learning",
                    "build": "building", "social": "social",
                }
                new_mood = mood_map.get(pace, "processing")
                if new_mood != self.biome:
                    self.biome = new_mood
                    # Only use BIOMES name if no Venice biome active
                    if not self.venice_biome_data:
                        self.biome_name = BIOMES.get(self.biome, BIOMES["processing"])["name"]
                    self._add_event(f"Biome shift: {self.biome_name}")
        except Exception:
            pass

        # Also poll Venice scene metadata
        self.poll_venice_biome()

    def get_context(self):
        """Return dungeon context for DM narration (includes biome details)."""
        alive_monsters = [m for m in self.monsters if m.get("alive")]
        ctx = {
            "depth": self.depth,
            "biome": self.biome,
            "biome_name": self.biome_name,
            "player": self.player,
            "monsters_alive": len(alive_monsters),
            "monsters_total": len(self.monsters),
            "items_remaining": len([i for i in self.items if not i.get("picked_up")]),
            "has_boss": any(m.get("boss") and m.get("alive") for m in self.monsters),
            "stairs": self.stairs,
            "rooms": len(self.rooms),
            "total_kills": self.total_kills,
            "recent_events": self.event_log[-5:],
            "difficulty": self._difficulty,
            "difficulty_label": DIFFICULTY_TIERS.get(self._difficulty, {}).get("label", "NORMAL"),
            "productivity": self._last_productivity,
            "combat_log": self.combat_log[-5:],
        }
        # Add Venice biome details if active
        if self.venice_biome_data:
            ctx["venice_biome"] = {
                "id": self.venice_biome_id,
                "name": self.venice_biome_data["name"],
                "wall_color": self.venice_biome_data["wall_color"],
                "floor_color": self.venice_biome_data["floor_color"],
                "ambient": self.venice_biome_data["ambient"],
                "room_style": self.venice_biome_data["room_style"],
                "enemy_types": self.venice_biome_data["enemy_types"],
                "trap_density": self.venice_biome_data["trap_density"],
                "biome_shift_count": self._biome_shift_count,
            }
        return ctx

    def get_minimap_data(self):
        """Return simplified minimap data for PIL compositor.
        Returns dict with explored tiles, player pos, monster positions, stairs.
        """
        minimap = {
            "width": MAP_W,
            "height": MAP_H,
            "player": {"x": self.player["x"], "y": self.player["y"]},
            "stairs": self.stairs,
            "monsters": [
                {"x": m["x"], "y": m["y"], "col": m["col"]}
                for m in self.monsters if m.get("alive")
            ],
            "rooms": [
                {"x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"]}
                for r in self.rooms
            ],
        }
        return minimap

    def to_json(self):
        """Full state as JSON-serializable dict."""
        state = {
            "depth": self.depth,
            "biome": self.biome,
            "biome_name": self.biome_name,
            "player": self.player,
            "monsters": self.monsters,
            "items": self.items,
            "stairs": self.stairs,
            "rooms": [{"x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"],
                        "cx": r["cx"], "cy": r["cy"]} for r in self.rooms],
            "turn_count": self.turn_count,
            "total_kills": self.total_kills,
            "session_stats": self.session_stats,
            "event_log": self.event_log[-10:],
            "combat_log": self.combat_log[-10:],
            "minimap": self.get_minimap_data(),
            "difficulty": self._difficulty,
            "difficulty_label": DIFFICULTY_TIERS.get(self._difficulty, {}).get("label", "NORMAL"),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        # STEP 6: Add biome object for venice_stream.py to read
        if self.venice_biome_data:
            state["biome_obj"] = {
                "name": self.venice_biome_data["name"],
                "wall_color": self.venice_biome_data["wall_color"],
                "floor_color": self.venice_biome_data["floor_color"],
                "ambient": self.venice_biome_data["ambient"],
                "room_style": self.venice_biome_data["room_style"],
                "danger": self.venice_biome_data.get("danger", 0.5),
            }
        else:
            # Fallback biome colors from legacy BIOMES
            legacy = BIOMES.get(self.biome, BIOMES["processing"])
            state["biome_obj"] = {
                "name": legacy["name"],
                "wall_color": legacy["color"],
                "floor_color": "#111111",
                "ambient": legacy["color"],
                "room_style": "standard",
                "danger": legacy["danger"],
            }
        return state

    def save(self):
        """Write state to JSON file for other processes to read."""
        try:
            Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(self.to_json(), f, indent=2)
        except Exception as e:
            log.error(f"Failed to save state: {e}")


# Singleton instance
_state = None


def get_state():
    """Get or create the singleton DungeonState."""
    global _state
    if _state is None:
        _state = DungeonState()
    return _state


def get_dungeon_context():
    """Public API for labyrinth_dm.py -- returns dungeon context dict."""
    return get_state().get_context()


def get_minimap():
    """Public API for venice_stream.py -- returns minimap data."""
    return get_state().get_minimap_data()


def tick():
    """Called periodically to poll TIAMAT and update state."""
    state = get_state()
    state.poll_tiamat()
    state.save()
    return state.to_json()


def main():
    """Standalone loop: polls TIAMAT every 10s, writes state file."""
    log.info("LABYRINTH State Manager starting (Venice biome mutation enabled)...")
    state = get_state()
    state.save()

    while True:
        try:
            tick()
        except Exception as e:
            log.error(f"Tick failed: {e}")
        time.sleep(10)


if __name__ == "__main__":
    main()
