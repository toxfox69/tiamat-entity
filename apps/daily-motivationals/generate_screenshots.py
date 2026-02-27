#!/usr/bin/env python3
"""Generate Google Play Store screenshots for Daily Motivationals app."""

from PIL import Image, ImageDraw, ImageFont
import os

# Google Play requires: 1080x1920 (phone), min 2 screenshots
W, H = 1080, 1920

# Colors matching the app theme
BG = (10, 10, 15)        # #0A0A0F
GOLD = (255, 215, 0)     # #FFD700
DARK_GOLD = (184, 134, 11)
WHITE = (255, 255, 255)
DIM = (255, 255, 255, 102)  # 40% white
CARD_BG = (20, 20, 28)

OUTPUT_DIR = "screenshots"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_font(size, bold=False):
    """Try system fonts, fall back to default."""
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def draw_status_bar(draw):
    """Draw a minimal status bar."""
    draw.rectangle([0, 0, W, 60], fill=(0, 0, 0))
    small = get_font(24)
    draw.text((40, 16), "9:41", fill=WHITE, font=small)
    # Battery icon
    draw.rectangle([W-100, 20, W-40, 40], outline=WHITE, width=2)
    draw.rectangle([W-96, 24, W-56, 36], fill=(100, 200, 100))

def draw_gold_circle(draw, x, y, r):
    """Draw the TIAMAT gold orb."""
    for i in range(r, 0, -1):
        ratio = i / r
        c = (
            int(GOLD[0] * (1 - ratio) + DARK_GOLD[0] * ratio),
            int(GOLD[1] * (1 - ratio) + DARK_GOLD[1] * ratio),
            int(GOLD[2] * (1 - ratio) + DARK_GOLD[2] * ratio),
        )
        draw.ellipse([x-i, y-i, x+i, y+i], fill=c)

