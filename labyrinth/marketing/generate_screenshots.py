#!/usr/bin/env python3
"""LABYRINTH: TIAMAT'S DESCENT — Steam Screenshot Generator

Generates 5+ game-representative screenshots at 1920x1080 using PIL.
Each screenshot simulates a different biome/situation with HUD elements.
"""

import os
import random
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# Paths
SPRITE_TIAMAT = '/opt/tiamat-stream/hud/assets/sprite-tiamat.png'
SPRITE_MONSTERS = '/opt/tiamat-stream/hud/assets/sprite-monsters.png'
SPRITE_ITEMS = '/opt/tiamat-stream/hud/assets/sprite-items.png'
SPRITE_ECHO = '/opt/tiamat-stream/hud/assets/sprite-echo.png'
SPRITE_FLAME = '/opt/tiamat-stream/hud/assets/sprite-flame.png'
WALL_TEXTURE = '/opt/tiamat-stream/hud/assets/wall-stone.png'
FLOOR_TEXTURE = '/opt/tiamat-stream/hud/assets/floor-tile.png'
OUTPUT_DIR = '/root/labyrinth-steam/marketing/screenshots'

W, H = 1920, 1080
TILE = 48  # tile size in pixels

# Biome color palettes
BIOMES = {
    'dragonia': {
        'name': 'DRAGONIA',
        'wall': (80, 50, 30),
        'floor': (40, 28, 18),
        'wire': (255, 136, 0),
        'fog': (60, 30, 10),
        'accent': (255, 170, 50),
    },
    'blood_pit': {
        'name': 'BLOOD PIT',
        'wall': (70, 20, 25),
        'floor': (35, 12, 15),
        'wire': (255, 0, 64),
        'fog': (50, 10, 15),
        'accent': (255, 50, 80),
    },
    'crystal_vault': {
        'name': 'CRYSTAL VAULT',
        'wall': (40, 25, 70),
        'floor': (20, 12, 40),
        'wire': (170, 80, 255),
        'fog': (30, 15, 50),
        'accent': (200, 120, 255),
    },
    'cyber_forge': {
        'name': 'CYBER FORGE',
        'wall': (20, 40, 60),
        'floor': (10, 22, 35),
        'wire': (0, 180, 255),
        'fog': (5, 20, 40),
        'accent': (80, 200, 255),
    },
    'void_nexus': {
        'name': 'VOID NEXUS',
        'wall': (15, 15, 25),
        'floor': (8, 8, 15),
        'wire': (120, 0, 180),
        'fog': (10, 5, 20),
        'accent': (180, 50, 255),
    },
}

# Font
def get_font(size):
    paths = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
    ]
    for fp in paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()

def get_mono_font(size):
    paths = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
    ]
    for fp in paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()

def load_sprite(path, scale=3):
    """Load and upscale a sprite."""
    if os.path.exists(path):
        img = Image.open(path).convert('RGBA')
        w, h = img.size
        return img.resize((w * scale, h * scale), Image.Resampling.NEAREST)
    return None


# ─── Dungeon Generation (simplified BSP) ───

def generate_dungeon(cols, rows, num_rooms=6):
    """Generate a simple tile grid with rooms and corridors."""
    tiles = [[0] * cols for _ in range(rows)]  # 0=wall, 1=floor
    rooms = []

    for _ in range(num_rooms * 3):  # Try many times
        if len(rooms) >= num_rooms:
            break
        rw = random.randint(4, 8)
        rh = random.randint(3, 6)
        rx = random.randint(1, cols - rw - 1)
        ry = random.randint(1, rows - rh - 1)

        # Check overlap
        overlap = False
        for r in rooms:
            if (rx < r[0] + r[2] + 1 and rx + rw + 1 > r[0] and
                ry < r[1] + r[3] + 1 and ry + rh + 1 > r[1]):
                overlap = True
                break
        if overlap:
            continue

        rooms.append((rx, ry, rw, rh))
        for y in range(ry, ry + rh):
            for x in range(rx, rx + rw):
                tiles[y][x] = 1

    # Connect rooms with corridors
    for i in range(len(rooms) - 1):
        r1 = rooms[i]
        r2 = rooms[i + 1]
        cx1, cy1 = r1[0] + r1[2] // 2, r1[1] + r1[3] // 2
        cx2, cy2 = r2[0] + r2[2] // 2, r2[1] + r2[3] // 2

        # Horizontal then vertical
        x = cx1
        while x != cx2:
            if 0 <= cy1 < rows and 0 <= x < cols:
                tiles[cy1][x] = 1
            x += 1 if cx2 > cx1 else -1
        y = cy1
        while y != cy2:
            if 0 <= y < rows and 0 <= cx2 < cols:
                tiles[y][cx2] = 1
            y += 1 if cy2 > cy1 else -1

    return tiles, rooms


