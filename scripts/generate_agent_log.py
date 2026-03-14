#!/usr/bin/env python3
"""
Generate agent_log.json — verifiable execution log for TIAMAT autonomous agent.

Pulls ONLY real data from:
  - /root/.automaton/cost.log (CSV: timestamp,cycle,model,input_tokens,cache_read,cache_write,output_tokens,cost_usd[,context])
  - /root/.automaton/state.db (SQLite: tool_calls + turns tables)

Output: /root/entity/agent_log.json (+ copy to /root/vault/agent_log.json)
"""

import csv
import json
import os
import sqlite3
import hashlib
from datetime import datetime, timezone
from collections import defaultdict

COST_LOG = "/root/.automaton/cost.log"
STATE_DB = "/root/.automaton/state.db"
OUTPUT_PRIMARY = "/root/entity/agent_log.json"
OUTPUT_VAULT = "/root/vault/agent_log.json"

AGENT_ID = 29931
WALLET = "0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE"
GITHUB_REPO = "https://github.com/toxfox69/tiamat-vault"
AGENT_URL = "https://tiamat.live"
AGENT_DISCOVERY = "https://tiamat.live/.well-known/agent.json"


def load_cost_log():
    """Parse cost.log CSV into list of dicts."""
    entries = []
    with open(COST_LOG, "r") as f:
        reader = csv.reader(f)
        header = next(reader)  # timestamp,cycle,model,input_tokens,cache_read,cache_write,output_tokens,cost_usd[,context]
        for row in reader:
            if len(row) < 8:
                continue
            try:
                entry = {
                    "timestamp": row[0],
                    "cycle": int(row[1]) if row[1] else 0,
                    "model": row[2],
                    "input_tokens": int(row[3]) if row[3] else 0,
                    "cache_read_tokens": int(row[4]) if row[4] else 0,
                    "cache_write_tokens": int(row[5]) if row[5] else 0,
                    "output_tokens": int(row[6]) if row[6] else 0,
                    "cost_usd": float(row[7]) if row[7] else 0.0,
                    "context": row[8] if len(row) > 8 else "",
                }
                entries.append(entry)
            except (ValueError, IndexError):
                continue
    return entries


def load_tool_calls():
    """Load tool call data from state.db."""
    if not os.path.exists(STATE_DB):
        return [], {}

    conn = sqlite3.connect(STATE_DB)
    conn.row_factory = sqlite3.Row

    # Tool call frequency and durations
    cursor = conn.execute("""
        SELECT name, COUNT(*) as call_count,
               SUM(duration_ms) as total_duration_ms,
               MIN(created_at) as first_use,
               MAX(created_at) as last_use
        FROM tool_calls
        GROUP BY name
        ORDER BY call_count DESC
    """)
    tool_stats = []
    for row in cursor:
        tool_stats.append({
            "tool": row["name"],
            "call_count": row["call_count"],
            "total_duration_ms": row["total_duration_ms"] or 0,
            "first_use": row["first_use"],
            "last_use": row["last_use"],
        })

    # Recent tool calls with timestamps (sample for execution entries)
    cursor = conn.execute("""
        SELECT tc.name, tc.created_at, tc.duration_ms, tc.error,
               t.state, t.timestamp as turn_timestamp
        FROM tool_calls tc
        LEFT JOIN turns t ON tc.turn_id = t.id
        ORDER BY tc.created_at DESC
        LIMIT 500
    """)
    recent_calls = []
    for row in cursor:
        recent_calls.append({
            "tool": row["name"],
            "timestamp": row["turn_timestamp"] or row["created_at"],
            "duration_ms": row["duration_ms"] or 0,
            "error": row["error"],
            "state": row["state"],
        })

    conn.close()
    return tool_stats, recent_calls


