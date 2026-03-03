#!/usr/bin/env python3
"""
TIK-439: ActivityWatch Syncing Plugin — Phase 1

Polls local ActivityWatch REST API (localhost:3636) for activity logs,
stores structured memories to the TIAMAT memory API, and appends a
time-tracking summary line to cost.log.

Designed to run as a cooldown task between agent cycles — fully non-blocking
with graceful degradation when ActivityWatch is unavailable.

Usage (standalone):
    python3 activitywatch_sync.py
    python3 activitywatch_sync.py '{"lookback_seconds": 300, "dry_run": true}'

Integration (from loop.ts cooldown):
    execFileSync('python3', ['/root/entity/src/agent/tools/activitywatch_sync.py'])
"""

import json
import sys
import os
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional

# ── Config ──────────────────────────────────────────────────────────────────

AW_BASE = "http://localhost:3636/api/0"
AW_TIMEOUT = 3  # seconds — never block cycle execution

MEMORY_API = os.environ.get("MEMORY_API_URL", "http://localhost:5001")
MEMORY_STORE_URL = f"{MEMORY_API}/api/memory/store"
MEMORY_TIMEOUT = 5  # seconds

COST_LOG = os.environ.get("COST_LOG", "/root/.automaton/cost.log")
ACTIVITY_LOG = "/root/.automaton/activity.log"

# How far back to look for events (default: last 5 minutes to avoid re-processing)
DEFAULT_LOOKBACK_SECONDS = 300

# Bucket types we care about
RELEVANT_BUCKET_PREFIXES = (
    "aw-watcher-window",
    "aw-watcher-afk",
    "aw-watcher-web",
)

# Minimum event duration to store (filter noise)
MIN_DURATION_SECONDS = 5.0

# Rate limit: max events to store per sync run
MAX_EVENTS_PER_RUN = 50


# ── ActivityWatch API ────────────────────────────────────────────────────────

def _aw_get(path: str) -> Optional[dict | list]:
    """GET from AW REST API. Returns None if unavailable."""
    url = f"{AW_BASE}{path}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=AW_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def check_aw_available() -> bool:
    """Returns True if ActivityWatch is running and reachable."""
    info = _aw_get("/info")
    return info is not None


def list_buckets() -> list[dict]:
    """List all AW buckets. Returns [] on failure."""
    buckets = _aw_get("/buckets")
    if not buckets:
        return []
    # AW returns a dict of {bucket_id: bucket_info}
    if isinstance(buckets, dict):
        return [{"id": k, **v} for k, v in buckets.items()]
    return buckets


def get_events(bucket_id: str, start: datetime, end: datetime) -> list[dict]:
    """
    Fetch events from a bucket within [start, end].
    AW event format: {id, timestamp, duration, data: {app, title, ...}}
    """
    # AW timestamps are ISO 8601 with UTC timezone
    start_str = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_str = end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    path = (
        f"/buckets/{bucket_id}/events"
        f"?start={urllib.parse.quote(start_str)}"
        f"&end={urllib.parse.quote(end_str)}"
        f"&limit={MAX_EVENTS_PER_RUN}"
    )
    events = _aw_get(path)
    return events if isinstance(events, list) else []


# ── Event Parsing ────────────────────────────────────────────────────────────

def parse_event(event: dict, bucket_id: str) -> Optional[dict]:
    """
    Normalize a raw AW event into our memory schema:
    {type, app, title, duration_seconds, timestamp, bucket, source}
    """
    data = event.get("data", {})
    duration = float(event.get("duration", 0))

    if duration < MIN_DURATION_SECONDS:
        return None

    # Derive app name + title from bucket type
    app = ""
    title = ""

    if "aw-watcher-window" in bucket_id:
        app = data.get("app", data.get("program", ""))
        title = data.get("title", "")
    elif "aw-watcher-afk" in bucket_id:
        app = "afk"
        title = data.get("status", "")  # "afk" or "not-afk"
    elif "aw-watcher-web" in bucket_id:
        app = "browser"
        title = data.get("title", data.get("url", ""))
    else:
        # Generic fallback — try common keys
        app = data.get("app", data.get("program", data.get("title", "")))
        title = data.get("title", data.get("url", ""))

    if not app:
        return None

    # Normalize timestamp to ISO 8601 UTC
    raw_ts = event.get("timestamp", "")
    try:
        ts = raw_ts if raw_ts.endswith("Z") else raw_ts + "Z"
    except AttributeError:
        ts = datetime.now(timezone.utc).isoformat()

    return {
        "type": "activity",
        "app": app[:128],
        "title": title[:256],
        "duration_seconds": round(duration, 1),
        "timestamp": ts,
        "bucket": bucket_id,
        "source": "activitywatch",
    }


