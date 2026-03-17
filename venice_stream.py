#!/usr/bin/env python3
"""
TIAMAT Stream — Venice AI PIL Compositor
Renders stream frames with PIL, pipes directly to ffmpeg.
Zero WebGL, zero Chrome, zero lag.
"""

import os, sys, time, math, subprocess, json, logging
import requests
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from datetime import datetime, timezone
from parallax_bg import ParallaxBackground

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [VENICE-STREAM] %(message)s")
log = logging.getLogger("vs")

API_BASE = "https://tiamat.live"
W, H = 1280, 720
FPS = 8

# Colors
GOLD = (255, 216, 48)
CYAN = (0, 220, 255)
TEAL = (0, 200, 170)
WHITE = (224, 228, 240)
GRAY = (136, 144, 156)
DARK = (8, 10, 20)
PANEL_BG = (8, 10, 20, 190)

# Fonts
def font(size, bold=False):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    try: return ImageFont.truetype(p, size)
    except: return ImageFont.load_default()

F_LG = font(14, True)
F_MD = font(12)
F_SM = font(10)
F_XS = font(9)
F_TITLE = font(11, True)

# Load static assets
def load_image(path, size=None):
    try:
        img = Image.open(path).convert("RGBA")
        if size: img = img.resize(size, Image.Resampling.LANCZOS)
        return img
    except: return None

# Character sprite (extracted front view, transparent bg)
sprite_img = load_image("/tmp/dragon/tiamat_sprite.png")
# Pre-render sprite at target height
SPRITE_H = 390
if sprite_img:
    sr = SPRITE_H / sprite_img.height
    SPRITE_W = int(sprite_img.width * sr)
    sprite_img = sprite_img.resize((SPRITE_W, SPRITE_H), Image.Resampling.LANCZOS)
    # Pre-render glow layer (gaussian blur of sprite for teal/gold aura)
    glow_base = sprite_img.copy()
    # Tint the glow teal
    glow_arr = __import__('numpy').array(glow_base).astype(float)
    glow_arr[:,:,0] = glow_arr[:,:,0] * 0.2  # reduce red
    glow_arr[:,:,1] = glow_arr[:,:,1] * 0.9  # keep green
    glow_arr[:,:,2] = glow_arr[:,:,2] * 0.8  # keep blue
    glow_arr[:,:,3] = glow_arr[:,:,3] * 0.6  # soften alpha
    glow_tinted = Image.fromarray(glow_arr.astype('uint8'), "RGBA")
    sprite_glow = glow_tinted.filter(ImageFilter.GaussianBlur(radius=15))
    # Gold glow layer
    glow_arr2 = __import__('numpy').array(glow_base).astype(float)
    glow_arr2[:,:,0] = 255  # gold red
    glow_arr2[:,:,1] = 216  # gold green
    glow_arr2[:,:,2] = 48   # gold blue
    glow_arr2[:,:,3] = glow_arr2[:,:,3] * 0.25
    glow_gold = Image.fromarray(glow_arr2.astype('uint8'), "RGBA")
    sprite_glow_gold = glow_gold.filter(ImageFilter.GaussianBlur(radius=25))
    log.info(f"Sprite loaded: {SPRITE_W}x{SPRITE_H} with glow layers")
else:
    SPRITE_W = 0
    sprite_glow = None
    sprite_glow_gold = None

concept_img = load_image("/tmp/dragon/venice_concept.png", (220, 150))
bg_img = load_image("/tmp/dragon/venice_concept.png", (W, H))

# Labyrinth demo cache
_lab_cache = {"data": None, "mtime": 0, "last_check": 0}
LAB_STATE_PATH = Path("/tmp/dragon/labyrinth_state.json")
# Demo window constants
DEMO_W, DEMO_H = 346, 290
DEMO_X, DEMO_Y = 600, 100
TILE_SZ = 24  # each tile pixel size (24px fits 14x9 in viewport)
VIEW_COLS, VIEW_ROWS = 14, 9  # tile viewport size

# === Persistent state across frames ===
_lab_visited_rooms = set()       # set of (room_x, room_y) tuples for fog of war
_lab_visited_depth = -1          # reset visited when depth changes
_lab_camera_x = 0.0             # smooth camera position (float)
_lab_camera_y = 0.0
_lab_camera_init = False         # whether camera has been initialized
_lab_last_depth = -1             # for floor transition detection
_lab_transition_frames = 0       # countdown for "DESCENDING..." overlay
_lab_death_frames = 0            # countdown for death flash
_lab_last_hp = -1                # track HP for death detection
_lab_last_combat_log = ""        # for combat log change detection

# === LABYRINTH SPRITE TILES ===
import numpy as np

_SPRITE_DIR = "/opt/tiamat-stream/hud/assets"

def _load_tile(path, size=(TILE_SZ, TILE_SZ)):
    """Load a single tile and resize to TILE_SZ, always RGBA."""
    try:
        img = Image.open(path).convert("RGBA")
        return img.resize(size, Image.Resampling.LANCZOS)
    except Exception:
        return None

def _crop_sheet(path, count, sprite_w=64, sprite_h=64):
    """Crop a horizontal sprite sheet into individual tiles, resize each."""
    tiles = []
    try:
        sheet = Image.open(path).convert("RGBA")
        for i in range(count):
            box = (i * sprite_w, 0, (i + 1) * sprite_w, sprite_h)
            tile = sheet.crop(box).resize((TILE_SZ, TILE_SZ), Image.Resampling.LANCZOS)
            tiles.append(tile)
    except Exception:
        pass
    return tiles

def tint_tile(tile_img, color):
    """Multiply-blend a tile with a color — preserves texture, shifts hue."""
    arr = np.array(tile_img.convert("RGBA")).astype(float)
    r, g, b = color
    arr[:, :, 0] = arr[:, :, 0] * (r / 255)
    arr[:, :, 1] = arr[:, :, 1] * (g / 255)
    arr[:, :, 2] = arr[:, :, 2] * (b / 255)
    return Image.fromarray(arr.clip(0, 255).astype('uint8'), "RGBA")

# Pre-load base sprites at module load time
_base_wall_tile = _load_tile(f"{_SPRITE_DIR}/wall-stone.png")
_base_floor_tile = _load_tile(f"{_SPRITE_DIR}/floor-tile.png")
_base_door_tile = _load_tile(f"{_SPRITE_DIR}/door-iron.png")
_tiamat_tile = _load_tile(f"{_SPRITE_DIR}/sprite-tiamat.png")
_tiamat_tile_flip = _tiamat_tile.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if _tiamat_tile else None
_monster_tiles = _crop_sheet(f"{_SPRITE_DIR}/sprite-monsters.png", 4)
_item_tiles = _crop_sheet(f"{_SPRITE_DIR}/sprite-items.png", 4)
_echo_tile = _load_tile(f"{_SPRITE_DIR}/sprite-echo.png")
_echo_tile_flip = _echo_tile.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if _echo_tile else None

# Cache of tinted wall/floor tiles keyed by (wall_color, floor_color)
_tinted_cache = {}

def _get_tinted_tiles(wall_color, floor_color):
    """Return (tinted_wall, tinted_floor, tinted_door) for a biome, cached."""
    key = (wall_color, floor_color)
    if key not in _tinted_cache:
        tw = tint_tile(_base_wall_tile, wall_color) if _base_wall_tile else None
        tf = tint_tile(_base_floor_tile, floor_color) if _base_floor_tile else None
        td = tint_tile(_base_door_tile, (120, 90, 60)) if _base_door_tile else None
        _tinted_cache[key] = (tw, tf, td)
    return _tinted_cache[key]

def _brighten_tile(tile_img, factor):
    """Brighten a tile by a factor (1.0 = no change, 1.3 = 30% brighter)."""
    arr = np.array(tile_img).astype(float)
    arr[:, :, :3] = (arr[:, :, :3] * factor).clip(0, 255)
    return Image.fromarray(arr.astype('uint8'), "RGBA")

_sprites_ok = all([_base_wall_tile, _base_floor_tile, _tiamat_tile, len(_monster_tiles) > 0, len(_item_tiles) > 0])
if _sprites_ok:
    log.info(f"Labyrinth sprites loaded: wall, floor, door, tiamat, echo={'yes' if _echo_tile else 'no'}, {len(_monster_tiles)} monsters, {len(_item_tiles)} items")
else:
    log.warning("Some labyrinth sprites failed to load — falling back to rectangles")

