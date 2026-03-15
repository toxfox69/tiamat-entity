#!/usr/bin/env python3
"""
TIAMAT Radio — Procedural synthwave radio using the synth engine.
Generates segments continuously, crossfades between them, plays to PulseAudio.
100% original, 0% DMCA risk.

Runs on the stream droplet, outputs to stream_sink for Twitch capture.
"""

import os
import sys
import time
import logging
import subprocess
import tempfile
import requests
import numpy as np

# Add parent dir for synth_engine import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from synth_engine import generate_segment, segment_metadata, MOOD_PROFILES, SR

import soundfile as sf

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [RADIO] %(message)s")
log = logging.getLogger("radio")

# Config
API_BASE = os.environ.get("TIAMAT_API", "https://tiamat.live")
SEGMENT_DURATION = 180.0  # seconds per segment (3 min, JRPG tracks auto-extend)
CROSSFADE = 3.0          # crossfade between segments
PULSE_DEVICE = os.environ.get("PULSE_SINK", "stream_sink")

# Track state
current_mood = "processing"
segment_count = 0


def get_tiamat_mood():
    """Fetch TIAMAT's current mood/state from API."""
    try:
        r = requests.get(f"{API_BASE}/api/thoughts", timeout=5)
        if r.ok:
            d = r.json()
            pacer = d.get("pacer", {})
            pace = pacer.get("pace", "idle")
            prod = pacer.get("productivity", 0)

            # Map pace/productivity to mood — mix synthwave and JRPG styles
            import random
            jrpg_moods = ["overworld", "town", "emotional", "dungeon", "battle"]
            synth_moods = ["strategic", "building", "resting", "processing"]

            # 70% JRPG, 30% synthwave
            if random.random() < 0.7:
                if pace == "burst":
                    return "battle"
                elif prod > 0.6:
                    return "overworld"
                elif prod < 0.2:
                    return random.choice(["town", "emotional"])
                else:
                    return random.choice(["overworld", "dungeon"])
            else:
                if pace == "burst":
                    return "strategic"
                elif prod > 0.6:
                    return "building"
                elif prod < 0.2:
                    return "resting"
                else:
                    return "processing"
    except:
        pass
    return "processing"


def play_audio(filepath):
    """Play a WAV file through PulseAudio stream_sink."""
    try:
        subprocess.run(
            ["paplay", f"--device={PULSE_DEVICE}", filepath],
            timeout=SEGMENT_DURATION + 10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.warning("Playback timed out")
    except Exception as e:
        log.error(f"Playback error: {e}")


def main():
    global current_mood, segment_count

    log.info(f"TIAMAT Radio started — {SEGMENT_DURATION}s segments, {CROSSFADE}s crossfade")
    log.info(f"Output device: {PULSE_DEVICE}")
    log.info(f"Available moods: {', '.join(MOOD_PROFILES.keys())}")

    # Pre-generate first segment
    seed = int(time.time())

    while True:
        try:
            # Check TIAMAT's mood
            new_mood = get_tiamat_mood()
            if new_mood != current_mood:
                log.info(f"Mood shift: {current_mood} → {new_mood}")
                current_mood = new_mood

            # Generate segment
            seed += 1
            segment_count += 1
            log.info(f"Generating segment #{segment_count}: mood={current_mood}, seed={seed}")

            t0 = time.time()
            audio = generate_segment(current_mood, seed=seed, duration=SEGMENT_DURATION)
            gen_time = time.time() - t0

            meta = segment_metadata(current_mood, seed)
            log.info(f"Generated in {gen_time:.1f}s — {meta['bpm']} BPM, {meta['key']}, {meta['style']}")

            # Save to temp file
            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False, dir='/tmp')
            sf.write(tmp.name, audio, SR)
            tmp.close()

            # Play
            log.info(f"Playing segment #{segment_count} ({SEGMENT_DURATION}s)")
            play_audio(tmp.name)

            # Clean up
            try:
                os.unlink(tmp.name)
            except:
                pass

        except KeyboardInterrupt:
            log.info("Radio stopped by user")
            break
        except Exception as e:
            log.error(f"Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
