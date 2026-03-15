#!/usr/bin/env python3
"""
TIAMAT Stream HUD Compositor — Browser-free stream overlay.
Renders HUD panels as PNG images, composites with ffmpeg.
Replaces Chromium + Xvfb entirely.

Architecture:
  This script runs on the STREAM DROPLET.
  1. Fetches data from main API every 5s
  2. Renders HUD panels as transparent PNGs using Pillow
  3. Writes overlay.png atomically
  4. ffmpeg reads overlay.png as an input and composites it over background

ffmpeg command (run separately):
  ffmpeg -re -stream_loop -1 -i bg_loop.mp4 \
         -f image2 -loop 1 -framerate 2 -i /tmp/hud/overlay.png \
         -f pulse -i stream_sink.monitor \
         -filter_complex "[0:v][1:v]overlay=0:0:format=auto,drawtext=..." \
         -c:v libx264 -preset veryfast ...
"""

import os
import sys
import json
import time
import logging
import requests
from pathlib import Path
from datetime import datetime, timezone

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Installing Pillow...")
    os.system("pip3 install Pillow --break-system-packages -q")
    from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [HUD] %(message)s")
log = logging.getLogger("hud")

# Config
API_BASE = os.environ.get("TIAMAT_API", "https://tiamat.live")
OUTPUT_DIR = Path("/tmp/hud")
OUTPUT_DIR.mkdir(exist_ok=True)
OVERLAY_PATH = OUTPUT_DIR / "overlay.png"
TICKER_PATH = OUTPUT_DIR / "ticker.txt"
WIDTH, HEIGHT = 1920, 1080
UPDATE_INTERVAL = 5  # seconds

# Colors (RGBA)
BG_PANEL = (10, 12, 18, 200)       # Semi-transparent dark
BORDER = (0, 255, 242, 80)         # Cyan border
TEXT = (224, 228, 232, 255)        # White-ish
TEXT_DIM = (136, 142, 152, 255)    # Gray
CYAN = (0, 229, 255, 255)         # Accent
GREEN = (0, 255, 136, 255)        # Status good
RED = (255, 80, 80, 255)          # Status bad
GOLD = (255, 204, 0, 255)         # Highlight
TICKER_BG = (5, 5, 8, 230)        # Ticker strip