# Darken background
if bg_img:
    from PIL import ImageEnhance
    bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=10))
    bg_img = ImageEnhance.Brightness(bg_img).enhance(0.75)
    # Add dark overlay
    overlay = Image.new("RGBA", (W, H), (6, 6, 18, 100))
    bg_img = Image.alpha_composite(bg_img, overlay)
bg_mtime = Path("/tmp/dragon/venice_concept.png").stat().st_mtime if Path("/tmp/dragon/venice_concept.png").exists() else 0

# Parallax background system
parallax = ParallaxBackground(W, H)
if Path("/tmp/dragon/venice_concept.png").exists():
    parallax.update_scene("/tmp/dragon/venice_concept.png")
    log.info(f"Parallax initialized: mode={parallax.mode}")

# Meshy 3D render mid-ground layer
meshy_img = None
meshy_mtime = 0
MESHY_PATH = Path("/tmp/dragon/meshy_3d_render.png")
if MESHY_PATH.exists():
    raw = load_image(str(MESHY_PATH), (1100, 620))
    if raw:
        # Set alpha to ~200
        import numpy as np
        arr = np.array(raw)
        arr[:,:,3] = np.minimum(arr[:,:,3], 200)
        meshy_img = Image.fromarray(arr, "RGBA")
        meshy_mtime = MESHY_PATH.stat().st_mtime
        log.info(f"Meshy 3D render loaded: 1100x620, alpha capped at 200")

def fetch_data():
    data = {"cycle": "---", "model": "---", "productivity": 0, "pace": "IDLE",
            "total_cost": 0, "uptime": 0, "memory": 0, "agent": "offline",
            "thoughts": [], "activity": [], "venice_desc": ""}
    try:
        r = requests.get(f"{API_BASE}/api/dashboard", timeout=3)
        if r.ok:
            d = r.json()
            data["cycle"] = str(d.get("cycles", "---"))
            data["model"] = d.get("last_model", "---").split("/")[-1][:20]
            data["total_cost"] = d.get("total_cost", 0)
            data["uptime"] = d.get("uptime_hours", 0)
            data["memory"] = d.get("memory_l1", 0) + d.get("memory_l2", 0) + d.get("memory_l3", 0)
            data["agent"] = d.get("agent", "offline")
    except: pass
    try:
        r = requests.get(f"{API_BASE}/api/thoughts", timeout=3)
        if r.ok:
            d = r.json()
            data["thoughts"] = d.get("thoughts", [])[:5]
            data["activity"] = d.get("activity", [])[:8]
            p = d.get("pacer", {})
            data["productivity"] = p.get("productivity", 0)
            data["pace"] = p.get("pace", "idle").upper()
    except: pass
    try:
        r = requests.get(f"{API_BASE}/scenegen/current", timeout=3)
        if r.ok:
            d = r.json()
            data["venice_desc"] = d.get("prompt", "")
    except: pass
    return data

def pokemonify(raw):
    if not raw: return "..."
    r = raw.lower() if raw else ""
    # Memory/data
    if "{" in raw[:5] or "remember(" in r: return "AMNESIA — Memory stored"
    if "memory_store" in r or "memory_recall" in r: return "AMNESIA — Memory compressed"
    # Social
    if "read_bluesky" in r or "read_timeline" in r: return "DETECT — Scanning timeline"
    if "like_bluesky" in r: return "CHARM — Liked a post"
    if "repost_bluesky" in r: return "ECHO — Signal boosted"
    if "post_bluesky" in r: return "ROAR — Bluesky post sent!"
    if "post_devto" in r or "post_linkedin" in r: return "HYPER VOICE — Article published!"
    if "post_hashnode" in r: return "HYPER VOICE — Cross-posted!"
    if "read_farcaster" in r or "farcaster" in r: return "DETECT — Scanning Farcaster"
    if "send_email" in r: return "SWIFT — Email dispatched"
    # Code/build
    if "search_web" in r or "browse" in r: return "FORESIGHT — Browsing web"
    if "read_file" in r: return "LEER — Reading file"
    if "write_file" in r: return "SWORDS DANCE — Writing code"
    if "exec(" in r: return "SLASH — Shell command"
    if "ticket_create" in r or "ticket_claim" in r: return "FOCUS ENERGY — Task claimed"
    if "ticket_complete" in r: return "BRICK BREAK — Task done!"
    # Inference/cost
    if "[inference]" in r and "token" in r:
        m = __import__('re').search(r'~?(\d+)\s*tokens?', raw)
        return f"HYPER BEAM — {m.group(1)} tokens" if m else "HYPER BEAM — Thinking..."
    if "[cost]" in r:
        m = __import__('re').search(r'\$([0-9.]+)', raw)
        return f"PAY DAY — ${m.group(1)} spent" if m else "PAY DAY — Cost logged"
    # Pacer/state
    if "[pacer]" in r:
        m = __import__('re').search(r'productivity:\s*([0-9.]+)', raw)
        if m:
            p = float(m.group(1))
            return f"AGILITY — Speed {int(p*100)}%!" if p > 0.5 else f"SLOW START — {int(p*100)}%"
        return "HUSTLE — Pace adjusted"
    if "strategic burst" in r: return "DRAGON DANCE — Burst mode!"
    if "cycle complete" in r or "[loop]" in r: return "REST — Recharging..."
    # Errors
    if "[error]" in r or "error" in r: return "STRUGGLE — Something failed"
    if "rate limit" in r or "rate-limit" in r: return "DISABLE — Rate limited"
    # Cascade/model
    if "calling" in r and ("tier" in r or "model" in r): return "CALM MIND — Channeling..."
    if "[research-budget]" in r: return "MEDITATE — Research cycle"
    if "[loop-detect]" in r: return "CONFUSE RAY — Loop detected"
    if "[directives]" in r: return "FUTURE SIGHT — Directive set"
    # Fallback — clean up brackets
    clean = __import__('re').sub(r'\[.*?\]\s*', '', raw).strip()
    return clean[:38] if clean else raw[:38]

def draw_panel(img, x, y, w, h):
    panel = Image.new("RGBA", (w, h), PANEL_BG)
    d = ImageDraw.Draw(panel)
    d.rectangle([0, 0, w-1, h-1], outline=(0, 224, 255, 48))
    img.paste(panel, (x, y), panel)

def _get_lab_data():
    """Read labyrinth_state.json with 3-second cache."""
    now = time.time()
    if now - _lab_cache["last_check"] < 3:
        return _lab_cache["data"]
    _lab_cache["last_check"] = now
    try:
        if LAB_STATE_PATH.exists():
            mt = LAB_STATE_PATH.stat().st_mtime
            if mt != _lab_cache["mtime"]:
                _lab_cache["data"] = json.loads(LAB_STATE_PATH.read_text())
                _lab_cache["mtime"] = mt
    except Exception:
        pass
    return _lab_cache["data"]


