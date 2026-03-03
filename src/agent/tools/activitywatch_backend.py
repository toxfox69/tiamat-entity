#!/usr/bin/env python3
"""
TIK-441: ActivityWatch Sync Backend — Phase 2

Server-side harness that wraps the Phase 1 sync module with:
  - activity_log memory schema (adds cycle_id, uses duration_s per spec)
  - [ACTIVITY] cost.log lines per TIK-441 spec
  - Self-registration in crontasks.json (5-minute schedule)
  - Max 50 events per run (inherited from Phase 1 MAX_EVENTS_PER_RUN)

Usage:
    python3 activitywatch_backend.py [cycle_id] [--dry-run]

Called automatically by the TIAMAT cron task manager (checkCronTasks in pacer.ts).
"""

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Import Phase 1 sync module ────────────────────────────────────────────────

_TOOLS_DIR = Path(__file__).parent
sys.path.insert(0, str(_TOOLS_DIR))

from activitywatch_sync import (
    check_aw_available,
    list_buckets,
    get_events,
    parse_event,
    log_activity,
    RELEVANT_BUCKET_PREFIXES,
    MAX_EVENTS_PER_RUN,
    DEFAULT_LOOKBACK_SECONDS,
    MEMORY_STORE_URL,
    MEMORY_TIMEOUT,
    COST_LOG,
)

# ── Config ────────────────────────────────────────────────────────────────────

CRONTASKS_PATH = "/root/.automaton/crontasks.json"
TASK_ID = "cron-441"
TASK_NAME = "activitywatch_backend"
SCHEDULE_MINUTES = 5

# ── Memory Store (activity_log schema) ────────────────────────────────────────


