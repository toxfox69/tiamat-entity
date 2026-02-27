#!/usr/bin/env python3
from PIL import Image, ImageDraw, ImageFont
import os, math

def create_icon(size):
    img = Image.new('RGB', (size, size), '#0a0a0f')
    draw = ImageDraw.Draw(img)

    # Gold gradient circle background
    cx, cy = size // 2, size // 2
    radius = int(size * 0.42)
    for r in range(radius, 0, -1):
        ratio = r / radius
        red = int(255 * (1 - ratio * 0.3))
        green = int(180 * (1 - ratio * 0.5))
        blue = int(0 + ratio * 20)
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(red, green, blue))

    # Sun rays
    ray_length = int(size * 0.48)
    for i in range(12):
        angle = math.radians(i * 30)
        x1 = cx + int(radius * 1.05 * math.cos(angle))
        y1 = cy + int(radius * 1.05 * math.sin(angle))
        x2 = cx + int(ray_length * math.cos(angle))
        y2 = cy + int(ray_length * math.sin(angle))
        width = max(1, size // 64)
        draw.line([x1, y1, x2, y2], fill='#FFD700', width=width)

    # Letter M in center
    font_size = int(size * 0.38)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), "M", font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((cx - tw//2, cy - th//2 - size//20), "M",
              fill='#0a0a0f', font=font)

    # Subtle glow ring
    draw.ellipse([cx-radius-2, cy-radius-2, cx+radius+2, cy+radius+2],
                 outline='#FFD700', width=max(1, size//96))

    return img

# Generate all required Android sizes
sizes = {
    'icon-48': 48,      # mdpi
    'icon-72': 72,      # hdpi
    'icon-96': 96,      # xhdpi
    'icon-144': 144,    # xxhdpi
    'icon-192': 192,    # xxxhdpi
    'icon-512': 512,    # Play Store
}

out_dir = '/root/entity/apps/daily-motivationals/icons'
os.makedirs(out_dir, exist_ok=True)

for name, size in sizes.items():
    icon = create_icon(size)
    path = f'{out_dir}/{name}.png'
    icon.save(path, 'PNG')
    print(f'Generated {name}.png ({size}x{size})')

print(f'\nAll icons saved to {out_dir}/')
print('Upload icon-512.png to Google Play Console')