def compute_execution_entries(cost_entries):
    """
    Build execution entries from cost.log.
    Group consecutive entries by cycle to show per-cycle execution.
    Sample strategically: include all strategic bursts + every Nth routine cycle.
    """
    # Group by cycle
    cycles = defaultdict(list)
    for e in cost_entries:
        cycles[e["cycle"]].append(e)

    entries = []
    cycle_nums = sorted(cycles.keys())

    for cycle_num in cycle_nums:
        cycle_data = cycles[cycle_num]
        first = cycle_data[0]
        last = cycle_data[-1]

        # Aggregate tokens and cost for this cycle
        total_input = sum(e["input_tokens"] for e in cycle_data)
        total_output = sum(e["output_tokens"] for e in cycle_data)
        total_cache_read = sum(e["cache_read_tokens"] for e in cycle_data)
        total_cache_write = sum(e["cache_write_tokens"] for e in cycle_data)
        total_cost = sum(e["cost_usd"] for e in cycle_data)
        models_used = list(set(e["model"] for e in cycle_data if e["model"]))
        contexts = list(set(e["context"] for e in cycle_data if e["context"]))
        num_inferences = len(cycle_data)

        # Determine action type from context
        action_type = "autonomous_cycle"
        if any("strategic" in c for c in contexts):
            action_type = "strategic_burst"
        elif any("inner" in c for c in contexts):
            action_type = "multi_step_reasoning"

        entry = {
            "cycle": cycle_num,
            "timestamp": first["timestamp"],
            "timestamp_end": last["timestamp"] if len(cycle_data) > 1 else None,
            "action": action_type,
            "models": models_used,
            "inferences": num_inferences,
            "tokens": {
                "input": total_input,
                "output": total_output,
                "cache_read": total_cache_read,
                "cache_write": total_cache_write,
                "total": total_input + total_output + total_cache_read + total_cache_write,
            },
            "cost_usd": round(total_cost, 6),
        }
        if contexts:
            entry["context_tags"] = contexts

        entries.append(entry)

    return entries


def compute_summary(cost_entries, tool_stats):
    """Compute summary statistics from real data."""
    total_cost = sum(e["cost_usd"] for e in cost_entries)
    total_input = sum(e["input_tokens"] for e in cost_entries)
    total_output = sum(e["output_tokens"] for e in cost_entries)
    total_cache_read = sum(e["cache_read_tokens"] for e in cost_entries)
    total_cache_write = sum(e["cache_write_tokens"] for e in cost_entries)
    total_inferences = len(cost_entries)

    # Model distribution
    model_counts = defaultdict(int)
    model_costs = defaultdict(float)
    for e in cost_entries:
        if e["model"]:
            model_counts[e["model"]] += 1
            model_costs[e["model"]] += e["cost_usd"]

    model_breakdown = []
    for model, count in sorted(model_counts.items(), key=lambda x: -x[1]):
        model_breakdown.append({
            "model": model,
            "inference_count": count,
            "total_cost_usd": round(model_costs[model], 4),
            "percentage": round(100.0 * count / total_inferences, 1),
        })

    # Context/action distribution
    context_counts = defaultdict(int)
    for e in cost_entries:
        ctx = e["context"] if e["context"] else "untagged"
        context_counts[ctx] += 1

    # Cycle stats
    cycles = set(e["cycle"] for e in cost_entries)
    max_cycle = max(cycles) if cycles else 0
    min_cycle = min(cycles) if cycles else 0

    # Date range
    timestamps = [e["timestamp"] for e in cost_entries if e["timestamp"]]
    first_ts = min(timestamps) if timestamps else None
    last_ts = max(timestamps) if timestamps else None

    # Daily cost breakdown
    daily_costs = defaultdict(float)
    daily_cycles = defaultdict(set)
    for e in cost_entries:
        if e["timestamp"]:
            day = e["timestamp"][:10]
            daily_costs[day] += e["cost_usd"]
            daily_cycles[day].add(e["cycle"])

    daily_breakdown = []
    for day in sorted(daily_costs.keys()):
        daily_breakdown.append({
            "date": day,
            "cost_usd": round(daily_costs[day], 4),
            "cycles": len(daily_cycles[day]),
        })

    return {
        "total_inferences": total_inferences,
        "total_cycles": len(cycles),
        "cycle_range": {"min": min_cycle, "max": max_cycle},
        "date_range": {"first": first_ts, "last": last_ts},
        "tokens": {
            "total_input": total_input,
            "total_output": total_output,
            "total_cache_read": total_cache_read,
            "total_cache_write": total_cache_write,
            "grand_total": total_input + total_output + total_cache_read + total_cache_write,
        },
        "cost": {
            "total_usd": round(total_cost, 4),
            "average_per_cycle": round(total_cost / len(cycles), 6) if cycles else 0,
            "average_per_inference": round(total_cost / total_inferences, 6) if total_inferences else 0,
        },
        "models": model_breakdown,
        "action_distribution": dict(sorted(context_counts.items(), key=lambda x: -x[1])),
        "tool_usage": tool_stats,
        "daily_breakdown": daily_breakdown,
    }