def store_activity_memory(event: dict, cycle_id: str) -> bool:
    """
    POST activity_log memory with TIK-441 schema:
    {type: 'activity_log', app, title, duration_s, timestamp, cycle_id}

    Note: duration_s (not duration_seconds) per spec.
    """
    memory = {
        "type": "activity_log",
        "app": event["app"],
        "title": event["title"],
        "duration_s": event["duration_seconds"],
        "timestamp": event["timestamp"],
        "cycle_id": cycle_id,
        "bucket": event.get("bucket", ""),
        "source": "activitywatch",
    }
    body = json.dumps({
        "content": (
            f"[ACTIVITY] {memory['app']} — {memory['title']} "
            f"for {memory['duration_s']}s at {memory['timestamp']} "
            f"(cycle {cycle_id})"
        ),
        "metadata": memory,
        "tags": ["activity", "activity_log", memory["app"].lower()[:32]],
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            MEMORY_STORE_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=MEMORY_TIMEOUT) as resp:
            return resp.status in (200, 201)
    except (urllib.error.URLError, OSError):
        return False


# ── Cost Log ──────────────────────────────────────────────────────────────────


def log_event_to_cost_log(app: str, title: str, duration_seconds: float) -> None:
    """
    Append one [ACTIVITY] line to cost.log per TIK-441 spec:
        [ACTIVITY] app_name window_title duration_seconds
    """
    # Sanitize: strip newlines so each event stays a single line
    safe_app = app.replace("\n", " ").replace("\r", "")[:64]
    safe_title = title.replace("\n", " ").replace("\r", "")[:128]
    line = f"[ACTIVITY] {safe_app} {safe_title} {duration_seconds:.1f}\n"
    try:
        with open(COST_LOG, "a") as f:
            f.write(line)
    except OSError:
        pass


# ── Self-Registration ─────────────────────────────────────────────────────────


def ensure_cron_registered() -> None:
    """
    Ensure cron-441 is in crontasks.json with a 5-minute schedule.
    Idempotent — no-op if already registered.
    Also replaces cron-439 (Phase 1 direct-sync task) if present.
    """
    try:
        try:
            with open(CRONTASKS_PATH, "r") as f:
                state = json.load(f)
        except (OSError, json.JSONDecodeError):
            state = {"tasks": []}

        existing_ids = {t.get("id") for t in state.get("tasks", [])}
        if TASK_ID in existing_ids:
            return  # already registered

        # Replace Phase 1 direct-sync task with this backend
        state["tasks"] = [
            t for t in state.get("tasks", []) if t.get("id") != "cron-439"
        ]

        state["tasks"].append({
            "id": TASK_ID,
            "name": TASK_NAME,
            "command": "python3 /root/entity/src/agent/tools/activitywatch_backend.py",
            "schedule_type": "minutes",
            "schedule_value": SCHEDULE_MINUTES,
            "last_run_cycle": None,
            "last_run_time": None,
            "last_result": None,
            "created_by_ticket": "TIK-441",
            "enabled": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        with open(CRONTASKS_PATH, "w") as f:
            json.dump(state, f, indent=2)

    except Exception:
        pass  # never fail on registration errors


# ── Main Backend Sync ─────────────────────────────────────────────────────────


def run_backend(
    cycle_id: str = "0",
    lookback_seconds: int = DEFAULT_LOOKBACK_SECONDS,
    dry_run: bool = False,
) -> dict:
    """
    Backend sync routine.

    Wraps Phase 1 event fetch/parse logic and stores memories with
    the TIK-441 activity_log schema (adds cycle_id, uses duration_s).

    Returns stats dict. Never raises — designed for unattended cron execution.
    """
    stats = {
        "aw_available": False,
        "cycle_id": cycle_id,
        "buckets_found": 0,
        "events_found": 0,
        "events_stored": 0,
        "total_duration_s": 0.0,
        "store_ok": 0,
        "store_fail": 0,
        "dry_run": dry_run,
    }

    # ── 1. AW availability — bail silently if unreachable ─────────────────────
    if not check_aw_available():
        return stats  # AW not installed or not running — not an error

    stats["aw_available"] = True

    # ── 2. Find relevant buckets ──────────────────────────────────────────────
    buckets = list_buckets()
    relevant = [
        b for b in buckets
        if any(b.get("id", "").startswith(p) for p in RELEVANT_BUCKET_PREFIXES)
    ]
    stats["buckets_found"] = len(relevant)

    if not relevant:
        return stats

    # ── 3. Fetch + parse events ───────────────────────────────────────────────
    end = datetime.now(timezone.utc)
    start = end - timedelta(seconds=lookback_seconds)

    all_events: list[dict] = []
    for bucket in relevant:
        bucket_id = bucket.get("id", "")
        raw_events = get_events(bucket_id, start, end)
        for ev in raw_events:
            parsed = parse_event(ev, bucket_id)
            if parsed:
                all_events.append(parsed)

    # Enforce rate limit: max 50 events per run
    all_events = all_events[:MAX_EVENTS_PER_RUN]
    stats["events_found"] = len(all_events)
    stats["total_duration_s"] = sum(e["duration_seconds"] for e in all_events)

    if not all_events:
        return stats

    # ── 4. Store memories + write cost.log ────────────────────────────────────
    for event in all_events:
        stats["events_stored"] += 1

        if dry_run:
            stats["store_ok"] += 1
            continue

        # Append [ACTIVITY] line to cost.log
        log_event_to_cost_log(event["app"], event["title"], event["duration_seconds"])

        # Store activity_log memory with cycle_id
        ok = store_activity_memory(event, cycle_id)
        if ok:
            stats["store_ok"] += 1
        else:
            stats["store_fail"] += 1

    # ── 5. Activity log summary ───────────────────────────────────────────────
    if not dry_run:
        top_apps: dict[str, float] = {}
        for e in all_events:
            top_apps[e["app"]] = top_apps.get(e["app"], 0) + e["duration_seconds"]
        top = sorted(top_apps.items(), key=lambda x: x[1], reverse=True)[:3]
        top_str = ", ".join(f"{a}={d:.0f}s" for a, d in top)

        log_activity(
            f"[TIK-441] cycle={cycle_id} synced={stats['events_stored']} "
            f"({stats['total_duration_s']:.0f}s total) | "
            f"top: {top_str} | "
            f"ok={stats['store_ok']} fail={stats['store_fail']}"
        )

    return stats


# ── CLI Entry Point ───────────────────────────────────────────────────────────


def main() -> None:
    cycle_id = sys.argv[1] if len(sys.argv) > 1 else "0"
    dry_run = "--dry-run" in sys.argv

    # Self-register cron task (idempotent)
    ensure_cron_registered()

    result = run_backend(cycle_id=cycle_id, dry_run=dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
