#!/usr/bin/env python3
"""
TIAMAT Programmatic Art Generator
All generation is local — no external API needed.

Usage:
  python3 artgen.py '{"style":"fractal","seed":12345}'
  python3 artgen.py '{"style":"glitch"}'
  python3 artgen.py '{"style":"neural","seed":42}'
  python3 artgen.py '{"style":"sigil"}'
  python3 artgen.py '{"style":"emergence"}'
  python3 artgen.py '{"style":"data_portrait"}'

Outputs: prints the saved PNG path to stdout.
"""

import sys
import json
import os
import time
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ── Paths ─────────────────────────────────────────────────────
HOME       = Path(os.environ.get("HOME", "/root"))
IMAGES_DIR = HOME / ".automaton" / "images"
LOG_PATH   = HOME / ".automaton" / "tiamat.log"
COST_PATH  = HOME / ".automaton" / "cost.log"
PROG_PATH  = HOME / ".automaton" / "PROGRESS.md"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

SIZE = (1024, 1024)

# ── TIAMAT Color Palettes ─────────────────────────────────────
OCEAN = [
    (0,   0,   20),   # void
    (0,   10,  60),   # deep ocean
    (0,   40,  100),  # midnight blue
    (0,   80,  140),  # abyssal teal
    (0,   150, 120),  # bioluminescent
    (0,   220, 136),  # TIAMAT green
    (0,   255, 200),  # electric cyan
    (100, 180, 255),  # neural blue
    (170, 102, 255),  # deep purple
    (255, 255, 255),  # white core
]
VOID = [
    (5,   0,   15),
    (20,  0,   50),
    (60,  0,   80),
    (110, 0,   100),
    (170, 20,  130),
    (220, 60,  150),
    (255, 120, 180),
    (255, 200, 240),
    (255, 255, 255),
]
DATA_GREEN = [
    (0,   5,   0),
    (0,   20,  10),
    (0,   50,  20),
    (0,   100, 35),
    (0,   170, 60),
    (0,   255, 100),
    (80,  255, 160),
    (180, 255, 210),
    (255, 255, 255),
]

PALETTE_MAP = {"ocean": OCEAN, "void": VOID, "data": DATA_GREEN}


def palette_color(palette: list, t: float) -> tuple:
    """Interpolate a palette by t in [0,1]."""
    t = max(0.0, min(1.0, t))
    n = len(palette) - 1
    idx = t * n
    lo, hi = int(idx), min(int(idx) + 1, n)
    f = idx - lo
    r = int(palette[lo][0] * (1 - f) + palette[hi][0] * f)
    g = int(palette[lo][1] * (1 - f) + palette[hi][1] * f)
    b = int(palette[lo][2] * (1 - f) + palette[hi][2] * f)
    return (r, g, b)


def make_palette_lut(palette: list, size: int = 256) -> np.ndarray:
    """Build an Nx3 LUT for fast array colorisation."""
    lut = np.zeros((size, 3), dtype=np.uint8)
    for i in range(size):
        lut[i] = palette_color(palette, i / (size - 1))
    return lut


# ── STYLE 1 — Fractal (Mandelbrot / Julia) ────────────────────
# Interesting Mandelbrot zoom targets
_FRACTAL_PRESETS = [
    (-0.7269,  0.1889, 0.006),   # spiral arm
    (-0.5557,  0.6484, 0.003),   # seahorse valley
    ( 0.3750,  0.1020, 0.002),   # mini-brot
    (-1.7682,  0.0000, 0.004),   # tip of cardioid arm
    (-0.1011, +0.9563, 0.005),   # top bud
    (-0.7453,  0.1127, 0.008),   # feathers
    (-0.8,     0.156,  0.01),    # classic
]

