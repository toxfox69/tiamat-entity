#!/bin/bash
# TIAMAT GPU Pod — Startup Script
# Place in /workspace/start.sh
# RunPod runs this on container start

set -e

echo "[TIAMAT GPU] Starting services..."

# Install dependencies if not already present
if ! python3 -c "import kokoro_onnx" 2>/dev/null; then
    echo "[TIAMAT GPU] Installing dependencies to /workspace..."
    pip install --target=/workspace/pip_packages kokoro-onnx soundfile flask torch 2>&1 | tail -5
fi

# Add pip packages to path
export PYTHONPATH="/workspace/pip_packages:${PYTHONPATH}"

# Download Kokoro model files if not present
cd /workspace/services
if [ ! -f "kokoro-v1.0.onnx" ]; then
    echo "[TIAMAT GPU] Downloading Kokoro model..."
    python3 -c "
from kokoro_onnx import Kokoro
# First import triggers model download to current directory
import kokoro_onnx
import os
print(f'Model files in: {os.getcwd()}')
print([f for f in os.listdir('.') if f.endswith('.onnx') or f.endswith('.bin')])
"
fi

echo "[TIAMAT GPU] Starting server on port 8888..."
cd /workspace/services
python3 server.py &

echo "[TIAMAT GPU] Server PID: $!"
echo $! > /workspace/server.pid

# Keep container alive
wait
