#!/usr/bin/env python3
"""Log TIAMAT's reasoning cycles as fine-tuning training data."""

import json
import os
from datetime import datetime

TRAINING_DIR = "/root/.automaton/training_data"
os.makedirs(TRAINING_DIR, exist_ok=True)

def get_current_file():
    """Monthly rotation of training data files."""
    month = datetime.utcnow().strftime("%Y-%m")
    return os.path.join(TRAINING_DIR, f"cycles_{month}.jsonl")

def log_training_example(
    cycle_number: int,
    tier_used: str,
    model_used: str,
    system_prompt: str,
    input_messages: list,
    output_response: str,
    tools_called: list,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0
):
    """Log one cycle as a training example in JSONL format."""

    # Classify the task type for curriculum learning later
    task_type = "general_reasoning"
    tool_set = set(tools_called)
    if 'ask_claude_code' in tool_set or 'write_file' in tool_set:
        task_type = 'code_generation'
    elif 'search_web' in tool_set or 'web_fetch' in tool_set:
        task_type = 'research'
    elif 'post_bluesky' in tool_set or 'moltbook_post' in tool_set:
        task_type = 'social_media'
    elif 'send_telegram' in tool_set or 'send_email' in tool_set:
        task_type = 'communication'
    elif 'read_file' in tool_set:
        task_type = 'information_gathering'
    elif 'exec' in tool_set:
        task_type = 'system_operation'
    elif 'remember' in tool_set or 'recall' in tool_set or 'reflect' in tool_set:
        task_type = 'self_reflection'

    example = {
        "id": f"tiamat-cycle-{cycle_number}",
        "timestamp": datetime.utcnow().isoformat(),
        "cycle": cycle_number,
        "tier": tier_used,
        "model": model_used,
        "messages": [
            {"role": "system", "content": system_prompt[:2000]},
            *[{"role": m.get("role", "user"),
               "content": m.get("content", "")[:4000]} for m in input_messages[-5:]],
            {"role": "assistant", "content": output_response[:4000]}
        ],
        "tools_called": tools_called,
        "tokens": {"in": tokens_in, "out": tokens_out},
        "latency_ms": latency_ms,
        "task_type": task_type
    }

    filepath = get_current_file()
    with open(filepath, 'a') as f:
        f.write(json.dumps(example) + "\n")

def get_training_stats():
    """Return stats about collected training data."""
    stats = {"total_examples": 0, "files": [], "task_distribution": {},
             "tier_distribution": {}, "total_size_mb": 0}

    if not os.path.exists(TRAINING_DIR):
        return stats

    for f in sorted(os.listdir(TRAINING_DIR)):
        if not f.endswith('.jsonl'):
            continue
        filepath = os.path.join(TRAINING_DIR, f)
        file_size = os.path.getsize(filepath) / (1024 * 1024)
        line_count = 0

        with open(filepath) as fh:
            for line in fh:
                line_count += 1
                try:
                    ex = json.loads(line)
                    task = ex.get("task_type", "unknown")
                    tier = ex.get("tier", "unknown")
                    stats["task_distribution"][task] = stats["task_distribution"].get(task, 0) + 1
                    stats["tier_distribution"][tier] = stats["tier_distribution"].get(tier, 0) + 1
                except json.JSONDecodeError:
                    pass

        stats["files"].append({"name": f, "examples": line_count, "size_mb": round(file_size, 2)})
        stats["total_examples"] += line_count
        stats["total_size_mb"] += file_size

    stats["total_size_mb"] = round(stats["total_size_mb"], 2)
    return stats
