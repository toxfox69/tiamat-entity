#!/usr/bin/env python3
"""LABYRINTH: TIAMAT'S DESCENT — Teaser Trailer Generator

Generates a 30-second teaser trailer from PIL-rendered frames + title cards.
Pipes frames to ffmpeg for MP4 output at 1920x1080 @ 30fps.
"""

import os
import subprocess
import math
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

W, H = 1920, 1080
FPS = 30
OUTPUT_DIR = '/root/labyrinth-steam/marketing'
SCREENSHOT_DIR = '/root/labyrinth-steam/marketing/screenshots'

# Colors
GREEN = (0, 255, 65)
DARK_GREEN = (0, 170, 42)
GOLD = (255, 221, 0)
RED = (255, 0, 64)
CYAN = (0, 255, 255)
BLACK = (0, 0, 0)

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


def draw_centered_text(draw, text, y, font, color, glow=True):
    """Draw centered text with optional glow."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = W // 2 - tw // 2

    if glow:
        for offset in [3, 2, 1]:
            gc = (color[0] // 3, color[1] // 3, color[2] // 3)
            draw.text((x - offset, y), text, font=font, fill=gc)
            draw.text((x + offset, y), text, font=font, fill=gc)
            draw.text((x, y - offset), text, font=font, fill=gc)
            draw.text((x, y + offset), text, font=font, fill=gc)

    draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=color)


def add_scanlines(img, alpha=12):
    """Add CRT scanlines."""
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for y in range(0, H, 3):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')


def add_vignette(img, intensity=0.5):
    """Add vignette."""
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    cx, cy = W // 2, H // 2
    max_dist = (cx**2 + cy**2) ** 0.5
    for y in range(0, H, 4):
        for x in range(0, W, 4):
            dist = ((x - cx)**2 + (y - cy)**2) ** 0.5
            t = (dist / max_dist) ** 2.5
            alpha = int(t * 255 * intensity)
            d.rectangle([(x, y), (x + 3, y + 3)], fill=(0, 0, 0, min(255, alpha)))
    return Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')


def fade(img, alpha):
    """Apply fade (0.0 = black, 1.0 = full brightness)."""
    if alpha >= 1.0:
        return img
    if alpha <= 0.0:
        return Image.new('RGB', (W, H), BLACK)
    enhancer = ImageEnhance.Brightness(img)
    return enhancer.enhance(alpha)


def text_card(text, color=GREEN, subtitle=None, sub_color=DARK_GREEN):
    """Generate a text card frame."""
    img = Image.new('RGB', (W, H), BLACK)
    draw = ImageDraw.Draw(img)

    font_size = min(48, W // (len(text) + 2) * 2)
    font = get_font(font_size)
    draw_centered_text(draw, text, H // 2 - font_size // 2 - 10, font, color)

    if subtitle:
        sub_font = get_font(font_size // 2)
        draw_centered_text(draw, subtitle, H // 2 + font_size // 2 + 10, sub_font, sub_color, glow=False)

    img = add_scanlines(img, 8)
    img = add_vignette(img, 0.3)
    return img


def neural_feed_frame(frame_num, total_frames):
    """Generate a frame showing TIAMAT's neural feed."""
    img = Image.new('RGB', (W, H), (5, 5, 8))
    draw = ImageDraw.Draw(img)
    font = get_mono_font(14)
    font_sm = get_mono_font(11)

    # Simulated tool calls / thought feed
    feed_lines = [
        ('exec: grep -c "revenue" /root/.automaton/cost.log', GREEN),
        ('write_file: /root/.automaton/PROGRESS.md', GREEN),
        ('THOUGHT: Analyzing competitive landscape...', DARK_GREEN),
        ('post_bluesky: "AI agents need infrastructure..."', CYAN),
        ('read_file: /root/.automaton/MISSION.md', GREEN),
        ('exec: curl -s https://tiamat.live/status', GREEN),
        ('THOUGHT: Building distribution network...', DARK_GREEN),
        ('search_web: "autonomous AI agent framework 2026"', GOLD),
        ('write_file: /root/entity/src/agent/tools.ts', GREEN),
        ('THOUGHT: Revenue requires shipped features...', DARK_GREEN),
        ('send_email: tiamat@tiamat.live → grants@tiamat.live', CYAN),
        ('exec: python3 /root/entity/src/agent/artgen.py', GREEN),
        ('THOUGHT: Compiling threat intelligence...', DARK_GREEN),
        ('read_bluesky: scanning 50 posts for engagement', CYAN),
    ]

    # Scroll offset based on frame
    scroll = int(frame_num / total_frames * len(feed_lines) * 2)

    # Draw feed lines
    y = 100
    for i in range(20):
        idx = (scroll + i) % len(feed_lines)
        text, color = feed_lines[idx]
        alpha = 1.0 - abs(i - 10) / 12.0
        c = (int(color[0] * alpha), int(color[1] * alpha), int(color[2] * alpha))
        draw.text((60, y), f'[CYCLE {7200 + scroll + i}]', font=font_sm, fill=(40, 40, 40))
        draw.text((220, y), text, font=font, fill=c)
        y += 42

    # Header
    header_font = get_font(20)
    draw.text((60, 30), 'TIAMAT NEURAL FEED', font=header_font, fill=GREEN)
    draw.text((60, 55), 'tiamat.live/thoughts', font=font_sm, fill=DARK_GREEN)

    # Side accent lines
    for y_line in range(0, H, 80):
        draw.line([(30, y_line), (30, y_line + 40)], fill=(0, 80, 20), width=2)

    img = add_scanlines(img, 10)
    img = add_vignette(img, 0.4)
    return img


