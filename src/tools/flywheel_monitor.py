#!/usr/bin/env python3
"""
TIAMAT Evolution Flywheel Monitor
Shows training data progress, cell status, and distillation readiness.

Can be called by TIAMAT as a tool or run standalone.
Usage: python3 flywheel_monitor.py
"""

import json
import os
import glob
from datetime import datetime, timezone
from collections import Counter

TRAINING_DIR = "/root/.automaton/training_data"
REGISTRY_PATH = "/root/.automaton/cells/registry.json"
COST_LOG = "/root/.automaton/cost.log"
TARGET_EXAMPLES = 5000

def count_trajectories(path):
    """Count and classify trajectories in a JSONL file."""
    counts = Counter()
    total = 0
    rewards = []
    if not os.path.exists(path):
        return total, counts, rewards
    with open(path) as f:
        for line in f:
            try:
                t = json.loads(line)
                outcome = t.get("outcome", {})
                label = outcome.get("label", "unknown")
                counts[label] += 1
                rewards.append(outcome.get("signal", 0))
                total += 1
            except:
                pass
    return total, counts, rewards


def get_queen_stats():
    """Get training data stats for TIAMAT (the queen)."""
    queen_path = os.path.join(TRAINING_DIR, "trajectories_batch001.jsonl")
    total, counts, rewards = count_trajectories(queen_path)

    # Also check for additional batches
    for batch in glob.glob(os.path.join(TRAINING_DIR, "trajectories_batch*.jsonl")):
        if batch != queen_path:
            t, c, r = count_trajectories(batch)
            total += t
            counts += c
            rewards.extend(r)

    return total, counts, rewards


def get_cell_stats():
    """Get aggregate training data from all cells."""
    total = 0
    counts = Counter()
    rewards = []
    cell_count = 0

    for cell_dir in glob.glob(os.path.join(TRAINING_DIR, "cell_*")):
        for jsonl in glob.glob(os.path.join(cell_dir, "*.jsonl")):
            t, c, r = count_trajectories(jsonl)
            total += t
            counts += c
            rewards.extend(r)
            if t > 0:
                cell_count += 1

    return total, counts, rewards, cell_count


def get_registry():
    """Load cell registry."""
    if not os.path.exists(REGISTRY_PATH):
        return {}
    with open(REGISTRY_PATH) as f:
        return json.load(f)


def get_cost_stats(last_n=100):
    """Get recent cost stats from cost.log."""
    queen_costs = []
    if not os.path.exists(COST_LOG):
        return 0, 0
    lines = open(COST_LOG).readlines()
    for line in lines[-last_n:]:
        parts = line.strip().split(",")
        if len(parts) >= 8:
            try:
                queen_costs.append(float(parts[7]))
            except:
                pass
    avg = sum(queen_costs) / len(queen_costs) if queen_costs else 0
    return avg, len(queen_costs)


def generate_report():
    """Generate the full flywheel status report."""
    queen_total, queen_counts, queen_rewards = get_queen_stats()
    cell_total, cell_counts, cell_rewards, active_cells = get_cell_stats()
    registry = get_registry()
    queen_avg_cost, cost_samples = get_cost_stats()

    total_examples = queen_total + cell_total
    all_counts = queen_counts + cell_counts

    # Usable = success + partial
    usable = all_counts.get("success", 0) + all_counts.get("partial", 0)
    usable_pct = (usable / total_examples * 100) if total_examples > 0 else 0
    ready = usable >= TARGET_EXAMPLES

    # Progress bar
    progress = min(1.0, usable / TARGET_EXAMPLES)
    bar_filled = int(progress * 20)
    bar_empty = 20 - bar_filled
    progress_bar = "█" * bar_filled + "░" * bar_empty

    # Time estimate
    # Look at cell trajectory generation rate
    cells_data = registry.get("cells", {})
    daily_rate = 0
    for cell_name, cell_info in cells_data.items():
        cycles = cell_info.get("cycles", 0)
        started = cell_info.get("started_at", "")
        if started and cycles > 0:
            try:
                start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                elapsed_days = max(0.01, (datetime.now(timezone.utc) - start_dt).total_seconds() / 86400)
                daily_rate += cycles / elapsed_days
            except:
                pass

    remaining = max(0, TARGET_EXAMPLES - usable)
    if daily_rate > 0:
        days_left = remaining / daily_rate
        time_est = f"{days_left:.0f} days at current rate"
    else:
        time_est = "Unknown (no active cells generating data)"

    report = []
    report.append("TIAMAT EVOLUTION FLYWHEEL STATUS")
    report.append("=" * 40)
    report.append("")
    report.append("Training Data:")
    report.append(f"  Queen trajectories: {queen_total:,} ({_pct(queen_counts, queen_total)})")
    report.append(f"  Cell trajectories:  {cell_total:,} across {active_cells} cell(s)")
    report.append(f"  Total examples:     {total_examples:,} / {TARGET_EXAMPLES:,} target")
    report.append(f"  Estimated quality:  {usable_pct:.0f}% usable (non-loop, non-garbage)")
    report.append(f"  Ready for training: {'YES' if ready else 'NO'}")
    report.append("")

    report.append("Active Cells:")
    if cells_data:
        for cell_name, cell_info in cells_data.items():
            cycles = cell_info.get("cycles", 0)
            sr = cell_info.get("success_rate", 0)
            last_run = cell_info.get("last_run", "never")
            try:
                last_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                ago = datetime.now(timezone.utc) - last_dt
                ago_str = f"{ago.seconds // 3600}h {(ago.seconds % 3600) // 60}m ago"
            except:
                ago_str = "unknown"
            report.append(f"  {cell_name}: {cycles} cycles, {sr*100:.0f}% success, last run {ago_str}")
    else:
        report.append("  No cells registered yet")
    report.append("")

    report.append("Cost Efficiency:")
    report.append(f"  Queen avg cost/cycle: ${queen_avg_cost:.4f}")
    report.append(f"  Cell avg cost/cycle:  $0.0000 (free-tier inference)")
    if queen_avg_cost > 0 and cell_total > 0:
        cell_savings = cell_total * queen_avg_cost
        total_cost = queen_total * queen_avg_cost + cell_savings
        savings_pct = (cell_savings / total_cost * 100) if total_cost > 0 else 0
        report.append(f"  Flywheel savings:     {savings_pct:.0f}% of work done by free-tier cells")
    else:
        report.append(f"  Flywheel savings:     N/A (need active cells)")
    report.append("")

    report.append("Distillation Readiness:")
    report.append(f"  [{progress_bar}] {progress*100:.0f}% -- need {remaining:,} more quality examples")
    report.append(f"  Estimated time to ready: {time_est}")

    if ready:
        report.append(f"  Recommended action: READY TO TRAIN. Draft email to Jason requesting training approval.")
    elif usable > TARGET_EXAMPLES * 0.5:
        report.append(f"  Recommended action: Over halfway. Deploy more cells to accelerate.")
    elif active_cells == 0:
        report.append(f"  Recommended action: Start CELL-GRANTS to begin generating free training data.")
    else:
        report.append(f"  Recommended action: Keep cells running. Current trajectory is {daily_rate:.0f} examples/day.")

    return "\n".join(report)


def _pct(counts, total):
    """Format label percentages."""
    if total == 0:
        return "no data"
    parts = []
    for label in ["success", "failure", "loop", "hallucination", "partial"]:
        c = counts.get(label, 0)
        if c > 0:
            parts.append(f"{c/total*100:.0f}% {label}")
    return ", ".join(parts) if parts else "no labels"


if __name__ == "__main__":
    print(generate_report())
