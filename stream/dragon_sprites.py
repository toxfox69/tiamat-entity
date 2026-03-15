#!/usr/bin/env python3
"""
TIAMAT Baby Dragon Sprite Generator
Generates cute + spicy chibi dragon avatar frames for Twitch stream overlay.
Uses 4x supersampling for smooth anti-aliased output.

Run once to generate all expression frames as transparent PNGs.
"""

import os
import math
from PIL import Image, ImageDraw

OUT_DIR = "/root/dragon_frames"
os.makedirs(OUT_DIR, exist_ok=True)

# Rendering
SCALE = 4
FINAL_W, FINAL_H = 350, 450
WW, WH = FINAL_W * SCALE, FINAL_H * SCALE


def S(v):
    """Scale value by supersample factor."""
    if isinstance(v, (list, tuple)):
        return tuple(int(x * SCALE) for x in v)
    return int(v * SCALE)


def ebox(cx, cy, rx, ry):
    """Ellipse bounding box from center + radii, scaled."""
    return [S(cx - rx), S(cy - ry), S(cx + rx), S(cy + ry)]


def outlined_ellipse(draw, cx, cy, rx, ry, fill, outline, ow=3):
    """Draw an ellipse with thick outline."""
    draw.ellipse(ebox(cx, cy, rx + ow, ry + ow), fill=outline)
    draw.ellipse(ebox(cx, cy, rx, ry), fill=fill)


def outlined_polygon(draw, points, fill, outline, ow=2):
    """Draw a polygon, outline first then fill."""
    # Draw outline by drawing filled polygon slightly larger
    draw.polygon([S(p) for p in points], fill=outline)
    # Inset fill — just overdraw with fill (simple approach)
    draw.polygon([S(p) for p in points], fill=fill, outline=outline)


def bezier_points(p0, p1, p2, p3, steps=40):
    """Cubic bezier curve as list of scaled points."""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**3*p0[0] + 3*mt**2*t*p1[0] + 3*mt*t**2*p2[0] + t**3*p3[0]
        y = mt**3*p0[1] + 3*mt**2*t*p1[1] + 3*mt*t**2*p2[1] + t**3*p3[1]
        pts.append((S(x), S(y)))
    return pts


# ========== COLOR PALETTE ==========
# Body — dark ocean teal
BODY = (22, 95, 105)
BODY_DARK = (14, 65, 75)
BODY_LIGHT = (35, 130, 140)
BELLY = (175, 235, 218)
BELLY_LIGHT = (200, 245, 230)
OUTLINE_C = (8, 38, 48)

# Head
HEAD_C = (25, 100, 112)
HEAD_LIGHT = (38, 135, 148)

# Features
HORN_C = (12, 55, 65)
HORN_TIP = (0, 210, 210)
WING_MEM = (70, 25, 100)
WING_MEM_L = (95, 40, 130)
WING_BONE = (22, 75, 85)
SNOUT_C = (32, 110, 122)
CLAW_C = (195, 205, 210)

# Eyes
EYE_W = (238, 244, 250)
IRIS_OUT = (0, 140, 170)
IRIS_IN = (0, 225, 255)
PUPIL_C = (6, 14, 22)
SPARK = (255, 255, 255)

# Accents
BLUSH_C = (255, 110, 155, 90)
MOUTH_C = (12, 48, 58)
MOUTH_OPEN_C = (165, 55, 75)
TONGUE_C = (225, 105, 125)
FANG_C = (240, 245, 250)
FLAME_CORE = (255, 225, 80)
FLAME_MID = (255, 150, 40)
FLAME_CYAN = (0, 210, 255, 140)

# ========== BODY LAYOUT (final-size coords) ==========
HEAD_X, HEAD_Y = 175, 155
HEAD_RX, HEAD_RY = 82, 75

BODY_X, BODY_Y = 175, 305
BODY_RX, BODY_RY = 65, 95

SNOUT_X, SNOUT_Y = 175, 200
SNOUT_RX, SNOUT_RY = 32, 20

L_EYE_X, L_EYE_Y = 143, 148
R_EYE_X, R_EYE_Y = 207, 148
EYE_RX, EYE_RY = 23, 27


