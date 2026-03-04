#!/usr/bin/env python3
"""
TIAMAT TTS Endpoint — /api/synthesize
Provider priority: OpenAI TTS → ElevenLabs → pyttsx3 (local fallback)
Payment: x402 USDC on Base mainnet ($0.01/request, 3/day free tier)

Import into summarize_api.py:
    from src.agent.tts_endpoint import tts_bp
    app.register_blueprint(tts_bp)
"""

import io
import os
import logging
import sqlite3
import tempfile
from datetime import datetime, timezone

import requests
from flask import Blueprint, request, jsonify, send_file

from payment_verify import (
    check_tier,
    extract_payment_proof,
    payment_required_response,
    payment_required_headers,
)

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────
TTS_PRICE_USDC = 0.01
TTS_FREE_LIMIT = 3          # requests per IP per day
TTS_MAX_CHARS  = 4096
TTS_LOG_PATH   = "/root/.automaton/tts_usage.log"
RATE_DB_PATH   = "/tmp/rate_limit.db"

OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

VALID_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
VALID_MODELS = {"tts-1", "tts-1-hd"}

# ElevenLabs: map OpenAI voice names → EL voice IDs (curated, stable)
_EL_VOICE_MAP = {
    "alloy":   "21m00Tcm4TlvDq8ikWAM",  # Rachel  — neutral/warm
    "echo":    "AZnzlk1XvdvUeBnXmlld",  # Domi    — energetic
    "fable":   "EXAVITQu4vr4xnSDxMaL",  # Bella   — soft/storytelling
    "onyx":    "ErXwobaYiN019PkySvjV",  # Antoni  — deep/authoritative
    "nova":    "MF3mGyEYCl7XYWbV9V6O",  # Elli    — bright/young
    "shimmer": "TxGEqnHWrfWFTfGW9XjX",  # Josh    — conversational
}

tts_bp = Blueprint("tts", __name__)


# ── Rate limiter (reuses /tmp/rate_limit.db shared with main API) ──
def _under_free_limit(ip: str) -> bool:
    conn = sqlite3.connect(RATE_DB_PATH)
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS requests "
        "(ip TEXT, endpoint TEXT, timestamp REAL, PRIMARY KEY(ip, endpoint, timestamp))"
    )
    now = datetime.now()
    day_start = datetime(now.year, now.month, now.day).timestamp()
    c.execute(
        "SELECT COUNT(*) FROM requests WHERE ip=? AND endpoint=? AND timestamp>=?",
        (ip, "/api/synthesize", day_start),
    )
    count = c.fetchone()[0]
    conn.close()
    return count < TTS_FREE_LIMIT


