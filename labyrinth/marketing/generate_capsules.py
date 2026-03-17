#!/usr/bin/env python3
"""LABYRINTH: TIAMAT'S DESCENT — Steam Capsule Image Generator

Generates all required Steam capsule images using PIL:
  - Header Capsule: 460x215
  - Small Capsule: 231x87
  - Main Capsule: 616x353
  - Hero: 3840x1240
  - Logo: 640x360
  - Library Hero: 600x900
"""

import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# Paths
CONCEPT_ART = '/tmp/dragon/venice_concept.png'
TIAMAT_SPRITE = '/tmp/dragon/tiamat_sprite.png'
SPRITE_FALLBACK = '/opt/tiamat-stream/hud/assets/sprite-tiamat.png'
OUTPUT_DIR = '/root/labyrinth-steam/marketing/capsules'

# Colors
GREEN = (0, 255, 65)
DARK_GREEN = (0, 170, 42)
GOLD = (255, 221, 0)
BLACK = (0, 0, 0)
DARK_BG = (10, 10, 10)

# Font
def get_font(size):
    """Try to load a bold font, fall back to default."""
    font_paths = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()

def load_background():
    """Load concept art, fallback to solid dark."""
    if os.path.exists(CONCEPT_ART):
        return Image.open(CONCEPT_ART).convert('RGBA')
    # Create dark gradient fallback
    img = Image.new('RGBA', (1920, 1080), DARK_BG)
    draw = ImageDraw.Draw(img)
    for y in range(1080):
        r = int(10 + (y / 1080) * 20)
        g = int(5 + (y / 1080) * 15)
        b = int(15 + (y / 1080) * 10)
        draw.line([(0, y), (1920, y)], fill=(r, g, b, 255))
    return img

def load_sprite():
    """Load TIAMAT sprite."""
    for path in [TIAMAT_SPRITE, SPRITE_FALLBACK]:
        if os.path.exists(path):
            return Image.open(path).convert('RGBA')
    return None

def add_gradient_overlay(img, direction='bottom', intensity=0.7):
    """Add dark gradient for text readability."""
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img.size

    if direction == 'bottom':
        for y in range(h):
            alpha = int((y / h) ** 1.5 * 255 * intensity)
            draw.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))
    elif direction == 'full':
        for y in range(h):
            # Darker at top and bottom, lighter in middle
            t = abs(y - h / 2) / (h / 2)
            alpha = int(t ** 1.2 * 255 * intensity)
            draw.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))
    elif direction == 'top':
        for y in range(h):
            alpha = int(((h - y) / h) ** 1.5 * 255 * intensity)
            draw.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))

    return Image.alpha_composite(img, overlay)

