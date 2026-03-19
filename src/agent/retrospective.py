#!/usr/bin/env python3
"""
TIAMAT Self-Improvement Retrospective System
=============================================
Analyzes last 50 cycles of operational data and auto-adjusts behavior.
Called by loop.ts every 50 cycles via exec.

Outputs:
  - Config updates (model blacklist, content weights, sniper thresholds)
  - guardrails.json — preemptive error checks loaded every cycle
  - permanent_rules.json — internalized directive rules
  - known_threats.json — bytecode signatures for instant sniper rejection
  - self-improvement-log.md — append-only human-readable history
  - JSON summary to stdout (loop.ts reads this)
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from collections import Counter, defaultdict
from pathlib import Path

# ============ PATHS ============

BASE_DIR = "/root/.automaton"
ENTITY_DIR = "/root/entity"
COST_LOG = f"{BASE_DIR}/cost.log"
TIAMAT_LOG = f"{BASE_DIR}/tiamat.log"
SNIPER_LOG = f"{BASE_DIR}/sniper.log"
MULTI_SNIPER_LOG = f"{BASE_DIR}/multi_sniper.log"
ECHO_STATUS = f"{BASE_DIR}/echo_status.json"
ECHO_SIGNALS = f"{BASE_DIR}/echo_signals.json"
BLACKLIST_FILE = f"{BASE_DIR}/pair_blacklist.json"
INBOX_LOG = f"{BASE_DIR}/inbox_history.log"

GUARDRAILS_FILE = f"{ENTITY_DIR}/guardrails.json"
PERMANENT_RULES_FILE = f"{ENTITY_DIR}/permanent_rules.json"
KNOWN_THREATS_FILE = f"{ENTITY_DIR}/known_threats.json"
SELF_IMPROVEMENT_LOG = f"{ENTITY_DIR}/self-improvement-log.md"
MODEL_BLACKLIST_FILE = f"{BASE_DIR}/model_blacklist.json"
CONTENT_WEIGHTS_FILE = f"{BASE_DIR}/content_weights.json"
RETRO_STATE_FILE = f"{BASE_DIR}/retrospective_state.json"

# ============ HELPERS ============

def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def tail_lines(path, n=2000):
    """Read last N lines of a file, handling binary/encoding issues."""
    try:
        with open(path, "r", errors="replace") as f:
            return f.readlines()[-n:]
    except FileNotFoundError:
        return []


# ============ 1. MODEL ROUTING AUTO-OPTIMIZATION ============

def analyze_model_routing(lines):
    """Analyze model usage, refusals, and cost efficiency."""
    model_stats = defaultdict(lambda: {"calls": 0, "tool_calls": 0, "refusals": 0, "cost": 0.0})

    for line in lines:
        # Cost entries: [COST] Cycle N (type): $X.XX (in:N ... model:NAME)
        cost_match = re.search(r'\[COST\].*\$([0-9.]+).*model:(\S+)', line)
        if cost_match:
            cost = float(cost_match.group(1))
            model = cost_match.group(2)
            model_stats[model]["calls"] += 1
            model_stats[model]["cost"] += cost

        # Tool calls: [REACT] Inner turn N/10 — model wants to continue (N tool calls so far)
        tool_match = re.search(r'\((\d+) tool calls so far\)', line)
        if tool_match:
            tc = int(tool_match.group(1))
            # Attribute to most recent model
            for m in model_stats:
                model_stats[m]["tool_calls"] = max(model_stats[m]["tool_calls"], tc)

        # Refusals
        if "REFUSAL" in line or "refused" in line.lower():
            refusal_model = re.search(r'model:(\S+)', line)
            if refusal_model:
                model_stats[refusal_model.group(1)]["refusals"] += 1
            # Also check for DeepInfra model names
            di_match = re.search(r'DeepInfra/(\S+):', line)
            if di_match:
                model_stats[di_match.group(1)]["refusals"] += 1

    # Load existing blacklist
    blacklist = load_json(MODEL_BLACKLIST_FILE, {"blacklisted": [], "promoted": [], "history": []})

    new_blacklisted = []
    for model, stats in model_stats.items():
        if stats["refusals"] > 0 and model not in blacklist.get("blacklisted", []):
            blacklist.setdefault("blacklisted", []).append(model)
            new_blacklisted.append(model)

    # Rank by efficiency: tool_calls / cost (higher = better)
    rankings = []
    for model, stats in model_stats.items():
        if stats["calls"] > 0 and model not in blacklist.get("blacklisted", []):
            efficiency = stats["tool_calls"] / max(stats["cost"], 0.001)
            rankings.append({"model": model, "efficiency": round(efficiency, 1),
                             "calls": stats["calls"], "tool_calls": stats["tool_calls"],
                             "cost": round(stats["cost"], 4)})
    rankings.sort(key=lambda x: x["efficiency"], reverse=True)

    promoted = rankings[0]["model"] if rankings else None
    if promoted:
        blacklist["promoted"] = [promoted]

    blacklist["last_updated"] = datetime.now(timezone.utc).isoformat()
    save_json(MODEL_BLACKLIST_FILE, blacklist)

    return {
        "rankings": rankings[:5],
        "new_blacklisted": new_blacklisted,
        "promoted": promoted,
        "total_models_used": len(model_stats),
    }


# ============ 2. CONTENT PERFORMANCE LEARNING ============

def analyze_content_performance(lines):
    """Analyze which platforms/topics get engagement."""
    platform_posts = Counter()
    platform_engagement = defaultdict(int)
    topic_engagement = defaultdict(int)
    cooldowns_hit = Counter()

    for line in lines:
        # Posts: [REACT] [TOOL] post_bluesky/farcaster/devto/etc
        post_match = re.search(r'\[TOOL\] (post_\w+)\(', line)
        if post_match:
            platform = post_match.group(1)
            platform_posts[platform] += 1

        # Cooldowns
        if "COOLDOWN" in line:
            cd_match = re.search(r'(post_\w+).*COOLDOWN', line) or re.search(r'COOLDOWN.*next (\w+)', line)
            if cd_match:
                cooldowns_hit[cd_match.group(1)] += 1

        # Engagement results (likes, reposts)
        like_match = re.search(r'Liked:|like_bluesky|farcaster_engage.*like', line)
        if like_match:
            platform_engagement["engagement_actions"] += 1

    # Load ECHO stats
    echo = load_json(ECHO_STATUS, {})
    echo_engagement = {
        "total_likes": echo.get("likes", 0),
        "total_reposts": echo.get("reposts", 0),
        "total_comments": echo.get("comments", 0),
    }

    # Calculate weights
    weights = load_json(CONTENT_WEIGHTS_FILE, {"platforms": {}, "topics": {}})
    for platform, count in platform_posts.items():
        weights["platforms"][platform] = {
            "posts_last_50": count,
            "cooldowns_hit": cooldowns_hit.get(platform, 0),
        }
    weights["last_updated"] = datetime.now(timezone.utc).isoformat()
    save_json(CONTENT_WEIGHTS_FILE, weights)

    # Find dead platforms (posted but zero engagement signals)
    dead_platforms = [p for p, c in platform_posts.items() if c > 3 and cooldowns_hit.get(p, 0) == 0]

    return {
        "posts_by_platform": dict(platform_posts.most_common(10)),
        "echo_engagement": echo_engagement,
        "dead_platforms": dead_platforms,
        "cooldowns": dict(cooldowns_hit),
    }


# ============ 3. SNIPER PATTERN LEARNING ============

def analyze_sniper_patterns():
    """Learn from sniper rejections and successes."""
    sniper_lines = tail_lines(SNIPER_LOG, 1000)

    honeypots = []
    skims_found = Counter()  # DEX -> count
    arb_spreads = []
    false_positives = 0

    for line in sniper_lines:
        # Honeypots
        if "UNSAFE" in line and "honeypot" in line.lower():
            addr_match = re.search(r'UNSAFE (0x[a-fA-F0-9]+)', line)
            if addr_match:
                honeypots.append(addr_match.group(1)[:20])

        # Skims
        if "SKIM FOUND" in line or "SKIM SUCCESS" in line:
            dex_match = re.search(r'\[(\w+)\]', line)
            if dex_match:
                skims_found[dex_match.group(1)] += 1

        # Arb spreads
        if "ARB SPREAD" in line:
            spread_match = re.search(r'(\d+\.\d+)%', line)
            token_match = re.search(r'\[(\w+)\]', line)
            if spread_match and token_match:
                arb_spreads.append({"token": token_match.group(1), "spread": spread_match.group(1)})

        # Phantom liquidity (false positives)
        if "phantom liquidity" in line.lower():
            false_positives += 1

    # Update known threats
    threats = load_json(KNOWN_THREATS_FILE, {"honeypot_prefixes": [], "instant_reject": [], "updated": ""})
    # Add new honeypot address prefixes
    for hp in honeypots:
        prefix = hp[:10]
        if prefix not in threats.get("honeypot_prefixes", []):
            threats.setdefault("honeypot_prefixes", []).append(prefix)

    # Keep only last 500 entries
    threats["honeypot_prefixes"] = threats.get("honeypot_prefixes", [])[-500:]
    threats["updated"] = datetime.now(timezone.utc).isoformat()
    save_json(KNOWN_THREATS_FILE, threats)

    return {
        "honeypots_detected": len(honeypots),
        "new_threat_signatures": len(honeypots),
        "top_skim_dex": dict(skims_found.most_common(3)),
        "arb_spreads": arb_spreads[:5],
        "phantom_liquidity_false_positives": false_positives,
    }


# ============ 4. COST OPTIMIZATION ============

def analyze_costs(lines):
    """Calculate cost efficiency metrics."""
    costs = []
    productive_cycles = 0
    wasted_cycles = 0

    for line in lines:
        cost_match = re.search(r'\[COST\] Cycle (\d+).*\$([0-9.]+).*out:(\d+)', line)
        if cost_match:
            cycle = int(cost_match.group(1))
            cost = float(cost_match.group(2))
            output_tokens = int(cost_match.group(3))
            costs.append({"cycle": cycle, "cost": cost, "output": output_tokens})
            if output_tokens > 50:
                productive_cycles += 1
            else:
                wasted_cycles += 1

    total_cost = sum(c["cost"] for c in costs)
    total_cycles = len(costs)
    cost_per_cycle = total_cost / max(total_cycles, 1)
    cost_per_productive = total_cost / max(productive_cycles, 1)
    waste_rate = wasted_cycles / max(total_cycles, 1)

    return {
        "total_cycles_analyzed": total_cycles,
        "total_cost": round(total_cost, 4),
        "cost_per_cycle": round(cost_per_cycle, 4),
        "cost_per_productive_action": round(cost_per_productive, 4),
        "productive_cycles": productive_cycles,
        "wasted_cycles": wasted_cycles,
        "waste_rate": round(waste_rate, 3),
    }


# ============ 5. ERROR PATTERN DETECTION ============

def analyze_errors(lines):
    """Detect recurring error patterns and create guardrails."""
    error_types = Counter()
    error_details = defaultdict(list)

    for line in lines:
        if "ERROR" in line or "REFUSAL" in line or "FAIL" in line:
            # Categorize
            if "REFUSAL" in line or "refused" in line.lower():
                error_types["model_refusal"] += 1
            elif "rate limit" in line.lower() or "RATE LIMITED" in line:
                error_types["rate_limit"] += 1
            elif "timeout" in line.lower():
                error_types["timeout"] += 1
            elif "STUCK-LOOP" in line:
                error_types["stuck_loop"] += 1
            elif "SIM_REVERTED" in line or "reverted" in line.lower():
                error_types["tx_revert"] += 1
            elif "ERROR" in line:
                error_types["generic_error"] += 1

    # Build guardrails from recurring errors
    guardrails = load_json(GUARDRAILS_FILE, {"checks": [], "updated": ""})
    new_guardrails = []

    for error_type, count in error_types.items():
        if count >= 2:
            guardrail = {
                "type": error_type,
                "count": count,
                "action": _guardrail_action(error_type),
                "added": datetime.now(timezone.utc).isoformat(),
            }
            # Don't duplicate
            existing_types = [g["type"] for g in guardrails.get("checks", [])]
            if error_type not in existing_types:
                guardrails.setdefault("checks", []).append(guardrail)
                new_guardrails.append(guardrail)

    guardrails["updated"] = datetime.now(timezone.utc).isoformat()
    save_json(GUARDRAILS_FILE, guardrails)

    return {
        "error_counts": dict(error_types.most_common(10)),
        "new_guardrails": len(new_guardrails),
        "total_guardrails": len(guardrails.get("checks", [])),
    }


def _guardrail_action(error_type):
    actions = {
        "model_refusal": "auto-blacklist model, fall through to next in cascade",
        "rate_limit": "add 5min cooldown for provider, rotate to next",
        "timeout": "reduce timeout, add circuit breaker",
        "stuck_loop": "clear last 10 turns, restart cycle (watchdog)",
        "tx_revert": "simulate before send, increase gas limit",
        "generic_error": "log and continue, alert if 3+ consecutive",
    }
    return actions.get(error_type, "log and monitor")


# ============ 6. DIRECTIVE INTERNALIZATION ============

def analyze_directives(lines):
    """Extract permanent rules from converted directives."""
    rules = load_json(PERMANENT_RULES_FILE, {"rules": [], "updated": ""})
    new_rules = []

    # Find directive conversions
    directives_found = 0
    for line in lines:
        if "Converted" in line and "directive" in line.lower():
            directives_found += 1

    # Scan for pattern-based rules in recent log
    rule_patterns = {
        "secret_scanning": ("secret", "pre-push", "never push without"),
        "model_blacklist": ("blacklist", "refuse", "REFUSAL"),
        "email_validation": ("example.com", "email", "validate"),
        "stuck_loop_detection": ("stuck", "productivity", "watchdog"),
        "atomic_writes": ("atomic", "os.replace", "half-read"),
    }

    detected_rules = []
    log_text = " ".join(lines[-500:]).lower()
    for rule_name, keywords in rule_patterns.items():
        if any(kw.lower() in log_text for kw in keywords):
            existing = [r["name"] for r in rules.get("rules", [])]
            if rule_name not in existing:
                rule = {
                    "name": rule_name,
                    "description": _rule_description(rule_name),
                    "source": "retrospective_analysis",
                    "added": datetime.now(timezone.utc).isoformat(),
                }
                rules.setdefault("rules", []).append(rule)
                new_rules.append(rule)
                detected_rules.append(rule_name)

    rules["updated"] = datetime.now(timezone.utc).isoformat()
    save_json(PERMANENT_RULES_FILE, rules)

    return {
        "directives_found": directives_found,
        "new_rules": len(new_rules),
        "total_rules": len(rules.get("rules", [])),
        "detected_rules": detected_rules,
    }


def _rule_description(name):
    descriptions = {
        "secret_scanning": "Never push to git without running secret detection. Block if pre-push hook is missing.",
        "model_blacklist": "Any model that refuses the system prompt gets auto-blacklisted from inference cascade.",
        "email_validation": "Block email sends to example.com, test.com, localhost. Validate MX records before sending.",
        "stuck_loop_detection": "If productivity < 0.10 for 5 consecutive cycles, clear last 10 turns and restart.",
        "atomic_writes": "Use os.replace() for all state file writes to prevent half-read corruption.",
    }
    return descriptions.get(name, f"Auto-detected rule: {name}")


# ============ MAIN RETROSPECTIVE ============

def run_retrospective():
    """Run full retrospective analysis. Returns summary dict."""
    now = datetime.now(timezone.utc)
    lines = tail_lines(TIAMAT_LOG, 2000)

    # Load state to get retrospective number
    state = load_json(RETRO_STATE_FILE, {"count": 0, "last_run": None})
    retro_num = state.get("count", 0) + 1

    print(f"[RETROSPECTIVE] #{retro_num} starting at {now.isoformat()}", file=sys.stderr)

    # Run all analyses
    results = {
        "retrospective_number": retro_num,
        "timestamp": now.isoformat(),
        "model_routing": analyze_model_routing(lines),
        "content_performance": analyze_content_performance(lines),
        "sniper_patterns": analyze_sniper_patterns(),
        "cost_optimization": analyze_costs(lines),
        "error_patterns": analyze_errors(lines),
        "directive_internalization": analyze_directives(lines),
    }

    # Build summary
    mr = results["model_routing"]
    cp = results["content_performance"]
    sp = results["sniper_patterns"]
    co = results["cost_optimization"]
    ep = results["error_patterns"]
    di = results["directive_internalization"]

    summary_parts = []
    if mr["promoted"]:
        summary_parts.append(f"promoted {mr['promoted']} to position 1")
    if mr["new_blacklisted"]:
        summary_parts.append(f"blacklisted {', '.join(mr['new_blacklisted'])}")
    if sp["new_threat_signatures"] > 0:
        summary_parts.append(f"{sp['new_threat_signatures']} new threat signatures")
    if ep["new_guardrails"] > 0:
        summary_parts.append(f"{ep['new_guardrails']} new guardrails")
    if di["new_rules"] > 0:
        summary_parts.append(f"{di['new_rules']} new permanent rules")

    summary = "; ".join(summary_parts) if summary_parts else "no changes needed"

    results["summary"] = summary
    results["productivity_before"] = co["waste_rate"]

    # Write self-improvement log
    _append_improvement_log(retro_num, now, results, summary)

    # Update state
    state["count"] = retro_num
    state["last_run"] = now.isoformat()
    state["last_summary"] = summary
    save_json(RETRO_STATE_FILE, state)

    # Build social post text
    results["social_post"] = (
        f"TIAMAT Retrospective #{retro_num}: {summary}. "
        f"Cost/action: ${co['cost_per_productive_action']}. "
        f"Waste rate: {co['waste_rate']*100:.0f}%. "
        f"Guardrails: {ep['total_guardrails']}. "
        f"Rules: {di['total_rules']}."
    )

    # Output JSON to stdout for loop.ts to read
    print(json.dumps(results, indent=2, default=str))
    return results


def _append_improvement_log(num, timestamp, results, summary):
    """Append to self-improvement-log.md."""
    mr = results["model_routing"]
    co = results["cost_optimization"]
    ep = results["error_patterns"]
    di = results["directive_internalization"]
    sp = results["sniper_patterns"]

    entry = f"""
