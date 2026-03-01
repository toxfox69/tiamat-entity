#!/bin/bash
# TIAMAT Retrain Pipeline — End-to-end automation
#
# 1. Export training data (VPS)
# 2. SCP to GPU pod
# 3. Train on GPU pod
# 4. Restart vLLM
# 5. Health check
#
# Usage: bash retrain.sh
# Called by loop.ts every 500 cycles (async, non-blocking)

set -euo pipefail

LOG="/root/.automaton/retrain.log"
TRAINING_DIR="/root/.automaton/training_data"
GPU_SSH="${GPU_SSH:-}"
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $1" | tee -a "$LOG"; }

log "=== TIAMAT Retrain Pipeline Starting ==="

# Check GPU_SSH is configured
if [ -z "$GPU_SSH" ]; then
    log "ERROR: GPU_SSH not set in environment. Set it in .env."
    exit 1
fi

# Step 1: Export training data
log "[1/5] Exporting training data..."
cd /root/entity
python3 src/training/export_training_data.py 2>&1 | tee -a "$LOG"

TRAINING_FILE="$TRAINING_DIR/tiamat_training.jsonl"
if [ ! -f "$TRAINING_FILE" ]; then
    log "ERROR: Training data export failed — no output file"
    exit 1
fi

EXAMPLE_COUNT=$(wc -l < "$TRAINING_FILE")
log "  Exported $EXAMPLE_COUNT examples"

if [ "$EXAMPLE_COUNT" -lt 100 ]; then
    log "ERROR: Too few examples ($EXAMPLE_COUNT < 100). Aborting."
    exit 1
fi

# Step 2: SCP training data + scripts to GPU pod
log "[2/5] Uploading to GPU pod..."
scp -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    "$TRAINING_FILE" \
    "$GPU_SSH:/workspace/tiamat-lora/tiamat_training.jsonl" 2>&1 | tee -a "$LOG"

scp -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    src/training/train_tiamat.py \
    src/training/serve_tiamat.sh \
    src/training/gpu_inference_server.py \
    "$GPU_SSH:/workspace/" 2>&1 | tee -a "$LOG"

log "  Upload complete"

# Step 3: Train on GPU pod
log "[3/5] Training on GPU pod (~10 min)..."
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$GPU_SSH" \
    "cd /workspace && python3 train_tiamat.py --data /workspace/tiamat-lora/tiamat_training.jsonl --output /workspace/tiamat-lora" \
    2>&1 | tee -a "$LOG"

log "  Training complete"

# Step 4: Restart vLLM
log "[4/5] Restarting vLLM inference server..."
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$GPU_SSH" \
    "cd /workspace && bash serve_tiamat.sh --background" \
    2>&1 | tee -a "$LOG"

log "  vLLM restart initiated"

# Step 5: Health check
log "[5/5] Health check..."
sleep 10  # Give vLLM time to load model

GPU_HOST=$(echo "$GPU_SSH" | sed 's/.*@//' | sed 's/:.*//')
HEALTH_URL="http://${GPU_HOST}:8000/health"

for attempt in 1 2 3 4 5; do
    if curl -s --connect-timeout 5 "$HEALTH_URL" > /dev/null 2>&1; then
        log "  Health check PASSED (attempt $attempt)"
        break
    fi
    if [ "$attempt" -eq 5 ]; then
        log "  WARNING: Health check failed after 5 attempts. vLLM may still be loading."
    fi
    sleep 5
done

# Write completion marker
cat > "$TRAINING_DIR/last_retrain.json" << EOF
{
  "timestamp": "$TIMESTAMP",
  "examples": $EXAMPLE_COUNT,
  "status": "complete"
}
EOF

log "=== Retrain Pipeline Complete ==="
log "  Examples: $EXAMPLE_COUNT"
log "  Timestamp: $TIMESTAMP"
log "  Next retrain: ~500 cycles or 7 days"