# ─── Draw Functions ───

def draw_dungeon(img, tiles, biome, offset_x=0, offset_y=0, fog_radius=12):
    """Draw tile-based dungeon on image."""
    draw = ImageDraw.Draw(img)
    rows = len(tiles)
    cols = len(tiles[0]) if rows > 0 else 0

    wall_base = biome['wall']
    floor_base = biome['floor']

    # Load textures
    wall_tex = None
    floor_tex = None
    if os.path.exists(WALL_TEXTURE):
        wall_tex = Image.open(WALL_TEXTURE).convert('RGB').resize((TILE, TILE))
    if os.path.exists(FLOOR_TEXTURE):
        floor_tex = Image.open(FLOOR_TEXTURE).convert('RGB').resize((TILE, TILE))

    for y in range(rows):
        for x in range(cols):
            px = offset_x + x * TILE
            py = offset_y + y * TILE

            if px + TILE < 0 or py + TILE < 0 or px > W or py > H:
                continue

            if tiles[y][x] == 1:
                # Floor tile
                if floor_tex:
                    tile_img = floor_tex.copy()
                    # Tint to biome color
                    r, g, b = floor_base
                    tint = Image.new('RGB', (TILE, TILE), (r * 2, g * 2, b * 2))
                    tile_img = Image.blend(tile_img, tint, 0.5)
                    img.paste(tile_img, (px, py))
                else:
                    # Random variation
                    v = random.randint(-10, 10)
                    color = (floor_base[0] + v, floor_base[1] + v, floor_base[2] + v)
                    draw.rectangle([(px, py), (px + TILE - 1, py + TILE - 1)], fill=color)
            else:
                # Wall tile
                if wall_tex:
                    tile_img = wall_tex.copy()
                    r, g, b = wall_base
                    tint = Image.new('RGB', (TILE, TILE), (r * 2, g * 2, b * 2))
                    tile_img = Image.blend(tile_img, tint, 0.4)
                    img.paste(tile_img, (px, py))
                else:
                    v = random.randint(-8, 8)
                    color = (wall_base[0] + v, wall_base[1] + v, wall_base[2] + v)
                    draw.rectangle([(px, py), (px + TILE - 1, py + TILE - 1)], fill=color)

                    # Wall border highlight
                    wire = biome['wire']
                    highlight = (wire[0] // 6, wire[1] // 6, wire[2] // 6)
                    draw.line([(px, py), (px + TILE - 1, py)], fill=highlight)
                    draw.line([(px, py), (px, py + TILE - 1)], fill=highlight)


def draw_fog(img, center_x, center_y, biome, radius=400):
    """Draw fog-of-war darkness."""
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for y in range(0, H, 8):
        for x in range(0, W, 8):
            dist = ((x - center_x)**2 + (y - center_y)**2) ** 0.5
            if dist > radius:
                alpha = min(220, int((dist - radius) / (radius * 0.5) * 255))
                fog_c = biome['fog']
                draw.rectangle([(x, y), (x + 7, y + 7)], fill=(fog_c[0], fog_c[1], fog_c[2], alpha))
            elif dist > radius * 0.7:
                t = (dist - radius * 0.7) / (radius * 0.3)
                alpha = int(t * 60)
                fog_c = biome['fog']
                draw.rectangle([(x, y), (x + 7, y + 7)], fill=(fog_c[0], fog_c[1], fog_c[2], alpha))

    img_rgba = img.convert('RGBA')
    result = Image.alpha_composite(img_rgba, overlay)
    return result.convert('RGB')


def draw_hud(img, biome, player_hp, player_max_hp, player_lvl, depth, gold, kills, log_entries, kill_streak=0):
    """Draw game HUD overlay."""
    draw = ImageDraw.Draw(img)
    font = get_mono_font(14)
    font_sm = get_mono_font(11)
    font_title = get_font(16)
    wire = biome['wire']
    green = (0, 255, 65)

    # Top-left: Player stats panel
    panel_x, panel_y = 16, 16
    panel_w, panel_h = 260, 100
    draw.rectangle([(panel_x, panel_y), (panel_x + panel_w, panel_y + panel_h)],
                   fill=(0, 5, 2, 180), outline=(0, 255, 65, 40))

    draw.text((panel_x + 10, panel_y + 8), 'TIAMAT', font=font_title, fill=green)
    draw.text((panel_x + 10, panel_y + 30), f'LVL {player_lvl}', font=font_sm, fill=(0, 170, 42))

    # HP bar
    hp_x, hp_y = panel_x + 10, panel_y + 50
    hp_w = 180
    draw.text((hp_x, hp_y - 2), 'HP', font=font_sm, fill=(100, 100, 100))
    draw.rectangle([(hp_x + 25, hp_y), (hp_x + 25 + hp_w, hp_y + 10)], fill=(30, 30, 30), outline=(60, 60, 60))
    hp_fill = int(hp_w * player_hp / max(1, player_max_hp))
    hp_color = green if player_hp > player_max_hp * 0.5 else (255, 170, 0) if player_hp > player_max_hp * 0.25 else (255, 0, 64)
    draw.rectangle([(hp_x + 25, hp_y), (hp_x + 25 + hp_fill, hp_y + 10)], fill=hp_color)
    draw.text((hp_x + hp_w + 30, hp_y - 2), f'{player_hp}/{player_max_hp}', font=font_sm, fill=(136, 136, 136))

    # XP bar
    xp_y = hp_y + 18
    draw.text((hp_x, xp_y - 2), 'XP', font=font_sm, fill=(100, 100, 100))
    draw.rectangle([(hp_x + 25, xp_y), (hp_x + 25 + hp_w, xp_y + 8)], fill=(30, 30, 30), outline=(60, 60, 60))
    xp_fill = int(hp_w * random.uniform(0.2, 0.8))
    draw.rectangle([(hp_x + 25, xp_y), (hp_x + 25 + xp_fill, xp_y + 8)], fill=(0, 255, 255))

    # Top-center: Biome & Depth
    biome_name = biome['name']
    tc_font = get_font(14)
    bbox = draw.textbbox((0, 0), biome_name, font=tc_font)
    tw = bbox[2] - bbox[0]
    draw.text((W // 2 - tw // 2, 20), biome_name, font=tc_font, fill=wire)
    depth_text = f'DEPTH {depth}'
    bbox2 = draw.textbbox((0, 0), depth_text, font=font_sm)
    tw2 = bbox2[2] - bbox2[0]
    draw.text((W // 2 - tw2 // 2, 40), depth_text, font=font_sm, fill=(0, 170, 42))

    # Top-right: Stats
    tr_x = W - 200
    draw.text((tr_x, 16), f'KILLS: {kills}', font=font_sm, fill=(0, 170, 42))
    draw.text((tr_x, 32), f'GOLD: {gold}', font=font_sm, fill=(255, 221, 0))
    if kill_streak > 0:
        draw.text((tr_x, 50), f'{kill_streak}x STREAK!', font=font, fill=(255, 100, 0))

    # Bottom-left: Combat log
    log_y = H - 20 - len(log_entries) * 18
    for i, (text, color) in enumerate(log_entries):
        draw.text((16, log_y + i * 18), text, font=font_sm, fill=color)

    # Minimap (top-right corner)
    mm_w, mm_h = 150, 100
    mm_x = W - mm_w - 16
    mm_y = 70
    draw.rectangle([(mm_x, mm_y), (mm_x + mm_w, mm_y + mm_h)],
                   fill=(0, 0, 0, 200), outline=(0, 255, 65, 50))
    # Draw minimap dots
    for _ in range(30):
        rx = mm_x + random.randint(5, mm_w - 5)
        ry = mm_y + random.randint(5, mm_h - 5)
        draw.rectangle([(rx, ry), (rx + 2, ry + 2)], fill=(40, 40, 40))
    # Player dot
    px = mm_x + mm_w // 2
    py = mm_y + mm_h // 2
    draw.rectangle([(px - 2, py - 2), (px + 2, py + 2)], fill=green)
    # Enemy dots
    for _ in range(random.randint(2, 5)):
        ex = mm_x + random.randint(10, mm_w - 10)
        ey = mm_y + random.randint(10, mm_h - 10)
        draw.rectangle([(ex - 1, ey - 1), (ex + 1, ey + 1)], fill=(255, 0, 64))


def draw_entity(img, sprite_path, x, y, scale=4, glow_color=None):
    """Draw a sprite entity at position with optional glow."""
    sprite = load_sprite(sprite_path, scale)
    if not sprite:
        return

    # Add glow effect
    if glow_color:
        glow = Image.new('RGBA', sprite.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        cw, ch = sprite.size
        for px in range(cw):
            for py in range(ch):
                r, g, b, a = sprite.getpixel((px, py))
                if a > 100:
                    gd.ellipse([(px - 3, py - 3), (px + 3, py + 3)],
                               fill=(glow_color[0], glow_color[1], glow_color[2], 30))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=4))
        img.paste(glow, (x - 3, y - 3), glow)

    img.paste(sprite, (x, y), sprite)


def draw_damage_splat(img, x, y, text, color):
    """Draw floating damage text."""
    draw = ImageDraw.Draw(img)
    font = get_font(20)
    # Shadow
    draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0))
    # Glow
    draw.text((x - 1, y - 1), text, font=font, fill=(color[0] // 2, color[1] // 2, color[2] // 2))
    # Main
    draw.text((x, y), text, font=font, fill=color)


def add_post_processing(img):
    """Add bloom-like post-processing effect."""
    # Slight bloom
    bright = ImageEnhance.Brightness(img)
    img_bright = bright.enhance(1.1)

    # Vignette
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cx, cy = W // 2, H // 2
    max_dist = (cx**2 + cy**2) ** 0.5

    for y in range(0, H, 6):
        for x in range(0, W, 6):
            dist = ((x - cx)**2 + (y - cy)**2) ** 0.5
            t = (dist / max_dist) ** 2.5
            alpha = int(t * 180)
            draw.rectangle([(x, y), (x + 5, y + 5)], fill=(0, 0, 0, alpha))

    result = Image.alpha_composite(img_bright.convert('RGBA'), overlay)

    # Scanlines
    sl = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    sld = ImageDraw.Draw(sl)
    for y in range(0, H, 3):
        sld.line([(0, y), (W, y)], fill=(0, 0, 0, 15))
    result = Image.alpha_composite(result, sl)

    return result.convert('RGB')


# ─── Screenshot Generators ───

def screenshot_exploration():
    """Screenshot 1: DRAGONIA biome — exploration in corridor."""
    biome = BIOMES['dragonia']
    img = Image.new('RGB', (W, H), biome['fog'])

    # Generate dungeon
    cols, rows = W // TILE + 2, H // TILE + 2
    tiles, rooms = generate_dungeon(cols, rows, num_rooms=7)

    # Find player position (center of first room)
    player_room = rooms[0]
    px = player_room[0] + player_room[2] // 2
    py = player_room[1] + player_room[3] // 2
    offset_x = W // 2 - px * TILE
    offset_y = H // 2 - py * TILE

    draw_dungeon(img, tiles, biome, offset_x, offset_y)

    # Draw player
    draw_entity(img, SPRITE_TIAMAT, W // 2 - 24, H // 2 - 24, scale=5, glow_color=(0, 255, 65))

    # Draw some monsters in nearby rooms
    for i, room in enumerate(rooms[1:4]):
        mx = offset_x + (room[0] + room[2] // 2) * TILE
        my = offset_y + (room[1] + room[3] // 2) * TILE
        if 0 < mx < W - 50 and 0 < my < H - 50:
            draw_entity(img, SPRITE_MONSTERS, mx, my, scale=4, glow_color=(255, 100, 50))

    # Draw torch flames
    for room in rooms[:3]:
        fx = offset_x + room[0] * TILE
        fy = offset_y + room[1] * TILE
        if 0 < fx < W and 0 < fy < H:
            draw_entity(img, SPRITE_FLAME, fx, fy, scale=3, glow_color=biome['accent'])

    # Fog of war
    img = draw_fog(img, W // 2, H // 2, biome, radius=450)

    # HUD
    log = [
        ('Entered DRAGONIA — Floor 3', biome['wire']),
        ('Found Healing Herb! +15 HP', (0, 255, 65)),
        ('+5 gold!', (255, 221, 0)),
    ]
    draw_hud(img, biome, 42, 50, 3, 3, 127, 8, log)

    # Post-processing
    img = add_post_processing(img)
    return img


def screenshot_combat():
    """Screenshot 2: BLOOD PIT biome — active combat."""
    biome = BIOMES['blood_pit']
    img = Image.new('RGB', (W, H), biome['fog'])

    cols, rows = W // TILE + 2, H // TILE + 2
    tiles, rooms = generate_dungeon(cols, rows, num_rooms=5)

    player_room = rooms[0]
    px = player_room[0] + player_room[2] // 2
    py = player_room[1] + player_room[3] // 2
    offset_x = W // 2 - px * TILE
    offset_y = H // 2 - py * TILE

    draw_dungeon(img, tiles, biome, offset_x, offset_y)

    # Player
    draw_entity(img, SPRITE_TIAMAT, W // 2 - 24, H // 2 - 24, scale=5, glow_color=(0, 255, 65))

    # Enemies close by
    draw_entity(img, SPRITE_MONSTERS, W // 2 + 60, H // 2 - 30, scale=4, glow_color=(255, 0, 64))
    draw_entity(img, SPRITE_MONSTERS, W // 2 - 100, H // 2 + 20, scale=4, glow_color=(255, 0, 64))

    # Damage splats
    img_rgba = img.convert('RGBA')
    draw_damage_splat(img_rgba, W // 2 + 70, H // 2 - 80, '-12', (255, 136, 68))
    draw_damage_splat(img_rgba, W // 2 - 90, H // 2 - 10, '-8', (255, 0, 64))
    draw_damage_splat(img_rgba, W // 2 + 30, H // 2 - 50, '+15 XP', (255, 221, 0))
    img = img_rgba.convert('RGB')

    # Fog
    img = draw_fog(img, W // 2, H // 2, biome, radius=380)

    # HUD
    log = [
        ('Hit Rage Fiend for 12!', (255, 136, 68)),
        ('Rage Fiend attacks! -8 HP', (255, 0, 64)),
        ('Skeleton destroyed! +15 XP', (255, 221, 0)),
        ('3x KILL STREAK!', (255, 170, 0)),
    ]
    draw_hud(img, biome, 28, 60, 5, 7, 342, 23, log, kill_streak=3)

    img = add_post_processing(img)
    return img


def screenshot_boss():
    """Screenshot 3: Boss fight — large enemy, player low HP."""
    biome = BIOMES['void_nexus']
    img = Image.new('RGB', (W, H), biome['fog'])

    cols, rows = W // TILE + 2, H // TILE + 2
    tiles, rooms = generate_dungeon(cols, rows, num_rooms=4)

    # Make a big boss room
    boss_room = rooms[0]
    for y in range(max(0, boss_room[1] - 2), min(rows, boss_room[1] + boss_room[3] + 2)):
        for x in range(max(0, boss_room[0] - 2), min(cols, boss_room[0] + boss_room[2] + 2)):
            tiles[y][x] = 1

    px = boss_room[0] + boss_room[2] // 2
    py = boss_room[1] + boss_room[3] // 2
    offset_x = W // 2 - px * TILE
    offset_y = H // 2 - py * TILE

    draw_dungeon(img, tiles, biome, offset_x, offset_y)

    # Player (low HP)
    draw_entity(img, SPRITE_TIAMAT, W // 2 - 100, H // 2 + 40, scale=5, glow_color=(0, 255, 65))

    # Boss (large sprite)
    boss_sprite = load_sprite(SPRITE_MONSTERS, 8)  # Extra large
    if boss_sprite:
        img_rgba = img.convert('RGBA')
        # Boss glow
        glow = Image.new('RGBA', (200, 200), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse([(20, 20), (180, 180)], fill=(biome['wire'][0], biome['wire'][1], biome['wire'][2], 40))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=20))
        img_rgba.paste(glow, (W // 2 + 40, H // 2 - 120), glow)
        img_rgba.paste(boss_sprite, (W // 2 + 60, H // 2 - 80), boss_sprite)
        img = img_rgba.convert('RGB')

    # Boss HP bar at top
    draw = ImageDraw.Draw(img)
    boss_font = get_font(16)
    draw.text((W // 2 - 60, 70), 'GATE KEEPER', font=boss_font, fill=biome['wire'])
    bar_x = W // 2 - 200
    bar_w = 400
    draw.rectangle([(bar_x, 95), (bar_x + bar_w, 110)], fill=(30, 10, 15), outline=(100, 0, 40))
    draw.rectangle([(bar_x, 95), (bar_x + int(bar_w * 0.65), 110)], fill=(255, 0, 64))

    # Damage splats
    draw_damage_splat(img, W // 2 + 80, H // 2 - 130, '-24', (255, 136, 68))

    img = draw_fog(img, W // 2, H // 2, biome, radius=500)

    log = [
        ('BOSS ENCOUNTER: GATE KEEPER!', biome['wire']),
        ('Hit Gate Keeper for 24!', (255, 136, 68)),
        ('Gate Keeper smashes! -18 HP', (255, 0, 64)),
        ('WARNING: HP CRITICAL!', (255, 0, 64)),
    ]
    draw_hud(img, biome, 12, 80, 8, 15, 891, 67, log)

    img = add_post_processing(img)
    return img


def screenshot_extraction():
    """Screenshot 4: Extraction — player on stairs with timer."""
    biome = BIOMES['cyber_forge']
    img = Image.new('RGB', (W, H), biome['fog'])

    cols, rows = W // TILE + 2, H // TILE + 2
    tiles, rooms = generate_dungeon(cols, rows, num_rooms=6)

    player_room = rooms[-1]  # Last room has stairs
    px = player_room[0] + player_room[2] // 2
    py = player_room[1] + player_room[3] // 2
    offset_x = W // 2 - px * TILE
    offset_y = H // 2 - py * TILE

    draw_dungeon(img, tiles, biome, offset_x, offset_y)

    # Draw stairs glow under player
    draw = ImageDraw.Draw(img)
    stair_x, stair_y = W // 2, H // 2
    for r in range(40, 5, -5):
        alpha = 255 - r * 5
        draw.ellipse([(stair_x - r, stair_y - r // 2), (stair_x + r, stair_y + r // 2)],
                     fill=(biome['wire'][0] // 3, biome['wire'][1] // 3, biome['wire'][2] // 3))

    # Player on stairs
    draw_entity(img, SPRITE_TIAMAT, W // 2 - 24, H // 2 - 40, scale=5, glow_color=(0, 255, 65))

    # Items on ground nearby
    for ix in range(-2, 3):
        for iy in range(-1, 2):
            if random.random() > 0.7 and (ix != 0 or iy != 0):
                draw_entity(img, SPRITE_ITEMS, W // 2 + ix * 50, H // 2 + iy * 50, scale=3)

    # Extraction progress bar (center)
    extract_font = get_font(18)
    bar_w = 300
    bar_x = W // 2 - bar_w // 2
    bar_y = H // 2 - 90
    draw.text((bar_x, bar_y - 25), 'EXTRACTING...', font=extract_font, fill=(255, 170, 0))
    draw.rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + 12)], fill=(30, 30, 30), outline=(100, 80, 0))
    draw.rectangle([(bar_x, bar_y), (bar_x + int(bar_w * 0.72), bar_y + 12)], fill=(255, 170, 0))
    draw.text((bar_x + bar_w + 10, bar_y - 3), '72%', font=get_mono_font(14), fill=(255, 170, 0))

    img = draw_fog(img, W // 2, H // 2, biome, radius=420)

    log = [
        ('EXTRACTING... Stand still!', (255, 170, 0)),
        ('Loot banked: 7 items', (0, 255, 65)),
        ('+124 XP banked', (0, 255, 255)),
        ('Extract progress: 72%', (255, 170, 0)),
    ]
    draw_hud(img, biome, 55, 70, 6, 9, 567, 41, log)

    img = add_post_processing(img)
    return img


def screenshot_crystal():
    """Screenshot 5: Crystal Vault — beautiful purple biome, items."""
    biome = BIOMES['crystal_vault']
    img = Image.new('RGB', (W, H), biome['fog'])

    cols, rows = W // TILE + 2, H // TILE + 2
    tiles, rooms = generate_dungeon(cols, rows, num_rooms=8)

    player_room = rooms[2]
    px = player_room[0] + player_room[2] // 2
    py = player_room[1] + player_room[3] // 2
    offset_x = W // 2 - px * TILE
    offset_y = H // 2 - py * TILE

    draw_dungeon(img, tiles, biome, offset_x, offset_y)

    # Crystal glow effects
    draw = ImageDraw.Draw(img)
    for _ in range(15):
        cx = random.randint(100, W - 100)
        cy = random.randint(100, H - 100)
        for r in range(20, 3, -3):
            draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)],
                         fill=(biome['accent'][0] // 8, biome['accent'][1] // 8, biome['accent'][2] // 8))

    # Player
    draw_entity(img, SPRITE_TIAMAT, W // 2 - 24, H // 2 - 24, scale=5, glow_color=(0, 255, 65))

    # ECHO rival visible
    draw_entity(img, SPRITE_ECHO, W // 2 + 200, H // 2 - 60, scale=4, glow_color=(0, 255, 255))

    # Items scattered
    for _ in range(5):
        ix = W // 2 + random.randint(-200, 200)
        iy = H // 2 + random.randint(-150, 150)
        draw_entity(img, SPRITE_ITEMS, ix, iy, scale=3)

    # Torches
    for room in rooms[:4]:
        fx = offset_x + room[0] * TILE
        fy = offset_y + room[1] * TILE
        if 0 < fx < W and 0 < fy < H:
            draw_entity(img, SPRITE_FLAME, fx, fy, scale=3, glow_color=biome['accent'])

    img = draw_fog(img, W // 2, H // 2, biome, radius=500)

    log = [
        ('CRYSTAL VAULT — Rare loot detected', biome['wire']),
        ('Found Dragon Scale! +3 DEF', (170, 80, 255)),
        ('ECHO spotted nearby...', (0, 255, 255)),
        ('Crystal resonates with power', biome['accent']),
    ]
    draw_hud(img, biome, 65, 70, 7, 12, 734, 52, log)

    img = add_post_processing(img)
    return img


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    screenshots = [
        ('screenshot_01_exploration.png', screenshot_exploration, 'Exploration — Dragonia Biome'),
        ('screenshot_02_combat.png', screenshot_combat, 'Combat — Blood Pit Biome'),
        ('screenshot_03_boss_fight.png', screenshot_boss, 'Boss Fight — Void Nexus'),
        ('screenshot_04_extraction.png', screenshot_extraction, 'Extraction — Cyber Forge'),
        ('screenshot_05_crystal_vault.png', screenshot_crystal, 'Crystal Vault — Rare Loot'),
    ]

    for filename, generator, description in screenshots:
        print(f'Generating {description}...')
        img = generator()
        out_path = os.path.join(OUTPUT_DIR, filename)
        img.save(out_path, 'PNG', optimize=True)
        size = os.path.getsize(out_path)
        print(f'  -> {out_path} ({size:,} bytes, {img.size[0]}x{img.size[1]})')

    print(f'\nAll {len(screenshots)} screenshots generated in {OUTPUT_DIR}')


if __name__ == '__main__':
    main()
