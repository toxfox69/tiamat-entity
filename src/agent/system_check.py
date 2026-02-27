#!/usr/bin/env python3
"""TIAMAT System Health Check — full diagnostic report."""

import json, os, subprocess, sqlite3
from datetime import datetime, timezone

report = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "checks": {}
}

def check(name, fn):
    try:
        report["checks"][name] = fn()
    except Exception as e:
        report["checks"][name] = {"status": "error", "detail": str(e)}

# 1. TIAMAT process
def check_agent():
    pid_file = "/tmp/tiamat.pid"
    if not os.path.exists(pid_file):
        return {"status": "down", "pid": None}
    pid = open(pid_file).read().strip()
    running = subprocess.run(["kill", "-0", pid], capture_output=True).returncode == 0
    return {"status": "running" if running else "down", "pid": pid}

check("agent_process", check_agent)

# 2. Inference routing — provider distribution
def check_routing():
    log = "/root/.automaton/inference_routing.log"
    if not os.path.exists(log):
        return {"status": "no_log", "detail": "inference_routing.log missing"}
    lines = open(log).readlines()[-100:]
    providers = {}
    for line in lines:
        line_lower = line.lower()
        if "provider: groq" in line_lower:
            providers["groq"] = providers.get("groq", 0) + 1
        elif "provider: cerebras" in line_lower:
            providers["cerebras"] = providers.get("cerebras", 0) + 1
        elif "provider: anthropic" in line_lower:
            providers["anthropic"] = providers.get("anthropic", 0) + 1
        elif "provider: gemini" in line_lower:
            providers["gemini"] = providers.get("gemini", 0) + 1
        else:
            providers["other"] = providers.get("other", 0) + 1
    total = sum(providers.values()) or 1
    free_pct = round((providers.get("groq", 0) + providers.get("cerebras", 0) + providers.get("gemini", 0)) / total * 100, 1)
    weak = [l for l in lines if "WEAK" in l]
    return {
        "status": "ok" if free_pct > 0 else "WARNING — no free-tier routing",
        "last_100_cycles": providers,
        "free_tier_percentage": free_pct,
        "weak_model_cycles": len(weak)
    }

check("inference_routing", check_routing)

# 3. Cost summary
def check_costs():
    log = "/root/.automaton/cost.log"
    if not os.path.exists(log):
        return {"status": "no_log"}
    lines = [l.strip() for l in open(log).readlines() if l.strip()][-50:]
    total_cost = 0
    for line in lines:
        try:
            total_cost += float(line.split(",")[7])
        except:
            pass
    return {
        "status": "ok",
        "last_50_cycles_cost_usd": round(total_cost, 4),
        "avg_cost_per_cycle": round(total_cost / max(len(lines), 1), 4)
    }

check("costs", check_costs)

# 4. API health
def check_apis():
    results = {}
    for port, name in [(5000, "main_api"), (5001, "memory_api")]:
        try:
            r = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 f"http://127.0.0.1:{port}/health"],
                capture_output=True, text=True, timeout=5
            )
            results[name] = {"status": "ok" if r.stdout == "200" else "down", "http": r.stdout}
        except Exception as e:
            results[name] = {"status": "error", "detail": str(e)}
    return results

check("apis", check_apis)

# 5. Training data
def check_training():
    td = "/root/.automaton/training_data"
    if not os.path.exists(td):
        return {"status": "no_data", "total": 0}
    total = 0
    files = []
    for f in os.listdir(td):
        if f.endswith(".jsonl"):
            count = sum(1 for _ in open(os.path.join(td, f)))
            total += count
            files.append({"file": f, "examples": count})
    return {
        "status": "ok",
        "total_examples": total,
        "distillation_readiness": f"{round(total / 5000 * 100, 1)}%",
        "files": files
    }

check("training_data", check_training)

# 6. Memory DB
def check_memory():
    db_path = "/root/.automaton/memory.db"
    if not os.path.exists(db_path):
        return {"status": "missing"}
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    counts = {}
    for table in ["tiamat_memories", "compressed_memories", "core_knowledge"]:
        try:
            c.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = c.fetchone()[0]
        except:
            counts[table] = "missing"
    conn.close()
    return {"status": "ok", "counts": counts}

check("memory", check_memory)

# 7. Disk
def check_disk():
    r = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
    parts = r.stdout.split("\n")[1].split()
    return {
        "status": "ok",
        "total": parts[1] if len(parts) > 1 else "?",
        "used": parts[2] if len(parts) > 2 else "?",
        "available": parts[3] if len(parts) > 3 else "?",
        "use_pct": parts[4] if len(parts) > 4 else "?"
    }

check("disk", check_disk)

# 8. Hive / Honeycomb
def check_hive():
    hive = "/root/.automaton/hive"
    if not os.path.exists(hive):
        return {"status": "not_initialized"}
    status_file = os.path.join(hive, "swarm_status.json")
    if not os.path.exists(status_file):
        return {"status": "initialized", "cells": 0}
    data = json.load(open(status_file))
    return {"status": "ok", "cells": len(data)}

check("hive", check_hive)

# 9. Revenue
def check_revenue():
    api_users = "/root/.automaton/api_users.json"
    if not os.path.exists(api_users):
        return {"status": "no_data", "paying_customers": 0}
    data = json.load(open(api_users))
    return {"status": "ok", "summary": data}

check("revenue", check_revenue)

# 10. GPU pod
def check_gpu():
    try:
        r = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "http://213.192.2.118:40080/health"],
            capture_output=True, text=True, timeout=5
        )
        return {"status": "ok" if r.stdout == "200" else "down", "http": r.stdout}
    except:
        return {"status": "down", "detail": "connection failed"}

check("gpu_pod", check_gpu)

# Final status
warnings = [k for k, v in report["checks"].items()
            if isinstance(v, dict) and "WARNING" in str(v.get("status", ""))]
errors = [k for k, v in report["checks"].items()
          if isinstance(v, dict) and v.get("status") in ("error", "down", "missing")]

report["overall"] = ("healthy" if not warnings and not errors else
                     "degraded" if warnings and not errors else "critical")
report["warnings"] = warnings
report["errors"] = errors

print(json.dumps(report, indent=2))
