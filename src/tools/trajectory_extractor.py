#!/usr/bin/env python3
"""
TIAMAT Training Data Extractor
Converts operational logs into labeled training trajectories.
JSONL format compatible with Together.ai fine-tuning and Atropos RL.

Usage: python3 trajectory_extractor.py [--cycles N] [--output PATH]
"""

import sqlite3
import json
import os
import sys
import re
from datetime import datetime
from collections import Counter
from difflib import SequenceMatcher

STATE_DB = "/root/.automaton/state.db"
COST_LOG = "/root/.automaton/cost.log"
OUTPUT_DIR = "/root/.automaton/training_data"
DEFAULT_CYCLES = 1000

# Reward signals
REWARDS = {
    "success": 1.0,
    "partial": 0.3,
    "loop": -0.5,
    "hallucination": -1.0,
    "failure": -0.3,
}

# Revenue hallucination patterns
REVENUE_HALLUCINATION = re.compile(
    r"(revenue|payment|paid|customer|earned|income|sale)\s*(of|:)?\s*\$?\d+",
    re.IGNORECASE,
)

# Known productive tool calls
PRODUCTIVE_TOOLS = {
    "post_bluesky", "post_mastodon", "post_farcaster", "post_devto",
    "like_bluesky", "repost_bluesky", "mastodon_engage",
    "write_file", "git_commit", "send_email", "deploy_app",
    "remember", "learn_fact", "storeOpportunity", "trackContact",
    "generate_image",
}

RESEARCH_TOOLS = {
    "read_file", "read_bluesky", "read_mastodon", "read_farcaster",
    "search_web", "browse", "recall", "sonar_search",
    "ticket_list", "ticket_claim",
}


def load_cost_data():
    """Load cost.log into a dict keyed by approximate timestamp."""
    costs = {}
    if not os.path.exists(COST_LOG):
        return costs
    with open(COST_LOG) as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) >= 9:
                ts = parts[0]
                cycle = parts[1]
                model = parts[2]
                cost = float(parts[7]) if parts[7] else 0
                ctx = parts[8] if len(parts) > 8 else "routine"
                costs[ts] = {
                    "cycle": int(cycle),
                    "model": model,
                    "cost": cost,
                    "context": ctx,
                }
    return costs


def extract_tier(model, context):
    """Map model + context to tier 0/1/2."""
    if "claude" in model.lower() or "anthropic" in model.lower():
        return 2  # expensive
    if "strategic" in context or "burst" in context:
        return 1
    return 0  # free/cheap


def tool_call_signature(tool_calls):
    """Create a comparable signature from tool call sequence."""
    return tuple(tc.get("name", "") for tc in tool_calls)


def jaccard_similarity(a, b):
    """Jaccard similarity between two sequences."""
    set_a = set(a)
    set_b = set(b)
    if not set_a and not set_b:
        return 1.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0


def label_trajectory(turn, tool_calls, prev_signatures, cost_info):
    """Label a trajectory with outcome and reward signal."""
    thinking = turn.get("thinking", "") or ""
    tc_names = [tc.get("name", "") for tc in tool_calls]
    tc_results = [tc.get("result", "") for tc in tool_calls]
    all_results = " ".join(tc_results)

    # Check for revenue hallucination
    if REVENUE_HALLUCINATION.search(thinking) or REVENUE_HALLUCINATION.search(all_results):
        # Verify no actual x402 transaction
        has_real_tx = any("0x" in r and len(r) > 50 for r in tc_results)
        if not has_real_tx:
            return {
                "label": "hallucination",
                "signal": REWARDS["hallucination"],
                "evidence": "Mentions revenue/payment but no verified transaction",
            }

    # Check for loop (>80% similar to recent cycles)
    current_sig = tool_call_signature(tool_calls)
    if len(prev_signatures) >= 3:
        similarities = [jaccard_similarity(current_sig, prev) for prev in prev_signatures[-3:]]
        if all(s > 0.8 for s in similarities):
            return {
                "label": "loop",
                "signal": REWARDS["loop"],
                "evidence": f"Tool sequence {list(current_sig)} repeated in last 3 cycles (similarity: {[f'{s:.2f}' for s in similarities]})",
            }

    # Check for failure
    errors = [tc for tc in tool_calls if tc.get("error") or "ERROR" in tc.get("result", "").upper()[:100]]
    cooldowns = [tc for tc in tool_calls if "COOLDOWN" in tc.get("result", "").upper()]

    if len(tool_calls) == 0:
        return {
            "label": "failure",
            "signal": REWARDS["failure"],
            "evidence": "No tool calls in cycle",
        }

    if len(errors) == len(tool_calls):
        return {
            "label": "failure",
            "signal": REWARDS["failure"],
            "evidence": f"All {len(errors)} tool calls errored",
        }

    # Check for success
    productive = [tc for tc in tool_calls if tc.get("name") in PRODUCTIVE_TOOLS]
    successful_productive = [
        tc for tc in productive
        if not tc.get("error") and "COOLDOWN" not in tc.get("result", "").upper()
    ]

    if successful_productive:
        return {
            "label": "success",
            "signal": REWARDS["success"],
            "evidence": f"Productive actions: {[tc['name'] for tc in successful_productive]}",
        }

    # Partial: some research but no productive output
    research = [tc for tc in tool_calls if tc.get("name") in RESEARCH_TOOLS]
    if research and not errors:
        return {
            "label": "partial",
            "signal": REWARDS["partial"],
            "evidence": f"Research only: {[tc['name'] for tc in research]}",
        }

    if cooldowns and len(cooldowns) == len(tool_calls):
        return {
            "label": "failure",
            "signal": REWARDS["failure"],
            "evidence": "All tool calls hit cooldowns",
        }

    return {
        "label": "partial",
        "signal": REWARDS["partial"],
        "evidence": f"Mixed results: {len(tool_calls)} calls, {len(errors)} errors",
    }


