#!/bin/bash
# LABYRINTH: TIAMAT'S DESCENT — Build Script
# Builds desktop binaries for Linux and Windows
# Usage: ./build.sh [--linux] [--win] [--mac] [--all]

set -e
cd "$(dirname "$0")"

echo "=== LABYRINTH: TIAMAT'S DESCENT — Build ==="
echo ""

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
  echo "[1/3] Installing dependencies..."
  npm install --no-audit --no-fund
else
  echo "[1/3] Dependencies already installed"
fi

# Create build resources directory
mkdir -p build/resources

# Generate placeholder icon from sprite-tiamat.png if no icon exists
if [ ! -f "build/resources/icon.png" ]; then
  echo "[2/3] Setting up build resources..."
  if [ -f "app/assets/sprite-tiamat.png" ]; then
    cp app/assets/sprite-tiamat.png build/resources/icon.png
    echo "  Using sprite-tiamat.png as icon"
  else
    echo "  WARNING: No icon found — builds may use default Electron icon"
  fi
fi

# Determine build targets
TARGETS=""
if [ "$1" == "--all" ] || [ -z "$1" ]; then
  TARGETS="--linux --win"
  echo "[3/3] Building for Linux + Windows..."
elif [ "$1" == "--linux" ]; then
  TARGETS="--linux"
  echo "[3/3] Building for Linux..."
elif [ "$1" == "--win" ]; then
  TARGETS="--win"
  echo "[3/3] Building for Windows..."
elif [ "$1" == "--mac" ]; then
  TARGETS="--mac"
  echo "[3/3] Building for macOS..."
fi

npx electron-builder $TARGETS

echo ""
echo "=== Build complete ==="
echo "Output: build/dist/"
ls -lh build/dist/ 2>/dev/null || echo "(no output files yet)"