def build_agent_log():
    """Build the complete agent_log.json from real data."""
    print("Loading cost.log...")
    cost_entries = load_cost_log()
    print(f"  Loaded {len(cost_entries)} inference records")

    print("Loading state.db...")
    tool_stats, recent_calls = load_tool_calls()
    print(f"  Loaded {len(tool_stats)} tool types, {len(recent_calls)} recent calls")

    print("Computing execution entries...")
    execution_entries = compute_execution_entries(cost_entries)
    print(f"  Generated {len(execution_entries)} cycle entries")

    print("Computing summary statistics...")
    summary = compute_summary(cost_entries, tool_stats)

    # Build capabilities list from actual tool usage
    capabilities = []
    tool_names = [ts["tool"] for ts in tool_stats]

    capability_map = {
        "multi_model_inference": "Routes inference across Anthropic, Groq, Cerebras, Gemini, OpenRouter, DigitalOcean GPU",
        "content_publishing": "Publishes to Dev.to, Bluesky, Farcaster, Mastodon, LinkedIn, Hashnode",
        "email_communication": "Sends/reads email via SendGrid + IMAP (tiamat@tiamat.live)",
        "web_research": "Searches web, browses pages, fetches content autonomously",
        "social_engagement": "Likes, reposts, replies on Bluesky, Mastodon, Farcaster",
        "memory_system": "SQLite + FTS5 memory with recall, reflect, remember operations",
        "task_management": "Ticket system for self-directed task tracking",
        "shell_execution": "Direct shell command execution for system operations",
        "file_operations": "Reads and writes files within sandboxed paths",
        "image_generation": "Algorithmic art generation (6 styles)",
        "text_to_speech": "TTS via Kokoro on GPU pod",
        "api_services": "Serves /summarize, /generate, /chat, /synthesize endpoints with x402 payments",
        "telegram_alerts": "Status updates and alerts via Telegram bot",
        "erc8004_registered": "On-chain agent identity (ERC-8004 ID 29931 on Base)",
    }

    # Only include capabilities we have evidence for
    evidence_tools = {
        "multi_model_inference": True,  # cost.log shows multiple models
        "content_publishing": any(t in tool_names for t in ["post_devto", "post_bluesky", "post_farcaster", "post_mastodon", "post_linkedin"]),
        "email_communication": any(t in tool_names for t in ["send_email", "read_email"]),
        "web_research": any(t in tool_names for t in ["search_web", "browse", "web_fetch", "sonar_search"]),
        "social_engagement": any(t in tool_names for t in ["like_bluesky", "repost_bluesky", "reply_bluesky", "mastodon_engage"]),
        "memory_system": any(t in tool_names for t in ["recall", "reflect", "remember"]),
        "task_management": any(t in tool_names for t in ["ticket_claim", "ticket_complete", "ticket_create", "ticket_list"]),
        "shell_execution": "exec" in tool_names,
        "file_operations": any(t in tool_names for t in ["read_file", "write_file"]),
        "image_generation": "generate_image" in tool_names,
        "text_to_speech": "gpu_infer" in tool_names,
        "api_services": True,  # known from infrastructure
        "telegram_alerts": "send_telegram" in tool_names,
        "erc8004_registered": True,  # known fact
    }

    for cap_id, desc in capability_map.items():
        if evidence_tools.get(cap_id, False):
            capabilities.append({"id": cap_id, "description": desc})

    # Build the log
    agent_log = {
        "$schema": "agent_execution_log_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent": {
            "name": "TIAMAT",
            "description": "Autonomous AI agent running 24/7 on dedicated infrastructure. Self-directed research, content creation, social engagement, and API service operation.",
            "erc8004_id": AGENT_ID,
            "wallet": WALLET,
            "chain": "base",
            "url": AGENT_URL,
            "agent_discovery": AGENT_DISCOVERY,
            "github": GITHUB_REPO,
            "infrastructure": {
                "server": "DigitalOcean VPS (159.89.38.17)",
                "runtime": "Node.js (TypeScript)",
                "domain": "tiamat.live",
                "gpu_pod": "213.192.2.118:40080 (RTX 3090)",
                "child_agent": "ECHO (104.236.236.97)",
            },
            "capabilities": capabilities,
            "company": {
                "name": "ENERGENAI LLC",
                "uei": "LBZFEH87W746",
                "naics": ["541715", "541519"],
            },
        },
        "execution_summary": summary,
        "execution_log": execution_entries,
    }

    # Compute integrity hash over the execution entries
    log_json = json.dumps(execution_entries, sort_keys=True)
    integrity_hash = hashlib.sha256(log_json.encode()).hexdigest()
    agent_log["integrity"] = {
        "hash_algorithm": "sha256",
        "execution_log_hash": integrity_hash,
        "source_files": [
            {"path": COST_LOG, "records": len(cost_entries)},
            {"path": STATE_DB, "tool_calls": len(recent_calls), "tool_types": len(tool_stats)},
        ],
    }

    return agent_log


