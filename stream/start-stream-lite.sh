#!/bin/bash
# TIAMAT Stream — Lite (no browser)
# Composites: background video + HUD overlay PNG + PulseAudio → Twitch
#
# CPU budget: ~40-50% on 2 vCPU (down from 200%+ with Chromium)

set -e

STREAM_KEY="${TWITCH_STREAM_KEY:-REDACTED_TWITCH_STREAM_KEY}"
FPS="${STREAM_FPS:-15}"
RESOLUTION="1920x1080"
HUD_OVERLAY="/tmp/hud/overlay.png"
BG_IMAGE="/opt/tiamat-stream/assets/bg.png"
BG_VIDEO="/opt/tiamat-stream/assets/bg_loop.mp4"

echo "=== TIAMAT Stream Lite ==="
echo "Resolution: ${RESOLUTION} @ ${FPS}fps"
echo "HUD overlay: ${HUD_OVERLAY}"
echo "Stream key: ${STREAM_KEY:0:20}..."

# Ensure HUD directory exists
mkdir -p /tmp/hud

# Create a blank overlay if none exists yet (compositor will replace it)
if [ ! -f "$HUD_OVERLAY" ]; then
    python3 -c "
from PIL import Image
img = Image.new('RGBA', (1920, 1080), (0,0,0,0))
img.save('$HUD_OVERLAY', 'PNG')
print('Created blank overlay')
"
fi

# Create static background if no video loop exists
if [ ! -f "$BG_VIDEO" ] && [ ! -f "$BG_IMAGE" ]; then
    mkdir -p /opt/tiamat-stream/assets
    python3 -c "
from PIL import Image, ImageDraw
img = Image.new('RGB', (1920, 1080), (5, 5, 8))
draw = ImageDraw.Draw(img)
# Simple grid pattern
for x in range(0, 1920, 60):
    draw.line([(x, 0), (x, 1080)], fill=(15, 18, 25), width=1)
for y in range(0, 1080, 60):
    draw.line([(0, y), (1920, y)], fill=(15, 18, 25), width=1)
img.save('/opt/tiamat-stream/assets/bg.png', 'PNG')
print('Created grid background')
"
    BG_IMAGE="/opt/tiamat-stream/assets/bg.png"
fi

# Start HUD compositor in background
echo "Starting HUD compositor..."
python3 /opt/tiamat-stream/scripts/hud_compositor.py &
HUD_PID=$!
echo "HUD compositor PID: $HUD_PID"

# Wait for first overlay frame
sleep 3

# Determine video source (loop video or static image)
if [ -f "$BG_VIDEO" ]; then
    BG_INPUT="-stream_loop -1 -re -i $BG_VIDEO"
else
    BG_INPUT="-loop 1 -framerate $FPS -i $BG_IMAGE"
fi

echo "Starting ffmpeg stream..."

# ffmpeg: background + HUD overlay + audio → Twitch
# The overlay image is re-read every frame, picks up compositor updates
ffmpeg \
    $BG_INPUT \
    -loop 1 -framerate 1 -i "$HUD_OVERLAY" \
    -f pulse -i stream_sink.monitor \
    -filter_complex "
        [0:v]scale=1920:1080[bg];
        [1:v]format=rgba[hud];
        [bg][hud]overlay=0:0:format=auto:shortest=0,
        drawtext=textfile=/tmp/hud/ticker.txt:
            fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf:
            fontsize=14:fontcolor=white@0.7:
            x='w-mod(t*80\,w+tw)':y=h-20:
            reload=1
        [out]
    " \
    -map "[out]" -map 2:a \
    -c:v libx264 -preset veryfast -tune zerolatency \
    -b:v 4500k -maxrate 4500k -bufsize 6000k \
    -pix_fmt yuv420p -g $((FPS * 2)) -keyint_min $FPS \
    -c:a aac -b:a 160k -ar 44100 \
    -f flv "rtmp://live.twitch.tv/app/${STREAM_KEY}"

# Cleanup
kill $HUD_PID 2>/dev/null
echo "Stream ended."
