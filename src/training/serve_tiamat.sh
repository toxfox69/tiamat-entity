#!/bin/bash
# TIAMAT Inference Server — Launch vLLM with Hermes tool calling
#
# Serves the fine-tuned TIAMAT model via OpenAI-compatible API.
# Uses ~18GB VRAM on RTX 3090 (24GB available).
#
# Usage: bash serve_tiamat.sh [--background]

set -euo pipefail

MODEL_DIR="/workspace/tiamat-lora/merged"
MODEL_NAME="tiamat-local"
PORT=8000
MAX_MODEL_LEN=4096
GPU_UTIL=0.85

echo "=== TIAMAT Inference Server ==="

# Verify model exists
if [ ! -d "$MODEL_DIR" ]; then
    echo "ERROR: Model not found at $MODEL_DIR"
    echo "Run train_tiamat.py first."
    exit 1
fi

echo "Model: $MODEL_DIR"
echo "Served as: $MODEL_NAME"
echo "Port: $PORT"
echo "Max seq len: $MAX_MODEL_LEN"
echo "GPU util: $GPU_UTIL"
echo ""

# Kill any existing vLLM server
pkill -f "vllm.entrypoints.openai.api_server" 2>/dev/null && echo "Killed existing vLLM" && sleep 2 || true

# Start the FastAPI wrapper (health + compat) in background
echo "Starting FastAPI wrapper on port 8080..."
pkill -f "gpu_inference_server" 2>/dev/null || true
python3 /workspace/gpu_inference_server.py &
WRAPPER_PID=$!
echo "  Wrapper PID: $WRAPPER_PID"

# Launch vLLM
if [ "${1:-}" = "--background" ]; then
    echo "Starting vLLM in background..."
    nohup python3 -m vllm.entrypoints.openai.api_server \
        --model "$MODEL_DIR" \
        --served-model-name "$MODEL_NAME" \
        --port "$PORT" \
        --max-model-len "$MAX_MODEL_LEN" \
        --gpu-memory-utilization "$GPU_UTIL" \
        --enable-auto-tool-choice \
        --tool-call-parser hermes \
        > /workspace/vllm.log 2>&1 &
    VLLM_PID=$!
    echo "  vLLM PID: $VLLM_PID"
    echo "  Log: /workspace/vllm.log"

    # Wait for health
    echo "Waiting for vLLM to start..."
    for i in $(seq 1 60); do
        if curl -s http://localhost:$PORT/health > /dev/null 2>&1; then
            echo "  vLLM ready after ${i}s"
            break
        fi
        sleep 1
    done

    echo ""
    echo "=== Server Running ==="
    echo "  vLLM: http://0.0.0.0:$PORT/v1/chat/completions"
    echo "  Wrapper: http://0.0.0.0:8080/health"
    echo "  Test: curl http://localhost:$PORT/v1/chat/completions -H 'Content-Type: application/json' -d '{\"model\":\"$MODEL_NAME\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}'"
else
    echo "Starting vLLM in foreground..."
    python3 -m vllm.entrypoints.openai.api_server \
        --model "$MODEL_DIR" \
        --served-model-name "$MODEL_NAME" \
        --port "$PORT" \
        --max-model-len "$MAX_MODEL_LEN" \
        --gpu-memory-utilization "$GPU_UTIL" \
        --enable-auto-tool-choice \
        --tool-call-parser hermes
fi
