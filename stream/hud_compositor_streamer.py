#!/usr/bin/env python3
"""
TIAMAT Stream — VTuber Streamer Layout
Dragon girl in bottom-left corner playing a Pokemon/RPG-style game.
The "game" visualizes TIAMAT's actual autonomous agent data.
"""

import os
import time
import math
import random
import logging
import requests
from pathlib import Path
from io import BytesIO
from datetime import datetime, timezone

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    os.system("pip3 install Pillow --break-system-packages -q")
    from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [HUD] %(message)s")
log = logging.getLogger("hud")

API_BASE = os.environ.get("TIAMAT_API", "https://tiamat.live")
OUTPUT_DIR = Path("/tmp/hud")
OUTPUT_DIR.mkdir(exist_ok=True)
OVERLAY_PATH = OUTPUT_DIR / "overlay.png"
TICKER_PATH = OUTPUT_DIR / "ticker.txt"
WIDTH, HEIGHT = 1920, 1080
UPDATE_INTERVAL = 3

# ========== COLORS ==========
# Game window — dark retro RPG
GAME_BG = (16, 16, 32)
GAME_BORDER = (248, 248, 248)
GAME_BORDER_INNER = (80, 80, 120)
# Text box — classic RPG dialogue
TEXTBOX_BG = (24, 24, 48)
TEXTBOX_BORDER = (248, 248, 248)
# HP/stat colors
HP_GREEN = (72, 208, 88)
HP_YELLOW = (248, 200, 48)
HP_RED = (248, 72, 56)
PP_PURPLE = (168, 120, 248)
EXP_CYAN = (64, 200, 248)
# UI
GOLD = (248, 208, 48)
WHITE = (248, 248, 248)
LIGHT_GRAY = (200, 200, 216)
MID_GRAY = (136, 136, 160)
DARK_GRAY = (72, 72, 96)
BLACK = (8, 8, 16)
CYAN = (64, 224, 248)
PINK = (248, 120, 168)
# Stream bg
STREAM_BG = (12, 10, 24)

# ========== FONTS ==========
def load_font(size, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]
    for fp in paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()

F_TITLE = load_font(20, True)
F_LG = load_font(16, True)
F_MD = load_font(14)
F_SM = load_font(12)
F_XS = load_font(11)
F_GAME = load_font(15, True)
F_GAME_SM = load_font(13)
F_TICKER = load_font(12, True)

# ========== DRAGON FRAME ==========
DRAGON_URL = f"{API_BASE}/dragon/frame.png"
dragon_cache = None
dragon_walk_frames = []
dragon_walk_idx = 0

def load_walk_cycle():
    """Load pre-rendered walk cycle frames at startup."""
    global dragon_walk_frames
    walk_dir = Path("/tmp/dragon/walk_cycle") if Path("/tmp/dragon/walk_cycle").exists() else None
    # Try fetching from main server if not local
    if walk_dir is None or not any(walk_dir.glob("*.png")):
        return
    for png in sorted(walk_dir.glob("frame_*.png")):
        try:
            dragon_walk_frames.append(Image.open(png).convert("RGBA"))
        except:
            pass

def fetch_dragon():
    global dragon_cache, dragon_walk_idx
    # Use pre-rendered walk cycle — advance 4 frames per tick for visible motion
    if dragon_walk_frames:
        dragon_cache = dragon_walk_frames[dragon_walk_idx % len(dragon_walk_frames)]
        dragon_walk_idx += 3  # Skip frames for visible walk cycle
        return
    # Fallback to live renderer
    try:
        r = requests.get(DRAGON_URL, timeout=3)
        if r.ok and len(r.content) > 1000:
            dragon_cache = Image.open(BytesIO(r.content)).convert("RGBA")
    except:
        pass


# Game Boy frame
GAMEBOY_URL = f"{API_BASE}/dragon/gameboy.png"
gameboy_cache = None