# ── Memory API ───────────────────────────────────────────────────────────────

def store_memory(payload: dict) -> bool:
    """
    POST structured activity memory to TIAMAT memory API.
    Returns True on success.
    """
    body = json.dumps({
        "content": (
            f"[ACTIVITY] {payload['app']} — {payload['title']} "
            f"for {payload['duration_seconds']}s at {payload['timestamp']}"
        ),
        "metadata": payload,
        "tags": ["activity", "productivity", payload.get("app", "").lower()],
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


# ── Cost Log ─────────────────────────────────────────────────────────────────

def log_to_cost_log(stats: dict) -> None:
    """
    Append a single CSV line to cost.log for time-tracking visibility.
    Format matches existing entries:
    timestamp,cycle,source,events_synced,duration_total_s,stored_ok,failed
    """
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    line = (
        f"{now},activitywatch_sync,{stats['events_found']},"
        f"{stats['events_stored']},{stats['total_duration_s']:.1f},"
        f"{stats['store_ok']},{stats['store_fail']}\n"
    )
    try:
        with open(COST_LOG, "a") as f:
            f.write(line)
    except OSError:
        pass  # never block on logging failures


def log_activity(message: str) -> None:
    """Append a human-readable line to activity.log."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        with open(ACTIVITY_LOG, "a") as f:
            f.write(f"[{now}] {message}\n")
    except OSError:
        pass


# ── Main Sync ────────────────────────────────────────────────────────────────

def sync(lookback_seconds: int = DEFAULT_LOOKBACK_SECONDS, dry_run: bool = False) -> dict:
    """
    Main sync routine. Returns stats dict.

    Steps:
    1. Check AW availability (bail early if down — no crash)
    2. List buckets, filter to relevant ones
    3. Fetch events in the lookback window
    4. Parse + deduplicate events
    5. Store to memory API
    6. Log summary to cost.log
    """
    stats = {
        "aw_available": False,
        "buckets_found": 0,
        "events_found": 0,
        "events_stored": 0,
        "total_duration_s": 0.0,
        "store_ok": 0,
        "store_fail": 0,
        "dry_run": dry_run,
    }

    # ── 1. AW availability check ─────────────────────────────────────────────
    if not check_aw_available():
        log_activity("ActivityWatch unavailable — skipping sync")
        return stats

    stats["aw_available"] = True

    # ── 2. List buckets ───────────────────────────────────────────────────────
    buckets = list_buckets()
    relevant = [
        b for b in buckets
        if any(b.get("id", "").startswith(p) for p in RELEVANT_BUCKET_PREFIXES)
    ]
    stats["buckets_found"] = len(relevant)

    if not relevant:
        log_activity("ActivityWatch running but no relevant buckets found")
        return stats

    # ── 3. Fetch events ───────────────────────────────────────────────────────
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

    # Cap total events to avoid rate limit hammering memory API
    all_events = all_events[:MAX_EVENTS_PER_RUN]
    stats["events_found"] = len(all_events)
    stats["total_duration_s"] = sum(e["duration_seconds"] for e in all_events)

    if not all_events:
        log_activity(f"No qualifying events in last {lookback_seconds}s")
        return stats

    # ── 4 + 5. Store to memory API ────────────────────────────────────────────
    for event in all_events:
        stats["events_stored"] += 1
        if dry_run:
            stats["store_ok"] += 1
            continue
        ok = store_memory(event)
        if ok:
            stats["store_ok"] += 1
        else:
            stats["store_fail"] += 1

    # ── 6. Log to cost.log ────────────────────────────────────────────────────
    if not dry_run:
        log_to_cost_log(stats)

    top_apps = {}
    for e in all_events:
        top_apps[e["app"]] = top_apps.get(e["app"], 0) + e["duration_seconds"]
    top = sorted(top_apps.items(), key=lambda x: x[1], reverse=True)[:3]
    top_str = ", ".join(f"{a}={d:.0f}s" for a, d in top)

    log_activity(
        f"Synced {stats['events_stored']} events "
        f"({stats['total_duration_s']:.0f}s total) | "
        f"top: {top_str} | "
        f"stored={stats['store_ok']} fail={stats['store_fail']}"
        + (" [DRY RUN]" if dry_run else "")
    )

    return stats


# ── CLI Entry Point ───────────────────────────────────────────────────────────

def main():
    config = {}
    if len(sys.argv) > 1:
        try:
            config = json.loads(sys.argv[1])
        except json.JSONDecodeError:
            print(json.dumps({"error": "invalid JSON argument"}))
            sys.exit(1)

    lookback = int(config.get("lookback_seconds", DEFAULT_LOOKBACK_SECONDS))
    dry_run = bool(config.get("dry_run", False))

    result = sync(lookback_seconds=lookback, dry_run=dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
