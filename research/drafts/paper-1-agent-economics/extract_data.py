#!/usr/bin/env python3
"""Extract TIAMAT operational data for Paper 1: The Cost of Autonomy."""

import csv
import json
import sqlite3
import os
import re
from datetime import datetime, timezone
from collections import Counter, defaultdict

DATA_DIR = "/root/.automaton/research/drafts/paper-1-agent-economics/data"
os.makedirs(DATA_DIR, exist_ok=True)

# ============================================================
# 1. COST DATA — from cost.log
# ============================================================
def extract_cost_data():
    cost_log = "/root/.automaton/cost.log"
    if not os.path.exists(cost_log):
        print(f"WARNING: {cost_log} not found")
        return

    costs = []
    total_cost = 0.0
    model_costs = defaultdict(float)
    model_counts = defaultdict(int)
    hourly_costs = defaultdict(float)
    daily_costs = defaultdict(float)
    label_costs = defaultdict(lambda: {"cost": 0.0, "count": 0})

    with open(cost_log, 'r') as f:
        reader = csv.reader(f)
        header = next(reader)  # skip header
        for row in reader:
            if len(row) < 8:
                continue
            entry = {
                "timestamp": row[0],
                "cycle": int(row[1]),
                "model": row[2],
                "input_tokens": int(row[3]),
                "cache_read": int(row[4]),
                "cache_write": int(row[5]),
                "output_tokens": int(row[6]),
                "cost_usd": float(row[7]),
                "label": row[8] if len(row) > 8 else "unlabeled"
            }
            costs.append(entry)

            total_cost += entry["cost_usd"]
            model_costs[entry["model"]] += entry["cost_usd"]
            model_counts[entry["model"]] += 1

            # Parse timestamp for hourly/daily aggregation
            try:
                ts = entry["timestamp"][:19]
                dt = datetime.fromisoformat(ts)
                hourly_costs[dt.strftime("%Y-%m-%d %H:00")] += entry["cost_usd"]
                daily_costs[dt.strftime("%Y-%m-%d")] += entry["cost_usd"]
            except (ValueError, IndexError):
                pass

            label_costs[entry["label"]]["cost"] += entry["cost_usd"]
            label_costs[entry["label"]]["count"] += 1

    # Save raw cost entries
    with open(f"{DATA_DIR}/cost_entries.json", 'w') as f:
        json.dump(costs, f, indent=2)

    # Save daily cost timeseries
    daily_series = [{"date": k, "cost_usd": round(v, 6)} for k, v in sorted(daily_costs.items())]
    with open(f"{DATA_DIR}/daily_costs.json", 'w') as f:
        json.dump(daily_series, f, indent=2)

    # Save model cost breakdown
    model_breakdown = {}
    for model in model_costs:
        model_breakdown[model] = {
            "total_cost": round(model_costs[model], 6),
            "cycle_count": model_counts[model],
            "avg_cost_per_cycle": round(model_costs[model] / model_counts[model], 6) if model_counts[model] > 0 else 0
        }
    with open(f"{DATA_DIR}/model_costs.json", 'w') as f:
        json.dump(model_breakdown, f, indent=2)

    # Save label breakdown (routine vs strategic)
    label_breakdown = {k: {"cost": round(v["cost"], 6), "count": v["count"]} for k, v in label_costs.items()}
    with open(f"{DATA_DIR}/label_costs.json", 'w') as f:
        json.dump(label_breakdown, f, indent=2)

    # Cache analysis
    total_cache_read = sum(c["cache_read"] for c in costs)
    total_cache_write = sum(c["cache_write"] for c in costs)
    total_input = sum(c["input_tokens"] for c in costs)
    cache_hit_rate = total_cache_read / (total_input + total_cache_read) * 100 if (total_input + total_cache_read) > 0 else 0

    cost_summary = {
        "total_cycles": len(costs),
        "total_cost_usd": round(total_cost, 4),
        "avg_cost_per_cycle": round(total_cost / len(costs), 6) if costs else 0,
        "min_cycle_cost": round(min(c["cost_usd"] for c in costs), 6) if costs else 0,
        "max_cycle_cost": round(max(c["cost_usd"] for c in costs), 6) if costs else 0,
        "first_cycle": costs[0]["cycle"] if costs else None,
        "last_cycle": costs[-1]["cycle"] if costs else None,
        "first_timestamp": costs[0]["timestamp"] if costs else None,
        "last_timestamp": costs[-1]["timestamp"] if costs else None,
        "days_of_operation": len(daily_costs),
        "avg_daily_cost": round(total_cost / len(daily_costs), 4) if daily_costs else 0,
        "model_breakdown": model_breakdown,
        "label_breakdown": label_breakdown,
        "total_input_tokens": total_input,
        "total_cache_read_tokens": total_cache_read,
        "total_cache_write_tokens": total_cache_write,
        "total_output_tokens": sum(c["output_tokens"] for c in costs),
        "cache_hit_rate_pct": round(cache_hit_rate, 2),
    }

    with open(f"{DATA_DIR}/cost_summary.json", 'w') as f:
        json.dump(cost_summary, f, indent=2)

    print(f"Extracted {len(costs)} cost entries")
    print(f"Total cost: ${total_cost:.4f}")
    print(f"Avg cost/cycle: ${total_cost/len(costs):.6f}" if costs else "")
    print(f"Cache hit rate: {cache_hit_rate:.1f}%")
    print(f"Days of operation: {len(daily_costs)}")
    print(f"Models: {dict(model_counts)}")
    return cost_summary


