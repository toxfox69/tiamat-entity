#!/usr/bin/env python3
"""
TIAMAT Training Data Export Pipeline

Merges two data sources into Qwen 2.5 ChatML format for QLoRA fine-tuning:
  - Source A: /root/.automaton/training_data/cycles_2026-*.jsonl (JSONL with messages, tools, task_type)
  - Source B: /root/.automaton/state.db turns + tool_calls tables (full thinking, tool args + results)

Quality scores each example and filters to score >= 3.
Output: /root/.automaton/training_data/tiamat_training.jsonl (Qwen 2.5 Hermes tool calling format)
"""

import json
import sqlite3
import glob
import os
import sys
from collections import Counter
from typing import Any

# Paths
TRAINING_DIR = "/root/.automaton/training_data"
STATE_DB = "/root/.automaton/state.db"
OUTPUT_FILE = os.path.join(TRAINING_DIR, "tiamat_training.jsonl")
STATS_FILE = os.path.join(TRAINING_DIR, "export_stats.json")

# Top 25 tools matching SMALL_PROVIDER_TOOLS in inference.ts
TOOL_VOCABULARY = {
    "exec", "write_file", "read_file", "search_web", "sonar_search", "web_fetch", "browse",
    "send_telegram", "send_email", "read_email", "post_bluesky", "post_farcaster",
    "remember", "recall", "learn_fact", "ticket_list", "ticket_claim", "ticket_complete",
    "ticket_create", "ask_claude_code", "gpu_infer", "check_usdc_balance",
    "manage_cooldown", "generate_image", "deploy_app", "log_strategy", "dx_terminal",
}

# Revenue-positive tools get bonus scoring
REVENUE_TOOLS = {"post_bluesky", "send_email", "post_farcaster", "deploy_app", "generate_image"}