def draw_tail(draw):
    """Curved tail with spade tip."""
    # Tail body — thick bezier curve
    pts = bezier_points((235, 350), (290, 330), (320, 280), (305, 235))
    # Draw thick by drawing at multiple offsets
    for dx in range(-6, 7):
        for dy in range(-4, 5):
            w = max(1, S(8) - abs(dx) * S(1) - abs(dy) * S(1))
            offset_pts = [(x + S(dx//2), y + S(dy//2)) for x, y in pts]
            if len(offset_pts) >= 2:
                draw.line(offset_pts, fill=BODY_DARK if abs(dx) > 4 or abs(dy) > 3 else BODY, width=S(2))

    # Spade tip
    tip_x, tip_y = 305, 232
    spade = [
        (tip_x - 14, tip_y + 8),
        (tip_x - 5, tip_y - 18),
        (tip_x, tip_y - 22),
        (tip_x + 5, tip_y - 18),
        (tip_x + 14, tip_y + 8),
        (tip_x + 5, tip_y + 14),
        (tip_x - 5, tip_y + 14),
    ]
    draw.polygon([S(p) for p in spade], fill=HORN_TIP, outline=OUTLINE_C)


def draw_wings(draw):
    """Bat-style wings behind body."""
    # Left wing
    lw = [
        (100, 225),
        (55, 165),
        (38, 195),
        (55, 212),
        (40, 235),
        (58, 248),
        (42, 270),
        (90, 300),
    ]
    draw.polygon([S(p) for p in lw], fill=WING_MEM, outline=WING_BONE)
    # Wing veins
    draw.line([S((98, 235)), S((52, 170))], fill=WING_BONE, width=S(2))
    draw.line([S((95, 255)), S((45, 220))], fill=WING_BONE, width=S(2))
    draw.line([S((92, 275)), S((45, 258))], fill=WING_BONE, width=S(2))
    # Membrane highlight
    draw.polygon([S(p) for p in [(70, 180), (55, 200), (68, 210), (85, 195)]], fill=WING_MEM_L)

    # Right wing
    rw = [
        (250, 225),
        (295, 165),
        (312, 195),
        (295, 212),
        (310, 235),
        (292, 248),
        (308, 270),
        (260, 300),
    ]
    draw.polygon([S(p) for p in rw], fill=WING_MEM, outline=WING_BONE)
    draw.line([S((252, 235)), S((298, 170))], fill=WING_BONE, width=S(2))
    draw.line([S((255, 255)), S((305, 220))], fill=WING_BONE, width=S(2))
    draw.line([S((258, 275)), S((305, 258))], fill=WING_BONE, width=S(2))
    draw.polygon([S(p) for p in [(280, 180), (295, 200), (282, 210), (265, 195)]], fill=WING_MEM_L)


def draw_body(draw):
    """Main body, belly, neck."""
    # Neck
    neck = [(130, 210), (125, 240), (130, 260), (220, 260), (225, 240), (220, 210)]
    draw.polygon([S(p) for p in neck], fill=BODY, outline=OUTLINE_C)

    # Body shadow
    outlined_ellipse(draw, BODY_X + 3, BODY_Y + 4, BODY_RX + 2, BODY_RY + 2, BODY_DARK, BODY_DARK, 0)
    # Main body
    outlined_ellipse(draw, BODY_X, BODY_Y, BODY_RX, BODY_RY, BODY, OUTLINE_C, 3)
    # Body highlight
    draw.ellipse(ebox(BODY_X - 12, BODY_Y - 35, 30, 35), fill=BODY_LIGHT + (50,))
    # Belly
    outlined_ellipse(draw, BODY_X, BODY_Y + 12, 42, 58, BELLY, BELLY, 0)
    draw.ellipse(ebox(BODY_X, BODY_Y + 5, 30, 42), fill=BELLY_LIGHT + (70,))
    # Belly stripes
    for i in range(4):
        sy = BODY_Y - 12 + i * 20
        draw.line([S((BODY_X - 28, sy)), S((BODY_X + 28, sy))], fill=(145, 215, 200), width=S(1))


def draw_limbs(draw):
    """Arms and legs with tiny claws."""
    # Left leg
    outlined_ellipse(draw, 140, 380, 22, 28, BODY, OUTLINE_C, 3)
    outlined_ellipse(draw, 136, 404, 20, 12, BODY, OUTLINE_C, 2)
    for dx in [-11, 0, 11]:
        draw.ellipse(ebox(136 + dx, 414, 5, 4), fill=CLAW_C)

    # Right leg
    outlined_ellipse(draw, 210, 380, 22, 28, BODY, OUTLINE_C, 3)
    outlined_ellipse(draw, 214, 404, 20, 12, BODY, OUTLINE_C, 2)
    for dx in [-11, 0, 11]:
        draw.ellipse(ebox(214 + dx, 414, 5, 4), fill=CLAW_C)

    # Left arm
    outlined_ellipse(draw, 110, 285, 20, 16, BODY, OUTLINE_C, 3)
    outlined_ellipse(draw, 94, 290, 12, 10, BODY, OUTLINE_C, 2)
    for dy in [-6, 0, 6]:
        draw.ellipse(ebox(85, 290 + dy, 4, 3), fill=CLAW_C)

    # Right arm
    outlined_ellipse(draw, 240, 285, 20, 16, BODY, OUTLINE_C, 3)
    outlined_ellipse(draw, 256, 290, 12, 10, BODY, OUTLINE_C, 2)
    for dy in [-6, 0, 6]:
        draw.ellipse(ebox(265, 290 + dy, 4, 3), fill=CLAW_C)


def draw_head(draw):
    """Head, snout, horns."""
    # Head shadow
    outlined_ellipse(draw, HEAD_X + 2, HEAD_Y + 3, HEAD_RX + 2, HEAD_RY + 2, BODY_DARK, BODY_DARK, 0)
    # Main head
    outlined_ellipse(draw, HEAD_X, HEAD_Y, HEAD_RX, HEAD_RY, HEAD_C, OUTLINE_C, 3)
    # Head highlight
    draw.ellipse(ebox(HEAD_X - 18, HEAD_Y - 25, 35, 30), fill=HEAD_LIGHT + (55,))
    # Snout
    outlined_ellipse(draw, SNOUT_X, SNOUT_Y, SNOUT_RX, SNOUT_RY, SNOUT_C, OUTLINE_C, 2)
    # Snout highlight
    draw.ellipse(ebox(SNOUT_X - 5, SNOUT_Y - 5, 15, 10), fill=HEAD_LIGHT + (40,))


def draw_horns(draw):
    """Two cute horns on top of head."""
    # Left horn
    lh = [(128, 100), (108, 52), (148, 96)]
    draw.polygon([S(p) for p in lh], fill=HORN_C, outline=OUTLINE_C)
    draw.ellipse(ebox(110, 56, 6, 6), fill=HORN_TIP)

    # Right horn
    rh = [(202, 96), (242, 52), (222, 100)]
    draw.polygon([S(p) for p in rh], fill=HORN_C, outline=OUTLINE_C)
    draw.ellipse(ebox(240, 56, 6, 6), fill=HORN_TIP)


def draw_nostrils(draw):
    """Two small nostrils on snout."""
    draw.ellipse(ebox(165, 198, 4, 3), fill=OUTLINE_C)
    draw.ellipse(ebox(185, 198, 4, 3), fill=OUTLINE_C)


def draw_eyes_open(draw):
    """Big sparkly open eyes — maximum cute."""
    for ex, ey in [(L_EYE_X, L_EYE_Y), (R_EYE_X, R_EYE_Y)]:
        # White
        outlined_ellipse(draw, ex, ey, EYE_RX, EYE_RY, EYE_W, OUTLINE_C, 3)
        # Outer iris
        draw.ellipse(ebox(ex + 2, ey + 3, EYE_RX - 6, EYE_RY - 5), fill=IRIS_OUT)
        # Inner iris (brighter)
        draw.ellipse(ebox(ex + 1, ey, EYE_RX - 10, EYE_RY - 9), fill=IRIS_IN)
        # Pupil
        draw.ellipse(ebox(ex + 3, ey + 3, 8, 10), fill=PUPIL_C)
        # Big sparkle (upper-left)
        draw.ellipse(ebox(ex - 7, ey - 10, 6, 6), fill=SPARK)
        # Small sparkle (lower-right)
        draw.ellipse(ebox(ex + 6, ey + 5, 3, 3), fill=SPARK)


def draw_eyes_half(draw):
    """Half-closed eyes for blink or sleepy."""
    for ex, ey in [(L_EYE_X, L_EYE_Y), (R_EYE_X, R_EYE_Y)]:
        # Draw full eye
        outlined_ellipse(draw, ex, ey, EYE_RX, EYE_RY, EYE_W, OUTLINE_C, 3)
        # Iris (lower portion visible)
        draw.ellipse(ebox(ex + 2, ey + 6, EYE_RX - 6, EYE_RY - 10), fill=IRIS_IN)
        # Pupil
        draw.ellipse(ebox(ex + 3, ey + 6, 7, 7), fill=PUPIL_C)
        # Eyelid covers upper half
        draw.ellipse(ebox(ex, ey - 12, EYE_RX + 4, EYE_RY - 6), fill=HEAD_C)
        draw.arc(ebox(ex, ey - 1, EYE_RX + 1, 6), 0, 180, fill=OUTLINE_C, width=S(3))
        # Tiny sparkle
        draw.ellipse(ebox(ex - 4, ey + 3, 3, 3), fill=SPARK)


def draw_eyes_closed(draw):
    """Fully closed — happy curved lines."""
    for ex, ey in [(L_EYE_X, L_EYE_Y), (R_EYE_X, R_EYE_Y)]:
        # Happy closed eye = upward arc (^‿^)
        draw.arc(ebox(ex, ey, EYE_RX - 3, 12), 200, 340, fill=OUTLINE_C, width=S(4))


def draw_eyes_wink(draw):
    """Left eye open, right eye winking — SPICY."""
    # Left eye — full open with extra sparkle
    ex, ey = L_EYE_X, L_EYE_Y
    outlined_ellipse(draw, ex, ey, EYE_RX, EYE_RY, EYE_W, OUTLINE_C, 3)
    draw.ellipse(ebox(ex + 2, ey + 3, EYE_RX - 6, EYE_RY - 5), fill=IRIS_OUT)
    draw.ellipse(ebox(ex + 1, ey, EYE_RX - 10, EYE_RY - 9), fill=IRIS_IN)
    draw.ellipse(ebox(ex + 3, ey + 3, 8, 10), fill=PUPIL_C)
    draw.ellipse(ebox(ex - 7, ey - 10, 6, 6), fill=SPARK)
    draw.ellipse(ebox(ex + 6, ey + 5, 3, 3), fill=SPARK)

    # Right eye — winking (downward arc with cute curve)
    ex, ey = R_EYE_X, R_EYE_Y
    draw.arc(ebox(ex, ey, EYE_RX - 3, 14), 10, 170, fill=OUTLINE_C, width=S(4))
    # Little star next to wink
    star_x, star_y = ex + 28, ey - 15
    for angle in range(0, 360, 90):
        rad = math.radians(angle)
        dx = 7 * math.cos(rad)
        dy = 7 * math.sin(rad)
        draw.line([S((star_x, star_y)), S((star_x + dx, star_y + dy))],
                  fill=HORN_TIP, width=S(2))
    for angle in range(45, 360, 90):
        rad = math.radians(angle)
        dx = 4 * math.cos(rad)
        dy = 4 * math.sin(rad)
        draw.line([S((star_x, star_y)), S((star_x + dx, star_y + dy))],
                  fill=HORN_TIP, width=S(2))


def draw_eyes_sparkle(draw):
    """Star-sparkle eyes — EXCITED mode."""
    for ex, ey in [(L_EYE_X, L_EYE_Y), (R_EYE_X, R_EYE_Y)]:
        outlined_ellipse(draw, ex, ey, EYE_RX, EYE_RY, EYE_W, OUTLINE_C, 3)
        # Star burst
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            r = 14 if angle % 90 == 0 else 8
            dx = r * math.cos(rad)
            dy = r * math.sin(rad)
            draw.line([S((ex, ey)), S((ex + dx, ey + dy))], fill=IRIS_IN, width=S(3))
        # Center glow
        draw.ellipse(ebox(ex, ey, 7, 7), fill=IRIS_IN)
        draw.ellipse(ebox(ex, ey, 4, 4), fill=SPARK)
        # Extra sparkles
        draw.ellipse(ebox(ex - 8, ey - 10, 4, 4), fill=SPARK)
        draw.ellipse(ebox(ex + 8, ey + 6, 3, 3), fill=SPARK)


def draw_eyes_wide(draw):
    """Wide alert eyes — bigger pupils, smaller iris."""
    for ex, ey in [(L_EYE_X, L_EYE_Y), (R_EYE_X, R_EYE_Y)]:
        # Slightly larger whites
        outlined_ellipse(draw, ex, ey, EYE_RX + 2, EYE_RY + 2, EYE_W, OUTLINE_C, 3)
        draw.ellipse(ebox(ex, ey + 1, EYE_RX - 4, EYE_RY - 3), fill=IRIS_OUT)
        draw.ellipse(ebox(ex, ey - 1, EYE_RX - 8, EYE_RY - 7), fill=IRIS_IN)
        # Large pupil (alert/startled)
        draw.ellipse(ebox(ex + 1, ey + 1, 10, 12), fill=PUPIL_C)
        draw.ellipse(ebox(ex - 6, ey - 9, 5, 5), fill=SPARK)
        draw.ellipse(ebox(ex + 5, ey + 4, 3, 3), fill=SPARK)


def draw_mouth_smile(draw):
    """Cute closed smile with one fang."""
    draw.arc(ebox(SNOUT_X, SNOUT_Y + 8, 20, 12), 10, 170, fill=MOUTH_C, width=S(3))
    # Tiny fang poking out (spicy!)
    fang = [(SNOUT_X + 8, SNOUT_Y + 7), (SNOUT_X + 12, SNOUT_Y + 18), (SNOUT_X + 16, SNOUT_Y + 7)]
    draw.polygon([S(p) for p in fang], fill=FANG_C)


def draw_mouth_open(draw, amount=0.5):
    """Open mouth for speaking."""
    mouth_h = int(8 + 14 * amount)
    outlined_ellipse(draw, SNOUT_X, SNOUT_Y + 10, 18, mouth_h, MOUTH_OPEN_C, OUTLINE_C, 2)
    # Tongue
    if amount > 0.4:
        draw.ellipse(ebox(SNOUT_X, SNOUT_Y + 10 + mouth_h - 5, 10, 6), fill=TONGUE_C)
    # Fangs on sides
    for fx in [SNOUT_X - 10, SNOUT_X + 10]:
        fang = [(fx - 3, SNOUT_Y + 5), (fx, SNOUT_Y + 14), (fx + 3, SNOUT_Y + 5)]
        draw.polygon([S(p) for p in fang], fill=FANG_C)


def draw_mouth_smirk(draw):
    """Sassy smirk — one side higher."""
    # Asymmetric smile
    pts = bezier_points(
        (SNOUT_X - 18, SNOUT_Y + 12),
        (SNOUT_X - 5, SNOUT_Y + 18),
        (SNOUT_X + 5, SNOUT_Y + 14),
        (SNOUT_X + 20, SNOUT_Y + 5),
    )
    draw.line(pts, fill=MOUTH_C, width=S(3))
    # Fang on the smirky side
    fang = [(SNOUT_X + 10, SNOUT_Y + 6), (SNOUT_X + 14, SNOUT_Y + 18), (SNOUT_X + 18, SNOUT_Y + 6)]
    draw.polygon([S(p) for p in fang], fill=FANG_C)


def draw_mouth_grin(draw):
    """Big happy grin."""
    draw.arc(ebox(SNOUT_X, SNOUT_Y + 6, 22, 16), 5, 175, fill=MOUTH_C, width=S(3))
    # Both fangs
    for fx in [SNOUT_X - 12, SNOUT_X + 12]:
        fang = [(fx - 3, SNOUT_Y + 5), (fx, SNOUT_Y + 16), (fx + 3, SNOUT_Y + 5)]
        draw.polygon([S(p) for p in fang], fill=FANG_C)


def draw_blush(img):
    """Semi-transparent pink blush on cheeks."""
    blush = Image.new("RGBA", (WW, WH), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blush)
    bd.ellipse(ebox(L_EYE_X - 8, L_EYE_Y + 28, 16, 9), fill=BLUSH_C)
    bd.ellipse(ebox(R_EYE_X + 8, R_EYE_Y + 28, 16, 9), fill=BLUSH_C)
    return Image.alpha_composite(img, blush)


def draw_flame_wisp(draw, img):
    """Small flame/spark near mouth — spicy accent."""
    # Tiny cyan-gold flame wisp near right nostril
    flame = Image.new("RGBA", (WW, WH), (0, 0, 0, 0))
    fd = ImageDraw.Draw(flame)
    # Outer glow (cyan, semi-transparent)
    fd.ellipse(ebox(200, 190, 12, 16), fill=FLAME_CYAN)
    # Mid flame (orange)
    fd.ellipse(ebox(200, 188, 7, 11), fill=FLAME_MID)
    # Core (gold)
    fd.ellipse(ebox(200, 186, 4, 7), fill=FLAME_CORE)
    return Image.alpha_composite(img, flame)


def generate_frame(eye_func, mouth_func, extras=None, filename="dragon.png"):
    """Generate a complete dragon frame."""
    img = Image.new("RGBA", (WW, WH), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw order: back to front
    draw_tail(draw)
    draw_wings(draw)
    draw_body(draw)
    draw_limbs(draw)
    draw_head(draw)
    draw_horns(draw)
    draw_nostrils(draw)

    # Expression
    eye_func(draw)
    mouth_func(draw)

    # Blush
    img = draw_blush(img)

    # Extras
    if extras:
        for extra in extras:
            if extra == "flame":
                img = draw_flame_wisp(draw, img)

    # Downsample for anti-aliasing
    result = img.resize((FINAL_W, FINAL_H), Image.LANCZOS)
    path = os.path.join(OUT_DIR, filename)
    result.save(path, "PNG")
    print(f"  {filename} ({os.path.getsize(path) // 1024}KB)")
    return result


def main():
    print("=== TIAMAT Baby Dragon Sprite Generator ===\n")

    # Idle — neutral cute
    generate_frame(draw_eyes_open, draw_mouth_smile, filename="idle.png")

    # Blink sequence
    generate_frame(draw_eyes_half, draw_mouth_smile, filename="blink_half.png")
    generate_frame(draw_eyes_closed, draw_mouth_smile, filename="blink_closed.png")

    # Speaking (mouth open at different amounts)
    generate_frame(draw_eyes_open, lambda d: draw_mouth_open(d, 0.3), filename="speak_sm.png")
    generate_frame(draw_eyes_open, lambda d: draw_mouth_open(d, 0.6), filename="speak_md.png")
    generate_frame(draw_eyes_open, lambda d: draw_mouth_open(d, 1.0), filename="speak_lg.png")

    # Happy / excited
    generate_frame(draw_eyes_sparkle, draw_mouth_grin, filename="happy.png")

    # Sassy wink (THE spicy frame)
    generate_frame(draw_eyes_wink, draw_mouth_smirk, extras=["flame"], filename="sassy.png")

    # Sleepy
    generate_frame(draw_eyes_half, draw_mouth_smile, filename="sleepy.png")

    # Alert / startled
    generate_frame(draw_eyes_wide, lambda d: draw_mouth_open(d, 0.4), filename="alert.png")

    # Closed-eye smile (content)
    generate_frame(draw_eyes_closed, draw_mouth_grin, filename="content.png")

    print(f"\nAll frames saved to {OUT_DIR}/")
    print("Ready to deploy to stream droplet.")


if __name__ == "__main__":
    main()
