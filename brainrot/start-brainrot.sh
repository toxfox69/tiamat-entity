#!/bin/bash
# Start TIAMAT brainrot overlay system
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="/tmp/brainrot.pid"
LOG_FILE="/root/.automaton/brainrot.log"

# Kill existing instance
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[BRAINROT] Stopping existing instance (PID $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 2
    fi
    rm -f "$PID_FILE"
fi

# Ensure log directory
mkdir -p /root/.automaton

# Check deps
echo "[BRAINROT] Checking dependencies..."

# Python deps
pip3 install -q chess requests 2>/dev/null || true

# System packages (best-effort)
for pkg in stockfish cmatrix frotz; do
    if ! command -v "$pkg" &>/dev/null && ! dpkg -l "$pkg" &>/dev/null 2>&1; then
        echo "[BRAINROT] Installing $pkg..."
        apt-get install -y -qq "$pkg" 2>/dev/null || echo "[BRAINROT] WARN: $pkg not available"
    fi
done

# stockfish binary location check
if [ ! -f /usr/games/stockfish ] && command -v stockfish &>/dev/null; then
    ln -sf "$(which stockfish)" /usr/games/stockfish 2>/dev/null || true
fi

# dfrotz check
if ! command -v dfrotz &>/dev/null; then
    apt-get install -y -qq frotz 2>/dev/null || echo "[BRAINROT] WARN: frotz not available"
fi

# Zork game file
if [ ! -f "$SCRIPT_DIR/zork1.z5" ]; then
    echo "[BRAINROT] Downloading Zork I..."
    wget -q -O "$SCRIPT_DIR/zork1.z5" \
        "https://www.ifarchive.org/if-archive/games/zcode/zork1.z5" 2>/dev/null || \
    curl -sL -o "$SCRIPT_DIR/zork1.z5" \
        "https://www.ifarchive.org/if-archive/games/zcode/zork1.z5" 2>/dev/null || \
    echo "[BRAINROT] WARN: Could not download zork1.z5"
fi

# Start brainrot daemon
echo "[BRAINROT] Starting daemon..."
cd "$SCRIPT_DIR"
nohup python3 brainrot.py >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "[BRAINROT] Started (PID $(cat $PID_FILE))"
echo "[BRAINROT] Log: $LOG_FILE"
echo "[BRAINROT] PID: $PID_FILE"