# ============================================================
# 2. TOOL USAGE — from tiamat.log
# ============================================================
def extract_tool_data():
    log_file = "/root/.automaton/tiamat.log"
    if not os.path.exists(log_file):
        print(f"WARNING: {log_file} not found")
        return

    tool_usage = Counter()
    tool_timeline = defaultdict(lambda: Counter())
    turn_count = 0
    turn_tools = []  # tools per turn

    with open(log_file, 'r') as f:
        current_turn_tools = 0
        for line in f:
            # Parse [TOOL] entries
            tool_match = re.search(r'\[TOOL\] (\w+)\(', line)
            if tool_match:
                tool_name = tool_match.group(1)
                tool_usage[tool_name] += 1

                # Extract date for timeline
                ts_match = re.search(r'\[(\d{4}-\d{2}-\d{2})', line)
                if ts_match:
                    tool_timeline[ts_match.group(1)][tool_name] += 1

            # Parse Turn entries
            turn_match = re.search(r'Turn \w+: (\d+) tools, (\d+) tokens', line)
            if turn_match:
                turn_count += 1
                n_tools = int(turn_match.group(1))
                n_tokens = int(turn_match.group(2))
                turn_tools.append({"tools": n_tools, "tokens": n_tokens})

    # Save tool distribution
    with open(f"{DATA_DIR}/tool_distribution.json", 'w') as f:
        json.dump(dict(tool_usage.most_common()), f, indent=2)

    # Save daily tool usage
    daily_tool_data = {date: dict(counts) for date, counts in sorted(tool_timeline.items())}
    with open(f"{DATA_DIR}/daily_tool_usage.json", 'w') as f:
        json.dump(daily_tool_data, f, indent=2)

    # Turn statistics
    if turn_tools:
        avg_tools = sum(t["tools"] for t in turn_tools) / len(turn_tools)
        avg_tokens = sum(t["tokens"] for t in turn_tools) / len(turn_tools)
    else:
        avg_tools = avg_tokens = 0

    tool_summary = {
        "total_turns": turn_count,
        "unique_tools": len(tool_usage),
        "total_tool_calls": sum(tool_usage.values()),
        "avg_tools_per_turn": round(avg_tools, 2),
        "avg_tokens_per_turn": round(avg_tokens, 1),
        "top_20_tools": dict(tool_usage.most_common(20)),
    }

    with open(f"{DATA_DIR}/tool_summary.json", 'w') as f:
        json.dump(tool_summary, f, indent=2)

    print(f"Extracted {turn_count} turns, {sum(tool_usage.values())} tool calls")
    print(f"Unique tools: {len(tool_usage)}")
    print(f"Top 10: {dict(tool_usage.most_common(10))}")
    return tool_summary