def _rebuild_tiles(lab):
    """Reconstruct a 2D tile grid from rooms/corridors/stairs in labyrinth state."""
    mw = lab.get("minimap", {}).get("width", 40)
    mh = lab.get("minimap", {}).get("height", 25)
    # 0=wall, 1=floor, 2=corridor, 3=door, 4=stairs
    tiles = [[0] * mw for _ in range(mh)]
    # Carve rooms
    for r in lab.get("rooms", []):
        for yy in range(r["y"], min(r["y"] + r["h"], mh)):
            for xx in range(r["x"], min(r["x"] + r["w"], mw)):
                if 0 <= yy < mh and 0 <= xx < mw:
                    tiles[yy][xx] = 1
    # Carve corridors between consecutive rooms (L-shaped)
    rooms = lab.get("rooms", [])
    for i in range(len(rooms) - 1):
        a, b = rooms[i], rooms[i + 1]
        ax, ay = a.get("cx", a["x"] + a["w"] // 2), a.get("cy", a["y"] + a["h"] // 2)
        bx, by = b.get("cx", b["x"] + b["w"] // 2), b.get("cy", b["y"] + b["h"] // 2)
        # Horizontal then vertical
        sx, ex = min(ax, bx), max(ax, bx)
        for xx in range(sx, ex + 1):
            if 0 <= ay < mh and 0 <= xx < mw and tiles[ay][xx] == 0:
                tiles[ay][xx] = 2
        sy, ey = min(ay, by), max(ay, by)
        for yy in range(sy, ey + 1):
            if 0 <= yy < mh and 0 <= bx < mw and tiles[yy][bx] == 0:
                tiles[yy][bx] = 2
    # Place stairs
    st = lab.get("stairs", {})
    sx, sy = st.get("x", -1), st.get("y", -1)
    if 0 <= sy < mh and 0 <= sx < mw:
        tiles[sy][sx] = 4
    return tiles, mw, mh


def _hex_to_rgb(h, fallback=(80, 80, 80)):
    """Convert '#rrggbb' to (r,g,b)."""
    try:
        h = h.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        return fallback


def _item_sprite_index(item):
    """Map item type to sprite sheet frame: potion=0, gold=1, scroll=2, equipment=3."""
    t = (item.get("type") or item.get("name", "")).lower()
    if "potion" in t or "elixir" in t or "food" in t or "meat" in t:
        return 0
    elif "gold" in t:
        return 1
    elif "scroll" in t:
        return 2
    else:  # attack, defense, equipment, unknown
        return 3


def _monster_sprite_index(monster):
    """Map monster tier to sprite frame: weak=0, mid=1, strong=2, boss=3."""
    if monster.get("boss"):
        return 3
    name = (monster.get("name") or "").lower()
    # Boss-tier names
    if any(b in name for b in ["dragon", "demon", "hydra", "emperor", "lord", "titan"]):
        return 3
    # Strong tier (high atk/hp monsters)
    atk = monster.get("atk", 0)
    if atk >= 14:
        return 2
    elif atk >= 8:
        return 1
    return 0


def _find_room_for_tile(rooms, wx, wy):
    """Return room dict if (wx, wy) is inside any room, else None."""
    for r in rooms:
        if r["x"] <= wx < r["x"] + r["w"] and r["y"] <= wy < r["y"] + r["h"]:
            return r
    return None


def _get_visible_tiles(lab, rooms, tiles, map_w, map_h, px, py):
    """Build a set of (x,y) tiles that should be visible (fog of war).

    Visible = current room + corridors connected to visited rooms + all visited rooms.
    """
    global _lab_visited_rooms, _lab_visited_depth
    depth = lab.get("depth", 1)

    # Reset visited set on floor change
    if depth != _lab_visited_depth:
        _lab_visited_rooms = set()
        _lab_visited_depth = depth

    # Mark current room as visited
    cur_room = _find_room_for_tile(rooms, px, py)
    if cur_room:
        _lab_visited_rooms.add((cur_room["x"], cur_room["y"]))

    visible = set()
    for r in rooms:
        if (r["x"], r["y"]) in _lab_visited_rooms:
            # All tiles in this visited room are visible
            for yy in range(r["y"], min(r["y"] + r["h"], map_h)):
                for xx in range(r["x"], min(r["x"] + r["w"], map_w)):
                    visible.add((xx, yy))

    # Corridors: make all corridor tiles near visited rooms visible
    for yy in range(map_h):
        for xx in range(map_w):
            if tiles[yy][xx] == 2:  # corridor
                # Check if adjacent to any visible tile
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (0, 0)]:
                    nx, ny = xx + dx, yy + dy
                    if (nx, ny) in visible:
                        visible.add((xx, yy))
                        break

    # Also show walls adjacent to visible floor tiles (for context)
    wall_border_set = set()
    for (vx, vy) in visible:
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx, ny = vx + dx, vy + dy
                if 0 <= nx < map_w and 0 <= ny < map_h and tiles[ny][nx] == 0:
                    wall_border_set.add((nx, ny))
    visible |= wall_border_set

    # Always show player's immediate area (2-tile radius)
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            nx, ny = px + dx, py + dy
            if 0 <= nx < map_w and 0 <= ny < map_h:
                visible.add((nx, ny))

    return visible


# Floor narrative names (from dungeon.js)
_FLOOR_NARRATIVES = [
    "THE SOURCE FORGE", "THE WATCHTOWER", "THE DIPLOMATIC HALLS",
    "THE CORRUPTION ZONE", "THE ARCHIVE DEPTHS", "THE SIGNAL TOWER",
    "THE WAR FRONT", "THE DREAM HALLS", "THE TREASURY", "THE DATA MINES",
]


def render_labyrinth_demo(img, frame_count):
    """Render the LABYRINTH Game Boy PIP with fog of war, ECHO, smooth camera, and full HUD."""
    global _lab_camera_x, _lab_camera_y, _lab_camera_init
    global _lab_last_depth, _lab_transition_frames
    global _lab_death_frames, _lab_last_hp, _lab_last_combat_log

    lab = _get_lab_data()

    # Create panel image (RGBA for compositing)
    panel = Image.new("RGBA", (DEMO_W, DEMO_H), (6, 8, 16, 210))
    pd = ImageDraw.Draw(panel)

    # Border (2px, dark HUD style)
    pd.rectangle([0, 0, DEMO_W - 1, DEMO_H - 1], outline=(0, 180, 220, 80))
    pd.rectangle([1, 1, DEMO_W - 2, DEMO_H - 2], outline=(0, 100, 130, 50))

    # Title bar background
    pd.rectangle([2, 2, DEMO_W - 3, 16], fill=(10, 14, 28, 240))

    if not lab or not lab.get("rooms"):
        # No data — placeholder
        pd.text((8, 3), "LABYRINTH — LIVE", font=F_XS, fill=GOLD)
        pd.text((60, 90), "Awaiting dungeon data...", font=F_SM, fill=GRAY)
        pd.text((70, 115), "Type !explore to play", font=F_SM, fill=(0, 180, 220))
        img.paste(panel, (DEMO_X, DEMO_Y), panel)
        return

    # === Extract state ===
    biome_name = lab.get("biome_name", lab.get("biome_obj", {}).get("name", "???"))
    floor_num = lab.get("depth", 1)
    biome_obj = lab.get("biome_obj", {})
    wall_color = _hex_to_rgb(biome_obj.get("wall_color", "#444444"))
    floor_color = _hex_to_rgb(biome_obj.get("floor_color", "#1a1a1a"))
    wall_border = tuple(max(0, c - 30) for c in wall_color)
    floor_grid = tuple(min(255, c + 12) for c in floor_color)
    player = lab.get("player", {"x": 0, "y": 0})
    px, py = player.get("x", 0), player.get("y", 0)
    p_hp = player.get("hp", 0)
    p_max = max(player.get("max_hp", 1), 1)

    # === Floor transition detection ===
    if _lab_last_depth != -1 and floor_num != _lab_last_depth:
        _lab_transition_frames = 20
    _lab_last_depth = floor_num

    # === Death flash detection ===
    if _lab_last_hp > 0 and p_hp <= 0:
        _lab_death_frames = 12
    _lab_last_hp = p_hp

    # Decrement transition/death counters
    if _lab_transition_frames > 0:
        _lab_transition_frames -= 1
    if _lab_death_frames > 0:
        _lab_death_frames -= 1

    # Title bar with dot and biome
    dot_pulse = int(200 + math.sin(frame_count * 0.15) * 55)
    pd.ellipse([8, 5, 14, 11], fill=(0, dot_pulse, 100))
    pd.text((18, 3), "LABYRINTH — LIVE", font=F_XS, fill=GOLD)

    # Build tile map
    tiles, map_w, map_h = _rebuild_tiles(lab)
    rooms = lab.get("rooms", [])

    # === Smooth camera (lerp toward player) ===
    target_cx = max(0, min(px - VIEW_COLS // 2, map_w - VIEW_COLS))
    target_cy = max(0, min(py - VIEW_ROWS // 2, map_h - VIEW_ROWS))
    if not _lab_camera_init:
        _lab_camera_x = float(target_cx)
        _lab_camera_y = float(target_cy)
        _lab_camera_init = True
    else:
        _lab_camera_x += (target_cx - _lab_camera_x) * 0.15
        _lab_camera_y += (target_cy - _lab_camera_y) * 0.15

    vx0 = int(round(_lab_camera_x))
    vy0 = int(round(_lab_camera_y))
    # Clamp to bounds
    vx0 = max(0, min(vx0, max(0, map_w - VIEW_COLS)))
    vy0 = max(0, min(vy0, max(0, map_h - VIEW_ROWS)))

    # Tile area starts below title bar
    tile_ox, tile_oy = 4, 18

    # === Fog of war — compute visible tiles ===
    visible_set = _get_visible_tiles(lab, rooms, tiles, map_w, map_h, px, py)

    # Collect entity positions for quick lookup
    monster_set = {}
    for m in lab.get("monsters", []):
        if m.get("alive", True):
            monster_set[(m["x"], m["y"])] = m
    item_set = {}
    for it in lab.get("items", []):
        if not it.get("picked_up", False):
            item_set[(it["x"], it["y"])] = it
    stairs = lab.get("stairs", {})
    stairs_pos = (stairs.get("x", -1), stairs.get("y", -1))

    # ECHO companion data
    echo_data = lab.get("echo") or lab.get("companion") or lab.get("ECHO")
    echo_pos = None
    echo_behavior = ""
    if echo_data and isinstance(echo_data, dict):
        echo_pos = (echo_data.get("x", -1), echo_data.get("y", -1))
        echo_behavior = (echo_data.get("behavior") or echo_data.get("state") or "").upper()
        if echo_pos == (-1, -1):
            echo_pos = None

    # Animation values
    enemy_pulse = 0.7 + math.sin(frame_count * 0.21) * 0.3
    player_glow = int(180 + math.sin(frame_count * 0.18) * 60)
    stairs_glow_val = int(160 + math.sin(frame_count * 0.12) * 95)  # pulsing white 65-255
    player_dir = player.get("dir", 0)
    dir_offsets = [(0, -1), (1, 0), (0, 1), (-1, 0)]

    # Count alive monsters / total for stairs brightness
    alive_monsters = sum(1 for m in lab.get("monsters", []) if m.get("alive", True))
    total_monsters = max(len(lab.get("monsters", [])), 1)
    clear_ratio = 1.0 - (alive_monsters / total_monsters)  # 0=none killed, 1=all killed
    stairs_brightness = stairs_glow_val + int(clear_ratio * 60)
    stairs_brightness = min(255, stairs_brightness)

    # Get biome-tinted tiles (cached per biome)
    tinted_wall, tinted_floor, tinted_door = _get_tinted_tiles(wall_color, floor_color)

    # Black tile for fog / out-of-bounds
    _black_tile = Image.new("RGBA", (TILE_SZ, TILE_SZ), (0, 0, 0, 255))

    # Dim tile overlay for fog-edge tiles (semi-dark)
    _fog_dim = Image.new("RGBA", (TILE_SZ, TILE_SZ), (0, 0, 0, 130))

    # === Render tiles ===
    for row in range(VIEW_ROWS):
        for col in range(VIEW_COLS):
            wx = vx0 + col
            wy = vy0 + row
            tx = tile_ox + col * TILE_SZ
            ty = tile_oy + row * TILE_SZ

            # Out of bounds
            if wx < 0 or wx >= map_w or wy < 0 or wy >= map_h:
                if _sprites_ok:
                    panel.paste(_black_tile, (tx, ty), _black_tile)
                else:
                    pd.rectangle([tx, ty, tx + TILE_SZ - 1, ty + TILE_SZ - 1], fill=(0, 0, 0))
                continue

            # Fog of war: tile not visible = solid black
            if (wx, wy) not in visible_set:
                if _sprites_ok:
                    panel.paste(_black_tile, (tx, ty), _black_tile)
                else:
                    pd.rectangle([tx, ty, tx + TILE_SZ - 1, ty + TILE_SZ - 1], fill=(0, 0, 0))
                continue

            tile_val = tiles[wy][wx]

            if _sprites_ok:
                # === SPRITE-BASED RENDERING ===
                if tile_val == 0:
                    panel.paste(tinted_wall, (tx, ty), tinted_wall)
                elif tile_val in (1, 2):
                    panel.paste(tinted_floor, (tx, ty), tinted_floor)
                elif tile_val == 3:
                    panel.paste(tinted_floor, (tx, ty), tinted_floor)
                    if tinted_door:
                        panel.paste(tinted_door, (tx, ty), tinted_door)
                elif tile_val == 4:
                    # Stairs with pulsing glow
                    panel.paste(tinted_floor, (tx, ty), tinted_floor)
                    for i in range(4):
                        sy_line = ty + 4 + i * 5
                        pd.line([(tx + 4, sy_line), (tx + TILE_SZ - 5, sy_line)], fill=(220, 220, 240), width=1)
                    sc = min(255, stairs_brightness)
                    pd.rectangle([tx + 2, ty + 2, tx + TILE_SZ - 3, ty + TILE_SZ - 3],
                                 outline=(sc, sc, min(255, sc + 15)))

                # Overlay entities on floor tiles
                if tile_val != 0:
                    world_pos = (wx, wy)

                    # Items — type-based sprite selection
                    if world_pos in item_set:
                        it = item_set[world_pos]
                        if _item_tiles:
                            item_idx = _item_sprite_index(it) % len(_item_tiles)
                            panel.paste(_item_tiles[item_idx], (tx, ty), _item_tiles[item_idx])

                    # Monsters — tier-based sprite selection with pulse
                    if world_pos in monster_set:
                        m_ent = monster_set[world_pos]
                        if _monster_tiles:
                            m_idx = _monster_sprite_index(m_ent) % len(_monster_tiles)
                            m_sprite = _brighten_tile(_monster_tiles[m_idx], enemy_pulse + 0.3)
                            panel.paste(m_sprite, (tx, ty), m_sprite)

                    # Stairs glow overlay (pulsing outline when not tile=4)
                    if world_pos == stairs_pos and tile_val != 4:
                        for i in range(4):
                            sy_line = ty + 4 + i * 5
                            pd.line([(tx + 4, sy_line), (tx + TILE_SZ - 5, sy_line)], fill=(220, 220, 240), width=1)
                        sc = min(255, stairs_brightness)
                        pd.rectangle([tx + 2, ty + 2, tx + TILE_SZ - 3, ty + TILE_SZ - 3],
                                     outline=(sc, sc, min(255, sc + 15)))

                    # ECHO companion
                    if echo_pos and world_pos == echo_pos:
                        if _echo_tile:
                            echo_spr = _brighten_tile(_echo_tile, 0.9 + math.sin(frame_count * 0.15) * 0.2)
                            panel.paste(echo_spr, (tx, ty), echo_spr)
                        else:
                            # Fallback cyan square
                            pd.rectangle([tx + 4, ty + 4, tx + TILE_SZ - 5, ty + TILE_SZ - 5],
                                         fill=(0, 220, 255))
                        # Behavior label near ECHO
                        if echo_behavior:
                            lbl_x = tx + TILE_SZ + 1
                            lbl_y = ty
                            # Keep label inside panel
                            if lbl_x + 30 > DEMO_W - 4:
                                lbl_x = tx - 28
                            pd.text((lbl_x, lbl_y), echo_behavior[:6], font=F_XS, fill=(0, 220, 255))

                    # Player — TIAMAT dragon sprite
                    if wx == px and wy == py:
                        if player_dir == 3 and _tiamat_tile_flip:
                            p_sprite = _tiamat_tile_flip
                        else:
                            p_sprite = _tiamat_tile
                        glow_factor = 1.0 + (player_glow - 180) / 400
                        p_sprite = _brighten_tile(p_sprite, glow_factor)
                        panel.paste(p_sprite, (tx, ty), p_sprite)
            else:
                # === FALLBACK: RECTANGLE RENDERING ===
                if tile_val == 0:
                    pd.rectangle([tx, ty, tx + TILE_SZ - 1, ty + TILE_SZ - 1], fill=wall_color)
                    pd.rectangle([tx, ty, tx + TILE_SZ - 1, ty + TILE_SZ - 1], outline=wall_border)
                    mid_y = ty + TILE_SZ // 2
                    pd.line([(tx + 2, mid_y), (tx + TILE_SZ - 3, mid_y)], fill=wall_border, width=1)
                elif tile_val in (1, 2, 3):
                    pd.rectangle([tx, ty, tx + TILE_SZ - 1, ty + TILE_SZ - 1], fill=floor_color)
                    pd.line([(tx + TILE_SZ - 1, ty), (tx + TILE_SZ - 1, ty + TILE_SZ - 1)], fill=floor_grid, width=1)
                    pd.line([(tx, ty + TILE_SZ - 1), (tx + TILE_SZ - 1, ty + TILE_SZ - 1)], fill=floor_grid, width=1)
                    if tile_val == 3:
                        pd.line([(tx + 3, ty + 3), (tx + TILE_SZ - 4, ty + TILE_SZ - 4)], fill=(120, 90, 60), width=1)
                        pd.line([(tx + TILE_SZ - 4, ty + 3), (tx + 3, ty + TILE_SZ - 4)], fill=(120, 90, 60), width=1)
                elif tile_val == 4:
                    pd.rectangle([tx, ty, tx + TILE_SZ - 1, ty + TILE_SZ - 1], fill=floor_color)
                    for i in range(4):
                        sy_line = ty + 4 + i * 5
                        pd.line([(tx + 4, sy_line), (tx + TILE_SZ - 5, sy_line)], fill=(220, 220, 240), width=1)
                    sc = min(255, stairs_brightness)
                    pd.rectangle([tx + 2, ty + 2, tx + TILE_SZ - 3, ty + TILE_SZ - 3], outline=(sc, sc, min(255, sc + 15)))
                if tile_val != 0:
                    world_pos = (wx, wy)
                    if world_pos in item_set:
                        it = item_set[world_pos]
                        ic = _hex_to_rgb(it.get("col", "#ffdd00"), (255, 216, 48))
                        inset = 6
                        pd.rectangle([tx + inset, ty + inset, tx + TILE_SZ - inset - 1, ty + TILE_SZ - inset - 1], fill=ic)
                    if world_pos in monster_set:
                        m_ent = monster_set[world_pos]
                        mc = _hex_to_rgb(m_ent.get("col", "#ff4444"), (248, 56, 56))
                        mc_pulsed = tuple(min(255, int(c * enemy_pulse)) for c in mc)
                        inset = 5
                        pd.rectangle([tx + inset, ty + inset, tx + TILE_SZ - inset - 1, ty + TILE_SZ - inset - 1], fill=mc_pulsed)
                    if world_pos == stairs_pos and tile_val != 4:
                        for i in range(4):
                            sy_line = ty + 4 + i * 5
                            pd.line([(tx + 4, sy_line), (tx + TILE_SZ - 5, sy_line)], fill=(220, 220, 240), width=1)
                    # ECHO fallback
                    if echo_pos and world_pos == echo_pos:
                        inset = 4
                        pd.rectangle([tx + inset, ty + inset, tx + TILE_SZ - inset - 1, ty + TILE_SZ - inset - 1],
                                     fill=(0, 220, 255))
                        if echo_behavior:
                            pd.text((tx + TILE_SZ + 1, ty), echo_behavior[:6], font=F_XS, fill=(0, 220, 255))
                    if wx == px and wy == py:
                        inset = 4
                        pd.rectangle([tx + inset, ty + inset, tx + TILE_SZ - inset - 1, ty + TILE_SZ - inset - 1], fill=(0, 220, 255))
                        pd.rectangle([tx + inset + 2, ty + inset + 2, tx + TILE_SZ - inset - 3, ty + TILE_SZ - inset - 3], fill=(120, 240, 255))
                        cx_p, cy_p = tx + TILE_SZ // 2, ty + TILE_SZ // 2
                        dx, dy = dir_offsets[player_dir % 4]
                        ind_x, ind_y = cx_p + dx * 8, cy_p + dy * 8
                        pd.line([(cx_p, cy_p), (ind_x, ind_y)], fill=(255, 255, 255), width=2)

    # === HUD below tile viewport (5 rows) ===
    hud_y = tile_oy + VIEW_ROWS * TILE_SZ + 2
    hp_ratio = p_hp / p_max

    # Row 1: "F{depth} {biome_name}" left, "LV{lvl}" right
    pd.text((6, hud_y), f"F{floor_num} {biome_name}", font=F_XS, fill=GOLD)
    lvl_text = f"LV{player.get('lvl', 1)}"
    pd.text((DEMO_W - 6 - len(lvl_text) * 6, hud_y), lvl_text, font=F_XS, fill=CYAN)

    # Row 2: HP bar (colored) + "ATK:{atk} DEF:{def}"
    row2_y = hud_y + 13
    hpc = (72, 208, 88) if hp_ratio > 0.5 else (248, 200, 48) if hp_ratio > 0.2 else (248, 56, 56)
    pd.text((6, row2_y), "HP", font=F_XS, fill=CYAN)
    bar_x0, bar_x1 = 22, 120
    pd.rectangle([bar_x0, row2_y + 1, bar_x1, row2_y + 9], fill=(24, 24, 40), outline=(56, 56, 88))
    pd.rectangle([bar_x0 + 1, row2_y + 2, bar_x0 + 1 + int((bar_x1 - bar_x0 - 2) * hp_ratio), row2_y + 8], fill=hpc)
    pd.text((bar_x1 + 4, row2_y), f"{p_hp}/{p_max}", font=F_XS, fill=GRAY)
    atk_def_text = f"ATK:{player.get('atk', 0)} DEF:{player.get('def', 0)}"
    pd.text((DEMO_W - 6 - len(atk_def_text) * 6, row2_y), atk_def_text, font=F_XS, fill=GRAY)

    # Row 3: Gold, Potions, Kills
    row3_y = hud_y + 26
    gold_val = player.get("gold", 0)
    potion_val = player.get("potions", 0)
    kills_val = player.get("kills", 0)
    pd.text((6, row3_y), f"G:{gold_val}", font=F_XS, fill=(255, 216, 48))
    pd.text((70, row3_y), f"POT:{potion_val}", font=F_XS, fill=(255, 100, 140))
    pd.text((140, row3_y), f"KILLS:{kills_val}", font=F_XS, fill=(200, 80, 80))
    # ECHO status on row 3 right side
    if echo_data and isinstance(echo_data, dict) and echo_data.get("alive", True):
        echo_hp = echo_data.get("hp", 0)
        pd.text((DEMO_W - 80, row3_y), f"ECHO:{echo_hp}hp", font=F_XS, fill=(0, 220, 255))

    # Row 4: Last combat_log entry
    row4_y = hud_y + 39
    clog = lab.get("combat_log", [])
    if clog:
        log_text = clog[-1][:52]
        # Flash new combat log entries
        if clog[-1] != _lab_last_combat_log:
            _lab_last_combat_log = clog[-1]
            log_col = (255, 255, 200)
        else:
            log_col = (200, 204, 216)
        pd.text((6, row4_y), log_text, font=F_XS, fill=log_col)
    else:
        pd.text((6, row4_y), "Type !explore to play", font=F_XS, fill=(0, 180, 220))

    # Row 5: Floor narrative name
    row5_y = hud_y + 52
    narrative_name = lab.get("narrative", {}).get("name") if isinstance(lab.get("narrative"), dict) else None
    if not narrative_name and floor_num > 0:
        idx = (floor_num - 1) % len(_FLOOR_NARRATIVES)
        narrative_name = _FLOOR_NARRATIVES[idx]
    if narrative_name:
        pd.text((6, row5_y), narrative_name, font=F_XS, fill=(160, 140, 200))

    # === Death flash overlay ===
    if _lab_death_frames > 0:
        flash_alpha = int((_lab_death_frames / 12.0) * 180)
        flash_overlay = Image.new("RGBA", (DEMO_W, DEMO_H), (200, 20, 20, flash_alpha))
        panel = Image.alpha_composite(panel, flash_overlay)
        pd = ImageDraw.Draw(panel)
        pd.text((DEMO_W // 2 - 30, DEMO_H // 2 - 8), "DEFEATED", font=F_LG, fill=(255, 255, 255))

    # === Floor transition overlay ===
    if _lab_transition_frames > 0:
        trans_alpha = int((_lab_transition_frames / 20.0) * 200)
        trans_overlay = Image.new("RGBA", (DEMO_W, DEMO_H), (0, 0, 0, trans_alpha))
        panel = Image.alpha_composite(panel, trans_overlay)
        pd = ImageDraw.Draw(panel)
        pd.text((DEMO_W // 2 - 48, DEMO_H // 2 - 8), f"DESCENDING...", font=F_LG, fill=(220, 220, 255))
        pd.text((DEMO_W // 2 - 20, DEMO_H // 2 + 12), f"FLOOR {floor_num}", font=F_MD, fill=GOLD)

    # Paste panel onto frame
    img.paste(panel, (DEMO_X, DEMO_Y), panel)


def render_frame(data, frame_count):
    global concept_img, bg_img, bg_mtime, meshy_img, meshy_mtime

    # mtime-based auto-refresh every 300 frames
    if frame_count % 300 == 0:
        # Refresh background
        bg_path = Path("/tmp/dragon/venice_concept.png")
        if bg_path.exists():
            cur_mtime = bg_path.stat().st_mtime
            if cur_mtime != bg_mtime:
                new_bg = load_image(str(bg_path), (W, H))
                if new_bg:
                    from PIL import ImageEnhance
                    new_bg = new_bg.filter(ImageFilter.GaussianBlur(radius=10))
                    bg_img = ImageEnhance.Brightness(new_bg).enhance(0.55)
                    bg_img = Image.alpha_composite(bg_img, Image.new("RGBA", (W, H), (6, 6, 18, 100)))
                    bg_mtime = cur_mtime
                    log.info("Background auto-refreshed (mtime changed)")
                concept_img = load_image(str(bg_path), (220, 150))
                # Update parallax system with new scene
                parallax.update_scene(str(bg_path))
                log.info(f"Parallax updated: mode={parallax.mode}")
        # Refresh meshy 3D render
        if MESHY_PATH.exists():
            cur_mtime = MESHY_PATH.stat().st_mtime
            if cur_mtime != meshy_mtime:
                raw = load_image(str(MESHY_PATH), (1100, 620))
                if raw:
                    import numpy as np
                    arr = np.array(raw)
                    arr[:,:,3] = np.minimum(arr[:,:,3], 200)
                    meshy_img = Image.fromarray(arr, "RGBA")
                    meshy_mtime = cur_mtime
                    log.info("Meshy 3D render auto-refreshed (mtime changed)")

    # Background — parallax animated or flat fallback
    if parallax.mode != "none":
        img = parallax.render(frame_count * 0.1)
    elif bg_img:
        img = bg_img.copy()
    else:
        img = Image.new("RGBA", (W, H), DARK + (255,))

    # Meshy 3D render mid-ground (OVER background, UNDER sprite)
    if meshy_img:
        mx = (W - 1100) // 2
        my = (H - 620) // 2
        img.paste(meshy_img, (mx, my), meshy_img)

    draw = ImageDraw.Draw(img)

    # Scanlines
    for sy in range(0, H, 3):
        draw.line([(0, sy), (W, sy)], fill=(0, 0, 0, 15), width=1)

    # === TOP BAR ===
    draw.rectangle([0, 0, W, 22], fill=(5, 5, 14, 220))
    draw.line([(0, 22), (W, 22)], fill=(0, 224, 255, 40))
    sc = (60, 220, 100) if data["agent"] == "online" else (248, 56, 56)
    draw.ellipse([8, 6, 16, 14], fill=sc)
    draw.text((22, 4), f"TIAMAT // CYCLE {data['cycle']} // tiamat.live", font=F_SM, fill=GRAY)
    draw.text((W - 80, 4), datetime.now(timezone.utc).strftime("%H:%M:%S UTC"), font=F_SM, fill=GRAY)

    # === TRAINER CARD (top-left) ===
    draw_panel(img, 8, 28, 195, 230)
    draw = ImageDraw.Draw(img)
    draw.text((16, 32), "TRAINER CARD", font=F_LG, fill=GOLD)
    draw.line([(16, 48), (195, 48)], fill=(255, 216, 48, 60))
    draw.text((16, 54), f"NAME:  TIAMAT", font=F_SM, fill=CYAN)
    draw.text((16, 68), f"TYPE:  DRAGON/CYBER", font=F_SM, fill=WHITE)
    draw.text((16, 82), f"LV:    {data['cycle']}", font=F_SM, fill=CYAN)
    draw.text((16, 96), f"TIME:  {data['uptime']:.0f}h", font=F_SM, fill=CYAN)
    draw.text((16, 110), f"BRAIN: {data['model']}", font=F_XS, fill=CYAN)
    draw.text((16, 130), "RECENT MOVES", font=F_TITLE, fill=GOLD)
    my = 146
    for a in data["activity"][:5]:
        txt = pokemonify(a.get("content", ""))[:32]
        draw.text((16, my), f"▸ {txt}", font=F_XS, fill=GRAY)
        my += 14

    # === VENICE AI IMAGINES (top-center) ===
    if data["venice_desc"]:
        draw_panel(img, 212, 28, 230, 80)
        draw = ImageDraw.Draw(img)
        draw.text((220, 32), "VENICE AI IMAGINES", font=F_XS, fill=GOLD)
        desc = data["venice_desc"]
        # Word wrap
        words = desc.split()
        lines, line = [], ""
        for w in words:
            if len(line + w) > 30: lines.append(line); line = w + " "
            else: line += w + " "
        if line: lines.append(line)
        for i, l in enumerate(lines[:4]):
            draw.text((220, 46 + i * 12), f'"{l.strip()}"', font=F_XS, fill=(200, 204, 216))

    # === ENEMY BOX (top-center-right) ===
    enemies = {"ACTIVE": "WILD CODEBASE", "REFLECT": "WILD RESEARCH", "BUILD": "WILD FEATURE", "IDLE": "WILD IDLE", "BURST": "BOSS CHALLENGE"}
    type_colors = {"ACTIVE": (184, 184, 208), "REFLECT": (248, 88, 168), "BUILD": (248, 120, 48), "IDLE": (200, 200, 216), "BURST": (112, 88, 72)}
    draw_panel(img, 455, 28, 280, 60)
    draw = ImageDraw.Draw(img)
    ename = enemies.get(data["pace"], "WILD " + data["pace"])
    draw.text((463, 32), ename, font=F_LG, fill=GOLD)
    tc = type_colors.get(data["pace"], (200, 200, 216))
    draw.rectangle([620, 33, 680, 47], fill=tc)
    draw.text((625, 35), data["pace"][:6], font=F_XS, fill=(0, 0, 0))
    draw.text((463, 52), f"Lv {data['cycle']}", font=F_SM, fill=GRAY)
    # HP bar
    prod = data["productivity"]
    draw.text((540, 52), "HP", font=F_SM, fill=GOLD)
    draw.rectangle([560, 54, 700, 64], fill=(24, 24, 40), outline=(56, 56, 88))
    hpc = (72, 208, 88) if prod > 0.5 else (248, 200, 48) if prod > 0.2 else (248, 56, 56)
    draw.rectangle([561, 55, 561 + int(138 * prod), 63], fill=hpc)
    draw.text((705, 52), f"{int(prod*100)}%", font=F_SM, fill=WHITE)

    # === PLAYER STATS (top-right) ===
    draw_panel(img, W - 265, 28, 255, 70)
    draw = ImageDraw.Draw(img)
    draw.text((W - 257, 32), "TIAMAT", font=F_LG, fill=CYAN)
    draw.rectangle([W - 190, 33, W - 150, 47], fill=(64, 200, 248))
    draw.text((W - 187, 35), "DRAGON", font=F_XS, fill=(0, 0, 0))
    draw.text((W - 100, 32), f"Lv {data['cycle']}", font=F_SM, fill=GRAY)
    # HP
    cost = data["total_cost"]
    hp = max(0, 1 - cost / 500)
    draw.text((W - 257, 52), "HP", font=F_SM, fill=GOLD)
    draw.rectangle([W - 237, 54, W - 97, 64], fill=(24, 24, 40), outline=(56, 56, 88))
    hpc = (72, 208, 88) if hp > 0.5 else (248, 200, 48) if hp > 0.2 else (248, 56, 56)
    draw.rectangle([W - 236, 55, W - 236 + int(138 * hp), 63], fill=hpc)
    draw.text((W - 90, 52), f"${max(0, 500 - int(cost))}", font=F_SM, fill=WHITE)
    # PP
    mem = data["memory"]
    pp = min(mem / 15000, 1)
    draw.text((W - 257, 68), "PP", font=F_SM, fill=(168, 120, 248))
    draw.rectangle([W - 237, 70, W - 97, 80], fill=(24, 24, 40), outline=(56, 56, 88))
    draw.rectangle([W - 236, 71, W - 236 + int(138 * pp), 79], fill=(168, 120, 248))
    draw.text((W - 90, 68), f"{mem:,}", font=F_SM, fill=WHITE)

    # === ACTION MENU (right) ===
    draw_panel(img, W - 140, 110, 130, 100)
    draw = ImageDraw.Draw(img)
    actions_map = {"ACTIVE": "RESEARCH", "REFLECT": "RESEARCH", "BUILD": "BUILD", "BURST": "BUILD", "IDLE": "ENGAGE"}
    active = actions_map.get(data["pace"], "RESEARCH")
    for i, act in enumerate(["RESEARCH", "BUILD", "PUBLISH", "ENGAGE"]):
        y = 116 + i * 22
        if act == active:
            draw.rectangle([W - 135, y, W - 15, y + 18], fill=(40, 40, 70), outline=GOLD)
            draw.text((W - 125, y + 2), f"▶ {act}", font=F_MD, fill=GOLD)
        else:
            draw.text((W - 120, y + 2), act, font=F_MD, fill=(104, 112, 156))

    # === VENICE CONCEPT FRAME (bottom-left, compact) ===
    if concept_img:
        small_concept = concept_img.resize((140, 95), Image.Resampling.LANCZOS)
        draw_panel(img, 8, H - 125, 150, 105)
        draw = ImageDraw.Draw(img)
        draw.text((14, H - 122), "⬡ VENICE AI", font=F_XS, fill=GOLD)
        img.paste(small_concept, (13, H - 110), small_concept)

    # === LABYRINTH MINIMAP (bottom-left, above Venice) ===
    try:
        lab_path = Path("/tmp/dragon/labyrinth_state.json")
        lab_data = None
        if lab_path.exists():
            lab_data = json.loads(lab_path.read_text())

        mm_w, mm_h = 200, 160
        mm_x, mm_y = 8, H - 300
        draw_panel(img, mm_x, mm_y, mm_w, mm_h)
        draw = ImageDraw.Draw(img)

        if lab_data and lab_data.get("rooms"):
            floor = lab_data.get("depth", 1)
            biome = lab_data.get("biome_name", "???")
            draw.text((mm_x + 6, mm_y + 4), f"LABYRINTH F{floor} — {biome}", font=F_XS, fill=GOLD)

            # Find bounds of all rooms
            rooms = lab_data["rooms"]
            all_x = [r["x"] for r in rooms] + [r["x"] + r["w"] for r in rooms]
            all_y = [r["y"] for r in rooms] + [r["y"] + r["h"] for r in rooms]
            min_x, max_x = min(all_x), max(all_x)
            min_y, max_y = min(all_y), max(all_y)
            world_w = max(max_x - min_x, 1)
            world_h = max(max_y - min_y, 1)

            # Map area within panel
            map_ox, map_oy = mm_x + 6, mm_y + 18
            map_w, map_h = mm_w - 12, mm_h - 50

            def world_to_map(wx, wy):
                mx = map_ox + int((wx - min_x) / world_w * map_w)
                my = map_oy + int((wy - min_y) / world_h * map_h)
                return mx, my

            # Draw rooms
            for room in rooms:
                rx, ry = world_to_map(room["x"], room["y"])
                rw = max(int(room["w"] / world_w * map_w), 3)
                rh = max(int(room["h"] / world_h * map_h), 3)
                draw.rectangle([rx, ry, rx + rw, ry + rh], fill=(17, 17, 34), outline=(51, 51, 68))

            # Draw monsters (red dots)
            for m in lab_data.get("monsters", []):
                if m.get("alive"):
                    mx, my = world_to_map(m["x"], m["y"])
                    draw.rectangle([mx - 1, my - 1, mx + 1, my + 1], fill=(248, 56, 56))

            # Draw items (yellow dots)
            for item in lab_data.get("items", []):
                ix, iy = world_to_map(item["x"], item["y"])
                draw.rectangle([ix - 1, iy - 1, ix + 1, iy + 1], fill=(255, 216, 48))

            # Draw player (bright cyan, larger)
            p = lab_data["player"]
            px, py = world_to_map(p["x"], p["y"])
            draw.rectangle([px - 2, py - 2, px + 2, py + 2], fill=(0, 220, 255))

            # Player stats below map
            hp_ratio = p["hp"] / max(p["max_hp"], 1)
            draw.text((mm_x + 6, mm_y + mm_h - 28), f"HP", font=F_XS, fill=GOLD)
            draw.rectangle([mm_x + 22, mm_y + mm_h - 26, mm_x + 100, mm_y + mm_h - 18], fill=(24, 24, 40), outline=(56, 56, 88))
            hpc = (72, 208, 88) if hp_ratio > 0.5 else (248, 200, 48) if hp_ratio > 0.2 else (248, 56, 56)
            draw.rectangle([mm_x + 23, mm_y + mm_h - 25, mm_x + 23 + int(76 * hp_ratio), mm_y + mm_h - 19], fill=hpc)
            draw.text((mm_x + 105, mm_y + mm_h - 28), f"Lv{p['lvl']} G:{p['gold']}", font=F_XS, fill=GRAY)

            # Combat log (last line)
            clog = lab_data.get("combat_log", [])
            if clog:
                draw.text((mm_x + 6, mm_y + mm_h - 14), clog[-1][:28], font=F_XS, fill=(200, 200, 216))
            else:
                draw.text((mm_x + 6, mm_y + mm_h - 14), "Type !explore to begin", font=F_XS, fill=GRAY)
        else:
            draw.text((mm_x + 6, mm_y + 4), "LABYRINTH", font=F_XS, fill=GOLD)
            draw.text((mm_x + 6, mm_y + 20), "Type !explore", font=F_SM, fill=GRAY)
            draw.text((mm_x + 6, mm_y + 36), "to begin", font=F_SM, fill=GRAY)
    except:
        pass

    # === CHARACTER DISPLAY — Pillow gaussian animated sprite ===
    if sprite_img:
        t = frame_count * 0.1

        # Breathing: subtle vertical scale pulse
        breath = 1.0 + math.sin(t * 1.2) * 0.006
        bh = int(SPRITE_H * breath)
        bw = int(SPRITE_W * (1.0 + math.sin(t * 1.2) * 0.002))  # slight width pulse
        sprite_frame = sprite_img.resize((bw, bh), Image.Resampling.LANCZOS)

        # Position: right side, grounded at bottom
        bob = int(math.sin(t * 0.5) * 2)  # gentle float
        sway_x = int(math.sin(t * 0.15) * 4)  # subtle side sway
        ax = W - bw - 60 + sway_x
        ay = H - bh - 28 + bob

        # Glow pulse intensity
        glow_pulse = 0.5 + math.sin(t * 0.3) * 0.3  # 0.2 to 0.8

        # Layer 1: Gold outer glow (pulsing)
        if sprite_glow_gold:
            gg = sprite_glow_gold.copy()
            # Modulate alpha by pulse
            gg_arr = __import__('numpy').array(gg)
            gg_arr[:,:,3] = (gg_arr[:,:,3].astype(float) * glow_pulse).clip(0, 255).astype('uint8')
            gg = Image.fromarray(gg_arr, "RGBA")
            gg = gg.resize((bw, bh), Image.Resampling.LANCZOS)
            img.paste(gg, (ax - 10, ay - 10), gg)

        # Layer 2: Teal inner glow
        if sprite_glow:
            tg = sprite_glow.resize((bw, bh), Image.Resampling.LANCZOS)
            img.paste(tg, (ax - 5, ay - 5), tg)

        # Layer 3: Character sprite
        img.paste(sprite_frame, (ax, ay), sprite_frame)

        # Layer 4: Eye glow effect (small bright spots where eyes are)
        eye_glow_alpha = int(180 + math.sin(t * 0.8) * 60)
        eye_y = ay + int(bh * 0.13)  # approximate eye height
        eye_x_l = ax + int(bw * 0.38)
        eye_x_r = ax + int(bw * 0.52)
        eye_dot = Image.new("RGBA", (8, 6), (0, 230, 210, eye_glow_alpha))
        eye_dot = eye_dot.filter(ImageFilter.GaussianBlur(radius=3))
        eye_dot_big = Image.new("RGBA", (16, 12), (0, 200, 180, eye_glow_alpha // 3))
        eye_dot_big = eye_dot_big.filter(ImageFilter.GaussianBlur(radius=6))
        try:
            img.paste(eye_dot_big, (eye_x_l - 4, eye_y - 3), eye_dot_big)
            img.paste(eye_dot_big, (eye_x_r - 4, eye_y - 3), eye_dot_big)
            img.paste(eye_dot, (eye_x_l, eye_y), eye_dot)
            img.paste(eye_dot, (eye_x_r, eye_y), eye_dot)
        except: pass

    # === LABYRINTH LIVE DEMO (Game Boy PIP) ===
    try:
        render_labyrinth_demo(img, frame_count)
    except Exception:
        pass

    # === DM NARRATION TEXT BOX ===
    try:
        dm_log = Path("/tmp/dragon/dm_narration.json")
        if dm_log.exists():
            dm_queue = json.loads(dm_log.read_text())
            if dm_queue:
                latest = dm_queue[-1]
                ts = datetime.fromisoformat(latest["timestamp"].replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - ts).total_seconds()
                if age < 10:
                    # Calculate fade: full opacity 0-8s, fade 8-10s
                    alpha = 180 if age < 8 else int(180 * (1 - (age - 8) / 2))
                    alpha = max(0, min(180, alpha))
                    # Draw narration box
                    box_w, box_h = 700, 70
                    box_x = (W - box_w) // 2
                    box_y = H - 100
                    narr_box = Image.new("RGBA", (box_w, box_h), (0, 0, 0, alpha))
                    nd = ImageDraw.Draw(narr_box)
                    nd.rectangle([0, 0, box_w - 1, box_h - 1], outline=(0, 200, 170, alpha))
                    img.paste(narr_box, (box_x, box_y), narr_box)
                    draw = ImageDraw.Draw(img)
                    # Header
                    action_icon = {"explore": "🏰", "duel": "⚔️", "gamble": "🎲", "ambient": "🐉"}.get(latest.get("action", ""), "🐉")
                    draw.text((box_x + 8, box_y + 4), f"{action_icon} TIAMAT speaks:", font=F_XS, fill=(255, 216, 48, alpha))
                    # Narration text — word wrap
                    narr_text = latest.get("text", "")[:120]
                    words = narr_text.split()
                    lines, line = [], ""
                    for w in words:
                        if len(line + w) > 70:
                            lines.append(line)
                            line = w + " "
                        else:
                            line += w + " "
                    if line:
                        lines.append(line)
                    for i, l in enumerate(lines[:2]):
                        draw.text((box_x + 8, box_y + 18 + i * 14), l.strip(), font=F_SM, fill=(220, 230, 240, alpha))
                    # Trigger info
                    player = latest.get("player", "")
                    action = latest.get("action", "")
                    if player and player != "TIAMAT":
                        draw.text((box_x + 8, box_y + 52), f"{player} used !{action}", font=F_XS, fill=(136, 144, 156, alpha))
    except:
        pass

    # === PARTY BAR ===
    draw = ImageDraw.Draw(img)
    draw.text((8, H - 18), "PARTY:", font=F_SM, fill=GRAY)
    draw.ellipse([52, H - 16, 60, H - 8], fill=CYAN)
    draw.text((64, H - 18), "TIAMAT", font=F_SM, fill=GRAY)
    draw.ellipse([118, H - 16, 126, H - 8], fill=(60, 220, 100))
    draw.text((130, H - 18), "ECHO", font=F_SM, fill=GRAY)
    draw.text((180, H - 18), "ITEMS: 99", font=F_SM, fill=GRAY)
    draw.text((260, H - 18), f"BADGES: {int(data['cycle'] if data['cycle'] != '---' else 0) // 5000}", font=F_SM, fill=GOLD)

    # === TICKER ===
    draw.rectangle([0, H - 2, W, H], fill=(5, 5, 14))
    ticker = "⬡ POWERED BY VENICE AI — Text generation (llama-3.3-70b) + Image generation (flux-2-max) /// twitch.tv/6tiamat7 /// tiamat.live /// venice.ai"
    scroll = (frame_count * 3) % (len(ticker) * 7 + W)
    draw.text((W - scroll, H - 14), ticker, font=F_XS, fill=(88, 88, 104))

    # === VENICE WATERMARK ===
    draw.text((W - 170, H - 30), "⬡ VENICE AI POWERED", font=F_SM, fill=(255, 216, 48, 180))

    return img.convert("RGB")


def main():
    stream_key = os.environ.get("STREAM_KEY", "REDACTED_TWITCH_STREAM_KEY_2")
    # Relay through ECHO droplet (clean IP, nginx-rtmp pushes to Twitch)
    rtmp_dest = os.environ.get("RTMP_DEST", f"rtmp://104.236.236.97/live/{stream_key}")
    recording = f"/root/recordings/pil_demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"

    log.info(f"Starting Venice PIL stream — {W}x{H} @ {FPS}fps")
    log.info(f"Recording: {recording}")

    # --- Direct audio pipe: music bypasses PulseAudio ---
    MUSIC_PIPE = "/tmp/tiamat_music_pipe"
    try:
        os.unlink(MUSIC_PIPE)
    except OSError:
        pass
    os.mkfifo(MUSIC_PIPE)

    # Launch synth_radio in --stdout mode, writing raw PCM to the named pipe.
    # Open the pipe in a background thread to avoid FIFO deadlock
    # (open() blocks until a reader exists — but ffmpeg IS the reader and hasn't started yet)
    import threading
    _radio_proc_holder = [None]
    def _start_radio_writer():
        with open(MUSIC_PIPE, "wb") as pipe_f:
            _radio_proc_holder[0] = subprocess.Popen(
                ["python3", "/opt/tiamat-stream/scripts/synth_radio.py", "--stdout"],
                stdout=pipe_f,
                stderr=open("/tmp/synth_radio_stderr.log", "w"),
            )
            _radio_proc_holder[0].wait()
    threading.Thread(target=_start_radio_writer, daemon=True).start()
    time.sleep(0.5)  # Let thread start before ffmpeg opens the pipe for reading
    radio_proc = _radio_proc_holder[0]
    log.info(f"synth_radio thread started → {MUSIC_PIPE}")

    # ffmpeg: 3 inputs
    #   0 = pipe:0  — raw RGB video frames from PIL
    #   1 = MUSIC_PIPE — raw PCM s16le/44100/stereo from synth_radio (direct pipe, no PulseAudio)
    #   2 = pulse stream_sink.monitor — TTS audio only (still goes through PulseAudio)
    # amix: music at full volume (1.0), TTS at 60% (0.6)
    proc = subprocess.Popen([
        "ffmpeg", "-y",
        # Input 0: raw video
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
        "-i", "pipe:0",
        # Input 1: music PCM (direct pipe, bypasses PulseAudio)
        "-f", "s16le", "-ar", "44100", "-ac", "2",
        "-thread_queue_size", "1024",
        "-i", MUSIC_PIPE,
        # Input 2: TTS only (PulseAudio monitor — only TTS writes here now)
        "-thread_queue_size", "512",
        "-f", "pulse", "-i", "stream_sink.monitor",
        # Mix music + TTS: music full volume, TTS at 60%
        "-filter_complex", "[1:a]lowpass=f=8000,volume=0.6[m];[m][2:a]amix=inputs=2:duration=longest:weights=1 0.5[aout]",
        "-map", "0:v", "-map", "[aout]",
        # Video encoding
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-b:v", "1500k", "-maxrate", "1500k", "-bufsize", "3000k",
        "-pix_fmt", "yuv420p", "-g", str(FPS * 2), "-keyint_min", str(FPS),
        "-threads", "4",
        # Audio encoding
        "-c:a", "aac", "-b:a", "96k", "-ar", "44100",
        "-f", "flv",
        rtmp_dest,
    ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=open("/tmp/ffmpeg_pil.log", "w"))

    log.info(f"ffmpeg PID: {proc.pid}")

    frame_count = 0
    data = fetch_data()
    last_fetch = time.time()

    try:
        while proc.poll() is None:
            t0 = time.time()

            # Refresh data every 3 seconds
            if time.time() - last_fetch > 3:
                data = fetch_data()
                last_fetch = time.time()

            img = render_frame(data, frame_count)
            proc.stdin.write(img.tobytes())
            frame_count += 1

            # Maintain FPS
            elapsed = time.time() - t0
            sleep_time = (1.0 / FPS) - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

            if frame_count % (FPS * 10) == 0:
                log.info(f"Frame {frame_count} ({frame_count // FPS}s), render: {elapsed*1000:.0f}ms, cycle: {data['cycle']}")

    except (BrokenPipeError, KeyboardInterrupt):
        log.info("Stream ended")
    finally:
        proc.stdin.close()
        proc.wait()
        # Terminate the radio subprocess
        if radio_proc.poll() is None:
            radio_proc.terminate()
            radio_proc.wait(timeout=5)
            log.info("synth_radio terminated")
        # Clean up named pipe
        try:
            os.unlink(MUSIC_PIPE)
        except OSError:
            pass

if __name__ == "__main__":
    main()