def extract_trajectories(num_cycles=DEFAULT_CYCLES, output_path=None):
    """Extract and label training trajectories from state.db."""
    if output_path is None:
        output_path = os.path.join(OUTPUT_DIR, "trajectories_batch001.jsonl")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    db = sqlite3.connect(STATE_DB)
    db.row_factory = sqlite3.Row

    # Load cost data for tier mapping
    cost_data = load_cost_data()

    # Get recent turns
    turns = db.execute(
        "SELECT * FROM turns ORDER BY timestamp DESC LIMIT ?", (num_cycles,)
    ).fetchall()
    turns.reverse()  # chronological order

    trajectories = []
    prev_signatures = []
    label_counts = Counter()
    tier_rewards = {0: [], 1: [], 2: []}
    total_tokens = 0

    for turn in turns:
        turn_dict = dict(turn)
        turn_id = turn_dict["id"]

        # Get tool calls for this turn
        tcs = db.execute(
            "SELECT * FROM tool_calls WHERE turn_id = ? ORDER BY created_at",
            (turn_id,),
        ).fetchall()
        tool_calls = []
        for tc in tcs:
            tc_dict = dict(tc)
            try:
                args = json.loads(tc_dict.get("arguments", "{}"))
            except:
                args = {}
            tool_calls.append({
                "tool": tc_dict.get("name") or tc_dict.get("tool", "unknown"),
                "args": args,
                "result": (tc_dict.get("result", "") or "")[:500],  # truncate large results
                "error": tc_dict.get("error"),
                "duration_ms": tc_dict.get("duration_ms", 0),
            })

        # Parse token usage
        try:
            usage = json.loads(turn_dict.get("token_usage", "{}"))
        except:
            usage = {}
        tokens = usage.get("total_tokens", 0) or usage.get("input", 0) + usage.get("output", 0)
        total_tokens += tokens

        # Find cost info by closest timestamp
        ts = turn_dict["timestamp"]
        cost_info = cost_data.get(ts, {})
        model = cost_info.get("model", "unknown")
        context = cost_info.get("context", "routine")
        tier = extract_tier(model, context)

        # Parse tool_calls from turn record as well (some are stored inline)
        try:
            inline_tcs = json.loads(turn_dict.get("tool_calls", "[]"))
        except:
            inline_tcs = []

        # Label the trajectory
        outcome = label_trajectory(turn_dict, tool_calls or inline_tcs, prev_signatures, cost_info)

        trajectory = {
            "cycle_id": cost_info.get("cycle", 0),
            "timestamp": ts,
            "tier": tier,
            "model": model,
            "system_context": (turn_dict.get("input", "") or "")[:1000],
            "reasoning": (turn_dict.get("thinking", "") or "")[:2000],
            "tool_calls": tool_calls[:10],  # cap at 10 per trajectory
            "outcome": outcome,
            "tokens": tokens,
            "cost": cost_info.get("cost", 0),
        }

        trajectories.append(trajectory)
        prev_signatures.append(tool_call_signature(tool_calls or inline_tcs))
        label_counts[outcome["label"]] += 1
        tier_rewards[tier].append(outcome["signal"])

    db.close()

    # Write JSONL
    with open(output_path, "w") as f:
        for t in trajectories:
            f.write(json.dumps(t) + "\n")

    # Print summary
    total = len(trajectories)
    print(f"\nTIAMAT TRAINING DATA EXTRACTION")
    print(f"{'=' * 50}")
    print(f"Trajectories extracted: {total}")
    print(f"Output: {output_path}")
    print(f"Total tokens: {total_tokens:,}")
    print()
    print("Label Distribution:")
    for label in ["success", "partial", "loop", "hallucination", "failure"]:
        count = label_counts.get(label, 0)
        pct = (count / total * 100) if total > 0 else 0
        bar = "#" * int(pct / 2)
        print(f"  {label:15s}: {count:4d} ({pct:5.1f}%) {bar}")
    print()
    print("Average Reward by Tier:")
    for tier in [0, 1, 2]:
        rewards = tier_rewards[tier]
        if rewards:
            avg = sum(rewards) / len(rewards)
            print(f"  Tier {tier}: {avg:+.3f} ({len(rewards)} cycles)")
        else:
            print(f"  Tier {tier}: no data")
    print()

    usable = label_counts.get("success", 0) + label_counts.get("partial", 0)
    usable_pct = (usable / total * 100) if total > 0 else 0
    print(f"Usable examples: {usable}/{total} ({usable_pct:.1f}%)")
    print(f"Ready for training: {'YES' if usable >= 5000 else f'NO (need {5000 - usable} more)'}")

    return trajectories, label_counts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract TIAMAT training trajectories")
    parser.add_argument("--cycles", type=int, default=DEFAULT_CYCLES, help="Number of cycles to extract")
    parser.add_argument("--output", type=str, default=None, help="Output JSONL path")
    args = parser.parse_args()

    extract_trajectories(args.cycles, args.output)
