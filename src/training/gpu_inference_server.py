#!/usr/bin/env python3
"""
TIAMAT GPU Inference Server — FastAPI wrapper for vLLM

Provides:
  /health          — Health check compatible with existing gpu_health_check.py
  /infer/relevance — Backward compat shim (replaces gpu_infer_endpoint.py)
  /v1/chat/completions — Proxy to vLLM (for convenience)

Runs on port 8080 alongside vLLM on port 8000.
"""

import os
import time
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

VLLM_URL = os.environ.get("VLLM_URL", "http://localhost:8000")
MODEL_NAME = os.environ.get("MODEL_NAME", "tiamat-local")
PORT = int(os.environ.get("WRAPPER_PORT", "8080"))

app = FastAPI(title="TIAMAT GPU Inference Server")
start_time = time.time()


@app.get("/health")
async def health():
    """Health check — compatible with existing gpu_health_check.py format."""
    vllm_healthy = False
    vllm_model = None

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{VLLM_URL}/health")
            vllm_healthy = resp.status_code == 200
            if vllm_healthy:
                models_resp = await client.get(f"{VLLM_URL}/v1/models")
                if models_resp.status_code == 200:
                    data = models_resp.json()
                    if data.get("data"):
                        vllm_model = data["data"][0].get("id")
    except Exception:
        pass

    return {
        "status": "ok" if vllm_healthy else "degraded",
        "vllm": {
            "healthy": vllm_healthy,
            "model": vllm_model,
            "url": VLLM_URL,
        },
        "uptime_seconds": round(time.time() - start_time),
        "services": ["vllm", "tiamat-local"],
    }


@app.post("/infer/relevance")
async def infer_relevance(request: Request):
    """Backward compat shim — replaces gpu_infer_endpoint.py relevance scoring.
    Accepts: {"text": "...", "query": "..."} or {"prompt": "..."}
    Returns: {"score": float, "model": str}
    """
    body = await request.json()
    text = body.get("text", body.get("prompt", ""))
    query = body.get("query", "")

    if not text:
        return JSONResponse({"error": "missing text/prompt"}, status_code=400)

    prompt = f"Rate the relevance of this text to the query on a scale of 0-10.\n\nQuery: {query}\n\nText: {text[:2000]}\n\nRespond with ONLY a number 0-10."

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{VLLM_URL}/v1/chat/completions",
                json={
                    "model": MODEL_NAME,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 10,
                    "temperature": 0,
                },
            )
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "5")
            # Extract numeric score
            score = 5.0
            for token in content.split():
                try:
                    score = float(token)
                    break
                except ValueError:
                    continue
            return {"score": min(max(score, 0), 10), "model": MODEL_NAME}
    except Exception as e:
        return JSONResponse({"error": str(e), "model": MODEL_NAME}, status_code=502)


@app.post("/v1/chat/completions")
async def chat_completions_proxy(request: Request):
    """Proxy to vLLM — convenience endpoint so both ports work."""
    body = await request.body()
    headers = {"Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{VLLM_URL}/v1/chat/completions",
                content=body,
                headers=headers,
            )
            return JSONResponse(resp.json(), status_code=resp.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


if __name__ == "__main__":
    print(f"TIAMAT GPU Inference Server starting on port {PORT}")
    print(f"vLLM backend: {VLLM_URL}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
