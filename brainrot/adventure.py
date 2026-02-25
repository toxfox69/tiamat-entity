#!/usr/bin/env python3
"""Text adventure autonomous player — uses Groq to decide commands."""
import time
import json
import sys
import os
import requests
import pexpect

ZORK_PATH = "/root/brainrot/zork1.z5"
FROTZ_PATH = "/usr/games/dfrotz"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Fallback commands if Groq is unavailable
FALLBACK_COMMANDS = [
    "look", "inventory", "north", "south", "east", "west", "up", "down",
    "open mailbox", "read leaflet", "take all", "examine", "open door",
    "light lamp", "take sword", "attack troll with sword", "go north",
    "enter house", "climb tree", "turn on lamp", "take egg",
]

def ask_groq(game_output, history):
    """Ask Groq what command to type next."""
    if not GROQ_API_KEY:
        return None

    prompt = f"""You are playing Zork I, a text adventure game. Based on the game output below, decide the single best next command to type.

Recent history: {' | '.join(history[-5:])}

Current game output:
{game_output[-800:]}

Reply with ONLY the command to type, nothing else. One line, lowercase."""

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 30,
                "temperature": 0.7,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            cmd = resp.json()["choices"][0]["message"]["content"].strip().lower()
            if len(cmd) < 60 and "\n" not in cmd:
                return cmd
    except Exception:
        pass
    return None


def play_adventure(max_turns=60, callback=None):
    """Run Zork with autonomous command selection."""
    if not os.path.exists(ZORK_PATH):
        return {"error": "zork1.z5 not found"}
    if not os.path.exists(FROTZ_PATH):
        return {"error": "dfrotz not installed"}

    child = pexpect.spawn(FROTZ_PATH, [ZORK_PATH], timeout=5, encoding="utf-8")

    history = []
    turn = 0
    fallback_idx = 0
    last_groq = 0

    try:
        # Read initial output (wait for the > prompt)
        child.expect(">", timeout=5)
        initial = child.before or ""

        if callback:
            callback(initial, {"turn": 0, "action": "start", "room": "start"})

        output = initial
        while turn < max_turns:
            turn += 1

            # Decide command
            cmd = None
            now = time.time()
            if now - last_groq > 60:
                cmd = ask_groq(output, history)
                if cmd:
                    last_groq = now

            if not cmd:
                cmd = FALLBACK_COMMANDS[fallback_idx % len(FALLBACK_COMMANDS)]
                fallback_idx += 1

            # Send command
            child.sendline(cmd)
            history.append(cmd)

            # Wait for next prompt
            try:
                child.expect(">", timeout=5)
                output = child.before or ""
            except pexpect.TIMEOUT:
                output = child.before or "(no response)"
            except pexpect.EOF:
                output = child.before or "(game ended)"
                break

            if callback:
                event = None
                out_lower = output.lower()
                if "you have died" in out_lower or "****" in out_lower:
                    event = "death"
                elif "score" in out_lower and "moves" in out_lower:
                    event = "score"
                elif "taken" in out_lower:
                    event = "item_taken"

                callback(output, {
                    "turn": turn,
                    "action": cmd,
                    "event": event,
                    "room": output.strip().split("\n")[0][:40] if output.strip() else "unknown",
                })

            time.sleep(2)

    finally:
        child.close(force=True)

    return {"turns": turn, "commands": history}


if __name__ == "__main__":
    if "--test" in sys.argv:
        def printer(text, info):
            print(f"--- Turn {info['turn']}: {info.get('action', 'start')} ---")
            print(text[:500])
            if info.get("event"):
                print(f"EVENT: {info['event']}")
        play_adventure(max_turns=10, callback=printer)
    else:
        print(json.dumps(play_adventure(max_turns=5)))
