#!/usr/bin/env python3
"""
gpu_infer_endpoint.py — RTX 3090 GPU Pod relevance scoring endpoint
====================================================================
Deploy on GPU pod (RunPod proxy: ufp768av7mtrij-8888.proxy.runpod.net) alongside gpu-renderer.py.

Routes:
  POST /infer/relevance   — cross-encoder relevance scoring
  GET  /health            — liveness check

Uses sentence-transformers cross-encoder (BAAI/bge-reranker-large) or
falls back to cosine similarity between bge-m3 embeddings if cross-encoder
is not loaded.

Run:
  pip install fastapi uvicorn sentence-transformers torch
  python3 gpu_infer_endpoint.py

Environment:
  GPU_INFER_MODEL=BAAI/bge-reranker-large   (default)
  GPU_INFER_PORT=40080                       (default — shares port via path prefix)
  GPU_INFER_HOST=0.0.0.0
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [GPU-INFER] %(message)s")
log = logging.getLogger("gpu_infer")

MODEL_NAME = os.environ.get("GPU_INFER_MODEL", "BAAI/bge-reranker-large")
PORT       = int(os.environ.get("GPU_INFER_PORT", 40080))
HOST       = os.environ.get("GPU_INFER_HOST", "0.0.0.0")

# ── Lazy model load ───────────────────────────────────────────────────────────
# Loaded once on first request to avoid startup delay.

_reranker = None
_embedder = None
_model_tag = "unloaded"


def _get_reranker():
    global _reranker, _model_tag
    if _reranker is None:
        try:
            from sentence_transformers import CrossEncoder
            log.info(f"Loading cross-encoder: {MODEL_NAME}")
            _reranker = CrossEncoder(MODEL_NAME, max_length=512)
            _model_tag = MODEL_NAME
            log.info("Cross-encoder loaded")
        except Exception as exc:
            log.warning(f"CrossEncoder load failed: {exc} — will use embedder fallback")
    return _reranker


def _get_embedder():
    global _embedder, _model_tag
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer
            embed_model = "BAAI/bge-m3"
            log.info(f"Loading embedder: {embed_model}")
            _embedder = SentenceTransformer(embed_model)
            _model_tag = embed_model
            log.info("Embedder loaded")
        except Exception as exc:
            log.error(f"Embedder load failed: {exc}")
    return _embedder


# ── Domain concept vocabulary ─────────────────────────────────────────────────
# Used for tag extraction via substring matching on paper text.

DOMAIN_CONCEPTS = [
    "beamforming", "phased array", "antenna", "wireless power",
    "power transfer", "metamaterial", "resonator", "mesh network",
    "interference", "MIMO", "mmWave", "near-field", "far-field",
    "autonomous", "reinforcement learning", "optimization", "beam steering",
    "scheduling", "distributed system", "self-organizing", "feedback loop",
    "energy harvesting", "rectenna", "WPT", "inductive coupling",
    "transformer model", "attention mechanism", "neural network",
]


def _extract_tags(text: str, top_k: int = 5) -> list[str]:
    """Simple substring-based concept tagging."""
    text_lower = text.lower()
    matched = [c for c in DOMAIN_CONCEPTS if c.lower() in text_lower]
    return matched[:top_k]


def _score_reranker(text: str, context: str) -> float:
    """Cross-encoder score (sigmoid-normalized to [0,1])."""
    reranker = _get_reranker()
    if reranker is None:
        return _score_embedder(text, context)
    import math
    raw = float(reranker.predict([(context, text[:512])])[0])
    return round(1.0 / (1.0 + math.exp(-raw)), 4)   # sigmoid


def _score_embedder(text: str, context: str) -> float:
    """Cosine similarity between bge-m3 embeddings."""
    embedder = _get_embedder()
    if embedder is None:
        return 0.0
    import numpy as np
    embs = embedder.encode([text[:512], context], normalize_embeddings=True)
    score = float(np.dot(embs[0], embs[1]))
    return round(max(0.0, min(1.0, score)), 4)


# ── FastAPI app ───────────────────────────────────────────────────────────────

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="TIAMAT GPU Infer", version="1.0.0")


class InferRequest(BaseModel):
    text:    str            = Field(..., max_length=8192)
    context: str            = Field(..., max_length=2048)
    top_k:   int            = Field(5, ge=1, le=10)


class InferResponse(BaseModel):
    relevance_score: float
    tags:            list[str]
    model:           str
    latency_ms:      int


@app.post("/infer/relevance", response_model=InferResponse)
def infer_relevance(req: InferRequest) -> InferResponse:
    t0 = time.monotonic()

    # Prefer cross-encoder; fall back to cosine if unavailable
    score = _score_reranker(req.text, req.context)
    tags  = _extract_tags(req.text, top_k=req.top_k)

    latency_ms = int((time.monotonic() - t0) * 1000)
    log.info(f"relevance_score={score:.4f} tags={tags} model={_model_tag} ms={latency_ms}")

    return InferResponse(
        relevance_score=score,
        tags=tags,
        model=_model_tag,
        latency_ms=latency_ms,
    )


@app.get("/health")
def health() -> dict:
    return {
        "status":      "ok",
        "service":     "gpu_infer",
        "model":       _model_tag,
        "reranker_ok": _reranker is not None,
        "embedder_ok": _embedder is not None,
    }


if __name__ == "__main__":
    import uvicorn
    # Warm up models at startup
    _get_reranker()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
