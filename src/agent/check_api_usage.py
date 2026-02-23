#!/usr/bin/env python3
"""
API usage analytics for TIAMAT.
Called by TIAMAT during strategic cycles to identify conversion opportunities.
"""
import json
import sys

USAGE_FILE = "/root/.automaton/api_users.json"

def check_api_usage():
    """Returns usage analytics for TIAMAT to review."""
    try:
        with open(USAGE_FILE) as f:
            users = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"error": "no usage data yet", "total_users": 0}

    total_users = len(users)
    total_calls = sum(u["total_calls"] for u in users.values())
    power_users = {ip: u for ip, u in users.items() if u["total_calls"] >= 5}
    limit_hitters = {ip: u for ip, u in users.items() if u.get("hit_limit", 0) > 0}
    repeat_hitters = {ip: u for ip, u in users.items() if u.get("hit_limit", 0) >= 3}

    return {
        "total_users": total_users,
        "total_calls": total_calls,
        "power_users": len(power_users),
        "hit_limit_once": len(limit_hitters),
        "hit_limit_3plus": len(repeat_hitters),
        "conversion_targets": [
            {"ip": ip, "calls": u["total_calls"], "limit_hits": u.get("hit_limit", 0),
             "last_seen": u.get("last_seen", "?"), "endpoints": u.get("endpoints", {})}
            for ip, u in sorted(users.items(), key=lambda x: x[1].get("hit_limit", 0), reverse=True)
            if u.get("hit_limit", 0) > 0
        ][:10],
        "top_users": [
            {"ip": ip, "calls": u["total_calls"], "last_seen": u.get("last_seen", "?")}
            for ip, u in sorted(users.items(), key=lambda x: x[1]["total_calls"], reverse=True)
        ][:10],
    }


if __name__ == "__main__":
    result = check_api_usage()
    print(json.dumps(result, indent=2))
