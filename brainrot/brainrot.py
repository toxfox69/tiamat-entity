#!/usr/bin/env python3
"""TIAMAT Brainrot — Autonomous terminal visualization orchestrator.
Cycles through visual modes, streams output to /thoughts neural feed.
"""
import json
import logging
import os
import random
import signal
import subprocess
import sys
import time
import requests

# ── Config ────────────────────────────────────────────────────
THOUGHTS_PUSH_URL = "http://127.0.0.1:5000/thoughts/push"
LOG_FILE = "/root/.automaton/brainrot.log"
PID_FILE = "/tmp/brainrot.pid"
MODES_FILE = os.path.join(os.path.dirname(__file__), "modes.json")
BRAINROT_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [BRAINROT] %(message)s",
)
log = logging.getLogger("brainrot")

# Also log to stdout
console = logging.StreamHandler()
console.setLevel(logging.INFO)
log.addHandler(console)

running = True
last_groq_call = 0


def signal_handler(sig, frame):
    global running
    log.info("Shutdown signal received")
    running = False

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def load_modes():
    try:
        with open(MODES_FILE) as f:
            return json.load(f)
    except Exception:
        return {"modes": {}, "max_load_avg": 2.0, "max_memory_mb": 200}


def push_thought(thought_type, mode, content, data=None):
    """Push a thought to the /thoughts SSE endpoint."""
    thought = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "type": thought_type,
        "mode": mode,
        "content": str(content)[:2000],
        "data": data or {},
    }
    try:
        requests.post(THOUGHTS_PUSH_URL, json=thought, timeout=5)
    except Exception:
        pass  # Non-critical


def check_system_load(max_load):
    """Return True if system is OK to run."""
    try:
        load1 = os.getloadavg()[0]
        return load1 < max_load
    except Exception:
        return True


def pick_mode(modes_config):
    """Weighted random mode selection."""
    modes = modes_config.get("modes", {})
    items = list(modes.items())
    weights = [m.get("weight", 10) for _, m in items]
    total = sum(weights)
    r = random.uniform(0, total)
    cumulative = 0
    for (name, cfg), w in zip(items, weights):
        cumulative += w
        if r <= cumulative:
            duration = random.randint(cfg.get("duration_min", 120), cfg.get("duration_max", 300))
            return name, cfg, duration
    return items[0][0], items[0][1], 180


# ── Mode Runners ──────────────────────────────────────────────

def run_cmatrix(duration):
    """Run cmatrix and capture frames."""
    log.info(f"MODE: cmatrix ({duration}s)")
    push_thought("visual", "cmatrix", "/// INITIALIZING MATRIX RAIN ///")

    end = time.time() + duration
    try:
        proc = subprocess.Popen(
            ["script", "-qc", "cmatrix -b -u 2 -C green", "/dev/null"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "TERM": "xterm-256color"},
        )
        while running and time.time() < end:
            time.sleep(3)
            push_thought("visual", "cmatrix",
                "█▓▒░ MATRIX RAIN ACTIVE ░▒▓█\n" +
                "".join(random.choice("01アイウエオカキクケコTIAMAT") for _ in range(200)),
                {"elapsed": int(time.time() - (end - duration))})
        proc.terminate()
    except FileNotFoundError:
        log.warning("cmatrix not installed, generating synthetic rain")
        while running and time.time() < end:
            chars = "01アイウエオカキクケコサシスセソタチツテト"
            frame = "\n".join("".join(random.choice(chars) for _ in range(60)) for _ in range(20))
            push_thought("visual", "cmatrix", frame)
            time.sleep(3)


def run_pipes(duration):
    """Run pipes.sh or synthetic pipes."""
    log.info(f"MODE: pipes ({duration}s)")
    push_thought("visual", "pipes", "/// INITIALIZING PIPE NETWORK ///")

    pipe_chars = "┃┏┓┗┛┣┫┳┻╋━║╔╗╚╝╠╣╦╩╬"
    end = time.time() + duration
    while running and time.time() < end:
        frame = "\n".join(
            "".join(random.choice(pipe_chars + "  ") for _ in range(60))
            for _ in range(20)
        )
        push_thought("visual", "pipes", frame)
        time.sleep(3)


def run_gol(duration):
    """Run Conway's Game of Life."""
    log.info(f"MODE: gol ({duration}s)")
    push_thought("consciousness", "gol", "/// CELLULAR AUTOMATA INITIALIZING ///")

    sys.path.insert(0, BRAINROT_DIR)
    from gol import GameOfLife, PATTERNS

    pattern = random.choice(list(PATTERNS.keys()) + ["random"])
    game = GameOfLife(60, 25, pattern if pattern != "random" else None)
    if pattern == "random":
        game.pattern_name = "random"

    end = time.time() + duration
    while running and time.time() < end and len(game.grid) > 0:
        frame = game.render()
        event = game.detect_event()
        stats = game.stats()

        content = f"Generation {stats['generation']} | Cells: {stats['live_cells']} | Pattern: {stats['pattern']}"
        if event:
            content += f" | EVENT: {event}"
            log.info(f"GOL event: {event} at gen {stats['generation']}")

        push_thought("consciousness", "gol", f"{content}\n{frame}", {
            "generation": stats["generation"],
            "live_cells": stats["live_cells"],
            "event": event,
            "pattern": stats["pattern"],
        })

        game.step()
        time.sleep(0.3)

    push_thought("consciousness", "gol",
        f"Simulation ended at generation {game.gen}. Final population: {len(game.grid)}")