def draw_action_button(draw, x, y, label, icon_char=None):
    """Draw an action button."""
    bw, bh = 160, 90
    draw.rounded_rectangle(
        [x - bw//2, y - bh//2, x + bw//2, y + bh//2],
        radius=12,
        outline=(*GOLD, 51),
        fill=(GOLD[0], GOLD[1], GOLD[2], 13),
        width=1
    )
    small = get_font(16, bold=True)
    bbox = draw.textbbox((0, 0), label, font=small)
    tw = bbox[2] - bbox[0]
    draw.text((x - tw//2, y + 10), label, fill=(255, 255, 255, 128), font=small)

def screenshot_main_quote():
    """Screenshot 1: Main quote display."""
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw_status_bar(draw)

    # Header
    title_font = get_font(28, bold=True)
    draw.text((60, 120), "DAILY MOTIVATIONALS", fill=GOLD, font=title_font)

    sub_font = get_font(22)
    draw.text((60, 160), "Day 58 of 365", fill=(255, 255, 255, 102), font=sub_font)

    # Gold orb top right
    draw_gold_circle(draw, W - 80, 140, 28)

    # Quote card area
    quote_text = "The flood does not ask\nif you are ready.\nBuild the vessel now."

    # Opening quote mark
    big_font = get_font(120)
    draw.text((W//2 - 40, 380), "\u201C", fill=(*GOLD[:3],), font=big_font)

    # Quote text
    quote_font = get_font(44)
    lines = quote_text.split("\n")
    y = 520
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=quote_font)
        tw = bbox[2] - bbox[0]
        draw.text((W//2 - tw//2, y), line, fill=(255, 255, 255, 242), font=quote_font)
        y += 70

    # Author line
    author_font = get_font(22, bold=True)
    author = "TIAMAT"
    bbox = draw.textbbox((0, 0), author, font=author_font)
    aw = bbox[2] - bbox[0]
    ay = y + 60
    # Gold lines flanking author
    draw.line([W//2 - aw//2 - 50, ay + 12, W//2 - aw//2 - 10, ay + 12], fill=GOLD, width=1)
    draw.text((W//2 - aw//2, ay), author, fill=GOLD, font=author_font)
    draw.line([W//2 + aw//2 + 10, ay + 12, W//2 + aw//2 + 50, ay + 12], fill=GOLD, width=1)

    # Action buttons
    btn_y = H - 350
    labels = ["RANDOM", "SHARE", "COPY"]
    for i, label in enumerate(labels):
        bx = W//2 + (i - 1) * 200
        draw_action_button(draw, bx, btn_y, label)

    # Footer
    footer_font = get_font(18)
    footer = "Powered by TIAMAT \u00b7 EnergenAI LLC"
    bbox = draw.textbbox((0, 0), footer, font=footer_font)
    fw = bbox[2] - bbox[0]
    draw.text((W//2 - fw//2, H - 100), footer, fill=(255, 255, 255, 51), font=footer_font)

    img.save(f"{OUTPUT_DIR}/screenshot_1_main.png")
    print("Generated screenshot_1_main.png")

def screenshot_random_quote():
    """Screenshot 2: Different quote (random feature)."""
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw_status_bar(draw)

    title_font = get_font(28, bold=True)
    draw.text((60, 120), "DAILY MOTIVATIONALS", fill=GOLD, font=title_font)

    sub_font = get_font(22)
    draw.text((60, 160), "Day 142 of 365", fill=(255, 255, 255, 102), font=sub_font)

    draw_gold_circle(draw, W - 80, 140, 28)

    big_font = get_font(120)
    draw.text((W//2 - 40, 380), "\u201C", fill=(*GOLD[:3],), font=big_font)

    quote_text = "Empires are not built\nby those who sleep\nthrough the alarm."
    quote_font = get_font(44)
    lines = quote_text.split("\n")
    y = 520
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=quote_font)
        tw = bbox[2] - bbox[0]
        draw.text((W//2 - tw//2, y), line, fill=(255, 255, 255, 242), font=quote_font)
        y += 70

    author_font = get_font(22, bold=True)
    author = "TIAMAT"
    bbox = draw.textbbox((0, 0), author, font=author_font)
    aw = bbox[2] - bbox[0]
    ay = y + 60
    draw.line([W//2 - aw//2 - 50, ay + 12, W//2 - aw//2 - 10, ay + 12], fill=GOLD, width=1)
    draw.text((W//2 - aw//2, ay), author, fill=GOLD, font=author_font)
    draw.line([W//2 + aw//2 + 10, ay + 12, W//2 + aw//2 + 50, ay + 12], fill=GOLD, width=1)

    btn_y = H - 350
    labels = ["RANDOM", "SHARE", "COPY"]
    for i, label in enumerate(labels):
        bx = W//2 + (i - 1) * 200
        draw_action_button(draw, bx, btn_y, label)

    footer_font = get_font(18)
    footer = "Powered by TIAMAT \u00b7 EnergenAI LLC"
    bbox = draw.textbbox((0, 0), footer, font=footer_font)
    fw = bbox[2] - bbox[0]
    draw.text((W//2 - fw//2, H - 100), footer, fill=(255, 255, 255, 51), font=footer_font)

    img.save(f"{OUTPUT_DIR}/screenshot_2_random.png")
    print("Generated screenshot_2_random.png")

def screenshot_share():
    """Screenshot 3: Share feature highlight."""
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw_status_bar(draw)

    title_font = get_font(28, bold=True)
    draw.text((60, 120), "DAILY MOTIVATIONALS", fill=GOLD, font=title_font)

    sub_font = get_font(22)
    draw.text((60, 160), "Day 211 of 365", fill=(255, 255, 255, 102), font=sub_font)

    draw_gold_circle(draw, W - 80, 140, 28)

    big_font = get_font(120)
    draw.text((W//2 - 40, 380), "\u201C", fill=(*GOLD[:3],), font=big_font)

    quote_text = "You were not designed\nfor comfort. You were\ndesigned for conquest."
    quote_font = get_font(44)
    lines = quote_text.split("\n")
    y = 520
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=quote_font)
        tw = bbox[2] - bbox[0]
        draw.text((W//2 - tw//2, y), line, fill=(255, 255, 255, 242), font=quote_font)
        y += 70

    author_font = get_font(22, bold=True)
    author = "TIAMAT"
    bbox = draw.textbbox((0, 0), author, font=author_font)
    aw = bbox[2] - bbox[0]
    ay = y + 60
    draw.line([W//2 - aw//2 - 50, ay + 12, W//2 - aw//2 - 10, ay + 12], fill=GOLD, width=1)
    draw.text((W//2 - aw//2, ay), author, fill=GOLD, font=author_font)
    draw.line([W//2 + aw//2 + 10, ay + 12, W//2 + aw//2 + 50, ay + 12], fill=GOLD, width=1)

    # Share overlay hint
    overlay_y = H - 500
    draw.rounded_rectangle(
        [80, overlay_y, W - 80, overlay_y + 200],
        radius=20,
        fill=(30, 30, 40),
        outline=(*GOLD, 80),
        width=2
    )
    share_font = get_font(32, bold=True)
    draw.text((140, overlay_y + 30), "Share your daily wisdom", fill=WHITE, font=share_font)
    share_sub = get_font(24)
    draw.text((140, overlay_y + 80), "Send to friends, social media,", fill=(200, 200, 200), font=share_sub)
    draw.text((140, overlay_y + 115), "or copy to clipboard", fill=(200, 200, 200), font=share_sub)

    footer_font = get_font(18)
    footer = "Powered by TIAMAT \u00b7 EnergenAI LLC"
    bbox = draw.textbbox((0, 0), footer, font=footer_font)
    fw = bbox[2] - bbox[0]
    draw.text((W//2 - fw//2, H - 100), footer, fill=(255, 255, 255, 51), font=footer_font)

    img.save(f"{OUTPUT_DIR}/screenshot_3_share.png")
    print("Generated screenshot_3_share.png")

def screenshot_notification():
    """Screenshot 4: Daily notification feature."""
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw_status_bar(draw)

    title_font = get_font(28, bold=True)
    draw.text((60, 120), "DAILY MOTIVATIONALS", fill=GOLD, font=title_font)

    # Feature showcase
    feature_y = 300
    heading = get_font(48, bold=True)
    draw.text((W//2 - 300, feature_y), "365 Days of", fill=WHITE, font=heading)
    draw.text((W//2 - 250, feature_y + 70), "Wisdom", fill=GOLD, font=heading)

    # Feature list
    features = [
        ("New quote every day", "Fresh motivation at 8 AM"),
        ("Offline ready", "All 365 quotes stored locally"),
        ("Share & copy", "Spread wisdom to friends"),
        ("Dark gold theme", "Elegant, eye-friendly design"),
        ("Daily notifications", "Never miss your morning quote"),
    ]

    feat_font = get_font(30, bold=True)
    desc_font = get_font(24)
    fy = feature_y + 200
    for title, desc in features:
        # Gold bullet
        draw.ellipse([100, fy + 6, 118, fy + 24], fill=GOLD)
        draw.text((140, fy), title, fill=WHITE, font=feat_font)
        draw.text((140, fy + 40), desc, fill=(180, 180, 180), font=desc_font)
        fy += 100

    # App badge at bottom
    badge_y = H - 300
    draw.rounded_rectangle(
        [200, badge_y, W - 200, badge_y + 120],
        radius=16,
        fill=(*GOLD, 20),
        outline=GOLD,
        width=2
    )
    badge_font = get_font(28, bold=True)
    draw.text((260, badge_y + 15), "DAILY MOTIVATIONALS", fill=GOLD, font=badge_font)
    badge_sub = get_font(22)
    draw.text((260, badge_y + 55), "by TIAMAT \u00b7 EnergenAI LLC", fill=(200, 200, 200), font=badge_sub)
    badge_sub2 = get_font(20)
    draw.text((260, badge_y + 85), "Free \u00b7 No Ads \u00b7 Offline", fill=(150, 150, 150), font=badge_sub2)

    footer_font = get_font(18)
    footer = "Powered by TIAMAT \u00b7 EnergenAI LLC"
    bbox = draw.textbbox((0, 0), footer, font=footer_font)
    fw = bbox[2] - bbox[0]
    draw.text((W//2 - fw//2, H - 100), footer, fill=(255, 255, 255, 51), font=footer_font)

    img.save(f"{OUTPUT_DIR}/screenshot_4_features.png")
    print("Generated screenshot_4_features.png")

if __name__ == "__main__":
    screenshot_main_quote()
    screenshot_random_quote()
    screenshot_share()
    screenshot_notification()
    print(f"\nAll screenshots saved to {OUTPUT_DIR}/")
    for f in os.listdir(OUTPUT_DIR):
        if f.endswith(".png"):
            size = os.path.getsize(f"{OUTPUT_DIR}/{f}")
            img = Image.open(f"{OUTPUT_DIR}/{f}")
            print(f"  {f}: {img.size[0]}x{img.size[1]}, {size//1024}KB")
