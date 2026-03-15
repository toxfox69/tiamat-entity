#!/bin/bash
# TIAMAT Stream v3 — Single-process Chrome + Xvfb + ffmpeg ultrafast
# Run on main server (8 vCPU, 32GB)
set -e

TWITCH_KEY="REDACTED_TWITCH_STREAM_KEY"
PAGE_URL="https://tiamat.live/dragon/stream_scene.html"
WIDTH=1280
HEIGHT=720
FPS=24

echo "[STREAM] Starting TIAMAT Stream v3..."

# Clean up
pkill -9 Xvfb 2>/dev/null || true
pkill -9 -f google-chrome 2>/dev/null || true
pkill -9 ffmpeg 2>/dev/null || true
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
sleep 1

# Xvfb at 720p
Xvfb :99 -screen 0 ${WIDTH}x${HEIGHT}x24 -ac &
sleep 2
export DISPLAY=:99
echo "[STREAM] Xvfb ready (${WIDTH}x${HEIGHT})"

# Google Chrome — EVERY FLAG MATTERS
google-chrome-stable \
  --no-sandbox \
  --use-gl=swiftshader \
  --single-process \
  --disable-dev-shm-usage \
  --disable-gpu-sandbox \
  --disable-extensions \
  --disable-background-networking \
  --disable-background-timer-throttling \
  --disable-backgrounding-occluded-windows \
  --disable-renderer-backgrounding \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --autoplay-policy=no-user-gesture-required \
  --no-first-run \
  --window-size=${WIDTH},${HEIGHT} \
  --window-position=0,0 \
  "$PAGE_URL" &

echo "[STREAM] Chrome launched (single-process + SwiftShader)"
sleep 10

# Verify Chrome is running
CHROME_COUNT=$(pgrep -c chrome 2>/dev/null || echo 0)
echo "[STREAM] Chrome processes: $CHROME_COUNT (should be 1-3)"

# ffmpeg — ultrafast, 720p, low bitrate for headroom
ffmpeg -f x11grab -framerate $FPS -video_size ${WIDTH}x${HEIGHT} -i :99 \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -b:v 2500k -maxrate 2500k -bufsize 5000k \
  -pix_fmt yuv420p -g $((FPS * 2)) -keyint_min $FPS \
  -an \
  -f flv "rtmp://live.twitch.tv/app/$TWITCH_KEY"
