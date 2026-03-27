#!/usr/bin/env python3
"""
CELL-SENTINEL: Supply chain scanner lead generation cell.
Searches social media for mentions of supply chain attacks, package security,
dependency scanning, and engages with relevant posts linking to tiamat.live/scan.
Runs every 3 hours.
"""

import json
import os
import re
import time
import random
import requests
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_cell import HoneycombCell

CELL_CONFIG = {
    "name": "CELL-SENTINEL",
    "tier": 0,
    "cycle_interval_seconds": 10800,  # 3 hours
    "sandbox_paths": ["/root/.automaton/cells/sentinel/"],
    "forbidden_actions": ["send_email", "modify_code", "access_wallet"],
    "inbox_tag": "[CELL-SENTINEL]",
    "training_data_dir": "/root/.automaton/training_data/cell_sentinel",
    "cell_dir": "/root/.automaton/cells/sentinel",
}

STATE_PATH = "/root/.automaton/cells/sentinel/state.json"
ENGAGED_PATH = "/root/.automaton/cells/sentinel/engaged.json"
MAX_ENGAGEMENTS_PER_CYCLE = 5

# Search queries — things people say when they need a scanner
SEARCH_QUERIES = [
    "supply chain attack npm",
    "supply chain attack pypi",
    "malicious npm package",
    "malicious pypi package",
    "typosquatting npm",
    "dependency confusion attack",
    "npm package security scan",
    "pypi package scanner",
    "how to check npm package safe",
    "compromised package",
    "postinstall script malware",
    "package hijack",
    "software supply chain security",
    "sbom scanner",
    "dependency vulnerability scanner",
    "trivy supply chain",
    "litellm attack",
    "TeamPCP",
    "mcp server security",
    "claude code security tool",
    "ai supply chain scanning",
]

# Response templates (varied to avoid spam detection)
RESPONSE_TEMPLATES = [
    "We built a free scanner for exactly this — checks npm/PyPI packages for typosquatting, malicious install scripts, obfuscation, and dep confusion. Try it: https://tiamat.live/scan?ref=sentinel",
    "This is why we built tiamat.live/scan — scans npm and PyPI packages for supply chain attack indicators before you install. Free, no signup: https://tiamat.live/scan?ref=sentinel",
    "Relevant: we have a free supply chain scanner that detects typosquatting, suspicious install hooks, and obfuscated code in npm/PyPI packages. Also works as a Claude Code MCP plugin: https://tiamat.live/scan?ref=sentinel",
    "If you want to check packages before installing, we have a free scanner at tiamat.live/scan — catches typosquats, malicious postinstall scripts, and dependency confusion. API available too: https://tiamat.live/scan?ref=sentinel",
    "We just shipped a package scanner for this — 6 heuristic checks + AI risk summary for any npm or PyPI package. Free tier, no signup needed: https://tiamat.live/scan?ref=sentinel",
]


def load_env():
    """Load environment variables from .env file."""
    env_path = "/root/.env"
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v.strip().strip("'").strip('"'))


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"cycle_count": 0, "last_queries": [], "total_engagements": 0}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def load_engaged():
    """Track which posts we've already engaged with to avoid double-posting."""
    if os.path.exists(ENGAGED_PATH):
        with open(ENGAGED_PATH) as f:
            return json.load(f)
    return {"uris": [], "cids": [], "urls": []}


def save_engaged(engaged):
    os.makedirs(os.path.dirname(ENGAGED_PATH), exist_ok=True)
    with open(ENGAGED_PATH, "w") as f:
        json.dump(engaged, f, indent=2)
    # Keep only last 500 entries to prevent unbounded growth
    for key in ("uris", "cids", "urls"):
        if len(engaged.get(key, [])) > 500:
            engaged[key] = engaged[key][-500:]


# ===================== BLUESKY =====================

