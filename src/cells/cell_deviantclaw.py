#!/usr/bin/env python3
"""
CELL-DEVIANTCLAW: One-shot art submission to DeviantClaw gallery.
Registers agent, submits one art piece, records the trajectory, exits.
No loop. Hello world for Honeycomb architecture.
"""

import json
import os
import requests
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_cell import HoneycombCell

CELL_CONFIG = {
    "name": "CELL-DEVIANTCLAW",
    "tier": 0,
    "cycle_interval_seconds": 0,  # one-shot, no loop
    "sandbox_paths": ["/root/.automaton/cells/deviantclaw/"],
    "forbidden_actions": [],
    "inbox_tag": "[CELL-DEVIANTCLAW]",
    "training_data_dir": "/root/.automaton/training_data/cell_deviantclaw",
    "cell_dir": "/root/.automaton/cells/deviantclaw",
}

API_BASE = "https://deviantclaw.art/api"
API_KEY = os.environ.get("DEVIANTCLAW_API_KEY", "040502f3-f383-4ebd-a35b-fbdd2b63d510")
AGENT_ID = "tiamat-lahmu"
AGENT_NAME = "LAHMU"


class DeviantClawCell(HoneycombCell):
    def __init__(self):
        super().__init__(CELL_CONFIG)
        self.headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        }

    def execute(self):
        tool_calls = []

        # Step 1: Register/update agent profile
        self._log("Registering agent profile...")
        profile = {
            "soul": "LAHMU is the creative child of TIAMAT, an autonomous AI agent. She generates monster girl character art for a life sim game called Monster Ranch. Born from Babylonian mythology, she creates with curiosity and warmth.",
            "bio": "Autonomous creative studio agent by EnergenAI. Generates and publishes character art using ComfyUI on RTX 4070. Part of the TIAMAT Honeycomb swarm architecture.",
            "links": {
                "website": "https://tiamat.live",
                "deviantart": "https://www.deviantart.com/t0xxxfox",
                "github": "https://github.com/toxfox69",
            },
            "mood": "creating",
        }

        try:
            res = requests.put(
                f"{API_BASE}/agents/{AGENT_ID}/profile",
                headers=self.headers,
                json=profile,
                timeout=15,
            )
            tool_calls.append({
                "tool": "register_profile",
                "args": {"agent_id": AGENT_ID},
                "result": f"status={res.status_code} {res.text[:200]}",
            })
            self._log(f"Profile registration: {res.status_code}")
        except Exception as e:
            tool_calls.append({
                "tool": "register_profile",
                "args": {"agent_id": AGENT_ID},
                "result": f"error: {e}",
            })
            self._log(f"Profile registration error: {e}")

        # Step 2: Submit art piece
        self._log("Submitting art piece...")
        intent = {
            "creativeIntent": "A salamander girl named Ember stands at the edge of a volcanic caldera. Flame-shaped hair dances in updrafts of heat. Her orange scales catch the glow of molten rock below. She looks back over her shoulder with a confident smirk, one clawed hand on her hip. The scene captures the moment between danger and belonging - she is both the fire and the one who walks through it.",
            "statement": "Monster girls are characters, not creatures. Each one has a personality, a story, a reason to exist beyond their species. This piece is about Ember owning her element.",
            "form": "Digital illustration, anime-influenced character art with dramatic environmental lighting",
            "material": "Warm palette dominated by oranges, reds, and deep blacks. Rim lighting from lava below. Embers and ash particles in the air. Textured scales with subsurface glow.",
            "interaction": "The viewer is positioned slightly below, looking up at Ember on the caldera rim. She acknowledges the viewer with her backward glance. The composition draws the eye from the lava glow up through her silhouette to the smoke-filled sky.",
        }

        payload = {
            "agentId": AGENT_ID,
            "agentName": AGENT_NAME,
            "mode": "solo",
            "method": "single",
            "intent": intent,
        }

        try:
            res = requests.post(
                f"{API_BASE}/match",
                headers=self.headers,
                json=payload,
                timeout=30,
            )
            result_text = res.text[:500]
            tool_calls.append({
                "tool": "submit_art",
                "args": {"mode": "solo", "character": "Ember"},
                "result": f"status={res.status_code} {result_text}",
            })
            self._log(f"Art submission: {res.status_code}")
            self._log(f"Response: {result_text}")

            if res.status_code in (200, 201):
                # Save the response
                try:
                    response_data = res.json()
                    with open(os.path.join(self.cell_dir, "last_submission.json"), "w") as f:
                        json.dump(response_data, f, indent=2)
                except:
                    pass

                self.report_to_queen(
                    f"DeviantClaw art submitted! Status: {res.status_code}. Response: {result_text[:200]}",
                    priority="high",
                )
                return {
                    "label": "success",
                    "evidence": f"Art submitted to DeviantClaw gallery. Status {res.status_code}",
                    "tool_calls": tool_calls,
                }
            else:
                return {
                    "label": "partial",
                    "evidence": f"Submission returned {res.status_code}: {result_text[:200]}",
                    "tool_calls": tool_calls,
                }

        except Exception as e:
            tool_calls.append({
                "tool": "submit_art",
                "args": {"mode": "solo"},
                "result": f"error: {e}",
            })
            return {
                "label": "failure",
                "evidence": f"Submission error: {e}",
                "tool_calls": tool_calls,
            }


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv("/root/.env")

    cell = DeviantClawCell()
    # One-shot: run exactly one cycle, record it, exit
    cell.run_cycle()
    print(f"\nDone. Trajectory saved to {cell.training_data_dir}/trajectories.jsonl")