# ============================================================
# 3. MEMORY DATA — from memory.db
# ============================================================
def extract_memory_data():
    db_path = "/root/.automaton/memory.db"
    if not os.path.exists(db_path):
        print("WARNING: memory.db not found")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get table info
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cursor.fetchall()]
    print(f"Memory DB tables: {tables}")

    memory_stats = {}
    for table_name in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
            count = cursor.fetchone()[0]
            memory_stats[table_name] = count
        except Exception as e:
            memory_stats[table_name] = f"error: {e}"

    # Try to get memory growth over time if timestamps exist
    growth_data = []
    for table_name in ['tiamat_memories', 'tiamat_knowledge', 'core_knowledge']:
        if table_name not in tables:
            continue
        try:
            # Get column names
            cursor.execute(f"PRAGMA table_info([{table_name}])")
            columns = [col[1] for col in cursor.fetchall()]

            # Look for timestamp-like columns
            ts_col = None
            for col in columns:
                if 'time' in col.lower() or 'date' in col.lower() or 'created' in col.lower():
                    ts_col = col
                    break

            if ts_col:
                cursor.execute(f"SELECT [{ts_col}], COUNT(*) FROM [{table_name}] GROUP BY substr([{ts_col}], 1, 10) ORDER BY [{ts_col}]")
                rows = cursor.fetchall()
                growth_data.append({
                    "table": table_name,
                    "column_used": ts_col,
                    "daily_growth": [{"date": r[0][:10] if r[0] else "unknown", "count": r[1]} for r in rows]
                })

            # Get column info for documentation
            memory_stats[f"{table_name}_columns"] = columns
        except Exception as e:
            print(f"  Error querying {table_name}: {e}")

    with open(f"{DATA_DIR}/memory_stats.json", 'w') as f:
        json.dump(memory_stats, f, indent=2)

    if growth_data:
        with open(f"{DATA_DIR}/memory_growth.json", 'w') as f:
            json.dump(growth_data, f, indent=2)

    conn.close()
    print(f"Memory stats: {memory_stats}")
    return memory_stats


# ============================================================
# 4. BEHAVIORAL PATTERNS — from tiamat.log
# ============================================================
def extract_behavioral_data():
    log_file = "/root/.automaton/tiamat.log"
    if not os.path.exists(log_file):
        return

    state_changes = Counter()
    errors = 0
    cooldown_tasks = Counter()

    with open(log_file, 'r') as f:
        for line in f:
            # State transitions
            state_match = re.search(r'State: (\w+)', line)
            if state_match:
                state_changes[state_match.group(1)] += 1

            # Errors
            if '[ERROR]' in line or 'Error:' in line:
                errors += 1

            # Cooldown tasks
            cooldown_match = re.search(r'\[COOLDOWN\] Running (\S+)', line)
            if cooldown_match:
                cooldown_tasks[cooldown_match.group(1)] += 1

    behavioral = {
        "state_transitions": dict(state_changes),
        "total_errors": errors,
        "cooldown_task_runs": dict(cooldown_tasks.most_common(20)),
    }

    with open(f"{DATA_DIR}/behavioral_stats.json", 'w') as f:
        json.dump(behavioral, f, indent=2)

    print(f"State transitions: {dict(state_changes)}")
    print(f"Errors: {errors}")
    print(f"Cooldown tasks: {len(cooldown_tasks)} unique")
    return behavioral


# ============================================================
# RUN ALL EXTRACTIONS
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("TIAMAT Paper 1 — Data Extraction")
    print("=" * 60)

    print("\n--- Cost Data ---")
    cost = extract_cost_data()

    print("\n--- Tool Usage ---")
    tools = extract_tool_data()

    print("\n--- Memory Data ---")
    memory = extract_memory_data()

    print("\n--- Behavioral Patterns ---")
    behavior = extract_behavioral_data()

    # Aggregate summary
    summary = {
        "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
        "cost": cost,
        "tools": tools,
        "memory": memory,
        "behavior": behavior,
    }
    with open(f"{DATA_DIR}/summary_stats.json", 'w') as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 60)
    print(f"All data saved to {DATA_DIR}")
    print("Ready for Paper 1 analysis and writing.")
