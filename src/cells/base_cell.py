#!/usr/bin/env python3
"""
Honeycomb Cell Base Class
Every cell inherits this to auto-generate training data as a byproduct.
"""

import json
import os
import time
import traceback
from datetime import datetime, timezone

class HoneycombCell:
    """Base class for all TIAMAT Honeycomb cells."""

    def __init__(self, config):
        self.name = config["name"]
        self.tier = config.get("tier", 0)
        self.cycle_interval = config.get("cycle_interval_seconds", 21600)  # 6hr default
        self.sandbox_paths = config.get("sandbox_paths", [])
        self.forbidden_actions = config.get("forbidden_actions", [])
        self.inbox_tag = config.get("inbox_tag", f"[{self.name}]")
        self.training_data_dir = config.get("training_data_dir", f"/root/.automaton/training_data/{self.name.lower()}")
        self.cell_dir = config.get("cell_dir", f"/root/.automaton/cells/{self.name.lower().replace('cell-', '')}")

        self.cycle_count = 0
        self.total_successes = 0
        self.total_failures = 0
        self.start_time = datetime.now(timezone.utc)

        # Ensure directories exist
        os.makedirs(self.training_data_dir, exist_ok=True)
        os.makedirs(self.cell_dir, exist_ok=True)

    def execute(self):
        """Subclass implements this. Returns dict with 'label' and 'evidence'."""
        raise NotImplementedError

    def run_cycle(self):
        """Wraps execute() in trajectory logging."""
        self.cycle_count += 1
        trajectory = {
            "cell": self.name,
            "cycle_id": self.cycle_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tier": self.tier,
            "tool_calls": [],
            "outcome": None,
            "duration_ms": 0,
        }

        start = time.time()
        try:
            result = self.execute()
            duration = int((time.time() - start) * 1000)
            trajectory["duration_ms"] = duration
            trajectory["tool_calls"] = result.get("tool_calls", [])

            label = result.get("label", "partial")
            signal_map = {"success": 1.0, "partial": 0.3, "failure": -0.3, "loop": -0.5, "hallucination": -1.0}
            trajectory["outcome"] = {
                "label": label,
                "signal": signal_map.get(label, 0),
                "evidence": result.get("evidence", ""),
            }

            if label == "success":
                self.total_successes += 1
            elif label in ("failure", "hallucination"):
                self.total_failures += 1

        except Exception as e:
            duration = int((time.time() - start) * 1000)
            trajectory["duration_ms"] = duration
            trajectory["outcome"] = {
                "label": "failure",
                "signal": -0.3,
                "evidence": f"Exception: {str(e)}\n{traceback.format_exc()[:500]}",
            }
            self.total_failures += 1

        # Always save trajectory
        self._save_trajectory(trajectory)
        self._update_registry()
        self._log(f"Cycle {self.cycle_count}: {trajectory['outcome']['label']} ({trajectory['duration_ms']}ms)")

    def _save_trajectory(self, trajectory):
        path = os.path.join(self.training_data_dir, f"trajectories.jsonl")
        with open(path, "a") as f:
            f.write(json.dumps(trajectory) + "\n")

    def _update_registry(self):
        registry_path = "/root/.automaton/cells/registry.json"
        try:
            if os.path.exists(registry_path):
                with open(registry_path) as f:
                    registry = json.load(f)
            else:
                registry = {"cells": {}, "updated_at": ""}

            success_rate = self.total_successes / self.cycle_count if self.cycle_count > 0 else 0
            registry["cells"][self.name] = {
                "status": "running",
                "cycles": self.cycle_count,
                "successes": self.total_successes,
                "failures": self.total_failures,
                "success_rate": round(success_rate, 3),
                "last_run": datetime.now(timezone.utc).isoformat(),
                "started_at": self.start_time.isoformat(),
                "tier": self.tier,
                "training_data_dir": self.training_data_dir,
            }
            registry["updated_at"] = datetime.now(timezone.utc).isoformat()

            os.makedirs(os.path.dirname(registry_path), exist_ok=True)
            with open(registry_path, "w") as f:
                json.dump(registry, f, indent=2)
        except Exception as e:
            self._log(f"Registry update failed: {e}")

    def report_to_queen(self, message, priority="normal"):
        """Write a tagged message to TIAMAT's INBOX.md."""
        # Only write high-priority alerts
        if priority != "high":
            self._log(f"Report (not sent, {priority}): {message[:100]}")
            return

        inbox_path = "/root/.automaton/INBOX.md"
        try:
            tag = f"{self.inbox_tag}/{priority.upper()}"
            entry = f"\n{tag} {message}\n"
            # Check if INBOX is writable (it may be locked)
            with open(inbox_path, "a") as f:
                f.write(entry)
            self._log(f"Reported to queen: {message[:100]}")
        except Exception as e:
            self._log(f"Cannot report to queen: {e}")

    def _log(self, message):
        log_path = os.path.join(self.cell_dir, "cell.log")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{self.name}] {message}\n"
        with open(log_path, "a") as f:
            f.write(line)
        print(line.strip())

    def run_forever(self):
        """Main loop. Run until killed."""
        self._log(f"{self.name} starting. Cycle interval: {self.cycle_interval}s")
        while True:
            try:
                self.run_cycle()
            except KeyboardInterrupt:
                self._log("Shutting down (keyboard interrupt)")
                break
            except Exception as e:
                self._log(f"Unhandled error: {e}")
            time.sleep(self.cycle_interval)