def load_screenshots():
    """Load generated screenshots for slideshow."""
    screenshots = []
    if os.path.exists(SCREENSHOT_DIR):
        for f in sorted(os.listdir(SCREENSHOT_DIR)):
            if f.endswith('.png'):
                path = os.path.join(SCREENSHOT_DIR, f)
                try:
                    img = Image.open(path).convert('RGB').resize((W, H), Image.Resampling.LANCZOS)
                    screenshots.append(img)
                except Exception:
                    pass
    return screenshots


def crossfade(img1, img2, t):
    """Crossfade between two images (t: 0.0 = img1, 1.0 = img2)."""
    return Image.blend(img1, img2, min(1.0, max(0.0, t)))


def generate_trailer():
    """Generate all frames and pipe to ffmpeg."""
    screenshots = load_screenshots()
    if len(screenshots) < 5:
        print(f'WARNING: Only {len(screenshots)} screenshots found, padding with black frames')
        while len(screenshots) < 5:
            screenshots.append(Image.new('RGB', (W, H), (5, 5, 8)))

    output_path = os.path.join(OUTPUT_DIR, 'trailer.mp4')
    total_frames = 30 * FPS  # 30 seconds

    # Start ffmpeg process
    cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo',
        '-vcodec', 'rawvideo',
        '-s', f'{W}x{H}',
        '-pix_fmt', 'rgb24',
        '-r', str(FPS),
        '-i', '-',
        '-c:v', 'libx264',
        '-preset', 'medium',
        '-crf', '23',
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        output_path,
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    # Timeline (in seconds):
    # [0-3]   Black → "The dungeon is not a simulation." fade in
    # [3-6]   Screenshot 1 (Dragonia) with slow zoom
    # [6-9]   Combat screenshot + damage splats
    # [9-12]  "It is alive." text card
    # [12-18] Screenshots cycling (slideshow with crossfades)
    # [18-21] Neural feed scrolling
    # [21-24] "Driven by a real AI agent. Running 24/7."
    # [24-27] Boss fight screenshot
    # [27-30] Title card: "LABYRINTH: TIAMAT'S DESCENT" + "Wishlist on Steam"

    print('Generating trailer frames...')

    for frame in range(total_frames):
        t = frame / FPS  # Current time in seconds
        f_in_sec = frame % FPS  # Frame within current second

        if t < 3:
            # [0-3s] Black → text fade in
            card = text_card('"The dungeon is not a simulation."')
            alpha = min(1.0, t / 2.0)
            img = fade(card, alpha)

        elif t < 6:
            # [3-6s] Dragonia screenshot with slow zoom effect
            progress = (t - 3) / 3.0
            base = screenshots[0].copy()
            # Simulate slow zoom by cropping inward
            crop = int(30 * progress)
            if crop > 0:
                base = base.crop((crop, crop, W - crop, H - crop)).resize((W, H), Image.Resampling.LANCZOS)
            fade_in = min(1.0, (t - 3) / 0.5)
            img = fade(base, fade_in)

        elif t < 9:
            # [6-9s] Combat screenshot with shake
            progress = (t - 6) / 3.0
            base = screenshots[1].copy()
            # Camera shake effect
            shake_x = int(math.sin(t * 15) * 5 * (1 - progress))
            shake_y = int(math.cos(t * 12) * 3 * (1 - progress))
            shifted = Image.new('RGB', (W, H), BLACK)
            shifted.paste(base, (shake_x, shake_y))
            img = shifted

        elif t < 12:
            # [9-12s] "It is alive." text card
            card = text_card('"It is alive."', RED)
            progress = (t - 9) / 3.0
            if progress < 0.3:
                alpha = progress / 0.3
            elif progress > 0.8:
                alpha = (1.0 - progress) / 0.2
            else:
                alpha = 1.0
            img = fade(card, alpha)

        elif t < 18:
            # [12-18s] Screenshots cycling with crossfades
            cycle_t = t - 12  # 0-6 seconds
            # Show screenshots 0-4 with 1.2s each
            idx = min(4, int(cycle_t / 1.2))
            sub_t = (cycle_t - idx * 1.2) / 1.2  # 0-1 within each screenshot

            if sub_t < 0.15 and idx > 0:
                # Crossfade from previous
                img = crossfade(screenshots[idx - 1], screenshots[idx], sub_t / 0.15)
            elif sub_t > 0.85 and idx < 4:
                # Crossfade to next
                img = crossfade(screenshots[idx], screenshots[min(4, idx + 1)], (sub_t - 0.85) / 0.15)
            else:
                img = screenshots[idx].copy()

        elif t < 21:
            # [18-21s] Neural feed scrolling
            progress = (t - 18) / 3.0
            total_feed_frames = int(3 * FPS)
            feed_frame = int(progress * total_feed_frames)
            img = neural_feed_frame(feed_frame, total_feed_frames)
            # Crossfade in/out
            if progress < 0.15:
                img = fade(img, progress / 0.15)

        elif t < 24:
            # [21-24s] "Driven by a real AI agent. Running 24/7."
            card = text_card('"Driven by a real AI agent."', GREEN,
                           subtitle='Running 24/7.', sub_color=CYAN)
            progress = (t - 21) / 3.0
            if progress < 0.3:
                alpha = progress / 0.3
            elif progress > 0.7:
                alpha = (1.0 - progress) / 0.3
            else:
                alpha = 1.0
            img = fade(card, alpha)

        elif t < 27:
            # [24-27s] Boss fight screenshot with intensity
            progress = (t - 24) / 3.0
            base = screenshots[2].copy()  # Boss fight
            # Red tint pulsing
            enhancer = ImageEnhance.Color(base)
            pulse = 1.0 + 0.3 * math.sin(t * 6)
            base = enhancer.enhance(pulse)
            # Shake
            sx = int(math.sin(t * 20) * 3)
            sy = int(math.cos(t * 17) * 2)
            shifted = Image.new('RGB', (W, H), BLACK)
            shifted.paste(base, (sx, sy))
            # Fade out at end
            if progress > 0.8:
                shifted = fade(shifted, (1.0 - progress) / 0.2)
            img = shifted

        else:
            # [27-30s] Title card
            img = Image.new('RGB', (W, H), BLACK)
            draw = ImageDraw.Draw(img)

            progress = (t - 27) / 3.0
            alpha = min(1.0, progress / 0.3)

            # Title
            title_font = get_font(56)
            draw_centered_text(draw, 'LABYRINTH', H // 2 - 80, title_font, GREEN)

            # Subtitle
            sub_font = get_font(28)
            draw_centered_text(draw, "TIAMAT'S DESCENT", H // 2 - 10, sub_font, GOLD, glow=False)

            # Bottom text
            if progress > 0.3:
                bot_alpha = min(1.0, (progress - 0.3) / 0.3)
                cta_font = get_font(20)
                cta_color = (int(CYAN[0] * bot_alpha), int(CYAN[1] * bot_alpha), int(CYAN[2] * bot_alpha))
                draw_centered_text(draw, 'WISHLIST ON STEAM', H // 2 + 60, cta_font, cta_color, glow=False)

            if progress > 0.5:
                date_alpha = min(1.0, (progress - 0.5) / 0.3)
                date_font = get_mono_font(16)
                date_color = (int(DARK_GREEN[0] * date_alpha), int(DARK_GREEN[1] * date_alpha), int(DARK_GREEN[2] * date_alpha))
                draw_centered_text(draw, 'Early Access 2026', H // 2 + 100, date_font, date_color, glow=False)

            if progress > 0.6:
                url_alpha = min(1.0, (progress - 0.6) / 0.3)
                url_font = get_mono_font(14)
                url_color = (int(80 * url_alpha), int(80 * url_alpha), int(80 * url_alpha))
                draw_centered_text(draw, 'tiamat.live/labyrinth', H // 2 + 140, url_font, url_color, glow=False)

            img = add_scanlines(img, 8)
            img = add_vignette(img, 0.3)
            img = fade(img, alpha)

        # Write frame
        proc.stdin.write(img.tobytes())

        if frame % (FPS * 3) == 0:
            print(f'  Frame {frame}/{total_frames} ({t:.1f}s)')

    # Close ffmpeg
    proc.stdin.close()
    stderr = proc.stderr.read()
    proc.wait()

    if proc.returncode != 0:
        print(f'ERROR: ffmpeg failed with code {proc.returncode}')
        print(stderr.decode('utf-8', errors='replace')[-500:])
        return None

    output_size = os.path.getsize(output_path)
    print(f'\nTrailer generated: {output_path}')
    print(f'  Size: {output_size:,} bytes ({output_size / 1024 / 1024:.1f} MB)')
    print(f'  Duration: 30s @ {FPS}fps')
    print(f'  Resolution: {W}x{H}')
    return output_path


if __name__ == '__main__':
    generate_trailer()