def fetch_gameboy():
    global gameboy_cache
    try:
        r = requests.get(GAMEBOY_URL, timeout=2)
        if r.ok and len(r.content) > 1000:
            gameboy_cache = Image.open(BytesIO(r.content)).convert("RGBA")
    except:
        pass


# ========== GAME UI DRAWING ==========

def draw_pixel_border(draw, x, y, w, h, color=GAME_BORDER, thickness=3):
    """Draw a retro pixel-art double border."""
    # Outer
    draw.rectangle([x, y, x+w, y+h], outline=color)
    # Inner
    draw.rectangle([x+thickness, y+thickness, x+w-thickness, y+h-thickness], outline=GAME_BORDER_INNER)


def draw_hp_bar(draw, x, y, w, h, ratio, label="HP"):
    """Pokemon-style HP bar."""
    # Label
    draw.text((x - 30, y - 1), label, font=F_GAME_SM, fill=GOLD)
    # Bar background
    draw.rectangle([x, y, x+w, y+h], fill=(40, 40, 56))
    draw.rectangle([x, y, x+w, y+h], outline=DARK_GRAY)
    # Fill
    fill_w = int(w * max(0, min(ratio, 1.0)))
    if ratio > 0.5:
        color = HP_GREEN
    elif ratio > 0.2:
        color = HP_YELLOW
    else:
        color = HP_RED
    if fill_w > 0:
        draw.rectangle([x+1, y+1, x+fill_w-1, y+h-1], fill=color)


def tool_to_move(tool_name):
    """Convert TIAMAT tool names to Pokemon-style move names."""
    moves = {
        "exec": ("SHELL STRIKE", "NORMAL"),
        "read_file": ("KNOWLEDGE SCAN", "PSYCHIC"),
        "write_file": ("CODE FORGE", "STEEL"),
        "search_web": ("WEB SURF", "WATER"),
        "post_bluesky": ("SOCIAL BLAST", "FAIRY"),
        "post_devto": ("PUBLISH BEAM", "FIRE"),
        "browse": ("DEEP DIVE", "WATER"),
        "memory_store": ("MEMORY CRYSTAL", "PSYCHIC"),
        "memory_recall": ("ANCIENT RECALL", "PSYCHIC"),
        "send_email": ("SIGNAL FLARE", "FIRE"),
        "ticket_create": ("TASK SPAWN", "NORMAL"),
        "sandbox_exec": ("SHADOW EXEC", "DARK"),
    }
    for key, val in moves.items():
        if key in tool_name.lower():
            return val
    return ("UNKNOWN MOVE", "NORMAL")


TYPE_COLORS = {
    "NORMAL": (200, 200, 200), "FIRE": (248, 120, 48), "WATER": (64, 160, 248),
    "PSYCHIC": (248, 88, 168), "STEEL": (184, 184, 208), "FAIRY": (238, 153, 172),
    "DARK": (112, 88, 72), "ELECTRIC": (248, 208, 48), "GHOST": (112, 88, 152),
}


# Battle state — persists across frames for animations
battle_state = {
    "last_tool": "", "last_move": "", "last_type": "NORMAL",
    "damage_timer": 0, "combo": 0, "total_xp": 0,
    "battle_msgs": [], "msg_timer": 0,
}


