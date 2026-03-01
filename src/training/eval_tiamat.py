#!/usr/bin/env python3
"""
TIAMAT Shadow Evaluation — Quality Gate

Compares tiamat-local responses against Claude for the same prompts.
Tracks tool selection accuracy, task completion, and garbage detection.

If tool accuracy drops below 60% over 50 evaluations, outputs DISABLE signal.

Usage:
  python3 eval_tiamat.py --prompt "You are waking up. Turn count: 500..."
  python3 eval_tiamat.py --report    # Print evaluation summary
  python3 eval_tiamat.py --check     # Exit 0 if quality OK, 1 if gate failed
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from typing import Any

EVAL_LOG = "/root/.automaton/model_comparison.jsonl"
TIAMAT_LOCAL_ENDPOINT = os.environ.get("TIAMAT_LOCAL_ENDPOINT", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
QUALITY_THRESHOLD = 0.60  # 60% tool accuracy minimum
EVAL_WINDOW = 50  # Rolling window size

# Same tool list as SMALL_PROVIDER_TOOLS
TOOL_DEFS = [
    {"type": "function", "function": {"name": "exec", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "write_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "search_web", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "sonar_search", "parameters": {"type": "object", "properties": {"question": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "send_telegram", "parameters": {"type": "object", "properties": {"message": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "post_bluesky", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "ticket_list", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "ticket_claim", "parameters": {"type": "object", "properties": {"ticket_id": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "ticket_complete", "parameters": {"type": "object", "properties": {"ticket_id": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "remember", "parameters": {"type": "object", "properties": {"content": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "recall", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "check_usdc_balance", "parameters": {"type": "object", "properties": {}}}},
]


def call_tiamat_local(messages: list[dict], tools: list[dict]) -> dict | None:
    """Call tiamat-local via OpenAI-compatible API."""
    if not TIAMAT_LOCAL_ENDPOINT:
        return None

    body = json.dumps({
        "model": "tiamat-local",
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": 1024,
        "temperature": 0.1,
    }).encode()

    req = urllib.request.Request(
        f"{TIAMAT_LOCAL_ENDPOINT}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            return {
                "content": msg.get("content", ""),
                "tool_calls": [tc["function"]["name"] for tc in (msg.get("tool_calls") or [])],
                "finish_reason": choice.get("finish_reason", ""),
                "model": data.get("model", "tiamat-local"),
            }
    except Exception as e:
        return {"error": str(e)}


def call_anthropic(messages: list[dict], tools: list[dict]) -> dict | None:
    """Call Claude Haiku via Anthropic API (reference model)."""
    if not ANTHROPIC_API_KEY:
        return None

    # Convert to Anthropic format
    system_msg = ""
    api_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_msg = msg["content"]
        else:
            api_messages.append(msg)

    # Convert tool format
    anthropic_tools = []
    for t in tools:
        fn = t.get("function", {})
        anthropic_tools.append({
            "name": fn.get("name", ""),
            "description": fn.get("name", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1024,
        "system": system_msg,
        "messages": api_messages if api_messages else [{"role": "user", "content": "Continue."}],
        "tools": anthropic_tools,
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            content_blocks = data.get("content", [])
            text = ""
            tool_calls = []
            for block in content_blocks:
                if block.get("type") == "text":
                    text += block.get("text", "")
                elif block.get("type") == "tool_use":
                    tool_calls.append(block.get("name", ""))
            return {
                "content": text,
                "tool_calls": tool_calls,
                "model": data.get("model", "claude-haiku"),
            }
    except Exception as e:
        return {"error": str(e)}


def evaluate_prompt(prompt: str) -> dict:
    """Run same prompt through both models and compare."""
    messages = [
        {"role": "system", "content": "You are TIAMAT, an autonomous AI agent. Choose the best tool for the task."},
        {"role": "user", "content": prompt},
    ]

    result: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prompt_preview": prompt[:200],
    }

    # Call both models
    local_result = call_tiamat_local(messages, TOOL_DEFS)
    claude_result = call_anthropic(messages, TOOL_DEFS)

    result["tiamat_local"] = local_result
    result["claude"] = claude_result

    # Compare tool selections
    if local_result and claude_result and "error" not in local_result and "error" not in claude_result:
        local_tools = set(local_result.get("tool_calls", []))
        claude_tools = set(claude_result.get("tool_calls", []))

        # Tool match: at least one tool in common, or both chose no tools
        if local_tools and claude_tools:
            result["tool_match"] = len(local_tools & claude_tools) > 0
        elif not local_tools and not claude_tools:
            result["tool_match"] = True
        else:
            result["tool_match"] = False

        # Garbage detection: empty content AND no tool calls
        result["local_garbage"] = not local_result.get("content", "").strip() and not local_tools
        result["claude_garbage"] = not claude_result.get("content", "").strip() and not claude_tools
    else:
        result["tool_match"] = None
        result["local_garbage"] = local_result is None or "error" in (local_result or {})
        result["claude_garbage"] = False

    # Append to log
    with open(EVAL_LOG, "a") as f:
        f.write(json.dumps(result) + "\n")

    return result


def load_evaluations() -> list[dict]:
    """Load all evaluation results."""
    if not os.path.exists(EVAL_LOG):
        return []
    results = []
    with open(EVAL_LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return results


def compute_metrics(evaluations: list[dict]) -> dict:
    """Compute quality metrics over evaluation window."""
    recent = evaluations[-EVAL_WINDOW:]
    if not recent:
        return {"total": 0, "tool_accuracy": 1.0, "garbage_rate": 0.0, "gate_passed": True}

    tool_matches = [e for e in recent if e.get("tool_match") is not None]
    garbage = [e for e in recent if e.get("local_garbage")]

    tool_accuracy = sum(1 for e in tool_matches if e["tool_match"]) / max(len(tool_matches), 1)
    garbage_rate = len(garbage) / max(len(recent), 1)

    return {
        "total": len(evaluations),
        "window": len(recent),
        "tool_accuracy": round(tool_accuracy, 3),
        "garbage_rate": round(garbage_rate, 3),
        "gate_passed": tool_accuracy >= QUALITY_THRESHOLD,
        "threshold": QUALITY_THRESHOLD,
    }


def print_report():
    """Print evaluation summary."""
    evals = load_evaluations()
    metrics = compute_metrics(evals)

    print(f"=== TIAMAT Model Evaluation Report ===\n")
    print(f"  Total evaluations: {metrics['total']}")
    print(f"  Window size: {metrics.get('window', 0)}/{EVAL_WINDOW}")
    print(f"  Tool accuracy: {metrics['tool_accuracy']:.1%} (threshold: {QUALITY_THRESHOLD:.0%})")
    print(f"  Garbage rate: {metrics['garbage_rate']:.1%}")
    print(f"  Quality gate: {'PASSED' if metrics['gate_passed'] else 'FAILED'}")

    if not metrics["gate_passed"]:
        print(f"\n  WARNING: Tool accuracy below threshold!")
        print(f"  Recommendation: Disable tiamat-local until retrained.")


def check_gate() -> bool:
    """Check quality gate. Returns True if OK, False if should disable."""
    evals = load_evaluations()
    if len(evals) < 10:
        return True  # Not enough data yet
    metrics = compute_metrics(evals)
    return metrics["gate_passed"]


def main():
    parser = argparse.ArgumentParser(description="TIAMAT Shadow Evaluation")
    parser.add_argument("--prompt", help="Prompt to evaluate")
    parser.add_argument("--report", action="store_true", help="Print evaluation report")
    parser.add_argument("--check", action="store_true", help="Check quality gate (exit 0=ok, 1=fail)")
    args = parser.parse_args()

    if args.report:
        print_report()
    elif args.check:
        ok = check_gate()
        if ok:
            print("GATE: PASSED")
            sys.exit(0)
        else:
            print("GATE: FAILED — disable tiamat-local")
            sys.exit(1)
    elif args.prompt:
        result = evaluate_prompt(args.prompt)
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