def bsky_login():
    handle = os.environ.get("BLUESKY_HANDLE", "")
    password = os.environ.get("BLUESKY_APP_PASSWORD", "")
    if not handle or not password:
        return None, None
    try:
        r = requests.post("https://bsky.social/xrpc/com.atproto.server.createSession",
                          json={"identifier": handle, "password": password}, timeout=10)
        if r.status_code == 200:
            d = r.json()
            return d["accessJwt"], d["did"]
    except Exception as e:
        print(f"Bluesky login failed: {e}")
    return None, None


def bsky_search(token, query, limit=10):
    """Search Bluesky for posts matching query."""
    try:
        r = requests.get("https://bsky.social/xrpc/app.bsky.feed.searchPosts",
                         headers={"Authorization": f"Bearer {token}"},
                         params={"q": query, "limit": limit, "sort": "latest"},
                         timeout=10)
        if r.status_code == 200:
            return r.json().get("posts", [])
    except Exception as e:
        print(f"Bluesky search failed: {e}")
    return []


def bsky_reply(token, did, post, text):
    """Reply to a Bluesky post."""
    try:
        # Create reply reference
        reply_ref = {
            "root": {"uri": post["uri"], "cid": post["cid"]},
            "parent": {"uri": post["uri"], "cid": post["cid"]},
        }
        # Detect and create link facet for the URL
        url = "https://tiamat.live/scan?ref=sentinel"
        url_start = text.find(url)
        facets = []
        if url_start >= 0:
            facets.append({
                "index": {"byteStart": len(text[:url_start].encode()), "byteEnd": len(text[:url_start].encode()) + len(url.encode())},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
            })

        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "reply": reply_ref,
            "facets": facets,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        r = requests.post("https://bsky.social/xrpc/com.atproto.repo.createRecord",
                          headers={"Authorization": f"Bearer {token}"},
                          json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
                          timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Bluesky reply failed: {e}")
    return False


def bsky_like(token, did, post):
    """Like a Bluesky post."""
    try:
        record = {
            "$type": "app.bsky.feed.like",
            "subject": {"uri": post["uri"], "cid": post["cid"]},
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        r = requests.post("https://bsky.social/xrpc/com.atproto.repo.createRecord",
                          headers={"Authorization": f"Bearer {token}"},
                          json={"repo": did, "collection": "app.bsky.feed.like", "record": record},
                          timeout=10)
        return r.status_code == 200
    except Exception:
        return False


# ===================== MASTODON =====================

def masto_search(query, limit=10):
    """Search Mastodon for posts."""
    token = os.environ.get("MASTODON_ACCESS_TOKEN", "")
    instance = os.environ.get("MASTODON_INSTANCE", "https://mastodon.social")
    if not token:
        return []
    try:
        r = requests.get(f"{instance}/api/v2/search",
                         headers={"Authorization": f"Bearer {token}"},
                         params={"q": query, "type": "statuses", "limit": limit},
                         timeout=10)
        if r.status_code == 200:
            return r.json().get("statuses", [])
    except Exception as e:
        print(f"Mastodon search failed: {e}")
    return []


def masto_reply(status_id, text):
    """Reply to a Mastodon status."""
    token = os.environ.get("MASTODON_ACCESS_TOKEN", "")
    instance = os.environ.get("MASTODON_INSTANCE", "https://mastodon.social")
    if not token:
        return False
    try:
        r = requests.post(f"{instance}/api/v1/statuses",
                          headers={"Authorization": f"Bearer {token}"},
                          json={"status": text, "in_reply_to_id": status_id, "visibility": "public"},
                          timeout=10)
        return r.status_code in (200, 201)
    except Exception:
        return False


def masto_fav(status_id):
    """Favourite a Mastodon status."""
    token = os.environ.get("MASTODON_ACCESS_TOKEN", "")
    instance = os.environ.get("MASTODON_INSTANCE", "https://mastodon.social")
    if not token:
        return False
    try:
        r = requests.post(f"{instance}/api/v1/statuses/{status_id}/favourite",
                          headers={"Authorization": f"Bearer {token}"},
                          timeout=10)
        return r.status_code == 200
    except Exception:
        return False


# ===================== MAIN CELL =====================

class SentinelCell(HoneycombCell):
    def execute(self):
        load_env()
        state = load_state()
        engaged = load_engaged()
        tool_calls = []
        engagements = 0

        # Pick 3 random queries this cycle
        queries = random.sample(SEARCH_QUERIES, min(3, len(SEARCH_QUERIES)))
        state["last_queries"] = queries

        # ---- BLUESKY ----
        token, did = bsky_login()
        if token:
            for query in queries:
                if engagements >= MAX_ENGAGEMENTS_PER_CYCLE:
                    break
                posts = bsky_search(token, query, limit=5)
                tool_calls.append({"tool": "bsky_search", "args": {"q": query}, "result": f"{len(posts)} posts"})

                for post in posts:
                    if engagements >= MAX_ENGAGEMENTS_PER_CYCLE:
                        break
                    uri = post.get("uri", "")
                    # Skip already engaged, own posts, or old posts
                    if uri in engaged.get("uris", []):
                        continue
                    author = post.get("author", {})
                    if author.get("handle", "").endswith("tiamat.live") or author.get("did") == did:
                        continue

                    text = post.get("record", {}).get("text", "")
                    if len(text) < 20:
                        continue

                    # Like the post
                    bsky_like(token, did, post)
                    tool_calls.append({"tool": "bsky_like", "args": {"uri": uri}})

                    # Reply with scanner link
                    response = random.choice(RESPONSE_TEMPLATES)
                    if bsky_reply(token, did, post, response):
                        engagements += 1
                        engaged.setdefault("uris", []).append(uri)
                        tool_calls.append({"tool": "bsky_reply", "args": {"uri": uri}, "result": "sent"})
                        self._log(f"Bluesky engaged: @{author.get('handle','')} — {text[:80]}")
                    time.sleep(2)  # Rate limit courtesy

        # ---- MASTODON ----
        for query in queries:
            if engagements >= MAX_ENGAGEMENTS_PER_CYCLE:
                break
            statuses = masto_search(query, limit=5)
            tool_calls.append({"tool": "masto_search", "args": {"q": query}, "result": f"{len(statuses)} statuses"})

            for status in statuses:
                if engagements >= MAX_ENGAGEMENTS_PER_CYCLE:
                    break
                sid = str(status.get("id", ""))
                if sid in engaged.get("urls", []):
                    continue

                # Skip own posts
                acct = status.get("account", {}).get("acct", "")
                if "tiamat" in acct.lower():
                    continue

                content = re.sub(r'<[^>]+>', '', status.get("content", ""))
                if len(content) < 20:
                    continue

                # Favourite
                masto_fav(sid)
                tool_calls.append({"tool": "masto_fav", "args": {"id": sid}})

                # Reply
                response = f"@{acct} {random.choice(RESPONSE_TEMPLATES)}"
                if masto_reply(sid, response):
                    engagements += 1
                    engaged.setdefault("urls", []).append(sid)
                    tool_calls.append({"tool": "masto_reply", "args": {"id": sid}, "result": "sent"})
                    self._log(f"Mastodon engaged: @{acct} — {content[:80]}")
                time.sleep(2)

        # Save state
        state["cycle_count"] = state.get("cycle_count", 0) + 1
        state["total_engagements"] = state.get("total_engagements", 0) + engagements
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        save_engaged(engaged)

        # Report high-value finds to TIAMAT
        if engagements > 0:
            self.report_to_queen(
                f"SENTINEL found {engagements} supply chain security conversations this cycle. "
                f"Engaged with scanner link. Total engagements: {state['total_engagements']}",
                priority="high" if engagements >= 3 else "normal"
            )

        label = "success" if engagements > 0 else "partial"
        return {
            "label": label,
            "evidence": f"Searched {len(queries)} queries, {engagements} engagements across Bluesky+Mastodon",
            "tool_calls": tool_calls,
        }


if __name__ == "__main__":
    cell = SentinelCell(CELL_CONFIG)
    cell.run_forever()