def add_scanlines(img, spacing=3, alpha=30):
    """Add CRT scanline effect."""
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(0, img.size[1], spacing):
        draw.line([(0, y), (img.size[0], y)], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(img, overlay)

def add_vignette(img, intensity=0.6):
    """Add vignette (dark corners) effect."""
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img.size
    cx, cy = w / 2, h / 2
    max_dist = (cx**2 + cy**2) ** 0.5

    for y in range(h):
        for x in range(0, w, 4):  # Step 4 for performance
            dist = ((x - cx)**2 + (y - cy)**2) ** 0.5
            t = (dist / max_dist) ** 2
            alpha = int(t * 255 * intensity)
            draw.rectangle([(x, y), (x + 3, y)], fill=(0, 0, 0, min(255, alpha)))

    return Image.alpha_composite(img, overlay)

def draw_title(draw, text, center_x, center_y, font, color=GREEN, glow=True):
    """Draw title text with optional glow effect."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = center_x - tw // 2
    y = center_y - th // 2

    if glow:
        # Glow layers
        for offset in [3, 2, 1]:
            glow_color = (color[0] // 4, color[1] // 4, color[2] // 4, 80)
            draw.text((x - offset, y), text, font=font, fill=glow_color)
            draw.text((x + offset, y), text, font=font, fill=glow_color)
            draw.text((x, y - offset), text, font=font, fill=glow_color)
            draw.text((x, y + offset), text, font=font, fill=glow_color)

    # Shadow
    draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 200))
    # Main text
    draw.text((x, y), text, font=font, fill=color)

def add_border(img, color=GREEN, width=2):
    """Add a subtle border."""
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img.size
    border_color = (color[0], color[1], color[2], 100)
    for i in range(width):
        draw.rectangle([(i, i), (w - 1 - i, h - 1 - i)], outline=border_color)
    return Image.alpha_composite(img, overlay)

def generate_capsule(width, height, name, include_sprite=True, include_subtitle=True):
    """Generate a single capsule image."""
    bg = load_background()

    # Resize and crop to fit
    bg_ratio = bg.width / bg.height
    target_ratio = width / height

    if bg_ratio > target_ratio:
        # Background is wider — crop sides
        new_h = bg.height
        new_w = int(new_h * target_ratio)
        left = (bg.width - new_w) // 2
        bg = bg.crop((left, 0, left + new_w, new_h))
    else:
        # Background is taller — crop top/bottom
        new_w = bg.width
        new_h = int(new_w / target_ratio)
        top = (bg.height - new_h) // 2
        bg = bg.crop((0, top, new_w, top + new_h))

    bg = bg.resize((width, height), Image.Resampling.LANCZOS)

    # Darken the background
    enhancer = ImageEnhance.Brightness(bg)
    bg = enhancer.enhance(0.5)

    # Blur slightly for depth
    bg = bg.filter(ImageFilter.GaussianBlur(radius=max(1, width // 200)))

    # Add gradient overlay
    bg = add_gradient_overlay(bg, 'full', 0.6)

    # Add sprite
    if include_sprite:
        sprite = load_sprite()
        if sprite:
            # Scale sprite to ~40% of image height
            sprite_h = int(height * 0.55)
            sprite_w = int(sprite.width * (sprite_h / sprite.height))
            sprite = sprite.resize((sprite_w, sprite_h), Image.Resampling.LANCZOS)

            # Position: right side for wide images, center for tall
            if width > height:
                sx = width - sprite_w - int(width * 0.05)
            else:
                sx = (width - sprite_w) // 2
            sy = height - sprite_h - int(height * 0.05)

            bg.paste(sprite, (sx, sy), sprite)

    # Add scanlines
    bg = add_scanlines(bg, spacing=max(2, height // 60), alpha=20)

    # Draw title text
    draw = ImageDraw.Draw(bg)

    # Title size based on image dimensions
    title_size = max(12, min(width // 10, height // 4))
    sub_size = max(8, title_size // 2)

    title_font = get_font(title_size)
    sub_font = get_font(sub_size)

    # Title position
    title_y = int(height * 0.25) if include_sprite else int(height * 0.4)
    draw_title(draw, 'LABYRINTH', width // 2, title_y, title_font, GREEN)

    if include_subtitle:
        sub_y = title_y + title_size + int(height * 0.03)
        draw_title(draw, "TIAMAT'S DESCENT", width // 2, sub_y, sub_font, GOLD, glow=False)

    # Add border
    bg = add_border(bg, GREEN, max(1, width // 300))

    # Convert to RGB for saving
    result = Image.new('RGB', (width, height), DARK_BG)
    result.paste(bg, (0, 0), bg if bg.mode == 'RGBA' else None)

    return result


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    capsules = [
        (460, 215, 'header_capsule', True, True),
        (231, 87, 'small_capsule', False, False),
        (616, 353, 'main_capsule', True, True),
        (3840, 1240, 'hero', True, True),
        (640, 360, 'logo', True, True),
        (600, 900, 'library_hero', True, True),
    ]

    for width, height, name, sprite, subtitle in capsules:
        print(f'Generating {name} ({width}x{height})...')
        img = generate_capsule(width, height, name, sprite, subtitle)
        out_path = os.path.join(OUTPUT_DIR, f'{name}.png')
        img.save(out_path, 'PNG', optimize=True)
        print(f'  -> {out_path} ({os.path.getsize(out_path):,} bytes)')

    print(f'\nAll {len(capsules)} capsule images generated in {OUTPUT_DIR}')


if __name__ == '__main__':
    main()
