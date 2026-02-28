#!/usr/bin/env python3
"""TIAMAT GPU Pod — TTS + Health Service
Runs on port 8888 behind RunPod proxy.
Persistent install in /workspace/services/
"""

import io
import os
import time
import logging
from flask import Flask, request, jsonify, send_file

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
log = logging.getLogger("gpu-server")

# Lazy-load Kokoro to avoid startup delay on health checks
_kokoro = None
_kokoro_voices = None

def get_kokoro():
    global _kokoro, _kokoro_voices
    if _kokoro is None:
        log.info("Loading Kokoro TTS model...")
        t0 = time.time()
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
        _kokoro_voices = _kokoro.get_voices()
        log.info(f"Kokoro loaded in {time.time()-t0:.1f}s — {len(_kokoro_voices)} voices available")
    return _kokoro, _kokoro_voices


@app.route("/health", methods=["GET"])
def health():
    import torch
    cuda_available = torch.cuda.is_available()
    gpu_info = {}
    if cuda_available:
        gpu_info = {
            "name": torch.cuda.get_device_name(0),
            "vram_total": f"{torch.cuda.get_device_properties(0).total_mem / 1e9:.1f}GB",
            "vram_free": f"{(torch.cuda.get_device_properties(0).total_mem - torch.cuda.memory_allocated(0)) / 1e9:.1f}GB",
        }
    return jsonify({
        "status": "ok",
        "cuda": cuda_available,
        "service": "tiamat-gpu",
        "version": "2.0",
        **gpu_info,
    })


@app.route("/tts", methods=["POST"])
def tts():
    data = request.get_json(silent=True)
    if not data or not data.get("text"):
        return jsonify({"error": "missing 'text' field"}), 400

    text = data["text"][:5000]  # Cap at 5000 chars
    voice = data.get("voice", "af_heart")
    speed = float(data.get("speed", 1.0))
    lang = data.get("lang", "a")  # a=American English

    try:
        kokoro, voices = get_kokoro()

        if voice not in voices:
            return jsonify({
                "error": f"unknown voice '{voice}'",
                "available": sorted(voices),
            }), 400

        t0 = time.time()
        samples, sample_rate = kokoro.create(text, voice=voice, speed=speed, lang=lang)
        gen_time = time.time() - t0

        # Convert to WAV in memory
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, samples, sample_rate, format="WAV")
        buf.seek(0)

        log.info(f"[TTS] {len(text)} chars, voice={voice}, {gen_time:.2f}s")

        return send_file(
            buf,
            mimetype="audio/wav",
            as_attachment=True,
            download_name=f"tts_{int(time.time())}.wav",
        )
    except Exception as e:
        log.error(f"[TTS] Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/tts/voices", methods=["GET"])
def list_voices():
    try:
        _, voices = get_kokoro()
        return jsonify({"voices": sorted(voices)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8888))
    log.info(f"Starting TIAMAT GPU server on port {port}")
    app.run(host="0.0.0.0", port=port, threaded=True)