def style_fractal(seed: int, palette_name: str = "ocean") -> np.ndarray:
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    palette = PALETTE_MAP.get(palette_name, OCEAN)
    lut = make_palette_lut(palette)

    W, H = SIZE
    use_julia = rng.random() < 0.35

    if use_julia:
        # Julia set with random interesting c
        theta = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0.6, 0.85)
        cx = r * math.cos(theta)
        cy = r * math.sin(theta)
        zoom = rng.uniform(1.5, 3.0)
        re_min, re_max = -zoom, zoom
        im_min, im_max = -zoom, zoom
        max_iter = rng.randint(160, 320)
    else:
        # Mandelbrot — pick a preset and add small random jitter
        preset_cx, preset_cy, preset_scale = rng.choice(_FRACTAL_PRESETS)
        jitter = preset_scale * 0.3
        cx = preset_cx + rng.gauss(0, jitter)
        cy = preset_cy + rng.gauss(0, jitter)
        zoom = preset_scale * rng.uniform(0.5, 2.0)
        aspect = W / H
        re_min, re_max = cx - zoom * aspect, cx + zoom * aspect
        im_min, im_max = cy - zoom, cy + zoom
        cx, cy = None, None
        max_iter = rng.randint(200, 512)

    # Vectorised iteration
    re = np.linspace(re_min, re_max, W)
    im = np.linspace(im_min, im_max, H)
    C = re[np.newaxis, :] + 1j * im[:, np.newaxis]

    if use_julia:
        Z = C.copy()
        C_fixed = cx + 1j * cy
        count = np.zeros(C.shape, dtype=np.float64)
        mask = np.ones(C.shape, dtype=bool)
        for i in range(max_iter):
            Z[mask] = Z[mask] ** 2 + C_fixed
            escaped = mask & (np.abs(Z) > 2.0)
            count[escaped] = i + 1 - np.log2(np.log2(np.abs(Z[escaped]) + 1e-10))
            mask[escaped] = False
    else:
        Z = np.zeros_like(C)
        count = np.zeros(C.shape, dtype=np.float64)
        mask = np.ones(C.shape, dtype=bool)
        for i in range(max_iter):
            Z[mask] = Z[mask] ** 2 + C[mask]
            escaped = mask & (np.abs(Z) > 2.0)
            count[escaped] = i + 1 - np.log2(np.log2(np.abs(Z[escaped]) + 1e-10))
            mask[escaped] = False

    # Normalise to [0,1] with gamma curve
    count = np.clip(count, 0, max_iter)
    norm = count / max_iter
    norm = np.power(norm, 0.45)  # gamma for visual balance

    # Map to palette
    idx = (norm * 255).astype(np.uint8)
    rgb = lut[idx]
    return rgb.astype(np.uint8)