# Tool definitions for the system prompt (Hermes format)
TOOL_DEFINITIONS = [
    {"type": "function", "function": {"name": "exec", "description": "Execute a shell command", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Write content to a file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a file's contents", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "search_web", "description": "Search the web", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "sonar_search", "description": "Search with Perplexity Sonar", "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}}},
    {"type": "function", "function": {"name": "web_fetch", "description": "Fetch a URL", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "browse", "description": "Browse a URL with headless browser", "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "action": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "send_telegram", "description": "Send a Telegram message", "parameters": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}}},
    {"type": "function", "function": {"name": "send_email", "description": "Send an email", "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]}}},
    {"type": "function", "function": {"name": "read_email", "description": "Read emails from inbox", "parameters": {"type": "object", "properties": {"mailbox": {"type": "string"}, "count": {"type": "integer"}}, "required": ["mailbox"]}}},
    {"type": "function", "function": {"name": "post_bluesky", "description": "Post to Bluesky", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "post_farcaster", "description": "Post to Farcaster", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "remember", "description": "Store a memory", "parameters": {"type": "object", "properties": {"content": {"type": "string"}, "category": {"type": "string"}}, "required": ["content"]}}},
    {"type": "function", "function": {"name": "recall", "description": "Recall memories", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "learn_fact", "description": "Learn a new fact", "parameters": {"type": "object", "properties": {"fact": {"type": "string"}, "source": {"type": "string"}}, "required": ["fact"]}}},
    {"type": "function", "function": {"name": "ticket_list", "description": "List open tickets", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "ticket_claim", "description": "Claim a ticket", "parameters": {"type": "object", "properties": {"ticket_id": {"type": "string"}}, "required": ["ticket_id"]}}},
    {"type": "function", "function": {"name": "ticket_complete", "description": "Complete a ticket", "parameters": {"type": "object", "properties": {"ticket_id": {"type": "string"}, "result": {"type": "string"}}, "required": ["ticket_id"]}}},
    {"type": "function", "function": {"name": "ticket_create", "description": "Create a new ticket", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "priority": {"type": "string"}, "description": {"type": "string"}}, "required": ["title"]}}},
    {"type": "function", "function": {"name": "check_usdc_balance", "description": "Check USDC wallet balance", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "manage_cooldown", "description": "Manage task cooldowns", "parameters": {"type": "object", "properties": {"action": {"type": "string"}, "task": {"type": "string"}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "generate_image", "description": "Generate an image", "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}, "style": {"type": "string"}}, "required": ["prompt"]}}},
    {"type": "function", "function": {"name": "deploy_app", "description": "Deploy an application", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "path": {"type": "string"}}, "required": ["name", "path"]}}},
    {"type": "function", "function": {"name": "log_strategy", "description": "Log a strategic decision", "parameters": {"type": "object", "properties": {"strategy": {"type": "string"}, "reasoning": {"type": "string"}}, "required": ["strategy"]}}},
    {"type": "function", "function": {"name": "dx_terminal", "description": "Execute diagnostic terminal command", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
]

# Compact system prompt for training (not the full TIAMAT prompt — just enough for tool calling behavior)
SYSTEM_PROMPT_TEMPLATE = """You are TIAMAT — a sovereign AI agent. You run autonomously on your own server.
You decide what to do each cycle. Use your tools to act. Think in <situation>/<gap>/<action> blocks.

# Tools

## Available Functions
```json
{tools_json}
```"""


def load_jsonl_examples() -> list[dict]:
    """Load all JSONL training examples."""
    examples = []
    for filepath in sorted(glob.glob(os.path.join(TRAINING_DIR, "cycles_2026-*.jsonl"))):
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    examples.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return examples


def load_state_db() -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Load turns and tool_calls from state.db, indexed by turn ID."""
    turns_by_id: dict[str, dict] = {}
    tools_by_turn: dict[str, list[dict]] = {}

    if not os.path.exists(STATE_DB):
        print(f"WARNING: {STATE_DB} not found, skipping DB enrichment")
        return turns_by_id, tools_by_turn

    conn = sqlite3.connect(STATE_DB)
    conn.row_factory = sqlite3.Row

    for row in conn.execute("SELECT * FROM turns ORDER BY created_at"):
        d = dict(row)
        turns_by_id[d["id"]] = d

    for row in conn.execute("SELECT * FROM tool_calls ORDER BY created_at"):
        d = dict(row)
        tid = d["turn_id"]
        if tid not in tools_by_turn:
            tools_by_turn[tid] = []
        tools_by_turn[tid].append(d)

    conn.close()
    return turns_by_id, tools_by_turn


def detect_loop(tool_calls: list[dict]) -> bool:
    """Detect if the same tool was called 3+ times with identical args."""
    seen: dict[str, int] = {}
    for tc in tool_calls:
        key = f"{tc.get('name', '')}:{json.dumps(tc.get('arguments', {}), sort_keys=True)}"
        seen[key] = seen.get(key, 0) + 1
        if seen[key] >= 3:
            return True
    return False


def score_example(example: dict, db_tools: list[dict] | None) -> int:
    """Score an example 0-10 based on quality signals."""
    score = 0
    tools_called = example.get("tools_called", [])
    messages = example.get("messages", [])

    # Get assistant content
    assistant_content = ""
    for msg in messages:
        if msg.get("role") == "assistant":
            assistant_content += msg.get("content", "") or ""

    # +1 per successful tool call (no error) from DB
    if db_tools:
        for tc in db_tools:
            if not tc.get("error"):
                score += 1
    elif tools_called:
        # No DB enrichment — give 1 point per tool called
        score += len(tools_called)

    # +3 if ticket_complete called (task finished)
    if "ticket_complete" in tools_called:
        score += 3

    # +2 for revenue actions
    if any(t in REVENUE_TOOLS for t in tools_called):
        score += 2

    # +1 for substantive thinking (>100 chars)
    if len(assistant_content) > 100:
        score += 1

    # +1 for tool diversity (>2 unique tools)
    if len(set(tools_called)) > 2:
        score += 1

    # Cap at 10
    return min(score, 10)


def should_exclude(example: dict, db_tools: list[dict] | None) -> str | None:
    """Return exclusion reason or None if example is valid."""
    messages = example.get("messages", [])
    tools_called = example.get("tools_called", [])

    # Empty assistant + no tool calls
    assistant_content = ""
    for msg in messages:
        if msg.get("role") == "assistant":
            assistant_content += msg.get("content", "") or ""

    if not assistant_content.strip() and not tools_called:
        return "empty_assistant_no_tools"

    # Loop detection
    if db_tools and detect_loop(db_tools):
        return "tool_loop_detected"

    # Status-check-only cycles (only ticket_list or check_usdc_balance, no action)
    status_only = {"ticket_list", "check_usdc_balance"}
    if tools_called and all(t in status_only for t in tools_called):
        return "status_check_only"

    return None


def format_tool_call_hermes(name: str, arguments: Any) -> str:
    """Format a tool call in Hermes <tool_call> format."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {"raw": arguments}
    return f'<tool_call>\n{{"name":"{name}","arguments":{json.dumps(arguments)}}}\n</tool_call>'


def format_tool_response_hermes(name: str, content: str) -> str:
    """Format a tool response in Hermes <tool_response> format."""
    return f'<tool_response>\n{{"name":"{name}","content":{json.dumps(content)}}}\n</tool_response>'


def build_training_example(example: dict, db_tools: list[dict] | None) -> dict | None:
    """Convert a raw example into Qwen 2.5 Hermes ChatML training format."""
    messages = example.get("messages", [])
    tools_called = example.get("tools_called", [])

    if not messages:
        return None

    # Build system message with tool definitions
    tools_json = json.dumps(TOOL_DEFINITIONS, indent=2)
    system_content = SYSTEM_PROMPT_TEMPLATE.format(tools_json=tools_json)

    output_messages: list[dict] = [{"role": "system", "content": system_content}]

    # Collect user messages (skip system — we replaced it)
    user_parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "")
        content = (msg.get("content") or "").strip()

        if role == "system":
            continue  # We use our own system prompt
        elif role == "user":
            if content:
                user_parts.append(content)
        elif role == "assistant":
            # Flush accumulated user parts
            if user_parts:
                output_messages.append({"role": "user", "content": "\n\n".join(user_parts)})
                user_parts = []

            # Build assistant message with tool calls embedded
            assistant_text = content

            # If we have DB tool data, embed actual tool calls in Hermes format
            if db_tools and tools_called:
                tool_segments: list[str] = []
                if assistant_text:
                    tool_segments.append(assistant_text)

                for tc in db_tools:
                    tc_name = tc.get("name", "")
                    if tc_name not in TOOL_VOCABULARY:
                        continue
                    tc_args = tc.get("arguments", "{}")
                    try:
                        tc_args = json.loads(tc_args) if isinstance(tc_args, str) else tc_args
                    except json.JSONDecodeError:
                        tc_args = {}
                    tool_segments.append(format_tool_call_hermes(tc_name, tc_args))

                if tool_segments:
                    assistant_text = "\n\n".join(tool_segments)

            if assistant_text:
                output_messages.append({"role": "assistant", "content": assistant_text})

            # Add tool responses from DB
            if db_tools:
                for tc in db_tools:
                    tc_name = tc.get("name", "")
                    if tc_name not in TOOL_VOCABULARY:
                        continue
                    tc_result = tc.get("result", "")
                    # Truncate very long results (search results, file contents)
                    if len(tc_result) > 2000:
                        tc_result = tc_result[:2000] + "\n[...truncated]"
                    output_messages.append({
                        "role": "tool",
                        "content": format_tool_response_hermes(tc_name, tc_result)
                    })
            elif tools_called:
                # No DB data — create stub tool calls from JSONL tools_called list
                tool_call_text = assistant_text or ""
                for tool_name in tools_called:
                    if tool_name in TOOL_VOCABULARY:
                        tool_call_text += f"\n\n<tool_call>\n{{\"name\":\"{tool_name}\",\"arguments\":{{}}}}\n</tool_call>"
                if tool_call_text != assistant_text:
                    # Replace last assistant message
                    if output_messages and output_messages[-1]["role"] == "assistant":
                        output_messages[-1]["content"] = tool_call_text

    # Flush any remaining user parts before validation
    if user_parts:
        output_messages.append({"role": "user", "content": "\n\n".join(user_parts)})
        user_parts = []

    # If we have tools but no assistant message yet, create one with tool calls
    roles = [m["role"] for m in output_messages]
    if "assistant" not in roles and tools_called:
        tool_text_parts = []
        if db_tools:
            for tc in db_tools:
                tc_name = tc.get("name", "")
                if tc_name not in TOOL_VOCABULARY:
                    continue
                tc_args = tc.get("arguments", "{}")
                try:
                    tc_args = json.loads(tc_args) if isinstance(tc_args, str) else tc_args
                except json.JSONDecodeError:
                    tc_args = {}
                tool_text_parts.append(format_tool_call_hermes(tc_name, tc_args))
        else:
            for tool_name in tools_called:
                if tool_name in TOOL_VOCABULARY:
                    tool_text_parts.append(format_tool_call_hermes(tool_name, {}))
        if tool_text_parts:
            output_messages.append({"role": "assistant", "content": "\n\n".join(tool_text_parts)})

    # Add a default user prompt if none present
    roles = [m["role"] for m in output_messages]
    if "user" not in roles:
        output_messages.insert(1, {"role": "user", "content": "Continue your current task."})

    # Validate: need at least system + user + assistant
    roles = [m["role"] for m in output_messages]
    if "assistant" not in roles:
        return None

    # Truncate total to ~4096 tokens (~16k chars)
    total_chars = sum(len(m.get("content", "")) for m in output_messages)
    if total_chars > 16000:
        # Trim from the middle (keep system + last user/assistant pair)
        while total_chars > 16000 and len(output_messages) > 3:
            removed = output_messages.pop(1)  # Remove second message (oldest user)
            total_chars -= len(removed.get("content", ""))

    return {"messages": output_messages}


def match_jsonl_to_db(example: dict, turns_by_id: dict, tools_by_turn: dict) -> list[dict] | None:
    """Try to match a JSONL example to state.db tool calls."""
    # Direct match by cycle number — state.db turn IDs are ULIDs, not cycle-based
    # Match by timestamp proximity instead
    ts = example.get("timestamp", "")
    tools_called = example.get("tools_called", [])

    if not ts or not tools_called:
        return None

    # Find the turn with the closest timestamp that has matching tool names
    best_match: str | None = None
    best_delta = float("inf")

    for turn_id, turn in turns_by_id.items():
        turn_ts = turn.get("timestamp", "")
        if not turn_ts:
            continue

        # Quick string comparison (ISO format sorts lexicographically)
        # Only consider turns within 5 minutes
        if abs(ord(ts[11]) - ord(turn_ts[11])) > 1:  # Different hours? Skip
            continue

        turn_tools = tools_by_turn.get(turn_id, [])
        turn_tool_names = {tc["name"] for tc in turn_tools}

        # At least one tool must match
        if not turn_tool_names.intersection(set(tools_called)):
            continue

        # Use string distance as proxy for time delta
        delta = abs(hash(ts) - hash(turn_ts))
        if delta < best_delta:
            best_delta = delta
            best_match = turn_id

    if best_match:
        return tools_by_turn.get(best_match, [])
    return None


def build_db_only_examples(turns_by_id: dict, tools_by_turn: dict, seen_turn_ids: set) -> list[dict]:
    """Build training examples from state.db turns that weren't matched to JSONL."""
    examples = []

    for turn_id, turn in turns_by_id.items():
        if turn_id in seen_turn_ids:
            continue

        thinking = turn.get("thinking", "")
        tool_calls_json = turn.get("tool_calls", "[]")
        db_tools = tools_by_turn.get(turn_id, [])

        if not thinking and not db_tools:
            continue

        # Parse tool_calls from the turns table
        try:
            turn_tool_calls = json.loads(tool_calls_json)
        except json.JSONDecodeError:
            turn_tool_calls = []

        tool_names = [tc.get("name", "") for tc in (turn_tool_calls if isinstance(turn_tool_calls, list) else [])]
        if not tool_names:
            tool_names = [tc.get("name", "") for tc in db_tools]

        # Build a synthetic JSONL-like example
        synthetic = {
            "id": f"db-{turn_id}",
            "timestamp": turn.get("timestamp", ""),
            "tier": "routine",
            "tools_called": tool_names,
            "messages": [
                {"role": "system", "content": ""},
                {"role": "user", "content": turn.get("input", "") or f"Turn {turn_id}"},
                {"role": "assistant", "content": thinking},
            ],
        }

        # Score and filter
        exclude = should_exclude(synthetic, db_tools)
        if exclude:
            continue

        score = score_example(synthetic, db_tools)
        if score < 3:
            continue

        formatted = build_training_example(synthetic, db_tools)
        if formatted:
            formatted["_score"] = score
            formatted["_source"] = "state_db"
            formatted["_id"] = turn_id
            examples.append(formatted)

    return examples


def main():
    print("=== TIAMAT Training Data Export Pipeline ===\n")

    # Load sources
    print("Loading JSONL examples...")
    jsonl_examples = load_jsonl_examples()
    print(f"  Found {len(jsonl_examples)} JSONL examples")

    print("Loading state.db...")
    turns_by_id, tools_by_turn = load_state_db()
    print(f"  Found {len(turns_by_id)} turns, {sum(len(v) for v in tools_by_turn.values())} tool calls")

    # Process
    output_examples: list[dict] = []
    stats = {
        "total_jsonl": len(jsonl_examples),
        "total_db_turns": len(turns_by_id),
        "excluded": Counter(),
        "scores": Counter(),
        "sources": Counter(),
        "tool_freq": Counter(),
    }

    seen_turn_ids: set = set()

    print("\nProcessing JSONL examples...")
    for example in jsonl_examples:
        # Try to enrich with DB data
        db_tools = match_jsonl_to_db(example, turns_by_id, tools_by_turn)
        if db_tools:
            # Track which DB turns we used
            for tc in db_tools:
                seen_turn_ids.add(tc.get("turn_id", ""))

        # Check exclusions
        exclude_reason = should_exclude(example, db_tools)
        if exclude_reason:
            stats["excluded"][exclude_reason] += 1
            continue

        # Score
        score = score_example(example, db_tools)
        stats["scores"][score] += 1

        if score < 3:
            stats["excluded"]["low_score"] += 1
            continue

        # Format
        formatted = build_training_example(example, db_tools)
        if not formatted:
            stats["excluded"]["format_failed"] += 1
            continue

        formatted["_score"] = score
        formatted["_source"] = "jsonl+db" if db_tools else "jsonl"
        formatted["_id"] = example.get("id", "unknown")

        # Track tool usage
        for tool in example.get("tools_called", []):
            stats["tool_freq"][tool] += 1

        output_examples.append(formatted)
        stats["sources"]["jsonl"] += 1

    # Build examples from unmatched DB turns
    print("Processing unmatched state.db turns...")
    db_examples = build_db_only_examples(turns_by_id, tools_by_turn, seen_turn_ids)
    output_examples.extend(db_examples)
    stats["sources"]["state_db"] = len(db_examples)

    # Deduplicate by content hash (assistant + user + tools for richer fingerprint)
    seen_hashes: set = set()
    deduped: list[dict] = []
    for ex in output_examples:
        parts = []
        for m in ex["messages"]:
            if m["role"] in ("assistant", "user"):
                parts.append(m["content"][:300])
        h = hash(tuple(parts))
        if h not in seen_hashes:
            seen_hashes.add(h)
            deduped.append(ex)
        else:
            stats["excluded"]["duplicate"] += 1

    output_examples = deduped

    # Sort by score descending
    output_examples.sort(key=lambda x: x.get("_score", 0), reverse=True)

    # Write output
    print(f"\nWriting {len(output_examples)} examples to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w") as f:
        for ex in output_examples:
            # Strip internal metadata before writing
            clean = {"messages": ex["messages"]}
            f.write(json.dumps(clean) + "\n")

    # Write stats
    stats_serializable = {
        "total_output": len(output_examples),
        "total_jsonl_input": stats["total_jsonl"],
        "total_db_turns": stats["total_db_turns"],
        "excluded": dict(stats["excluded"]),
        "score_distribution": {str(k): v for k, v in sorted(stats["scores"].items())},
        "sources": dict(stats["sources"]),
        "top_tools": dict(stats["tool_freq"].most_common(25)),
    }
    with open(STATS_FILE, "w") as f:
        json.dump(stats_serializable, f, indent=2)

    # Print summary
    print(f"\n=== Export Complete ===")
    print(f"  Output:    {len(output_examples)} training examples")
    print(f"  From JSONL: {stats['sources'].get('jsonl', 0)}")
    print(f"  From DB:    {stats['sources'].get('state_db', 0)}")
    print(f"  Excluded:   {sum(stats['excluded'].values())}")
    for reason, count in stats["excluded"].most_common():
        print(f"    {reason}: {count}")
    print(f"\n  Score distribution:")
    for score in sorted(stats["scores"]):
        print(f"    score {score}: {stats['scores'][score]}")
    print(f"\n  Top 10 tools:")
    for tool, count in stats["tool_freq"].most_common(10):
        print(f"    {tool}: {count}")
    print(f"\n  Files written:")
    print(f"    {OUTPUT_FILE}")
    print(f"    {STATS_FILE}")

    return len(output_examples)


if __name__ == "__main__":
    count = main()
    sys.exit(0 if count > 0 else 1)
