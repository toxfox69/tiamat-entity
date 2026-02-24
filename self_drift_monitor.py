#!/usr/bin/env python3
"""
TIAMAT Self-Drift Monitor (TIK-048)
Reads cost.log, detects inference/quality/cache drift, alerts via Telegram.
Run every 50 cycles via cron or loop.ts integration.
"""

import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Any

import requests

# ── Paths ─────────────────────────────────────────────────────────────────────
AUTOMATON_DIR = Path("/root/.automaton")
COST_LOG      = AUTOMATON_DIR / "cost.log"
BASELINE_FILE = AUTOMATON_DIR / "drift_baseline.json"
EVENTS_LOG    = AUTOMATON_DIR / "drift_events.log"

# ── SDK import (adjust sys.path so we don't need the package installed) ───────
SDK_PATH = AUTOMATON_DIR / "drift_sdk"
if str(SDK_PATH) not in sys.path:
    sys.path.insert(0, str(SDK_PATH))

from tiamat_drift import DriftMonitor  # noqa: E402

# ── Config ────────────────────────────────────────────────────────────────────
WINDOW_RECENT   = 10    # cycles treated as "current"
WINDOW_BASELINE = 90    # cycles treated as reference window
TOTAL_WINDOW    = WINDOW_RECENT + WINDOW_BASELINE  # 100 cycles total
DRIFT_THRESHOLD = 0.05  # percentile boundary (5th / 95th)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("drift_monitor")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def send_telegram(message: str) -> bool:
    """Fire-and-forget Telegram alert. Returns True on success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram creds missing — skipping alert")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.error("Telegram send failed: %s", exc)
        return False


def log_drift_event(event: dict[str, Any]) -> None:
    """Append a JSON line to drift_events.log."""
    EVENTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_LOG.open("a") as fh:
        fh.write(json.dumps(event) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Cost-log parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_cost_log(n: int = TOTAL_WINDOW) -> list[dict[str, Any]]:
    """
    Return the last *n* valid rows from cost.log as a list of dicts.
    Each dict contains numeric keys: cost_usd, input_tokens, output_tokens,
    cache_read, cache_write, cache_hit (0/1), cache_efficiency.
    Also retains: timestamp, cycle, model, label.
    """
    if not COST_LOG.exists():
        raise FileNotFoundError(f"cost.log not found at {COST_LOG}")

    rows: list[dict[str, Any]] = []

    with COST_LOG.open() as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            try:
                input_tok  = int(raw["input_tokens"])
                cache_read = int(raw["cache_read"])
                cache_write= int(raw.get("cache_write", 0))
                output_tok = int(raw["output_tokens"])
                cost       = float(raw["cost_usd"])
            except (KeyError, ValueError):
                continue  # skip malformed rows

            total_input = input_tok + cache_read
            cache_eff   = cache_read / total_input if total_input > 0 else 0.0

            rows.append({
                "timestamp":        raw.get("timestamp", ""),
                "cycle":            int(raw.get("cycle", 0)),
                "model":            raw.get("model", "unknown"),
                "label":            raw.get("label", "routine"),
                "input_tokens":     input_tok,
                "cache_read":       cache_read,
                "cache_write":      cache_write,
                "output_tokens":    output_tok,
                "cost_usd":         cost,
                "cache_hit":        1.0 if cache_read > 0 else 0.0,
                "cache_efficiency": round(cache_eff, 4),
            })

    return rows[-n:]  # most recent n rows


# ─────────────────────────────────────────────────────────────────────────────
# Baseline management
# ─────────────────────────────────────────────────────────────────────────────

def _compute_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise a list of cycle dicts into aggregate stats."""
    costs        = [r["cost_usd"]         for r in rows]
    input_toks   = [r["input_tokens"]     for r in rows]
    output_toks  = [r["output_tokens"]    for r in rows]
    cache_reads  = [r["cache_read"]       for r in rows]
    cache_effs   = [r["cache_efficiency"] for r in rows]
    cache_hits   = [r["cache_hit"]        for r in rows]

    model_counts: dict[str, int] = {}
    for r in rows:
        m = r["model"]
        model_counts[m] = model_counts.get(m, 0) + 1
    total = len(rows) or 1
    model_dist = {m: round(c / total, 3) for m, c in model_counts.items()}

    return {
        "cycles_sampled":       len(rows),
        "mean_cost_usd":        round(mean(costs),       6),
        "std_cost_usd":         round(stdev(costs) if len(costs) > 1 else 0, 6),
        "mean_input_tokens":    round(mean(input_toks),  2),
        "mean_output_tokens":   round(mean(output_toks), 2),
        "mean_cache_read":      round(mean(cache_reads), 2),
        "cache_hit_rate":       round(mean(cache_hits),  4),
        "mean_cache_efficiency":round(mean(cache_effs),  4),
        "model_distribution":   model_dist,
    }