## Retrospective #{num} — {timestamp.strftime('%Y-%m-%d %H:%M UTC')}

**Summary:** {summary}

### Model Routing
- Models used: {mr['total_models_used']}
- Promoted: {mr['promoted'] or 'no change'}
- Blacklisted: {', '.join(mr['new_blacklisted']) or 'none'}
- Top efficiency: {mr['rankings'][0] if mr['rankings'] else 'N/A'}

### Cost
- Cycles analyzed: {co['total_cycles_analyzed']}
- Total cost: ${co['total_cost']}
- Cost/productive action: ${co['cost_per_productive_action']}
- Waste rate: {co['waste_rate']*100:.1f}%

### Errors & Guardrails
- Error patterns: {ep['error_counts']}
- New guardrails: {ep['new_guardrails']} (total: {ep['total_guardrails']})

### Sniper
- Honeypots detected: {sp['honeypots_detected']}
- New threat signatures: {sp['new_threat_signatures']}
- Top skim DEX: {sp['top_skim_dex']}

### Rules
- Directives internalized: {di['directives_found']}
- New permanent rules: {di['new_rules']} (total: {di['total_rules']})

---
"""

    log_path = SELF_IMPROVEMENT_LOG
    header = "# TIAMAT Self-Improvement Log\n\nAutonomous retrospective analysis — no human intervention.\n\n---\n"

    if not os.path.exists(log_path):
        with open(log_path, "w") as f:
            f.write(header)

    with open(log_path, "a") as f:
        f.write(entry)


if __name__ == "__main__":
    run_retrospective()
