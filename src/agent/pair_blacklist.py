#!/usr/bin/env python3
"""
Pair blacklist — skip contracts that consistently return empty.
Tracks "reserves == balances" (dry) hits per pair.
After MAX_DRY_HITS, pair is blacklisted for BLACKLIST_HOURS.

Shared by: auto_executor.py, continuous_scanner.py, block_watcher.py
"""

import os
import json
import time
import threading

BLACKLIST_FILE = "/root/.automaton/pair_blacklist.json"
MAX_DRY_HITS = 3          # blacklist after this many consecutive dry results
BLACKLIST_HOURS = 24       # how long to blacklist (hours)
BLACKLIST_TTL = BLACKLIST_HOURS * 3600

_lock = threading.Lock()
_cache = None
_cache_time = 0
CACHE_TTL = 30  # reload from disk every 30s


def _load():
    global _cache, _cache_time
    now = time.time()
    if _cache is not None and now - _cache_time < CACHE_TTL:
        return _cache
    try:
        with open(BLACKLIST_FILE) as f:
            _cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _cache = {"dry_counts": {}, "blacklisted": {}}
    _cache_time = now
    # Ensure keys exist
    _cache.setdefault("dry_counts", {})
    _cache.setdefault("blacklisted", {})
    return _cache


def _save(data):
    global _cache, _cache_time
    try:
        with open(BLACKLIST_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        _cache = data
        _cache_time = time.time()
    except Exception:
        pass


def is_blacklisted(pair_address):
    """Check if a pair is currently blacklisted."""
    addr = pair_address.lower()
    with _lock:
        data = _load()
        entry = data["blacklisted"].get(addr)
        if entry is None:
            return False
        if time.time() > entry.get("expires", 0):
            # Expired — remove
            del data["blacklisted"][addr]
            data["dry_counts"].pop(addr, None)
            _save(data)
            return False
        return True


def record_dry(pair_address):
    """Record a dry hit (reserves == balances). Returns True if now blacklisted."""
    addr = pair_address.lower()
    with _lock:
        data = _load()
        count = data["dry_counts"].get(addr, 0) + 1
        data["dry_counts"][addr] = count
        if count >= MAX_DRY_HITS:
            data["blacklisted"][addr] = {
                "since": time.time(),
                "expires": time.time() + BLACKLIST_TTL,
                "dry_count": count,
            }
            _save(data)
            return True
        _save(data)
        return False


def record_success(pair_address):
    """Reset dry count on a successful skim (actually received tokens)."""
    addr = pair_address.lower()
    with _lock:
        data = _load()
        data["dry_counts"].pop(addr, None)
        data["blacklisted"].pop(addr, None)
        _save(data)


def blacklist_permanently(pair_address, reason="manual"):
    """Permanently blacklist a pair (expires in 1 year)."""
    addr = pair_address.lower()
    with _lock:
        data = _load()
        data["blacklisted"][addr] = {
            "since": time.time(),
            "expires": time.time() + 365 * 86400,
            "reason": reason,
        }
        data["dry_counts"][addr] = 999
        _save(data)


def get_stats():
    """Return blacklist stats for debugging."""
    with _lock:
        data = _load()
        now = time.time()
        active = {k: v for k, v in data["blacklisted"].items() if v.get("expires", 0) > now}
        return {
            "tracked_pairs": len(data["dry_counts"]),
            "blacklisted_pairs": len(active),
            "pairs": {k: v for k, v in data["dry_counts"].items() if v >= 2},  # only show pairs with 2+ dry hits
        }