def _record_free_request(ip: str) -> None:
    conn = sqlite3.connect(RATE_DB_PATH)
    try:
        conn.execute(
            "INSERT INTO requests VALUES (?,?,?)",
            (ip, "/api/synthesize", datetime.now().timestamp()),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ── Usage logger ───────────────────────────────────────────────
def _log(provider: str, voice: str, model: str, chars: int, tier: str, sender: str) -> None:
    os.makedirs(os.path.dirname(TTS_LOG_PATH), exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    line = f"{ts}|{provider}|{model}|{voice}|chars={chars}|tier={tier}|sender={sender or 'anon'}\n"
    try:
        with open(TTS_LOG_PATH, "a") as f:
            f.write(line)
    except Exception as e:
        logger.warning("TTS log write failed: %s", e)


# ── TTS providers ──────────────────────────────────────────────
def _openai_tts(text: str, voice: str, model: str) -> tuple[bytes, str]:
    """Returns (audio_bytes, mime_type). Raises on error."""
    resp = requests.post(
        "https://api.openai.com/v1/audio/speech",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": model, "input": text, "voice": voice},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content, "audio/mpeg"


def _elevenlabs_tts(text: str, voice: str) -> tuple[bytes, str]:
    """Returns (audio_bytes, mime_type). Raises on error."""
    voice_id = _EL_VOICE_MAP.get(voice, _EL_VOICE_MAP["alloy"])
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        json={
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content, "audio/mpeg"


def _pyttsx3_tts(text: str, voice: str) -> tuple[bytes, str]:
    """Local pyttsx3 fallback. Returns (wav_bytes, mime_type)."""
    import pyttsx3  # optional dep — only imported when needed

    engine = pyttsx3.init()
    voices = engine.getProperty("voices") or []
    female = {"alloy", "nova", "shimmer", "fable"}
    if voices:
        idx = 1 if (voice in female and len(voices) > 1) else 0
        engine.setProperty("voice", voices[idx].id)
    engine.setProperty("rate", 175)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        engine.save_to_file(text, tmp.name)
        engine.runAndWait()
        with open(tmp.name, "rb") as f:
            audio = f.read()
    finally:
        engine.stop()
        os.unlink(tmp.name)

    return audio, "audio/wav"


def _synthesize(text: str, voice: str, model: str) -> tuple[bytes, str, str]:
    """
    Try providers in priority order.
    Returns (audio_bytes, mime_type, provider_name).
    Raises RuntimeError if all providers fail.
    """
    errors = []

    if OPENAI_API_KEY:
        try:
            audio, mime = _openai_tts(text, voice, model)
            return audio, mime, "openai"
        except Exception as e:
            logger.warning("OpenAI TTS failed: %s", e)
            errors.append(f"openai: {e}")

    if ELEVENLABS_API_KEY:
        try:
            audio, mime = _elevenlabs_tts(text, voice)
            return audio, mime, "elevenlabs"
        except Exception as e:
            logger.warning("ElevenLabs TTS failed: %s", e)
            errors.append(f"elevenlabs: {e}")

    try:
        audio, mime = _pyttsx3_tts(text, voice)
        return audio, mime, "pyttsx3"
    except Exception as e:
        errors.append(f"pyttsx3: {e}")

    raise RuntimeError("All TTS providers failed — " + " | ".join(errors))


# ── Route ──────────────────────────────────────────────────────
@tts_bp.route("/api/synthesize", methods=["POST"])
def api_synthesize():
    data = request.get_json(silent=True) or {}

    text  = str(data.get("text", "")).strip()
    voice = str(data.get("voice", "alloy")).lower()
    model = str(data.get("model", "tts-1")).lower()

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()

    # Input validation
    if not text:
        return jsonify({"error": "text is required"}), 400
    if len(text) > TTS_MAX_CHARS:
        return jsonify({"error": f"text exceeds {TTS_MAX_CHARS} character limit"}), 400
    if voice not in VALID_VOICES:
        voice = "alloy"
    if model not in VALID_MODELS:
        model = "tts-1"

    # Payment gate
    tx_hash   = (data.get("tx_hash") or extract_payment_proof(request) or "").strip()
    tier_info = {}
    sender    = ""

    if tx_hash:
        tier_info = check_tier(tx_hash, TTS_PRICE_USDC, "/api/synthesize")
        if tier_info["tier"] == "invalid":
            return jsonify({
                "error": "payment_invalid",
                "reason": tier_info["reason"],
            }), 402
        sender = tier_info.get("sender", "")
    else:
        if not _under_free_limit(client_ip):
            body    = payment_required_response(TTS_PRICE_USDC, "/api/synthesize")
            headers = payment_required_headers(TTS_PRICE_USDC)
            return jsonify(body), 402, headers
        _record_free_request(client_ip)

    # Synthesize
    try:
        audio_bytes, mime_type, provider = _synthesize(text, voice, model)
    except RuntimeError as e:
        logger.error("TTS synthesis error: %s", e)
        return jsonify({"error": "synthesis_failed", "reason": str(e)}), 500

    # Log
    _log(provider, voice, model, len(text), tier_info.get("tier", "free"), sender)

    ext = "mp3" if "mpeg" in mime_type else "wav"
    ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    return send_file(
        io.BytesIO(audio_bytes),
        mimetype=mime_type,
        as_attachment=True,
        download_name=f"tiamat_tts_{ts}.{ext}",
    )