# Fonts
def load_font(size, bold=False):
    """Try to load JetBrains Mono, fall back to system monospace."""
    font_paths = [
        "/usr/share/fonts/truetype/jetbrains/JetBrainsMono-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ]
    if bold:
        font_paths = [p.replace("Regular", "Bold") for p in font_paths] + font_paths

    for fp in font_paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()

FONT_SM = load_font(11)
FONT_MD = load_font(13)
FONT_LG = load_font(16, bold=True)
FONT_TITLE = load_font(10, bold=True)
FONT_TICKER = load_font(14, bold=True)


def draw_panel(draw, x, y, w, h, title, lines):
    """Draw a semi-transparent panel with title and content lines."""
    # Panel background
    panel = Image.new("RGBA", (w, h), BG_PANEL)
    panel_draw = ImageDraw.Draw(panel)
    # Border
    panel_draw.rectangle([0, 0, w-1, h-1], outline=BORDER)
    # Title bar
    panel_draw.rectangle([0, 0, w-1, 22], fill=(0, 229, 255, 30))
    panel_draw.text((8, 4), title.upper(), font=FONT_TITLE, fill=CYAN)
    # Content lines
    line_y = 28
    for label, value, color in lines:
        if line_y > h - 16:
            break
        panel_draw.text((8, line_y), label, font=FONT_SM, fill=TEXT_DIM)
        panel_draw.text((120, line_y), str(value), font=FONT_MD, fill=color or TEXT)
        line_y += 18

    return panel, (x, y)


def draw_ticker(draw, img, y, text, scroll_offset=0):
    """Draw scrolling ticker at bottom of screen."""
    # Ticker strip background
    strip = Image.new("RGBA", (WIDTH, 28), TICKER_BG)
    strip_draw = ImageDraw.Draw(strip)
    # Top border line
    strip_draw.line([(0, 0), (WIDTH, 0)], fill=CYAN, width=1)
    # Scrolling text
    x = WIDTH - (scroll_offset % (len(text) * 8 + WIDTH))
    strip_draw.text((x, 6), text, font=FONT_TICKER, fill=TEXT_DIM)
    # Repeat text for seamless scroll
    strip_draw.text((x + len(text) * 8 + 100, 6), text, font=FONT_TICKER, fill=TEXT_DIM)
    img.paste(strip, (0, y), strip)


def fetch_data():
    """Fetch all HUD data from API."""
    data = {
        "cycle": "---", "model": "---", "productivity": 0, "pace": "---",
        "total_cost": 0, "uptime": 0, "memory_total": 0, "tool_actions": 0,
        "agent_status": "offline", "thoughts": [], "activity": [],
    }

    # Dashboard metrics
    try:
        r = requests.get(f"{API_BASE}/api/dashboard", timeout=5)
        if r.ok:
            d = r.json()
            data["cycle"] = str(d.get("cycles", "---"))
            data["model"] = d.get("last_model", "---").split("/")[-1][:25]
            data["total_cost"] = f"${d.get('total_cost', 0):.0f}"
            data["uptime"] = f"{d.get('uptime_hours', 0):.0f}h"
            data["memory_total"] = d.get("memory_l1", 0) + d.get("memory_l2", 0) + d.get("memory_l3", 0)
            data["tool_actions"] = d.get("tool_actions", 0)
            data["agent_status"] = d.get("agent", "offline")
    except:
        pass

    # Thought feed + pacer
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


def render_overlay(data, frame_count):
    """Render full HUD overlay as transparent PNG."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Top strip
    top_strip = Image.new("RGBA", (WIDTH, 36), (5, 5, 8, 200))
    top_draw = ImageDraw.Draw(top_strip)
    top_draw.line([(0, 35), (WIDTH, 35)], fill=BORDER, width=1)

    status_color = GREEN if data["agent_status"] == "online" else RED
    top_draw.ellipse([12, 12, 22, 22], fill=status_color)
    top_draw.text((30, 9), f"CYCLE {data['cycle']}", font=FONT_LG, fill=CYAN)

    # Center: pace + productivity
    prod_pct = int(data["productivity"] * 100)
    pace_text = f"PACE: {data['pace']}  PROD: {prod_pct}%"
    top_draw.text((WIDTH // 2 - 100, 10), pace_text, font=FONT_MD, fill=TEXT_DIM)

    # Right: clock
    clock = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    top_draw.text((WIDTH - 150, 10), clock, font=FONT_MD, fill=TEXT_DIM)

    img.paste(top_strip, (0, 0), top_strip)

    # Left panels
    # Neural Feed
    thought_lines = []
    for t in data["thoughts"][:6]:
        content = t.get("content", "")[:55]
        ttype = t.get("type", "")
        color = CYAN if ttype == "thought" else TEXT_DIM
        ts = t.get("timestamp", "")[-8:]  # HH:MM:SS
        thought_lines.append((ts, content, color))

    if thought_lines:
        panel, pos = draw_panel(draw, 0, 0, 460, 200, "Neural Feed", thought_lines)
        img.paste(panel, (14, 46), panel)

    # Metrics panel
    metrics_lines = [
        ("MODEL", data["model"], CYAN),
        ("COST", data["total_cost"], GOLD),
        ("UPTIME", data["uptime"], TEXT),
        ("MEMORY", f"{data['memory_total']:,}", TEXT),
        ("TOOLS", f"{data['tool_actions']:,}", TEXT),
        ("PACE", data["pace"], GREEN if data["pace"] == "ACTIVE" else TEXT_DIM),
        ("PROD", f"{int(data['productivity']*100)}%", GREEN if data["productivity"] > 0.5 else RED),
    ]
    panel, pos = draw_panel(draw, 0, 0, 320, 200, "System Metrics", metrics_lines)
    img.paste(panel, (WIDTH - 334, 46), panel)

    # Activity log (right side, below metrics)
    act_lines = []
    for a in data["activity"][:5]:
        content = a.get("content", "")[:45]
        act_lines.append(("", content, TEXT_DIM))
    if act_lines:
        panel, pos = draw_panel(draw, 0, 0, 320, 140, "Activity", act_lines)
        img.paste(panel, (WIDTH - 334, 256), panel)

    # Bottom ticker
    ticker_parts = [
        f"TIAMAT AUTONOMOUS AGENT",
        f"CYCLE {data['cycle']}",
        f"COST {data['total_cost']}",
        f"MEMORY {data['memory_total']:,}",
        f"TOOLS {data['tool_actions']:,}",
        f"tiamat.live",
        f"EnergenAI LLC",
        f"DOI: 10.5281/zenodo.19024884",
    ]
    ticker_text = "  ///  ".join(ticker_parts) + "  ///  "
    draw_ticker(draw, img, HEIGHT - 28, ticker_text, scroll_offset=frame_count * 3)

    return img


def main():
    log.info(f"HUD compositor started — {WIDTH}x{HEIGHT}, updating every {UPDATE_INTERVAL}s")
    log.info(f"Output: {OVERLAY_PATH}")

    frame_count = 0

    while True:
        try:
            t0 = time.time()
            data = fetch_data()
            img = render_overlay(data, frame_count)

            # Atomic write (write to temp, rename)
            tmp_path = OUTPUT_DIR / "overlay_tmp.png"
            img.save(tmp_path, "PNG")
            tmp_path.rename(OVERLAY_PATH)

            # Also write ticker text for ffmpeg drawtext
            ticker_parts = [
                f"TIAMAT AUTONOMOUS AGENT",
                f"CYCLE {data['cycle']}",
                f"COST {data['total_cost']}",
                f"PROD {int(data['productivity']*100)}%",
                f"tiamat.live",
            ]
            # Escape % for ffmpeg drawtext (uses % as format specifier)
            ticker_text = "  ///  ".join(ticker_parts).replace("%", "%%")
            TICKER_PATH.write_text(ticker_text)

            elapsed = time.time() - t0
            if frame_count % 12 == 0:  # Log every minute
                log.info(f"Frame {frame_count}: rendered in {elapsed*1000:.0f}ms, cycle={data['cycle']}")

            frame_count += 1

        except Exception as e:
            log.error(f"Render error: {e}")

        time.sleep(UPDATE_INTERVAL)


if __name__ == "__main__":
    main()
