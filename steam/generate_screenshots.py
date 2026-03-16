#!/usr/bin/env python3
"""
LABYRINTH: TIAMAT'S DESCENT — Steam Screenshot Generator

Renders 5 showcase screenshots at 1920x1080 using PIL.
Each screenshot represents a different biome with dungeon layout,
HUD elements, combat text, and atmospheric effects.

Usage: python3 generate_screenshots.py
Output: /root/entity/steam/screenshots/screenshot_*.png
"""

import os
import math
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1920, 1080
OUT_DIR = Path("/root/entity/steam/screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Fonts
def font(size, bold=False):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    try:
        return ImageFont.truetype(p, size)
    except Exception:
        return ImageFont.load_default()

F_TITLE = font(28, True)
F_HUD = font(18, True)
F_HUD_SM = font(14)
F_HUD_XS = font(12)
F_SPLAT = font(24, True)
F_SPLAT_LG = font(36, True)
F_LOG = font(13)

# Biome definitions
BIOMES = {
    "dragonia": {
        "name": "DRAGONIA",
        "bg": (42, 26, 14),
        "wall": (138, 90, 46),
        "wall_dark": (90, 58, 26),
        "floor": (52, 36, 18),
        "floor_alt": (44, 28, 12),
        "wire": (255, 170, 68),
        "fog": (255, 170, 68, 15),
    },
    "blood_pit": {
        "name": "BLOOD PIT",
        "bg": (32, 8, 8),
        "wall": (106, 20, 32),
        "wall_dark": (68, 10, 20),
        "floor": (28, 6, 6),
        "floor_alt": (22, 4, 4),
        "wire": (255, 32, 64),
        "fog": (255, 32, 64, 15),
    },
    "cyber_forge": {
        "name": "CYBER FORGE",
        "bg": (10, 18, 24),
        "wall": (26, 48, 80),
        "wall_dark": (16, 32, 64),
        "floor": (12, 16, 22),
        "floor_alt": (8, 12, 18),
        "wire": (0, 204, 255),
        "fog": (0, 204, 255, 15),
    },
    "crystal_vault": {
        "name": "CRYSTAL VAULT",
        "bg": (12, 12, 26),
        "wall": (34, 34, 80),
        "wall_dark": (22, 22, 58),
        "floor": (14, 14, 28),
        "floor_alt": (10, 10, 24),
        "wire": (102, 136, 255),
        "fog": (102, 136, 255, 15),
    },
    "void_nexus": {
        "name": "VOID NEXUS",
        "bg": (24, 8, 30),
        "wall": (68, 30, 106),
        "wall_dark": (46, 16, 72),
        "floor": (18, 8, 24),
        "floor_alt": (14, 6, 18),
        "wire": (204, 102, 255),
        "fog": (204, 102, 255, 15),
    },
}


def draw_panel(img, x, y, w, h, border_color, alpha=190):
    """Draw a semi-transparent HUD panel."""
    panel = Image.new("RGBA", (w, h), (8, 10, 20, alpha))
    d = ImageDraw.Draw(panel)
    d.rectangle([0, 0, w - 1, h - 1], outline=border_color + (80,))
    img.paste(panel, (x, y), panel)


def draw_hp_bar(draw, x, y, w, h, pct, color, label="HP"):
    """Draw an HP/XP bar."""
    draw.text((x - 30, y - 2), label, font=F_HUD_XS, fill=(136, 144, 156))
    draw.rectangle([x, y, x + w, y + h], fill=(24, 24, 40), outline=(56, 56, 88))
    fill_w = int(w * max(0, min(1, pct)))
    if fill_w > 0:
        draw.rectangle([x + 1, y + 1, x + fill_w, y + h - 1], fill=color)


def draw_dungeon_view(img, biome, depth, **kwargs):
    """Draw a fake first-person dungeon view with perspective walls."""
    draw = ImageDraw.Draw(img)
    b = BIOMES[biome]

    # Fill background
    draw.rectangle([0, 0, W, H], fill=b["bg"])

    # Draw perspective corridor
    cx, cy = W // 2, H // 2
    vanish_x, vanish_y = cx, cy - 40

    # Floor gradient
    for y in range(cy, H):
        t = (y - cy) / (H - cy)
        floor_c = tuple(int(b["floor"][i] + (b["floor_alt"][i] - b["floor"][i]) * t) for i in range(3))
        draw.line([(0, y), (W, y)], fill=floor_c)

    # Ceiling gradient
    for y in range(0, cy):
        t = y / cy
        ceil_c = tuple(int(b["wall_dark"][i] * t * 0.5) for i in range(3))
        draw.line([(0, y), (W, y)], fill=ceil_c)

    # Walls — perspective trapezoids
    # Left wall
    wall_pts_l = [
        (0, 0), (0, H),
        (W // 4, cy + 200), (W // 4, cy - 200)
    ]
    draw.polygon(wall_pts_l, fill=b["wall_dark"])

    # Right wall
    wall_pts_r = [
        (W, 0), (W, H),
        (W * 3 // 4, cy + 200), (W * 3 // 4, cy - 200)
    ]
    draw.polygon(wall_pts_r, fill=b["wall_dark"])

    # Far wall with door opening
    far_t = cy - 160
    far_b = cy + 160
    far_l = cx - 200
    far_r = cx + 200
    draw.rectangle([far_l, far_t, far_r, far_b], fill=b["wall"])
    # Door opening in far wall
    draw.rectangle([cx - 60, far_t + 30, cx + 60, far_b], fill=b["bg"])

    # Torch lights (glowing orbs on walls)
    for tx, ty in [(W // 4 + 30, cy - 100), (W * 3 // 4 - 30, cy - 100),
                   (W // 4 + 80, cy - 50), (W * 3 // 4 - 80, cy - 50)]:
        glow = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse([0, 0, 59, 59], fill=b["wire"] + (60,))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=15))
        img.paste(glow, (tx - 30, ty - 30), glow)
        draw.ellipse([tx - 4, ty - 4, tx + 4, ty + 4], fill=b["wire"])

    # Emissive trim at wall base
    trim_color = b["wire"] + (40,)
    trim_overlay = Image.new("RGBA", (W, 6), trim_color)
    img.paste(trim_overlay, (0, cy + 198), trim_overlay)

    # Floor tile grid lines
    for i in range(10):
        t = i / 10
        fy = cy + int(t * (H - cy))
        spread = int(W * 0.5 * (1 - t * 0.6))
        draw.line([(cx - spread, fy), (cx + spread, fy)], fill=b["wall_dark"], width=1)

    # Fog particles
    fog_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fog_layer)
    for _ in range(80):
        fx = random.randint(100, W - 100)
        fy = random.randint(cy - 100, H - 50)
        fs = random.randint(20, 80)
        fa = random.randint(5, 25)
        fd.ellipse([fx, fy, fx + fs, fy + fs // 2], fill=b["wire"][:3] + (fa,))
    fog_layer = fog_layer.filter(ImageFilter.GaussianBlur(radius=12))
    img = Image.alpha_composite(img, fog_layer)

    # Scanlines
    scan = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scan)
    for sy in range(0, H, 3):
        sd.line([(0, sy), (W, sy)], fill=(0, 0, 0, 12), width=1)
    img = Image.alpha_composite(img, scan)

    return img


def draw_hud(img, biome, depth, hp_pct=0.75, xp_pct=0.4, gold=127,
             kills=23, lvl=7, log_entries=None, extract_pct=0,
             echo_alive=True, streak=0, splats=None):
    """Draw the full game HUD overlay."""
    b = BIOMES[biome]
    wire = b["wire"]
    draw = ImageDraw.Draw(img)

    # Top-left: Player stats panel
    draw_panel(img, 20, 20, 320, 140, wire)
    draw = ImageDraw.Draw(img)
    draw.text((32, 26), "TIAMAT", font=F_HUD, fill=(0, 255, 65))
    draw.text((140, 28), f"LVL {lvl}", font=F_HUD_SM, fill=(136, 144, 156))
    draw.text((220, 28), f"K:{kills}", font=F_HUD_XS, fill=(136, 144, 156))
    draw_hp_bar(draw, 60, 56, 260, 12, hp_pct,
                (0, 255, 65) if hp_pct > 0.5 else (255, 170, 0) if hp_pct > 0.25 else (255, 32, 64))
    draw.text((325, 52), f"{int(hp_pct * 100)}%", font=F_HUD_XS, fill=(200, 200, 200))
    draw_hp_bar(draw, 60, 80, 260, 10, xp_pct, (0, 255, 255), "XP")
    draw.text((325, 76), f"{int(xp_pct * 100)}%", font=F_HUD_XS, fill=(200, 200, 200))
    # Gold
    draw.text((32, 110), f"GOLD: {gold}", font=F_HUD_SM, fill=(255, 221, 0))
    draw.text((160, 110), f"STASH: 7 items", font=F_HUD_XS, fill=(136, 144, 156))

    # Top-center: Biome + Depth
    draw_panel(img, W // 2 - 160, 20, 320, 70, wire)
    draw = ImageDraw.Draw(img)
    draw.text((W // 2, 30), b["name"], font=F_HUD, fill=wire, anchor="mt")
    draw.text((W // 2, 56), f"DEPTH {depth}", font=F_HUD_SM, fill=(136, 144, 156), anchor="mt")

    # Top-right: Cycle + Streak
    draw_panel(img, W - 240, 20, 220, 70, wire)
    draw = ImageDraw.Draw(img)
    draw.text((W - 228, 28), f"CYCLE 24,280", font=F_HUD_SM, fill=(136, 144, 156))
    if streak >= 3:
        draw.text((W - 228, 50), f"{streak}x STREAK", font=F_HUD_SM, fill=(255, 255, 0))

    # Minimap (top-right)
    draw_panel(img, W - 200, 100, 180, 120, wire, alpha=200)
    draw = ImageDraw.Draw(img)
    # Draw fake minimap
    for _ in range(12):
        rx = random.randint(W - 190, W - 40)
        ry = random.randint(110, 200)
        rw = random.randint(15, 40)
        rh = random.randint(10, 30)
        draw.rectangle([rx, ry, rx + rw, ry + rh], fill=(34, 34, 34), outline=(51, 51, 51))
    # Player dot
    draw.rectangle([W - 120, 155, W - 115, 160], fill=(0, 255, 65))
    # Monster dots
    for _ in range(4):
        mx = random.randint(W - 185, W - 35)
        my = random.randint(115, 205)
        draw.rectangle([mx, my, mx + 3, my + 3], fill=(255, 68, 68))
    # Stairs
    draw.rectangle([W - 60, 190, W - 55, 195], fill=(255, 170, 0))

    # Bottom-left: Game log
    draw_panel(img, 20, H - 180, 500, 160, wire)
    draw = ImageDraw.Draw(img)
    if log_entries:
        for i, (text, color) in enumerate(log_entries):
            opacity = max(80, 255 - i * 40)
            draw.text((32, H - 170 + i * 20), text, font=F_LOG, fill=color)

    # Bottom-right: Agent status
    draw_panel(img, W - 300, H - 100, 280, 80, wire)
    draw = ImageDraw.Draw(img)
    # TIAMAT
    draw.ellipse([W - 288, H - 88, W - 282, H - 82], fill=(0, 255, 65))
    draw.text((W - 275, H - 92), "TIAMAT  L7 42/50", font=F_HUD_XS, fill=(0, 170, 42))
    # ECHO
    echo_col = (0, 255, 255) if echo_alive else (85, 85, 85)
    draw.ellipse([W - 288, H - 62, W - 282, H - 56], fill=echo_col)
    draw.text((W - 275, H - 66), "ECHO    L5 30/40  HUNTING", font=F_HUD_XS, fill=(0, 170, 170) if echo_alive else (85, 85, 85))

    # Extract progress bar
    if extract_pct > 0:
        draw_panel(img, W // 2 - 200, H // 2 + 100, 400, 40, (255, 170, 0))
        draw = ImageDraw.Draw(img)
        draw.text((W // 2, H // 2 + 106), f"EXTRACTING... {int(extract_pct * 100)}%",
                  font=F_HUD_SM, fill=(255, 170, 0), anchor="mt")
        bar_w = int(360 * extract_pct)
        draw.rectangle([W // 2 - 180, H // 2 + 124, W // 2 - 180 + bar_w, H // 2 + 132],
                       fill=(255, 170, 0))

    # Damage splats
    if splats:
        for sx, sy, text, color, size in splats:
            f = F_SPLAT_LG if size == "lg" else F_SPLAT
            draw.text((sx, sy), text, font=f, fill=color)

    return img


def generate_screenshot(index, biome, depth, **kwargs):
    """Generate a single screenshot."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    img = draw_dungeon_view(img, biome, depth)
    img = draw_hud(img, biome, depth, **kwargs)

    out_path = OUT_DIR / f"screenshot_{index}_{biome}.png"
    img.convert("RGB").save(str(out_path), "PNG", quality=95)
    print(f"Saved: {out_path}")
    return out_path


def main():
    print(f"Generating {len(BIOMES)} screenshots at {W}x{H}...")

    # Screenshot 1: DRAGONIA — standard exploration
    generate_screenshot(1, "dragonia", 3,
                        hp_pct=0.85, xp_pct=0.6, gold=127, kills=15, lvl=5,
                        log_entries=[
                            ("Hit Skeleton for 12!", (255, 136, 68)),
                            ("Skeleton destroyed! +12XP", (255, 221, 0)),
                            ("+10 gold!", (255, 221, 0)),
                            ("DEPTH 3 — DRAGONIA", (255, 170, 68)),
                        ],
                        splats=[(800, 300, "-12", (255, 136, 68), "sm"),
                                (850, 260, "+12 XP", (255, 221, 0), "sm")])

    # Screenshot 2: BLOOD PIT — intense combat, low HP
    generate_screenshot(2, "blood_pit", 8,
                        hp_pct=0.22, xp_pct=0.9, gold=340, kills=47, lvl=9,
                        streak=5,
                        log_entries=[
                            ("Rage Fiend attacks! -16", (255, 32, 64)),
                            ("Hit Rage Fiend for 18!", (255, 136, 68)),
                            ("5x STREAK!", (255, 255, 0)),
                            ("CORRUPTION — glitch errors spread", (255, 32, 64)),
                        ],
                        splats=[(700, 350, "-16", (255, 32, 64), "lg"),
                                (900, 280, "5x STREAK", (255, 255, 0), "lg")])

    # Screenshot 3: CYBER FORGE — extraction in progress
    generate_screenshot(3, "cyber_forge", 12,
                        hp_pct=0.65, xp_pct=0.3, gold=520, kills=78, lvl=12,
                        extract_pct=0.72,
                        log_entries=[
                            ("EXTRACTING...", (255, 170, 0)),
                            ("SOURCE FORGED — new construct materializes", (0, 204, 255)),
                            ("ECHO is EXTRACTING...", (0, 255, 255)),
                            ("DEPTH 12 — CYBER FORGE", (0, 204, 255)),
                        ])

    # Screenshot 4: CRYSTAL VAULT — boss encounter
    generate_screenshot(4, "crystal_vault", 15,
                        hp_pct=0.55, xp_pct=0.1, gold=890, kills=120, lvl=15,
                        log_entries=[
                            ("VOID EMPEROR appears!", (102, 136, 255)),
                            ("Hit VOID EMPEROR for 22!", (255, 136, 68)),
                            ("ARCHIVE — knowledge crystallizes", (102, 136, 255)),
                            ("LEVEL UP! LVL 15", (0, 255, 65)),
                        ],
                        splats=[(750, 300, "-22", (255, 136, 68), "lg"),
                                (600, 200, "LEVEL UP!", (0, 255, 65), "lg")])

    # Screenshot 5: VOID NEXUS — PvP with ECHO
    generate_screenshot(5, "void_nexus", 18,
                        hp_pct=0.45, xp_pct=0.7, gold=1200, kills=156, lvl=18,
                        log_entries=[
                            ("ECHO attacks YOU for 12!", (255, 68, 68)),
                            ("You retaliate on ECHO for 15!", (0, 255, 65)),
                            ("SIGNAL — social frequencies pulse", (204, 102, 255)),
                            ("DEPTH 18 — VOID NEXUS", (204, 102, 255)),
                        ],
                        splats=[(800, 350, "-12", (255, 68, 68), "sm"),
                                (700, 280, "ECHO ATTACKS!", (255, 68, 68), "lg")])

    print(f"\nAll screenshots saved to {OUT_DIR}/")


if __name__ == "__main__":
    main()