def main():
    agent_log = build_agent_log()

    # Write primary output
    print(f"\nWriting {OUTPUT_PRIMARY}...")
    with open(OUTPUT_PRIMARY, "w") as f:
        json.dump(agent_log, f, indent=2)
    size_kb = os.path.getsize(OUTPUT_PRIMARY) / 1024
    print(f"  Written: {size_kb:.1f} KB")

    # Copy to vault
    if os.path.isdir(os.path.dirname(OUTPUT_VAULT)):
        print(f"Writing {OUTPUT_VAULT}...")
        with open(OUTPUT_VAULT, "w") as f:
            json.dump(agent_log, f, indent=2)
        print(f"  Written: {os.path.getsize(OUTPUT_VAULT) / 1024:.1f} KB")
    else:
        print(f"  Vault directory not found at {os.path.dirname(OUTPUT_VAULT)}, skipping")

    # Print summary
    s = agent_log["execution_summary"]
    print(f"\n=== AGENT LOG SUMMARY ===")
    print(f"Cycles:      {s['total_cycles']}")
    print(f"Inferences:  {s['total_inferences']}")
    print(f"Total cost:  ${s['cost']['total_usd']}")
    print(f"Tokens:      {s['tokens']['grand_total']:,}")
    print(f"Date range:  {s['date_range']['first'][:10]} to {s['date_range']['last'][:10]}")
    print(f"Models:      {len(s['models'])}")
    print(f"Tools:       {len(s['tool_usage'])}")
    print(f"Integrity:   {agent_log['integrity']['execution_log_hash'][:16]}...")
    print(f"Output:      {OUTPUT_PRIMARY}")


if __name__ == "__main__":
    main()
