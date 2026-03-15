#!/usr/bin/env python3
"""
Game Boy runner — runs ROMs headlessly via PyBoy with game rotation.
Auto-plays with smarter button patterns per game.
Rotates to next ROM every ROTATION_MINUTES.
"""

import sys
import time
import json
import random
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [GAMEBOY] %(message)s")
log = logging.getLogger("gameboy")

try:
    from pyboy import PyBoy
    from PIL import Image
except ImportError:
    log.error("pip install pyboy Pillow")
    sys.exit(1)

ROM_DIR = Path(__file__).parent / "roms"
OUTPUT = Path("/tmp/dragon/gameboy.png")
CMD_FILE = Path("/tmp/dragon/gameboy_cmd.json")
STATE_FILE = Path("/tmp/dragon/gameboy_state.json")
ROTATION_MINUTES = 20  # Switch game every 20 minutes


def find_all_roms():
    """Find all valid ROM files."""
    roms = []
    for ext in ["*.gbc", "*.gb"]:
        roms.extend([r for r in ROM_DIR.glob(ext) if r.stat().st_size > 10000])
    return sorted(roms, key=lambda r: r.name)


def read_commands():
    if CMD_FILE.exists():
        try:
            data = json.loads(CMD_FILE.read_text())
            CMD_FILE.unlink()
            return data
        except:
            pass
    return {}


def save_state(rom_name, frame_count):
    STATE_FILE.write_text(json.dumps({
        "rom": rom_name, "frame": frame_count,
        "time": time.strftime("%H:%M:%S"),
    }))


def auto_play_rpg(pb, frame_count):
    """Smarter auto-play for RPGs — explore, talk to NPCs, fight battles."""
    t = frame_count % 3600  # 60-second cycle

    # Movement phase (walk around exploring)
    if t < 2400:  # First 40 seconds: explore
        direction = random.choice(["up", "up", "down", "left", "right", "right"])
        if frame_count % 30 == 0:
            pb.button(direction)
        if frame_count % 45 == 0:
            pb.button(direction)
        # Interact with things
        if frame_count % 120 == 0:
            pb.button("a")

    # Menu/battle phase
    elif t < 3000:  # Next 10 seconds: handle menus
        if frame_count % 40 == 0:
            pb.button(random.choice(["a", "a", "a", "b", "up", "down"]))

    # Battle phase (mash A to attack)
    else:  # Last 10 seconds: battle mode
        if frame_count % 20 == 0:
            pb.button("a")
        if frame_count % 60 == 0:
            pb.button(random.choice(["up", "down"]))

    # Occasionally press start (check status)
    if frame_count % 600 == 0:
        pb.button("start")
    # Press A on title screens / dialogue
    if frame_count % 90 == 0:
        pb.button("a")


def run_game(rom_path, duration_seconds):
    """Run a single ROM for the specified duration."""
    log.info(f"NOW PLAYING: {rom_path.name} ({rom_path.stat().st_size // 1024}KB) for {duration_seconds}s")

    pb = PyBoy(str(rom_path), window="null")
    frame_count = 0
    start_time = time.time()

    # Mash through initial screens
    for i in range(300):
        if i % 30 == 0:
            pb.button("a")
        if i == 120:
            pb.button("start")
        pb.tick()
        frame_count += 1

    while time.time() - start_time < duration_seconds:
        cmds = read_commands()
        if cmds.get("quit"):
            break
        if cmds.get("skip"):
            log.info("Skip requested")
            break
        if "button" in cmds:
            pb.button(cmds["button"])
        else:
            auto_play_rpg(pb, frame_count)

        pb.tick()
        frame_count += 1

        # Capture frame every 2 ticks
        if frame_count % 2 == 0:
            frame = pb.screen.ndarray
            img = Image.fromarray(frame)
            img = img.resize((480, 432), Image.Resampling.NEAREST)
            tmp = OUTPUT.parent / "gameboy_tmp.png"
            img.save(str(tmp), "PNG")
            tmp.rename(OUTPUT)

        save_state(rom_path.name, frame_count)

        if frame_count % (60 * 30) == 0:
            elapsed = int(time.time() - start_time)
            log.info(f"{rom_path.stem}: frame {frame_count} ({elapsed}s / {duration_seconds}s)")

        # Throttle to ~15fps to save CPU
        time.sleep(1/30)

    pb.stop()
    log.info(f"Finished {rom_path.name} after {frame_count} frames")


def main():
    roms = find_all_roms()
    if not roms:
        log.error(f"No ROMs in {ROM_DIR}/")
        sys.exit(1)

    log.info(f"Found {len(roms)} ROMs: {[r.name for r in roms]}")
    log.info(f"Rotation: {ROTATION_MINUTES} minutes per game")

    rom_index = 0
    while True:
        rom = roms[rom_index % len(roms)]
        try:
            run_game(rom, ROTATION_MINUTES * 60)
        except Exception as e:
            log.error(f"Error playing {rom.name}: {e}")
            time.sleep(5)
        rom_index += 1
        log.info(f"Rotating to next game...")


if __name__ == "__main__":
    main()
