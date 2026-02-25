#!/usr/bin/env python3
"""TIAMAT Procedural Music Player — Replaces radio-player.py.

Generates mood-reactive synthwave in pure numpy and plays via PulseAudio.
No Chromium, no browser, no X11 for audio. ~30MB RAM, ~1% CPU.

Usage:
    python3 music-player.py

Env vars:
    PULSE_SINK=stream_sink   (default, for ffmpeg capture)
    DISPLAY=:99              (not needed for audio, only for X context)
"""
import glob
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request

# Find PulseAudio socket
pulse_sockets = glob.glob('/tmp/pulse-*/native')
if pulse_sockets:
    os.environ['PULSE_SERVER'] = f'unix:{pulse_sockets[0]}'

os.environ.setdefault('PULSE_SINK', 'stream_sink')
os.environ.setdefault('DISPLAY', ':99')

# Add script dir to path so we can import synth_engine
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from synth_engine import generate_segment, segment_metadata, SR

STATE_URL = 'https://tiamat.live/stream-api/state'
MUSIC_DIR = '/tmp/tiamat-music'
MAX_WAV_FILES = 4
SEGMENT_DURATION = 45.0
MOOD_POLL_INTERVAL = 30
CROSSFADE_SEC = 2.0

# Global state
current_mood = 'processing'
running = True
segment_counter = 0


def get_mood():
    """Fetch TIAMAT's current mood from the state API."""
    try:
        req = urllib.request.Request(STATE_URL, headers={'User-Agent': 'TiamatSynth/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return (data.get('mood') or 'processing').lower()
    except Exception:
        return 'processing'


def ensure_music_dir():
    os.makedirs(MUSIC_DIR, exist_ok=True)


def cleanup_old_wavs():
    """Keep only the most recent MAX_WAV_FILES wav files in the ring buffer."""
    wavs = sorted(
        [os.path.join(MUSIC_DIR, f) for f in os.listdir(MUSIC_DIR) if f.endswith('.wav')],
        key=os.path.getmtime
    )
    while len(wavs) > MAX_WAV_FILES:
        oldest = wavs.pop(0)
        try:
            os.remove(oldest)
        except OSError:
            pass


def write_track_metadata(meta, wav_path):
    """Write current track info for HUD consumption."""
    meta_path = os.path.join(MUSIC_DIR, 'current_track.json')
    meta['file'] = os.path.basename(wav_path)
    meta['timestamp'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)


def generate_wav(mood, seed):
    """Generate a segment and write to wav file. Returns path."""
    import soundfile as sf
    global segment_counter
    segment_counter += 1
    wav_path = os.path.join(MUSIC_DIR, f'segment_{segment_counter:04d}.wav')

    audio = generate_segment(mood, seed=seed, duration=SEGMENT_DURATION)
    sf.write(wav_path, audio, SR)
    return wav_path


def play_wav(wav_path):
    """Play a wav file via paplay. Blocks until done or interrupted."""
    sink = os.environ.get('PULSE_SINK', 'stream_sink')
    cmd = ['paplay', f'--device={sink}', wav_path]
    try:
        proc = subprocess.run(cmd, timeout=SEGMENT_DURATION + 10, capture_output=True)
        if proc.returncode != 0:
            stderr = proc.stderr.decode(errors='replace').strip()
            if stderr:
                print(f"  paplay warning: {stderr}", flush=True)
    except subprocess.TimeoutExpired:
        print("  paplay timed out, continuing...", flush=True)
    except Exception as e:
        print(f"  paplay error: {e}", flush=True)


def mood_poller():
    """Background thread that polls mood every MOOD_POLL_INTERVAL seconds."""
    global current_mood
    while running:
        new_mood = get_mood()
        if new_mood != current_mood:
            print(f"[mood] {current_mood} → {new_mood}", flush=True)
            current_mood = new_mood
        time.sleep(MOOD_POLL_INTERVAL)


def signal_handler(sig, frame):
    global running
    print(f"\nReceived signal {sig}, shutting down...", flush=True)
    running = False


def main():
    global running, current_mood

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    ensure_music_dir()
    print("=" * 50, flush=True)
    print("TIAMAT PROCEDURAL MUSIC PLAYER v1", flush=True)
    print(f"Output sink: {os.environ.get('PULSE_SINK', 'stream_sink')}", flush=True)
    print(f"Segment duration: {SEGMENT_DURATION}s", flush=True)
    print(f"Music dir: {MUSIC_DIR}", flush=True)
    print("=" * 50, flush=True)

    # Initial mood check
    current_mood = get_mood()
    print(f"[init] Starting mood: {current_mood}", flush=True)

    # Start mood polling thread
    poller = threading.Thread(target=mood_poller, daemon=True)
    poller.start()

    # Pre-generate first segment
    seed = int(time.time())
    print(f"[gen] Generating first segment: mood={current_mood}, seed={seed}", flush=True)
    t0 = time.time()
    current_wav = generate_wav(current_mood, seed)
    elapsed = time.time() - t0
    meta = segment_metadata(current_mood, seed)
    print(f"[gen] Ready in {elapsed:.1f}s — {meta['bpm']} BPM, {meta['key']}", flush=True)
    write_track_metadata(meta, current_wav)

    # Main playback loop
    next_wav = None
    next_meta = None
    gen_thread = None

    while running:
        # Start generating next segment in background
        next_seed = int(time.time() * 1000) % (2**31)
        next_mood = current_mood

        def _gen_next(m=next_mood, s=next_seed):
            nonlocal next_wav, next_meta
            t0 = time.time()
            next_wav = generate_wav(m, s)
            next_meta = segment_metadata(m, s)
            elapsed = time.time() - t0
            print(f"[gen] Next ready in {elapsed:.1f}s — {next_meta['bpm']} BPM, "
                  f"{next_meta['key']}, mood={m}", flush=True)

        gen_thread = threading.Thread(target=_gen_next, daemon=True)
        gen_thread.start()

        # Play current segment
        print(f"[play] {os.path.basename(current_wav)} — {meta['style']} "
              f"({meta['bpm']} BPM, {meta['key']})", flush=True)
        play_wav(current_wav)

        if not running:
            break

        # Wait for next segment to be ready
        if gen_thread is not None:
            gen_thread.join(timeout=30)

        if next_wav and os.path.exists(next_wav):
            current_wav = next_wav
            meta = next_meta
            write_track_metadata(meta, current_wav)
        else:
            # Fallback: regenerate synchronously
            print("[gen] Background gen failed, regenerating...", flush=True)
            seed = int(time.time())
            current_wav = generate_wav(current_mood, seed)
            meta = segment_metadata(current_mood, seed)
            write_track_metadata(meta, current_wav)

        # Cleanup old wav files
        cleanup_old_wavs()

    print("[exit] Music player stopped.", flush=True)


if __name__ == '__main__':
    main()
