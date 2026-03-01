#!/bin/bash
# TIAMAT GPU Pod Setup — Install training + inference dependencies
# Run on GPU pod (RTX 3090) after restart from RunPod dashboard
#
# Usage: ssh $GPU_SSH 'bash -s' < gpu_setup.sh

set -euo pipefail

echo "=== TIAMAT GPU Pod Setup ==="
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'unknown')"

# Create workspace
mkdir -p /workspace/tiamat-lora
cd /workspace

# Install unsloth (QLoRA with 2x speedup)
echo "[1/4] Installing unsloth..."
pip install --quiet --upgrade "unsloth[colab-new]" 2>/dev/null || \
pip install --quiet --upgrade unsloth

# Install training dependencies
echo "[2/4] Installing training deps..."
pip install --quiet \
    peft \
    accelerate \
    bitsandbytes \
    datasets \
    trl \
    transformers \
    torch \
    sentencepiece \
    protobuf

# Install vLLM for inference serving
echo "[3/4] Installing vLLM..."
pip install --quiet vllm

# Install FastAPI for wrapper server
echo "[4/4] Installing FastAPI + uvicorn..."
pip install --quiet fastapi uvicorn httpx

# Verify installations
echo ""
echo "=== Verification ==="
python3 -c "import unsloth; print(f'unsloth: {unsloth.__version__}')" 2>/dev/null || echo "unsloth: import check needed"
python3 -c "import vllm; print(f'vllm: {vllm.__version__}')"
python3 -c "import torch; print(f'torch: {torch.__version__}, CUDA: {torch.cuda.is_available()}, GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"none\"}')"
python3 -c "import peft; print(f'peft: {peft.__version__}')"
python3 -c "import trl; print(f'trl: {trl.__version__}')"

echo ""
echo "=== GPU Memory ==="
nvidia-smi --query-gpu=memory.free,memory.total --format=csv,noheader

echo ""
echo "=== Setup Complete ==="
echo "Next: SCP training data to /workspace/tiamat-lora/tiamat_training.jsonl"
echo "Then: python3 train_tiamat.py"
