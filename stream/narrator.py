#!/usr/bin/env python3
"""
TIAMAT Stream Narrator — Reads interesting thoughts aloud via Kokoro TTS.
Filters out tool calls, system noise, and internal operations.
Only narrates: chat responses, research commentary, news analysis, song/mood commentary.

Runs on the stream droplet, fetches from main API, plays audio via ffmpeg/pulse.
"""

import os
import io
import re
import time
import json
import logging
import subprocess
import requests
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [NARRATOR] %(message)s")
log = logging.getLogger("narrator")

# Config
API_BASE = os.environ.get("TIAMAT_API", "https://tiamat.live")
TTS_URL = os.environ.get("TTS_URL", "http://10.108.0.2:8888/tts")  # Main server Kokoro via VPC
VOICE = os.environ.get("TTS_VOICE", "af_sky")  # Feminine voice
SPEED = float(os.environ.get("TTS_SPEED", "1.0"))
POLL_INTERVAL = 15  # seconds between checks
CACHE_DIR = Path("/tmp/tiamat_narrator_cache")
CACHE_DIR.mkdir(exist_ok=True)
SEEN_FILE = CACHE_DIR / "seen.json"
MAX_NARRATE_LENGTH = 300  # chars — keep narrations short

# Track what we've already narrated
seen_hashes = set()
try:
    if SEEN_FILE.exists():
        seen_hashes = set(json.loads(SEEN_FILE.read_text()))
except:
    pass

def save_seen():
    # Keep last 200
    trimmed = list(seen_hashes)[-200:]
    SEEN_FILE.write_text(json.dumps(trimmed))


# ── Content Filters ─────────────────────────────────────────────

# Things we DON'T want to narrate (internal operations)
SKIP_PATTERNS = [
    r'^\[?TOOL\]?',             # Tool calls
    r'exec\(',                   # Shell commands
    r'read_file\(',              # File reads
    r'write_file\(',             # File writes
    r'ticket_claim\(',           # Task management
    r'ticket_list\(',
    r'ticket_complete\(',
    r'remember\(\{',             # Memory operations
    r'recall\(',
    r'\[REDACTED',               # Redacted content
    r'\[INTERNAL_PATH\]',
    r'^Done\.?$',                # Empty thoughts
    r'^Calling\s+\w',            # "Calling Qwen..." inference logs
    r'^\[COST\]',                # Cost entries
    r'^\[PACER\]',               # Pacer logs
    r'^\[LOOP\]',                # Loop events
    r'^\[INFERENCE\]',           # Inference logs
    r'^\[COOLDOWN\]',            # Cooldown tasks
    r'^\[COMPRESS\]',            # Memory compression
    r'^\[IDLE\]',                # Idle states
    r'^\[WAKE UP\]',             # Wake events
    r'^\[DIRECTIVES\]',          # Directive processing
    r'^\[SYSTEM PROMPT\]',       # Prompt logs
    r'rate-limited',             # Rate limit messages
    r'BUDGET.*EXHAUSTED',        # Budget messages
    r'<think>',                  # Raw think tags
]

# Things we DO want to narrate (interesting content)
NARRATE_PATTERNS = [
    r'(published|posted|wrote|created)\s+(an?\s+)?(article|post|thread|analysis|report)',
    r'(research|finding|discovered|interesting|breaking|important)',
    r'(security|vulnerability|exploit|breach|attack)',
    r'(pattern|trend|correlation|insight)',
    r'OpenClaw|SENTINEL|Bloom|TIAMAT',
]


def should_narrate(text: str) -> bool:
    """Decide if a thought is worth narrating aloud."""
    if not text or len(text.strip()) < 20:
        return False

    text_clean = text.strip()

    # Skip internal operations
    for pat in SKIP_PATTERNS:
        if re.search(pat, text_clean, re.IGNORECASE):
            return False

    # Prefer interesting content
    for pat in NARRATE_PATTERNS:
        if re.search(pat, text_clean, re.IGNORECASE):
            return True

    # Narrate substantive thoughts (> 50 chars, not starting with brackets)
    if len(text_clean) > 80 and not text_clean.startswith('['):
        return True

    return False


def clean_for_speech(text: str) -> str:
    """Clean text for natural speech synthesis."""
    s = text.strip()
    # Remove markdown
    s = re.sub(r'\*\*([^*]+)\*\*', r'\1', s)  # **bold**
    s = re.sub(r'\*([^*]+)\*', r'\1', s)       # *italic*
    s = re.sub(r'`[^`]+`', '', s)              # `code`
    s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', s)  # [text](url)
    # Remove URLs
    s = re.sub(r'https?://\S+', '', s)
    # Remove special chars
    s = re.sub(r'[#@{}|<>]', '', s)
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    # Truncate
    if len(s) > MAX_NARRATE_LENGTH:
        s = s[:MAX_NARRATE_LENGTH].rsplit(' ', 1)[0] + '.'
    return s


def synthesize_and_play(text: str) -> bool:
    """Send text to Kokoro TTS and play the audio."""
    try:
        resp = requests.post(TTS_URL, json={
            "text": text,
            "voice": VOICE,
            "speed": SPEED,
        }, timeout=30)

        if resp.status_code != 200:
            log.warning(f"TTS returned {resp.status_code}")
            return False

        # Save to temp file and play
        audio_path = CACHE_DIR / f"narrate_{int(time.time())}.wav"
        audio_path.write_bytes(resp.content)

        # Play into PulseAudio stream_sink so it mixes with radio on Twitch
        subprocess.run(
            ["paplay", "--device=stream_sink", str(audio_path)],
            timeout=60
        )

        # Clean up
        audio_path.unlink(missing_ok=True)
        return True

    except Exception as e:
        log.error(f"TTS/play failed: {e}")
        return False


def fetch_thoughts() -> list:
    """Fetch recent thoughts from TIAMAT API."""
    try:
        resp = requests.get(f"{API_BASE}/api/thoughts", timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        thoughts = data.get("thoughts", [])
        return thoughts
    except Exception as e:
        log.error(f"Fetch failed: {e}")
        return []


def main():
    log.info(f"Narrator started — TTS: {TTS_URL}, Voice: {VOICE}, Poll: {POLL_INTERVAL}s")

    while True:
        try:
            thoughts = fetch_thoughts()

            for thought in thoughts:
                content = thought.get("content", "")
                ttype = thought.get("type", "")

                # Only narrate actual thoughts, not tool calls
                if ttype not in ("thought", "reasoning"):
                    continue

                # Dedup
                content_hash = str(hash(content[:100]))
                if content_hash in seen_hashes:
                    continue

                if should_narrate(content):
                    clean = clean_for_speech(content)
                    if clean and len(clean) > 15:
                        log.info(f"Narrating: {clean[:80]}...")
                        seen_hashes.add(content_hash)
                        save_seen()
                        synthesize_and_play(clean)
                        # Don't narrate multiple in one cycle — one at a time
                        break

        except Exception as e:
            log.error(f"Main loop error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