def load_baseline() -> dict[str, Any]:
    if BASELINE_FILE.exists():
        with BASELINE_FILE.open() as fh:
            return json.load(fh)
    return {}


def save_baseline(stats: dict[str, Any]) -> None:
    data = {**stats, "updated_at": _now_iso()}
    if "created_at" not in data or not data.get("created_at"):
        data["created_at"] = _now_iso()
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with BASELINE_FILE.open("w") as fh:
        json.dump(data, fh, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# Drift checks
# ─────────────────────────────────────────────────────────────────────────────

def run_drift_check(
    monitor: DriftMonitor,
    recent_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Run three drift checks and merge results:
      1. inference_drift  — cost_usd, cache_efficiency (cost / cache trend)
      2. quality_drift    — output_tokens (proxy for response quality)
      3. routing_drift    — cache_hit, input_tokens (model routing behaviour)
    Uses DriftMonitor.local_drift_check (pure-local, no HTTP).
    """
    # Aggregate recent window into a single "current" measurement
    def avg(rows, key):
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return mean(vals) if vals else 0.0

    current_inference = {
        "cost_usd":         avg(recent_rows, "cost_usd"),
        "cache_efficiency": avg(recent_rows, "cache_efficiency"),
    }
    current_quality = {
        "output_tokens":    avg(recent_rows, "output_tokens"),
    }
    current_routing = {
        "cache_hit":        avg(recent_rows, "cache_hit"),
        "input_tokens":     avg(recent_rows, "input_tokens"),
    }

    inference_result = monitor.local_drift_check(current_inference, baseline_rows, DRIFT_THRESHOLD)
    quality_result   = monitor.local_drift_check(current_quality,   baseline_rows, DRIFT_THRESHOLD)
    routing_result   = monitor.local_drift_check(current_routing,   baseline_rows, DRIFT_THRESHOLD)

    any_drift = (
        inference_result["drift_detected"]
        or quality_result["drift_detected"]
        or routing_result["drift_detected"]
    )
    max_score = max(
        inference_result["drift_score"],
        quality_result["drift_score"],
        routing_result["drift_score"],
    )

    return {
        "drift_detected":  any_drift,
        "drift_score":     round(max_score, 4),
        "inference_drift": inference_result,
        "quality_drift":   quality_result,
        "routing_drift":   routing_result,
        "current_metrics": {**current_inference, **current_quality, **current_routing},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> dict[str, Any]:
    t_start = time.time()
    log.info("TIAMAT self-drift monitor starting")

    # 1. Parse cost.log --------------------------------------------------------
    try:
        all_rows = parse_cost_log(TOTAL_WINDOW)
    except FileNotFoundError as exc:
        result = {"ok": False, "error": str(exc), "timestamp": _now_iso()}
        log.error(str(exc))
        return result

    if len(all_rows) < WINDOW_RECENT + 2:
        result = {
            "ok": False,
            "error": f"Not enough data: {len(all_rows)} rows (need >{WINDOW_RECENT+2})",
            "timestamp": _now_iso(),
        }
        log.warning(result["error"])
        return result

    # Split recent vs baseline window
    recent_rows   = all_rows[-WINDOW_RECENT:]
    baseline_rows = all_rows[:-WINDOW_RECENT] if len(all_rows) > WINDOW_RECENT else all_rows

    # 2. Compute stats ---------------------------------------------------------
    recent_stats   = _compute_stats(recent_rows)
    baseline_stats = _compute_stats(baseline_rows)

    # 3. Bootstrap baseline if empty -------------------------------------------
    stored_baseline = load_baseline()
    if not stored_baseline.get("mean_cost_usd"):
        log.info("No baseline found — writing initial baseline from %d cycles", baseline_stats["cycles_sampled"])
        save_baseline({**baseline_stats, "created_at": _now_iso()})
        stored_baseline = load_baseline()

    # 4. Run drift checks ------------------------------------------------------
    # Use a lightweight model_id; no remote calls — local_drift_check only
    monitor = DriftMonitor(api_key="local", model_id="tiamat-loop")
    drift_result = run_drift_check(monitor, recent_rows, baseline_rows)

    # 5. Refresh baseline with full 100-cycle window ---------------------------
    full_stats = _compute_stats(all_rows)
    save_baseline({**full_stats, "created_at": stored_baseline.get("created_at", _now_iso())})

    # 6. Log event & alert if drift detected -----------------------------------
    flat_affected = (
        drift_result["inference_drift"]["affected_features"]
        + drift_result["quality_drift"]["affected_features"]
        + drift_result["routing_drift"]["affected_features"]
    )
    event: dict[str, Any] = {
        "timestamp":        _now_iso(),
        "cycles_checked":   len(all_rows),
        "recent_window":    len(recent_rows),
        "baseline_window":  len(baseline_rows),
        "affected_features": flat_affected,
        **drift_result,
        "baseline_summary": baseline_stats,
        "recent_summary":   recent_stats,
    }
    log_drift_event(event)

    if drift_result["drift_detected"]:
        affected = []
        for check_name, check_key in [
            ("inference", "inference_drift"),
            ("quality",   "quality_drift"),
            ("routing",   "routing_drift"),
        ]:
            feats = drift_result[check_key].get("affected_features", [])
            if feats:
                affected.append(f"*{check_name}*: {', '.join(feats)}")

        affected_lines = "\n".join(f"  - {a}" for a in affected)
        msg = (
            f"TIAMAT Drift Alert\n"
            f"Score: {drift_result['drift_score']:.3f} "
            f"(recent {WINDOW_RECENT} vs baseline {len(baseline_rows)} cycles)\n"
            f"Affected:\n{affected_lines}\n\n"
            f"Recent  -> cost ${recent_stats['mean_cost_usd']:.5f} | "
            f"cache hit {recent_stats['cache_hit_rate']:.1%} | "
            f"output tokens {recent_stats['mean_output_tokens']:.0f}\n"
            f"Baseline -> cost ${baseline_stats['mean_cost_usd']:.5f} | "
            f"cache hit {baseline_stats['cache_hit_rate']:.1%} | "
            f"output tokens {baseline_stats['mean_output_tokens']:.0f}"
        )
        log.warning("DRIFT DETECTED — score=%.3f  affected=%s", drift_result["drift_score"], affected)
        sent = send_telegram(msg)
        event["telegram_alert_sent"] = sent
    else:
        log.info(
            "No drift detected — recent: cost=$%.5f  cache_hit=%.1f%%  output_tok=%.0f",
            recent_stats["mean_cost_usd"],
            recent_stats["cache_hit_rate"] * 100,
            recent_stats["mean_output_tokens"],
        )

    # 7. Build return payload --------------------------------------------------
    elapsed = round(time.time() - t_start, 3)
    status: dict[str, Any] = {
        "ok":             True,
        "timestamp":      _now_iso(),
        "elapsed_s":      elapsed,
        "cycles_checked": len(all_rows),
        "drift_detected": drift_result["drift_detected"],
        "drift_score":    drift_result["drift_score"],
        "affected_features": (
            drift_result["inference_drift"]["affected_features"]
            + drift_result["quality_drift"]["affected_features"]
            + drift_result["routing_drift"]["affected_features"]
        ),
        "recent_summary":   recent_stats,
        "baseline_summary": baseline_stats,
    }

    log.info("Done in %.3fs — status: %s", elapsed, "DRIFT" if drift_result["drift_detected"] else "OK")
    return status


if __name__ == "__main__":
    # Load .env if running standalone (not under TIAMAT's already-loaded env)
    env_file = Path("/root/.env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    result = main()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("ok") else 1)