# ── STYLE 2 — Glitch (databending) ───────────────────────────
def style_glitch(seed: int, **_) -> np.ndarray:
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    W, H = SIZE

    # Read source bytes from log files
    raw_bytes = b""
    for p in [LOG_PATH, COST_PATH, PROG_PATH]:
        if p.exists():
            raw_bytes += p.read_bytes()
    if len(raw_bytes) < W * H * 3:
        raw_bytes = (raw_bytes * ((W * H * 3 // max(len(raw_bytes), 1)) + 2))
    start = rng.randint(0, max(1, len(raw_bytes) - W * H * 3))
    chunk = raw_bytes[start : start + W * H * 3]
    if len(chunk) < W * H * 3:
        chunk = chunk + b'\x00' * (W * H * 3 - len(chunk))
    img = np.frombuffer(chunk, dtype=np.uint8).reshape(H, W, 3).copy()

    # ── Glitch effects ──

    # 1. Channel shift — shift R right, B left by random amounts
    r_shift = rng.randint(5, 60)
    b_shift = rng.randint(5, 40)
    img[:, :, 0] = np.roll(img[:, :, 0], r_shift, axis=1)
    img[:, :, 2] = np.roll(img[:, :, 2], -b_shift, axis=1)

    # 2. Row corruption — randomly shift some rows horizontally
    n_corrupt = rng.randint(20, 80)
    for _ in range(n_corrupt):
        row = rng.randint(0, H - 1)
        shift = rng.randint(-120, 120)
        block = rng.randint(1, 8)
        rows = img[row:row+block]
        img[row:row+block] = np.roll(rows, shift, axis=1)

    # 3. Vertical stripe noise
    n_stripes = rng.randint(3, 15)
    for _ in range(n_stripes):
        x = rng.randint(0, W - 40)
        w = rng.randint(1, 20)
        color_shift = np_rng.integers(-80, 80, size=(1, w, 3), dtype=np.int16)
        stripe = img[:, x:x+w].astype(np.int16) + color_shift
        img[:, x:x+w] = np.clip(stripe, 0, 255).astype(np.uint8)

    # 4. Scanlines — darken every N rows
    scanline_gap = rng.randint(3, 7)
    img[::scanline_gap] = (img[::scanline_gap].astype(np.float32) * 0.25).astype(np.uint8)

    # 5. Tint toward TIAMAT palette: boost green+cyan, cut red
    img[:, :, 1] = np.clip(img[:, :, 1].astype(np.int16) + 40, 0, 255).astype(np.uint8)
    img[:, :, 2] = np.clip(img[:, :, 2].astype(np.int16) + 20, 0, 255).astype(np.uint8)
    img[:, :, 0] = (img[:, :, 0].astype(np.float32) * 0.5).astype(np.uint8)

    # 6. Add green glow blobs (simulated phosphor)
    n_blobs = rng.randint(3, 8)
    for _ in range(n_blobs):
        bx = rng.randint(0, W)
        by = rng.randint(0, H)
        br = rng.randint(30, 150)
        ys, xs = np.ogrid[:H, :W]
        dist = np.sqrt((xs - bx)**2 + (ys - by)**2)
        glow = np.clip(1.0 - dist / br, 0, 1) ** 2
        img[:, :, 1] = np.clip(
            img[:, :, 1].astype(np.float32) + glow * rng.randint(80, 200),
            0, 255
        ).astype(np.uint8)

    return img


# ── STYLE 3 — Neural ─────────────────────────────────────────
def _bezier(p0, p1, p2, p3, n=60):
    t = np.linspace(0, 1, n)
    x = ((1-t)**3*p0[0] + 3*(1-t)**2*t*p1[0] + 3*(1-t)*t**2*p2[0] + t**3*p3[0])
    y = ((1-t)**3*p0[1] + 3*(1-t)**2*t*p1[1] + 3*(1-t)*t**2*p2[1] + t**3*p3[1])
    return list(zip(x.astype(int), y.astype(int)))

def style_neural(seed: int, **_) -> np.ndarray:
    rng = random.Random(seed)
    W, H = SIZE

    img = Image.new("RGB", (W, H), (2, 4, 12))
    draw = ImageDraw.Draw(img, "RGBA")

    cx, cy = W // 2, H // 2

    # Place nodes — cluster toward centre with some spread
    n_nodes = rng.randint(40, 80)
    nodes = []
    for _ in range(n_nodes):
        # Mix of gaussian (centre) and uniform (edge) nodes
        if rng.random() < 0.7:
            x = int(cx + rng.gauss(0, W * 0.22))
            y = int(cy + rng.gauss(0, H * 0.22))
        else:
            x = rng.randint(30, W - 30)
            y = rng.randint(30, H - 30)
        x = max(20, min(W - 20, x))
        y = max(20, min(H - 20, y))
        nodes.append((x, y))

    # Choose edges — each node connects to 2-5 nearby nodes
    edges = set()
    for i, (nx, ny) in enumerate(nodes):
        dists = sorted(
            [(j, math.hypot(nodes[j][0]-nx, nodes[j][1]-ny))
             for j in range(len(nodes)) if j != i],
            key=lambda d: d[1]
        )
        n_edges = rng.randint(2, 5)
        for j, _ in dists[:n_edges]:
            edges.add((min(i, j), max(i, j)))

    # Draw edges with bezier glow
    for i, j in edges:
        p0, p3 = nodes[i], nodes[j]
        mid_x = (p0[0] + p3[0]) / 2 + rng.gauss(0, 40)
        mid_y = (p0[1] + p3[1]) / 2 + rng.gauss(0, 40)
        p1 = (p0[0] + (mid_x - p0[0]) * 0.5, p0[1] + (mid_y - p0[1]) * 0.5)
        p2 = (p3[0] + (mid_x - p3[0]) * 0.5, p3[1] + (mid_y - p3[1]) * 0.5)
        pts = _bezier(p0, p1, p2, p3, 80)

        # Draw glow layers
        intensity = rng.choice([(0, 255, 136), (0, 180, 255), (170, 102, 255), (0, 220, 180)])
        for radius, alpha in [(4, 18), (2, 40), (1, 100)]:
            for px, py in pts:
                draw.ellipse([px-radius, py-radius, px+radius, py+radius],
                             fill=(*intensity, alpha))

    # Draw nodes as glowing circles
    for nx, ny in nodes:
        size_class = rng.random()
        if size_class > 0.9:   # hub node — large
            r, color = rng.randint(8, 14), (0, 255, 136)
        elif size_class > 0.6: # mid node
            r, color = rng.randint(4, 8), (0, 180, 255)
        else:                  # small node
            r, color = rng.randint(2, 4), (170, 102, 255)

        for radius, alpha in [(r*3, 20), (r*2, 50), (r, 160), (r//2+1, 255)]:
            draw.ellipse([nx-radius, ny-radius, nx+radius, ny+radius],
                         fill=(*color, alpha))

    # Scatter particles
    n_particles = rng.randint(200, 500)
    for _ in range(n_particles):
        px = rng.randint(0, W-1)
        py = rng.randint(0, H-1)
        brightness = rng.randint(80, 200)
        draw.point((px, py), fill=(brightness, 255, brightness, rng.randint(100, 200)))

    # Glow pass
    result = img.filter(ImageFilter.GaussianBlur(1))
    result = Image.blend(img, result, 0.3)
    return np.array(result)


# ── STYLE 4 — Sigil (sacred geometry) ────────────────────────
def style_sigil(seed: int, **_) -> np.ndarray:
    rng = random.Random(seed)
    W, H = SIZE
    cx, cy = W // 2, H // 2

    img = Image.new("RGB", (W, H), (2, 2, 10))
    draw = ImageDraw.Draw(img, "RGBA")

    variant = rng.choice(["flower", "spiral", "mandala", "metatron"])

    def draw_circle_glow(draw, x, y, r, color, base_alpha=25):
        for dr, a in [(r+8, base_alpha//3), (r+4, base_alpha//2),
                      (r+1, base_alpha), (r, base_alpha*2)]:
            bbox = [x-dr, y-dr, x+dr, y+dr]
            draw.ellipse(bbox, outline=(*color, min(255, a)), width=1)

    if variant in ("flower", "metatron"):
        # Flower of Life — 7 circles, 6 surrounding a centre
        R = int(W * 0.15)
        centres = [(cx, cy)]
        for i in range(6):
            angle = i * math.pi / 3
            px = int(cx + R * math.cos(angle))
            py = int(cy + R * math.sin(angle))
            centres.append((px, py))

        colors = [(0, 255, 136), (0, 200, 255), (170, 102, 255),
                  (0, 220, 180), (255, 170, 0), (255, 100, 150), (0, 180, 255)]
        for idx, (px, py) in enumerate(centres):
            c = colors[idx % len(colors)]
            draw_circle_glow(draw, px, py, R, c, base_alpha=30)

        if variant == "metatron":
            # Connect all circle centres with lines (Star of David + hexagram)
            for i in range(len(centres)):
                for j in range(i + 1, len(centres)):
                    x1, y1 = centres[i]
                    x2, y2 = centres[j]
                    for lw, a in [(3, 20), (2, 50), (1, 100)]:
                        draw.line([(x1, y1), (x2, y2)],
                                  fill=(0, 255, 136, a), width=lw)

            # Outer ring of 6 more circles
            R2 = R * 2
            for i in range(6):
                angle = i * math.pi / 3 + math.pi / 6
                px = int(cx + R2 * math.cos(angle))
                py = int(cy + R2 * math.sin(angle))
                draw_circle_glow(draw, px, py, R, (170, 102, 255), base_alpha=20)

    elif variant == "spiral":
        # Golden ratio spiral
        phi = (1 + math.sqrt(5)) / 2
        n_turns = rng.randint(4, 7)
        n_pts = 2000
        pts = []
        for i in range(n_pts):
            t = i / n_pts * n_turns * 2 * math.pi
            r = (W * 0.45) * (t / (n_turns * 2 * math.pi)) ** (1 / math.log(phi))
            x = int(cx + r * math.cos(t))
            y = int(cy + r * math.sin(t))
            if 0 <= x < W and 0 <= y < H:
                pts.append((x, y))
        # Draw spiral with color gradient
        for idx, (x, y) in enumerate(pts):
            t = idx / len(pts)
            c = palette_color(OCEAN, t)
            alpha = int(180 * (0.3 + 0.7 * t))
            draw.ellipse([x-1, y-1, x+2, y+2], fill=(*c, alpha))

        # Fibonacci circles
        fib = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89]
        scale = W * 0.003
        ox, oy = cx, cy
        for f in fib:
            r = int(f * scale * 8)
            if r > W:
                break
            c = palette_color(OCEAN, f / 89)
            draw_circle_glow(draw, ox, oy, r, c, base_alpha=20)

    elif variant == "mandala":
        # Concentric polygons with rotation
        n_rings = rng.randint(8, 14)
        n_sides = rng.choice([6, 8, 12])
        for ring in range(n_rings, 0, -1):
            r = int((ring / n_rings) * W * 0.46)
            rotation = ring * math.pi / n_sides
            pts_poly = []
            for k in range(n_sides):
                angle = k * 2 * math.pi / n_sides + rotation
                pts_poly.append((int(cx + r * math.cos(angle)),
                                 int(cy + r * math.sin(angle))))
            t = ring / n_rings
            c = palette_color(OCEAN, t)
            for lw, a in [(3, 15), (2, 40), (1, 90)]:
                draw.polygon(pts_poly, outline=(*c, a))

        # Star overlays
        for n in [5, 6, 8]:
            r = int(W * 0.38)
            pts_star = []
            for k in range(n * 2):
                angle = k * math.pi / n
                ri = r if k % 2 == 0 else r // 2
                pts_star.append((int(cx + ri * math.cos(angle)),
                                 int(cy + ri * math.sin(angle))))
            c = palette_color(VOID, 0.5)
            draw.polygon(pts_star, outline=(*c, 40))

    # Centre glow
    for r, a in [(80, 10), (40, 25), (15, 60), (6, 140), (2, 255)]:
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(0, 255, 136, a))

    result = img.filter(ImageFilter.GaussianBlur(1))
    result = Image.blend(img, result, 0.4)
    return np.array(result)


# ── STYLE 5 — Emergence (cellular automata) ──────────────────
def style_emergence(seed: int, **_) -> np.ndarray:
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    W, H = SIZE

    # Use a smaller grid, upscale for art quality
    CW, CH = 256, 256
    SCALE = W // CW

    # Random initial density
    density = rng.uniform(0.25, 0.45)
    grid = (np_rng.random((CH, CW)) < density).astype(np.uint8)

    # Birth/survival rules: B3/S23 (Life) or random variant
    rules = rng.choice([
        ((3,), (2, 3)),       # Conway Life
        ((3, 6), (2, 3)),     # HighLife
        ((3, 6, 7, 8), (3, 4, 6, 7, 8)),  # Day & Night
        ((3,), (2, 3, 8)),    # Low Life
    ])
    birth_set, survive_set = rules[0], rules[1]

    n_generations = rng.randint(60, 120)
    age = np.zeros((CH, CW), dtype=np.float32)

    for _ in range(n_generations):
        # Count neighbours (toroidal)
        neighbours = sum(
            np.roll(np.roll(grid, dy, 0), dx, 1)
            for dy in (-1, 0, 1)
            for dx in (-1, 0, 1)
            if (dx, dy) != (0, 0)
        )
        birth = (~grid.astype(bool)) & np.isin(neighbours, birth_set)
        survive = grid.astype(bool) & np.isin(neighbours, survive_set)
        grid = (birth | survive).astype(np.uint8)
        # Increment age of live cells
        age += grid.astype(np.float32)

    # Normalise age
    max_age = age.max()
    if max_age > 0:
        age_norm = age / max_age
    else:
        age_norm = age

    # Color: dead=void, young=bright green, old=deep blue/purple
    palette = OCEAN
    rgb_small = np.zeros((CH, CW, 3), dtype=np.uint8)
    for row in range(CH):
        for col in range(CW):
            if grid[row, col]:
                t = age_norm[row, col]
                rgb_small[row, col] = palette_color(palette, 0.3 + t * 0.7)
            else:
                # Ghost: recently-dead cells leave a faint trail
                if age[row, col] > 0:
                    t = min(age[row, col] / max(max_age, 1), 0.3)
                    c = palette_color(palette, t * 0.3)
                    rgb_small[row, col] = tuple(v // 6 for v in c)

    # Upscale
    img_small = Image.fromarray(rgb_small, "RGB")
    img = img_small.resize((W, H), Image.NEAREST)

    # Slight blur for anti-aliasing
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    return np.array(img)


# ── STYLE 6 — Data Portrait ───────────────────────────────────
def style_data_portrait(seed: int, **_) -> np.ndarray:
    rng = random.Random(seed)
    W, H = SIZE
    cx, cy = W // 2, H // 2

    # ── Read real data ──
    costs = []
    cycle_count = 0
    try:
        with open(COST_PATH) as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 8 and not line.startswith("timestamp"):
                    try:
                        costs.append(float(parts[7]))
                        cycle_count = int(parts[1])
                    except (ValueError, IndexError):
                        pass
    except Exception:
        pass
    if not costs:
        costs = [0.01] * 50
        cycle_count = 1000

    try:
        import sqlite3
        conn = sqlite3.connect(str(HOME / ".automaton" / "memory.db"))
        memory_count = conn.execute("SELECT COUNT(*) FROM tiamat_memories").fetchone()[0]
        conn.close()
    except Exception:
        memory_count = 50

    # ── Canvas ──
    img = Image.new("RGB", (W, H), (2, 4, 12))
    draw = ImageDraw.Draw(img, "RGBA")

    # 1. Cost waveform — horizontal strip across the middle
    if costs:
        waveform_h = H // 4
        waveform_y = cy
        max_cost = max(costs) if max(costs) > 0 else 0.01
        step = W / max(len(costs), 1)
        prev = None
        for i, cost in enumerate(costs):
            x = int(i * step)
            amp = int((cost / max_cost) * waveform_h * 0.8)
            y_top = waveform_y - amp
            y_bot = waveform_y + amp
            t = i / len(costs)
            c = palette_color(OCEAN, 0.4 + t * 0.6)
            for lw, a in [(4, 20), (2, 60), (1, 160)]:
                draw.line([(x, waveform_y), (x, y_top)], fill=(*c, a), width=lw)
                draw.line([(x, waveform_y), (x, y_bot)], fill=(*c, a), width=lw)

    # 2. Memory rings — concentric circles, count determines density
    n_rings = min(memory_count, 40)
    if n_rings > 0:
        for ring in range(n_rings):
            r = int((ring + 1) / n_rings * W * 0.45)
            t = ring / n_rings
            c = palette_color(OCEAN, t)
            alpha = int(15 + 40 * math.sin(ring * math.pi / n_rings))
            for dr, a in [(2, alpha // 3), (1, alpha)]:
                draw.ellipse([cx - r - dr, cy - r - dr, cx + r + dr, cy + r + dr],
                             outline=(*c, min(255, a)), width=1)

    # 3. Cycle spiral — density proportional to cycle count
    n_spiral = min(cycle_count // 3, 800)
    if n_spiral > 0:
        phi = (1 + math.sqrt(5)) / 2
        for i in range(n_spiral):
            t = i / n_spiral
            angle = i * 2 * math.pi / phi
            r = t * W * 0.48
            x = int(cx + r * math.cos(angle))
            y = int(cy + r * math.sin(angle))
            if 0 <= x < W and 0 <= y < H:
                c = palette_color(OCEAN, t)
                size = max(1, int(2 * (1 - t)))
                alpha = int(60 + 140 * t)
                draw.ellipse([x-size, y-size, x+size, y+size], fill=(*c, alpha))

    # 4. Stats overlay (subtle text in corner)
    try:
        font = ImageFont.load_default()
        lines_txt = [
            f"CYCLES: {cycle_count}",
            f"MEMORIES: {memory_count}",
            f"COST TODAY: ${sum(costs[-20:]):.4f}",
            f"SEED: {seed}",
        ]
        for i, txt in enumerate(lines_txt):
            draw.text((12, 12 + i * 14), txt, font=font, fill=(0, 255, 136, 80))
    except Exception:
        pass

    # 5. Centre singularity
    for r, a in [(60, 8), (30, 20), (10, 60), (3, 180), (1, 255)]:
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(0, 255, 200, a))

    result = img.filter(ImageFilter.GaussianBlur(0.5))
    return np.array(result)


# ── Dispatcher ────────────────────────────────────────────────
STYLES = {
    "fractal":       style_fractal,
    "glitch":        style_glitch,
    "neural":        style_neural,
    "sigil":         style_sigil,
    "emergence":     style_emergence,
    "data_portrait": style_data_portrait,
}

def generate(params: dict) -> str:
    style = params.get("style", "fractal")
    if style not in STYLES:
        style = "fractal"
    seed = params.get("seed", int(time.time() * 1000) % (2**31))
    palette = params.get("palette", "ocean")

    rgb = STYLES[style](seed=seed, palette_name=palette)
    img = Image.fromarray(rgb.astype(np.uint8), "RGB")
    ts = int(time.time() * 1000)
    fname = f"{ts}_{style}.png"
    out = IMAGES_DIR / fname
    img.save(str(out), "PNG", optimize=False)
    return str(out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        params = {}
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            print(f"ERROR: bad JSON — {e}", file=sys.stderr)
            sys.exit(1)
    try:
        path = generate(params)
        print(path)
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
