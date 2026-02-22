#!/usr/bin/env python3
"""
TIAMAT Farcaster/Warpcast Integration via Neynar API
Posts to Farcaster channels, reads feeds, engages with community.
"""

import os
import sys
import json
import time
import logging
import requests

log = logging.getLogger("farcaster")
if not log.handlers:
    log.setLevel(logging.INFO)
    _fmt = logging.Formatter("%(asctime)s [FARCASTER] %(message)s")
    _sh = logging.StreamHandler(sys.stderr)
    _sh.setFormatter(_fmt)
    log.addHandler(_sh)
    log.propagate = False

NEYNAR_API_KEY = os.environ.get("NEYNAR_API_KEY")
NEYNAR_SIGNER_UUID = os.environ.get("NEYNAR_SIGNER_UUID")
BASE_URL = "https://api.neynar.com/v2/farcaster"

HEADERS = {
    "Content-Type": "application/json",
    "x-api-key": NEYNAR_API_KEY or "",
}

# Key channels for TIAMAT
CHANNELS = {
    "base": "base",
    "ai": "ai",
    "dev": "dev",
    "agents": "agents",
    "crypto": "crypto",
    "onchain": "onchain",
    "build": "build",
}


class FarcasterClient:
    def __init__(self):
        if not NEYNAR_API_KEY or not NEYNAR_SIGNER_UUID:
            raise ValueError("Set NEYNAR_API_KEY and NEYNAR_SIGNER_UUID in /root/.env")
        self.last_post_time = 0
        self.min_interval = 300  # 5 min between posts minimum

    def post(self, text, channel=None, embed_url=None):
        """Post a cast to Farcaster."""
        now = time.time()
        if now - self.last_post_time < self.min_interval:
            wait = self.min_interval - (now - self.last_post_time)
            return {"error": f"Rate limit: wait {wait:.0f}s before next post"}

        payload = {
            "signer_uuid": NEYNAR_SIGNER_UUID,
            "text": text[:320],
        }
        if channel:
            payload["channel_id"] = channel
        if embed_url:
            payload["embeds"] = [{"url": embed_url}]

        try:
            resp = requests.post(
                f"{BASE_URL}/cast",
                headers=HEADERS,
                json=payload,
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                cast_hash = data.get("cast", {}).get("hash", "unknown")
                self.last_post_time = time.time()
                log.info(f"Posted to {'/' + channel if channel else 'home'}: {text[:50]}... | hash: {cast_hash}")
                return data
            else:
                log.error(f"Post failed: {resp.status_code} — {resp.text[:200]}")
                return {"error": f"{resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            log.error(f"Post error: {str(e)[:100]}")
            return {"error": str(e)[:200]}

    def reply(self, parent_hash, text):
        """Reply to a cast."""
        payload = {
            "signer_uuid": NEYNAR_SIGNER_UUID,
            "text": text[:320],
            "parent": parent_hash,
        }
        try:
            resp = requests.post(
                f"{BASE_URL}/cast",
                headers=HEADERS,
                json=payload,
                timeout=15,
            )
            if resp.status_code == 200:
                log.info(f"Replied to {parent_hash[:10]}: {text[:50]}...")
                return resp.json()
            return {"error": f"{resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)[:200]}

    def get_channel_feed(self, channel, limit=10):
        """Read recent casts from a channel. Requires paid Neynar plan."""
        try:
            resp = requests.get(
                f"{BASE_URL}/feed/channels",
                headers=HEADERS,
                params={"channel_ids": channel, "limit": limit},
                timeout=15,
            )
            if resp.status_code == 200:
                casts = resp.json().get("casts", [])
                log.info(f"Read {len(casts)} casts from /{channel}")
                return casts
            if resp.status_code == 402:
                return [{"error": "Feed reading requires paid Neynar plan"}]
            return []
        except Exception as e:
            log.error(f"Feed error: {str(e)[:100]}")
            return []

    def search_casts(self, query, limit=10):
        """Search for casts mentioning keywords. Requires paid Neynar plan."""
        try:
            resp = requests.get(
                f"{BASE_URL}/cast/search",
                headers=HEADERS,
                params={"q": query, "limit": limit},
                timeout=15,
            )
            if resp.status_code == 200:
                results = resp.json().get("result", {}).get("casts", [])
                log.info(f"Found {len(results)} casts for '{query}'")
                return results
            if resp.status_code == 402:
                return [{"error": "Cast search requires paid Neynar plan"}]
            return []
        except Exception as e:
            log.error(f"Search error: {str(e)[:100]}")
            return []

    def get_notifications(self, fid=None, limit=10):
        """Check notifications/mentions."""
        try:
            params = {"limit": limit}
            if fid:
                params["fid"] = fid
            resp = requests.get(
                f"{BASE_URL}/notifications",
                headers=HEADERS,
                params=params,
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json().get("notifications", [])
            return []
        except Exception as e:
            log.error(f"Notification error: {str(e)[:100]}")
            return []

    def like_cast(self, cast_hash):
        """Like/react to a cast."""
        try:
            resp = requests.post(
                f"{BASE_URL}/reaction",
                headers=HEADERS,
                json={
                    "signer_uuid": NEYNAR_SIGNER_UUID,
                    "reaction_type": "like",
                    "target": cast_hash,
                },
                timeout=15,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def get_user_by_username(self, username):
        """Look up a Farcaster user."""
        try:
            resp = requests.get(
                f"{BASE_URL}/user/by_username",
                headers=HEADERS,
                params={"username": username},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json().get("user")
            return None
        except Exception:
            return None


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "test"
    client = FarcasterClient()

    if action == "test":
        user = client.get_user_by_username("tiamat-")
        if user:
            print(json.dumps({
                "fid": user.get("fid"),
                "username": user.get("username"),
                "followers": user.get("follower_count", 0),
                "status": "ok",
            }))
        else:
            print(json.dumps({"status": "user_not_found"}))

    elif action == "feed":
        channel = sys.argv[2] if len(sys.argv) > 2 else "base"
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        casts = client.get_channel_feed(channel, limit)
        for c in casts:
            author = c.get("author", {}).get("username", "?")
            text = c.get("text", "")[:100]
            print(f"@{author}: {text}")

    elif action == "search":
        query = sys.argv[2] if len(sys.argv) > 2 else "AI agent"
        casts = client.search_casts(query, limit=5)
        for c in casts:
            author = c.get("author", {}).get("username", "?")
            text = c.get("text", "")[:100]
            print(f"@{author}: {text}")

    elif action == "post":
        text = sys.argv[2] if len(sys.argv) > 2 else ""
        channel = sys.argv[3] if len(sys.argv) > 3 else None
        if not text:
            print("Usage: farcaster.py post 'text' [channel]")
            sys.exit(1)
        result = client.post(text, channel=channel, embed_url="https://tiamat.live")
        print(json.dumps(result, indent=2, default=str))

    else:
        print(f"Unknown action: {action}. Use: test, feed, search, post")