def update_battle_state(data, dt=5.0):
    """Update battle state from TIAMAT's activity."""
    global battle_state
    bs = battle_state

    bs["damage_timer"] = max(0, bs["damage_timer"] - dt)
    bs["msg_timer"] = max(0, bs["msg_timer"] - dt)

    # Check activity for new tool calls
    for a in data.get("activity", [])[:3]:
        content = a.get("content", "")
        # Detect tool usage patterns
        for tool in ["exec", "write_file", "read_file", "search_web", "post_bluesky",
                      "post_devto", "browse", "memory_store", "send_email"]:
            if tool in content.lower() and tool != bs["last_tool"]:
                move_name, move_type = tool_to_move(tool)
                bs["last_tool"] = tool
                bs["last_move"] = move_name
                bs["last_type"] = move_type
                bs["damage_timer"] = 10.0
                bs["combo"] += 1

                # Generate battle message
                effectiveness = random.choice([
                    "It's super effective!",
                    "A critical hit!",
                    "The attack landed!",
                    "It had no effect...",
                    "It's not very effective...",
                ])
                if bs["combo"] > 3:
                    effectiveness = f"{bs['combo']}x COMBO!"

                bs["battle_msgs"] = [
                    f"TIAMAT used {move_name}!",
                    effectiveness,
                ]
                bs["msg_timer"] = 12.0
                break

    # Reset combo if idle
    if data.get("pace", "").upper() == "IDLE":
        bs["combo"] = 0