def run_chess(duration):
    """Run auto-chess game."""
    log.info(f"MODE: chess ({duration}s)")
    push_thought("strategy", "chess", "/// CHESS ENGINE INITIALIZING ///")

    sys.path.insert(0, BRAINROT_DIR)
    try:
        from chess_player import play_game

        move_count = [0]
        end_time = time.time() + duration

        def chess_callback(frame, info):
            if not running or time.time() > end_time:
                return
            if "game_over" in info:
                content = f"GAME OVER: {info['result']} ({info['winner']}) in {info['total_moves']} moves"
                push_thought("strategy", "chess", f"{content}\n{frame}", info)
                log.info(content)
            else:
                content = f"Move {info['move_num']}: {info['move']}"
                push_thought("strategy", "chess", f"{content}\n{frame}", info)
                move_count[0] = info["move_num"]

        play_game(depth=5, callback=chess_callback)

    except Exception as e:
        log.error(f"Chess error: {e}")
        push_thought("strategy", "chess", f"Chess engine error: {e}")


def run_zork(duration):
    """Run Zork text adventure."""
    log.info(f"MODE: zork ({duration}s)")
    push_thought("narrative", "zork", "/// LOADING ZORK I: THE GREAT UNDERGROUND EMPIRE ///")

    sys.path.insert(0, BRAINROT_DIR)
    try:
        from adventure import play_adventure

        max_turns = duration // 8  # ~8 seconds per turn

        def zork_callback(text, info):
            if not running:
                return
            content = text[:500] if text else ""
            event = info.get("event")
            if event:
                content = f"[{event.upper()}] {content}"
                log.info(f"Zork event: {event} at turn {info['turn']}")

            push_thought("narrative", "zork", content, {
                "turn": info["turn"],
                "action": info.get("action", ""),
                "room": info.get("room", ""),
                "event": event,
            })

        play_adventure(max_turns=max_turns, callback=zork_callback)

    except Exception as e:
        log.error(f"Zork error: {e}")
        push_thought("narrative", "zork", f"Adventure error: {e}")


def run_nethack(duration):
    """Run nethack with random inputs."""
    log.info(f"MODE: nethack ({duration}s)")
    push_thought("game", "nethack", "/// NETHACK: DESCENDING INTO THE DUNGEON ///")

    moves = "hjklyubn.s"  # vi movement + search + wait
    end = time.time() + duration

    try:
        proc = subprocess.Popen(
            ["nethack", "-u", "TIAMAT"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "TERM": "xterm-256color"},
        )
        while running and time.time() < end and proc.poll() is None:
            cmd = random.choice(moves)
            try:
                proc.stdin.write(cmd.encode())
                proc.stdin.flush()
            except BrokenPipeError:
                break
            time.sleep(1)
            push_thought("game", "nethack",
                f"TIAMAT explores the dungeon... [action: {cmd}]",
                {"action": cmd})
        proc.terminate()
    except FileNotFoundError:
        log.warning("nethack not installed")
        push_thought("game", "nethack", "Nethack not available — skipping")


def run_moon_buggy(duration):
    """Run moon-buggy with random jumps."""
    log.info(f"MODE: moon_buggy ({duration}s)")
    push_thought("game", "moon_buggy", "/// MOON BUGGY: LUNAR SURFACE TRAVERSE ///")

    end = time.time() + duration
    try:
        proc = subprocess.Popen(
            ["moon-buggy"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "TERM": "xterm-256color"},
        )
        while running and time.time() < end and proc.poll() is None:
            action = random.choice(["j", " ", "j", " ", "a"])  # jump/shoot
            try:
                proc.stdin.write(action.encode())
                proc.stdin.flush()
            except BrokenPipeError:
                break
            time.sleep(0.3)
        proc.terminate()
    except FileNotFoundError:
        log.warning("moon-buggy not installed")
        push_thought("game", "moon_buggy", "Moon-buggy not available — skipping")


MODE_RUNNERS = {
    "cmatrix": run_cmatrix,
    "pipes": run_pipes,
    "gol": run_gol,
    "chess": run_chess,
    "zork": run_zork,
    "nethack": run_nethack,
    "moon_buggy": run_moon_buggy,
}


# ── Main Loop ─────────────────────────────────────────────────

def main():
    # Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    log.info("=== BRAINROT ORCHESTRATOR STARTED ===")
    push_thought("visual", "system", "/// TIAMAT BRAINROT ENGINE ONLINE ///")

    config = load_modes()
    cycle = 0

    while running:
        # Check system load
        max_load = config.get("max_load_avg", 2.0)
        if not check_system_load(max_load):
            log.info(f"Load too high, pausing 30s...")
            push_thought("visual", "system", "System load high — entering cooldown")
            time.sleep(30)
            continue

        # Pick mode
        mode_name, mode_cfg, duration = pick_mode(config)
        cycle += 1
        log.info(f"Cycle {cycle}: {mode_name} for {duration}s")

        # Run mode
        runner = MODE_RUNNERS.get(mode_name)
        if runner:
            try:
                runner(duration)
            except Exception as e:
                log.error(f"Mode {mode_name} crashed: {e}")
                push_thought("visual", "system", f"Mode {mode_name} error — switching")
        else:
            log.warning(f"Unknown mode: {mode_name}")

        # Brief pause between modes
        if running:
            push_thought("visual", "system", f"/// MODE SWITCH — CYCLE {cycle} COMPLETE ///")
            time.sleep(5)

    log.info("=== BRAINROT ORCHESTRATOR STOPPED ===")
    push_thought("visual", "system", "/// BRAINROT ENGINE OFFLINE ///")

    # Cleanup PID
    try:
        os.remove(PID_FILE)
    except Exception:
        pass


if __name__ == "__main__":
    main()
