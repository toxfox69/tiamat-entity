#!/usr/bin/env python3
"""
TIAMAT 4chan Research Tool — read-only.
Reads catalogs, threads, and searches posts from whitelisted boards.
Uses the public 4chan JSON API (a.4cdn.org). No auth needed.
"""

import sys
import json
import re
import time
import logging
import requests

log = logging.getLogger("fourchan")
if not log.handlers:
    log.setLevel(logging.INFO)
    _fmt = logging.Formatter("%(asctime)s [4CHAN] %(message)s")
    _sh = logging.StreamHandler(sys.stderr)
    _sh.setFormatter(_fmt)
    log.addHandler(_sh)
    log.propagate = False

API_BASE = "https://a.4cdn.org"
BOARD_WHITELIST = ["g", "sci", "biz", "diy", "pol"]

# Rate limit: 1 request per second (4chan API rule)
_last_request_time = 0


def _rate_limit():
    """Enforce 1 req/sec rate limit."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _last_request_time = time.time()


def _strip_html(text):
    """Strip HTML tags and decode entities from 4chan post content."""
    if not text:
        return ""
    # Replace <br> with newlines
    text = re.sub(r"<br\s*/?>", "\n", text)
    # Strip all other tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities
    try:
        from html import unescape
        text = unescape(text)
    except ImportError:
        pass
    return text.strip()


def _validate_board(board):
    """Validate board against whitelist."""
    board = board.strip("/").lower()
    if board not in BOARD_WHITELIST:
        raise ValueError(
            f"Board /{board}/ not in whitelist. Allowed: {', '.join('/' + b + '/' for b in BOARD_WHITELIST)}"
        )
    return board


def catalog(board, limit=20):
    """Get thread catalog from a board. Returns top threads by reply count."""
    board = _validate_board(board)
    _rate_limit()

    resp = requests.get(f"{API_BASE}/{board}/catalog.json", timeout=15)
    if resp.status_code != 200:
        return {"error": f"{resp.status_code}: {resp.text[:200]}"}

    threads = []
    for page in resp.json():
        for t in page.get("threads", []):
            threads.append({
                "no": t.get("no"),
                "sub": _strip_html(t.get("sub", "")),
                "com": _strip_html(t.get("com", ""))[:200],
                "replies": t.get("replies", 0),
                "images": t.get("images", 0),
                "time": t.get("time", 0),
            })

    # Sort by replies descending, take top N
    threads.sort(key=lambda x: x["replies"], reverse=True)
    threads = threads[:limit]

    log.info(f"Catalog /{board}/: {len(threads)} threads")
    return {"board": board, "threads": threads}


def thread(board, thread_id):
    """Read a specific thread. Returns OP + all replies."""
    board = _validate_board(board)
    thread_id = int(thread_id)
    _rate_limit()

    resp = requests.get(f"{API_BASE}/{board}/thread/{thread_id}.json", timeout=15)
    if resp.status_code == 404:
        return {"error": f"Thread {thread_id} not found on /{board}/"}
    if resp.status_code != 200:
        return {"error": f"{resp.status_code}: {resp.text[:200]}"}

    posts = []
    for p in resp.json().get("posts", []):
        posts.append({
            "no": p.get("no"),
            "name": p.get("name", "Anonymous"),
            "com": _strip_html(p.get("com", ""))[:500],
            "time": p.get("time", 0),
            "replies_to": p.get("resto", 0),
        })

    log.info(f"Thread /{board}/{thread_id}: {len(posts)} posts")
    return {"board": board, "thread_id": thread_id, "posts": posts[:50]}


def search(board, query, limit=15):
    """Search a board's catalog for threads matching a query."""
    board = _validate_board(board)
    query_lower = query.lower()
    _rate_limit()

    resp = requests.get(f"{API_BASE}/{board}/catalog.json", timeout=15)
    if resp.status_code != 200:
        return {"error": f"{resp.status_code}: {resp.text[:200]}"}

    matches = []
    for page in resp.json():
        for t in page.get("threads", []):
            sub = _strip_html(t.get("sub", ""))
            com = _strip_html(t.get("com", ""))
            if query_lower in sub.lower() or query_lower in com.lower():
                matches.append({
                    "no": t.get("no"),
                    "sub": sub[:100],
                    "com": com[:200],
                    "replies": t.get("replies", 0),
                    "time": t.get("time", 0),
                })

    matches.sort(key=lambda x: x["replies"], reverse=True)
    matches = matches[:limit]

    log.info(f"Search /{board}/ for '{query}': {len(matches)} matches")
    return {"board": board, "query": query, "matches": matches}


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "catalog"

    if action == "catalog":
        board = sys.argv[2] if len(sys.argv) > 2 else "g"
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        result = catalog(board, limit)
        print(json.dumps(result, indent=2))

    elif action == "thread":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: fourchan.py thread <board> <thread_id>"}))
            sys.exit(1)
        result = thread(sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2))

    elif action == "search":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: fourchan.py search <board> <query>"}))
            sys.exit(1)
        board = sys.argv[2]
        query = " ".join(sys.argv[3:])
        result = search(board, query)
        print(json.dumps(result, indent=2))

    elif action == "test":
        # Quick smoke test — fetch /g/ catalog
        try:
            result = catalog("g", 5)
            if "error" in result:
                print(json.dumps({"status": "error", "detail": result["error"]}))
            else:
                print(json.dumps({
                    "status": "ok",
                    "board": "g",
                    "threads_fetched": len(result.get("threads", [])),
                    "top_thread": (result.get("threads") or [{}])[0].get("sub", "")[:80] if result.get("threads") else "",
                }))
        except Exception as e:
            print(json.dumps({"status": "error", "detail": str(e)[:200]}))

    else:
        print(json.dumps({"error": f"Unknown action: {action}. Use: catalog, thread, search, test"}))
        sys.exit(1)