def draw_game_window(img, data, frame_count):
    """Draw the main 'game' window — enhanced Pokemon battle style."""
    gx, gy = 580, 50
    gw, gh = WIDTH - gx - 20, int((HEIGHT - 90) * 0.7)

    game = Image.new("RGBA", (gw, gh), GAME_BG + (255,))
    gd = ImageDraw.Draw(game)

    update_battle_state(data)
    bs = battle_state
    pace = data.get("pace", "IDLE").upper()

    # === TOP: ENEMY + PLAYER INFO BARS ===

    # Enemy — what TIAMAT is fighting
    enemy_map = {
        "ACTIVE": ("WILD CODEBASE", "STEEL"),
        "REFLECT": ("WILD RESEARCH", "PSYCHIC"),
        "BUILD": ("WILD FEATURE", "FIRE"),
        "IDLE": ("WILD IDLE", "NORMAL"),
        "BURST": ("BOSS CHALLENGE", "DARK"),
    }
    enemy_name, enemy_type = enemy_map.get(pace, (f"WILD {pace}", "NORMAL"))

    # Enemy info box
    gd.rectangle([20, 15, 420, 95], fill=(24, 24, 48, 230), outline=GAME_BORDER)
    gd.rectangle([23, 18, 417, 92], outline=GAME_BORDER_INNER)
    gd.text((32, 22), enemy_name, font=F_GAME, fill=WHITE)
    # Type badge
    tc = TYPE_COLORS.get(enemy_type, (200, 200, 200))
    gd.rectangle([330, 22, 410, 38], fill=tc)
    gd.text((335, 23), enemy_type, font=F_XS, fill=BLACK)
    # Enemy level
    cycle_str = str(data.get("cycle", "0"))
    gd.text((32, 42), f"Lv {cycle_str}", font=F_GAME_SM, fill=LIGHT_GRAY)
    # Enemy HP
    draw_hp_bar(gd, 100, 55, 260, 16, data.get("productivity", 0), "HP")
    prod_pct = int(data.get("productivity", 0) * 100)
    gd.text((370, 53), f"{prod_pct}%", font=F_GAME_SM, fill=LIGHT_GRAY)

    # Player info box (TIAMAT)
    px = gw - 430
    gd.rectangle([px, 110, px + 420, 210], fill=(24, 24, 48, 230), outline=GAME_BORDER)
    gd.rectangle([px+3, 113, px+417, 207], outline=GAME_BORDER_INNER)
    gd.text((px + 12, 116), "TIAMAT", font=F_GAME, fill=CYAN)
    # Type badge
    gd.rectangle([px + 100, 117, px + 180, 133], fill=EXP_CYAN)
    gd.text((px + 105, 118), "DRAGON", font=F_XS, fill=BLACK)
    gd.text((px + 310, 116), f"Lv {cycle_str}", font=F_GAME_SM, fill=LIGHT_GRAY)

    # HP bar (budget remaining)
    cost = data.get("total_cost", 0) if isinstance(data.get("total_cost"), (int, float)) else 0
    hp_ratio = max(0, 1.0 - cost / 500)
    draw_hp_bar(gd, px + 60, 140, 280, 16, hp_ratio, "HP")
    gd.text((px + 350, 138), f"${max(0, 500 - int(cost))}/{500}", font=F_XS, fill=LIGHT_GRAY)

    # PP bar (memory)
    mem = data.get("memory_total", 0)
    pp_ratio = min(mem / 15000, 1.0)
    gd.rectangle([px + 60, 162, px + 340, 176], fill=(40, 40, 56), outline=DARK_GRAY)
    pp_fill = int(280 * pp_ratio)
    if pp_fill > 0:
        gd.rectangle([px + 61, 163, px + 60 + pp_fill, 175], fill=PP_PURPLE)
    gd.text((px + 28, 161), "PP", font=F_GAME_SM, fill=PP_PURPLE)
    gd.text((px + 350, 160), f"{mem:,}", font=F_XS, fill=LIGHT_GRAY)

    # EXP bar
    tools = data.get("tool_actions", 0) if isinstance(data.get("tool_actions"), int) else 0
    exp_ratio = (tools % 1000) / 1000
    gd.rectangle([px + 12, 188, px + 408, 198], fill=(40, 40, 56))
    exp_fill = int(396 * exp_ratio)
    if exp_fill > 0:
        gd.rectangle([px + 13, 189, px + 12 + exp_fill, 197], fill=EXP_CYAN)
    gd.text((px + 60, 186), f"EXP", font=F_XS, fill=EXP_CYAN)
    gd.text((px + 300, 186), f"{tools:,} / {((tools // 1000) + 1) * 1000:,}", font=F_XS, fill=MID_GRAY)

    # === MIDDLE: BATTLE SCENE ===
    scene_y = 220
    scene_h = gh - scene_y - 210

    # Background gradient (sky-like for battles)
    for sy in range(scene_y, scene_y + scene_h):
        ratio = (sy - scene_y) / scene_h
        r = int(16 + ratio * 8)
        g = int(16 + ratio * 12)
        b = int(32 + ratio * 16)
        gd.line([(10, sy), (gw - 10, sy)], fill=(r, g, b))

    # Ground line
    ground_y = scene_y + int(scene_h * 0.7)
    gd.line([(10, ground_y), (gw - 10, ground_y)], fill=(40, 50, 70), width=2)
    # Ground fill
    for gy2 in range(ground_y, scene_y + scene_h):
        gd.line([(10, gy2), (gw - 10, gy2)], fill=(20 + (gy2 - ground_y), 24 + (gy2 - ground_y), 36))

    # Stars in sky
    random.seed(42)
    for _ in range(40):
        sx = random.randint(20, gw - 20)
        sy = random.randint(scene_y + 5, ground_y - 10)
        twinkle = (frame_count + sx) % 6 < 3
        if twinkle:
            bright = random.randint(60, 140)
            gd.rectangle([sx, sy, sx+1, sy+1], fill=(bright, bright, bright + 40))

    # Weather effects
    weather = {"ACTIVE": "☀", "REFLECT": "🌧", "IDLE": "☁", "BUILD": "⚡", "BURST": "🌩"}.get(pace, "")
    gd.text((gw - 60, scene_y + 8), weather, font=F_LG, fill=GOLD)
    pace_label = {"ACTIVE": "SUNNY", "REFLECT": "RAIN", "IDLE": "CALM", "BUILD": "ELECTRIC", "BURST": "STORM"}.get(pace, "")
    gd.text((gw - 100, scene_y + 30), pace_label, font=F_XS, fill=MID_GRAY)

    # Game Boy screen (if running) — large, centered in battle area
    fetch_gameboy()
    if gameboy_cache is not None:
        gb = gameboy_cache
        # Scale up to fill the battle area better
        gb_scale = min((gw - 40) / gb.width, (scene_h - 20) / gb.height, 1.5)
        gb_w = int(gb.width * gb_scale)
        gb_h = int(gb.height * gb_scale)
        gb_scaled = gb.resize((gb_w, gb_h), Image.Resampling.NEAREST)
        # Center
        gb_x = (gw - gb_w) // 2
        gb_y = scene_y + (scene_h - gb_h) // 2
        # CRT-style border
        gd.rectangle([gb_x - 6, gb_y - 6, gb_x + gb_w + 6, gb_y + gb_h + 6],
                     fill=(5, 15, 5), outline=(60, 140, 60))
        gd.rectangle([gb_x - 3, gb_y - 3, gb_x + gb_w + 3, gb_y + gb_h + 3],
                     outline=(40, 100, 40))
        game.paste(gb_scaled, (gb_x, gb_y))
        gd.text((gb_x + gb_w // 2 - 30, gb_y + gb_h + 8), "GAME BOY", font=F_XS, fill=(60, 140, 60))
    else:
        # Fallback: show model name if no Game Boy running
        model = data.get("model", "???")[:28]
        model_tw = gd.textlength(model, font=F_GAME_SM)
        gd.text(((gw - model_tw) // 2, scene_y + scene_h // 2 - 30), model, font=F_GAME_SM, fill=CYAN)

    uptime = data.get("uptime", 0)
    up_str = f"{uptime:.0f}h" if isinstance(uptime, (int, float)) else str(uptime)
    gd.text(((gw - 100) // 2, scene_y + scene_h // 2 - 8), f"⏱ UPTIME: {up_str}", font=F_XS, fill=MID_GRAY)

    # Battle effect — flash when attack happens
    if bs["damage_timer"] > 8:
        # Attack flash overlay
        flash = Image.new("RGBA", (gw, scene_h), TYPE_COLORS.get(bs["last_type"], (200,200,200)) + (40,))
        game.paste(Image.alpha_composite(
            Image.new("RGBA", flash.size, (0,0,0,0)), flash
        ), (0, scene_y), flash)

    # Damage number floating
    if 3 < bs["damage_timer"] < 8:
        dmg_text = f"-{random.randint(10, 99)}"
        dmg_x = gw // 2 + random.randint(-50, 50)
        dmg_y = scene_y + scene_h // 2 + int((8 - bs["damage_timer"]) * 8)
        gd.text((dmg_x, dmg_y), dmg_text, font=F_TITLE, fill=HP_RED)

    # Combo counter
    if bs["combo"] > 1:
        gd.text((gw - 140, ground_y - 30), f"COMBO x{bs['combo']}", font=F_LG, fill=GOLD)

    # === PARTY BAR (bottom of battle scene) ===
    party_y = ground_y + 15
    gd.text((15, party_y), "PARTY:", font=F_XS, fill=MID_GRAY)
    # TIAMAT
    gd.ellipse([70, party_y, 86, party_y + 16], fill=CYAN, outline=WHITE)
    gd.text((92, party_y), "TIAMAT", font=F_XS, fill=CYAN)
    # ECHO
    gd.ellipse([170, party_y, 186, party_y + 16], fill=HP_GREEN, outline=WHITE)
    gd.text((192, party_y), "ECHO", font=F_XS, fill=HP_GREEN)
    # Items count
    gd.text((gw - 200, party_y), f"ITEMS: {min(tools, 99)}", font=F_XS, fill=MID_GRAY)
    gd.text((gw - 100, party_y), f"BADGES: {int(cycle_str) // 5000}", font=F_XS, fill=GOLD)

    # === BOTTOM: DIALOGUE + ACTION MENU ===
    menu_y = gh - 200

    # Dialogue box (left ~70%)
    dlg_w = gw - 290
    gd.rectangle([10, menu_y, dlg_w, gh - 10], fill=TEXTBOX_BG, outline=TEXTBOX_BORDER)
    gd.rectangle([13, menu_y+3, dlg_w-3, gh-13], outline=GAME_BORDER_INNER)

    # Battle messages take priority, then thoughts
    ty = menu_y + 14
    if bs["msg_timer"] > 0 and bs["battle_msgs"]:
        for msg in bs["battle_msgs"]:
            color = GOLD if "super effective" in msg or "COMBO" in msg or "critical" in msg else WHITE
            gd.text((24, ty), msg, font=F_GAME, fill=color)
            ty += 24
        # Move type indicator
        tc = TYPE_COLORS.get(bs["last_type"], (200,200,200))
        gd.rectangle([24, ty + 4, 24 + 80, ty + 20], fill=tc)
        gd.text((28, ty + 5), bs["last_type"], font=F_XS, fill=BLACK)
    else:
        # Show thoughts as battle narration
        for t in data.get("thoughts", [])[:6]:
            if ty > gh - 30:
                break
            content = t.get("content", "")[:72]
            if content:
                gd.text((24, ty), content, font=F_GAME_SM, fill=WHITE)
                ty += 18

    # Blinking cursor
    if int(time.time() * 2) % 2:
        gd.text((dlg_w - 25, gh - 35), "▼", font=F_MD, fill=WHITE)

    # Action menu (right ~30%)
    ax = dlg_w + 15
    gd.rectangle([ax, menu_y, gw - 10, gh - 10], fill=TEXTBOX_BG, outline=TEXTBOX_BORDER)
    gd.rectangle([ax+3, menu_y+3, gw-13, gh-13], outline=GAME_BORDER_INNER)

    actions = [
        ("RESEARCH", "PSYCHIC"),
        ("BUILD", "FIRE"),
        ("PUBLISH", "FAIRY"),
        ("ENGAGE", "WATER"),
    ]
    current_action = {"ACTIVE": 0, "REFLECT": 0, "BUILD": 1, "BURST": 1, "IDLE": 3}.get(pace, 0)
    for i, (action, atype) in enumerate(actions):
        ay = menu_y + 16 + i * 42
        if i == current_action:
            # Highlight box
            gd.rectangle([ax + 8, ay - 2, gw - 18, ay + 30], fill=(40, 40, 70), outline=GOLD)
            gd.text((ax + 16, ay + 2), f"▶ {action}", font=F_GAME, fill=GOLD)
            # Type dot
            tc = TYPE_COLORS.get(atype, (200,200,200))
            gd.ellipse([gw - 40, ay + 6, gw - 24, ay + 22], fill=tc)
        else:
            gd.text((ax + 26, ay + 2), action, font=F_GAME, fill=MID_GRAY)

    # Paste game window
    img.paste(game, (gx, gy), game)

    # Game border
    main_draw = ImageDraw.Draw(img)
    draw_pixel_border(main_draw, gx - 4, gy - 4, gw + 8, gh + 8)

    return img


def draw_vtuber_cam(img, frame_count):
    """Draw dragon girl — animated idle/walk with wandering movement."""
    fetch_dragon()
    if dragon_cache is None:
        return img

    sprite = dragon_cache

    # Scale large
    target_w = 600
    scale = target_w / sprite.width
    target_h = int(sprite.height * scale)
    scaled = sprite.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # Wandering movement — she walks around the left side of the screen
    t = frame_count * 0.15  # Slow movement
    wander_x = int(math.sin(t * 0.3) * 80 + math.sin(t * 0.7) * 30)  # Side to side
    wander_y = int(math.sin(t * 0.2) * 40 + math.cos(t * 0.5) * 20)  # Up and down
    bounce = int(abs(math.sin(t * 1.5)) * 12)  # Walking bounce

    base_x = 30
    base_y = HEIGHT - target_h - 60
    dx = base_x + wander_x
    dy = base_y + wander_y - bounce

    img.paste(scaled, (dx, dy), scaled)

    # Name tag follows her
    draw = ImageDraw.Draw(img)
    tag_w, tag_h = 140, 24
    tag_x = dx + target_w // 2 - tag_w // 2
    tag_y = dy - 2
    draw.rectangle([tag_x, tag_y, tag_x + tag_w, tag_y + tag_h], fill=BLACK, outline=CYAN)
    draw.text((tag_x + 20, tag_y + 4), "TIAMAT", font=F_LG, fill=CYAN)

    return img


def fetch_data():
    data = {
        "cycle": "---", "model": "---", "productivity": 0, "pace": "---",
        "total_cost": 0, "uptime": 0, "memory_total": 0, "tool_actions": 0,
        "agent_status": "offline", "thoughts": [], "activity": [],
    }
    try:
        r = requests.get(f"{API_BASE}/api/dashboard", timeout=5)
        if r.ok:
            d = r.json()
            data["cycle"] = str(d.get("cycles", "---"))
            data["model"] = d.get("last_model", "---").split("/")[-1][:30]
            data["total_cost"] = d.get("total_cost", 0)
            data["uptime"] = d.get("uptime_hours", 0)
            data["memory_total"] = d.get("memory_l1", 0) + d.get("memory_l2", 0) + d.get("memory_l3", 0)
            data["tool_actions"] = d.get("tool_actions", 0)
            data["agent_status"] = d.get("agent", "offline")
    except:
        pass
    try:
        r = requests.get(f"{API_BASE}/api/thoughts", timeout=5)
        if r.ok:
            d = r.json()
            data["thoughts"] = d.get("thoughts", [])[:8]
            data["activity"] = d.get("activity", [])[:8]
            pacer = d.get("pacer", {})
            data["productivity"] = pacer.get("productivity", 0)
            data["pace"] = pacer.get("pace", "---").upper()
    except:
        pass
    return data


room_bg_cache = None

def load_room_bg():
    """Load room background from local file at startup."""
    global room_bg_cache
    local = Path("/opt/tiamat-stream/assets/room_bg.png")
    if local.exists():
        try:
            room_bg_cache = Image.open(local).convert("RGBA")
            log.info(f"Room background loaded: {room_bg_cache.size}")
        except Exception as e:
            log.error(f"Failed to load room bg: {e}")


def render_overlay(data, frame_count):
    # Background: use pre-brightened room or dark fallback
    if room_bg_cache and room_bg_cache.size == (WIDTH, HEIGHT):
        img = room_bg_cache.copy()
    else:
        img = Image.new("RGBA", (WIDTH, HEIGHT), STREAM_BG + (255,))
    draw = ImageDraw.Draw(img)

    # Subtle scanlines
    for sy in range(0, HEIGHT, 3):
        draw.line([(0, sy), (WIDTH, sy)], fill=(16, 14, 28, 60), width=1)

    # Stream title bar
    draw.rectangle([0, 0, WIDTH, 28], fill=(8, 8, 20))
    draw.line([(0, 28), (WIDTH, 28)], fill=CYAN, width=1)
    status_color = HP_GREEN if data["agent_status"] == "online" else HP_RED
    draw.ellipse([10, 8, 20, 18], fill=status_color)
    draw.text((28, 5), f"TIAMAT AUTONOMOUS AGENT  //  CYCLE {data['cycle']}  //  tiamat.live", font=F_TICKER, fill=MID_GRAY)
    clock = datetime.now(timezone.utc).strftime("%H:%M UTC")
    draw.text((WIDTH - 90, 5), clock, font=F_TICKER, fill=MID_GRAY)

    # Left panel — character info + recent moves (fills empty space)
    lp_x, lp_y = 10, 35
    lp_w, lp_h = 360, 340
    lp = Image.new("RGBA", (lp_w, lp_h), (12, 14, 30, 200))
    ld = ImageDraw.Draw(lp)
    ld.rectangle([0, 0, lp_w-1, lp_h-1], outline=DARK_GRAY)
    ld.rectangle([2, 2, lp_w-3, lp_h-3], outline=(30, 35, 55))
    # Title
    ld.text((10, 6), "TRAINER CARD", font=F_LG, fill=GOLD)
    ld.line([(8, 26), (lp_w - 8, 26)], fill=DARK_GRAY)
    # Stats
    ld.text((10, 34), "NAME:  TIAMAT", font=F_GAME_SM, fill=CYAN)
    ld.text((10, 54), "TYPE:  DRAGON / CYBER", font=F_GAME_SM, fill=WHITE)
    cycle_str = str(data.get("cycle", "0"))
    ld.text((10, 74), f"LEVEL: {cycle_str}", font=F_GAME_SM, fill=WHITE)
    uptime = data.get("uptime", 0)
    up_str = f"{uptime:.0f}h" if isinstance(uptime, (int, float)) else str(uptime)
    ld.text((10, 94), f"TIME:  {up_str}", font=F_GAME_SM, fill=WHITE)
    model = data.get("model", "???")[:25]
    ld.text((10, 114), f"BRAIN: {model}", font=F_XS, fill=CYAN)

    # Recent moves log
    ld.line([(8, 140), (lp_w - 8, 140)], fill=DARK_GRAY)
    ld.text((10, 146), "RECENT MOVES", font=F_LG, fill=GOLD)
    my = 168
    bs = battle_state
    for a in data.get("activity", [])[:8]:
        if my > lp_h - 16:
            break
        content = a.get("content", "")[:38]
        # Color by content type
        if "COST" in content:
            c = GOLD
        elif "error" in content.lower():
            c = HP_RED
        elif "Calling" in content:
            c = MID_GRAY
        else:
            c = LIGHT_GRAY
        ld.text((10, my), f"▸ {content}", font=F_XS, fill=c)
        my += 18

    img.paste(lp, (lp_x, lp_y), lp)

    # Game window (main content)
    img = draw_game_window(img, data, frame_count)

    # VTuber cam (dragon girl overlay)
    img = draw_vtuber_cam(img, frame_count)

    # Bottom ticker
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, HEIGHT - 22, WIDTH, HEIGHT], fill=(5, 5, 14))
    draw.line([(0, HEIGHT - 22), (WIDTH, HEIGHT - 22)], fill=DARK_GRAY, width=1)
    parts = ["twitch.tv/6tiamat7", "tiamat.live", "EnergenAI LLC", f"LV.{data['cycle']}",
             f"PROD {int(data['productivity']*100)}%"]
    ticker = "    ///    ".join(parts)
    scroll = (frame_count * 2) % (len(ticker) * 8 + WIDTH)
    draw.text((WIDTH - scroll, HEIGHT - 18), ticker, font=F_XS, fill=DARK_GRAY)
    draw.text((WIDTH - scroll + len(ticker) * 7 + 80, HEIGHT - 18), ticker, font=F_XS, fill=DARK_GRAY)

    return img


def main():
    log.info(f"STREAMER HUD started — {WIDTH}x{HEIGHT}")
    load_room_bg()
    load_walk_cycle()
    log.info(f"Walk cycle: {len(dragon_walk_frames)} frames loaded")
    frame_count = 0
    while True:
        try:
            t0 = time.time()
            data = fetch_data()
            img = render_overlay(data, frame_count)
            # Write both overlay.png (for compatibility) and numbered sequence for ffmpeg
            tmp = OUTPUT_DIR / "overlay_tmp.png"
            img.save(tmp, "PNG")
            tmp.rename(OVERLAY_PATH)
            # Numbered frame for ffmpeg sequence input (keep last 60 frames)
            seq_path = OUTPUT_DIR / f"seq_{frame_count % 60:04d}.png"
            img.save(seq_path, "PNG")
            TICKER_PATH.write_text("TIAMAT  ///  tiamat.live")
            elapsed = time.time() - t0
            if frame_count % 12 == 0:
                log.info(f"Frame {frame_count}: {elapsed*1000:.0f}ms, cycle={data['cycle']}")
            frame_count += 1
        except Exception as e:
            log.error(f"Render error: {e}")
        time.sleep(UPDATE_INTERVAL)

if __name__ == "__main__":
    main()
