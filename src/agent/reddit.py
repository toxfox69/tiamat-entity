#!/usr/bin/env python3
"""
TIAMAT Reddit Integration — OAuth2 password grant client.
Post, comment, read, and search Reddit via the API.
"""

import os
import sys
import json
import time
import logging
import requests

log = logging.getLogger("reddit")
if not log.handlers:
    log.setLevel(logging.INFO)
    _fmt = logging.Formatter("%(asctime)s [REDDIT] %(message)s")
    _sh = logging.StreamHandler(sys.stderr)
    _sh.setFormatter(_fmt)
    log.addHandler(_sh)
    log.propagate = False

CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
USERNAME = os.environ.get("REDDIT_USERNAME", "")
PASSWORD = os.environ.get("REDDIT_PASSWORD", "")

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"
USER_AGENT = "python:TIAMAT-Agent:v1.0 (by /u/{})".format(USERNAME or "tiamat")

SUBREDDIT_WHITELIST = [
    "SideProject", "artificial", "MachineLearning", "androiddev",
    "programming", "Python", "opensource", "selfhosted",
    "ArtificialIntelligence", "LLM", "LocalLLaMA", "ChatGPT",
    "singularity", "technology", "webdev", "startups",
    "IndieHackers", "buildinpublic",
]

# Lowercase lookup for case-insensitive matching
_WHITELIST_LOWER = {s.lower(): s for s in SUBREDDIT_WHITELIST}


class RedditClient:
    def __init__(self):
        self._token = None
        self._token_expires = 0
        self.last_post_time = 0
        self.min_post_interval = 300  # 5 min between posts

    def _get_token(self):
        """Get OAuth2 token via password grant."""
        now = time.time()
        if self._token and now < self._token_expires:
            return self._token

        if not CLIENT_ID or not CLIENT_SECRET:
            raise ValueError("Missing REDDIT_CLIENT_ID or REDDIT_CLIENT_SECRET in env")
        if not USERNAME or not PASSWORD:
            raise ValueError("Missing REDDIT_USERNAME or REDDIT_PASSWORD in env")

        resp = requests.post(
            TOKEN_URL,
            auth=(CLIENT_ID, CLIENT_SECRET),
            data={
                "grant_type": "password",
                "username": USERNAME,
                "password": PASSWORD,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        if resp.status_code != 200:
            raise ValueError(f"OAuth2 failed: {resp.status_code} — {resp.text[:200]}")

        data = resp.json()
        if "access_token" not in data:
            raise ValueError(f"OAuth2 no token: {json.dumps(data)[:200]}")

        self._token = data["access_token"]
        self._token_expires = now + data.get("expires_in", 3600) - 60
        log.info("OAuth2 token acquired")
        return self._token

    def _headers(self):
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "User-Agent": USER_AGENT,
        }

    def _validate_subreddit(self, subreddit):
        """Validate subreddit against whitelist, return canonical name."""
        key = subreddit.lower()
        if key not in _WHITELIST_LOWER:
            raise ValueError(
                f"Subreddit r/{subreddit} not in whitelist. "
                f"Allowed: {', '.join(SUBREDDIT_WHITELIST)}"
            )
        return _WHITELIST_LOWER[key]

    def test(self):
        """Test authentication and return account info."""
        resp = requests.get(
            f"{API_BASE}/api/v1/me",
            headers=self._headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "status": "ok",
                "username": data.get("name"),
                "karma": data.get("link_karma", 0) + data.get("comment_karma", 0),
                "created_utc": data.get("created_utc"),
            }
        return {"status": "error", "code": resp.status_code, "detail": resp.text[:200]}

    def post(self, subreddit, title, text=None, url=None):
        """Submit a post to a subreddit."""
        subreddit = self._validate_subreddit(subreddit)

        now = time.time()
        if now - self.last_post_time < self.min_post_interval:
            wait = self.min_post_interval - (now - self.last_post_time)
            return {"error": f"Rate limit: wait {wait:.0f}s before next post"}

        data = {
            "sr": subreddit,
            "title": title[:300],
            "kind": "link" if url else "self",
        }
        if url:
            data["url"] = url
        if text:
            data["text"] = text[:10000]

        resp = requests.post(
            f"{API_BASE}/api/submit",
            headers=self._headers(),
            data=data,
            timeout=20,
        )
        if resp.status_code == 200:
            result = resp.json()
            errors = result.get("json", {}).get("errors", [])
            if errors:
                return {"error": str(errors)}
            post_data = result.get("json", {}).get("data", {})
            self.last_post_time = time.time()
            post_url = post_data.get("url", "")
            post_id = post_data.get("id", "")
            log.info(f"Posted to r/{subreddit}: {title[:50]}... id={post_id}")
            return {"status": "posted", "id": post_id, "url": post_url, "subreddit": subreddit}
        return {"error": f"{resp.status_code}: {resp.text[:300]}"}

    def comment(self, post_id, text):
        """Comment on a post. post_id should be full name like t3_xxxxx."""
        if not post_id.startswith("t"):
            post_id = f"t3_{post_id}"

        now = time.time()
        if now - self.last_post_time < self.min_post_interval:
            wait = self.min_post_interval - (now - self.last_post_time)
            return {"error": f"Rate limit: wait {wait:.0f}s before next comment"}

        resp = requests.post(
            f"{API_BASE}/api/comment",
            headers=self._headers(),
            data={"thing_id": post_id, "text": text[:10000]},
            timeout=20,
        )
        if resp.status_code == 200:
            result = resp.json()
            errors = result.get("json", {}).get("errors", [])
            if errors:
                return {"error": str(errors)}
            comment_data = (
                result.get("json", {})
                .get("data", {})
                .get("things", [{}])[0]
                .get("data", {})
            )
            comment_id = comment_data.get("id", "unknown")
            self.last_post_time = time.time()
            log.info(f"Commented on {post_id}: {text[:50]}... id={comment_id}")
            return {"status": "commented", "id": comment_id, "parent": post_id}
        return {"error": f"{resp.status_code}: {resp.text[:300]}"}

    def read(self, subreddit, sort="hot", limit=10):
        """Read posts from a subreddit."""
        subreddit = self._validate_subreddit(subreddit)
        limit = min(int(limit), 25)
        sort = sort if sort in ("hot", "new", "top", "rising") else "hot"

        resp = requests.get(
            f"{API_BASE}/r/{subreddit}/{sort}",
            headers=self._headers(),
            params={"limit": limit},
            timeout=15,
        )
        if resp.status_code != 200:
            return {"error": f"{resp.status_code}: {resp.text[:200]}"}

        posts = []
        for child in resp.json().get("data", {}).get("children", []):
            d = child.get("data", {})
            posts.append({
                "id": d.get("name", ""),
                "title": d.get("title", ""),
                "author": d.get("author", ""),
                "score": d.get("score", 0),
                "comments": d.get("num_comments", 0),
                "url": d.get("url", ""),
                "selftext": (d.get("selftext", "") or "")[:200],
                "created_utc": d.get("created_utc", 0),
            })
        log.info(f"Read {len(posts)} posts from r/{subreddit}/{sort}")
        return {"subreddit": subreddit, "sort": sort, "posts": posts}

    def search(self, query, subreddit=None, limit=10):
        """Search Reddit. Optionally restrict to a subreddit."""
        limit = min(int(limit), 25)
        params = {"q": query, "limit": limit, "sort": "relevance", "t": "month"}

        if subreddit:
            subreddit = self._validate_subreddit(subreddit)
            url = f"{API_BASE}/r/{subreddit}/search"
            params["restrict_sr"] = "true"
        else:
            url = f"{API_BASE}/search"

        resp = requests.get(url, headers=self._headers(), params=params, timeout=15)
        if resp.status_code != 200:
            return {"error": f"{resp.status_code}: {resp.text[:200]}"}

        posts = []
        for child in resp.json().get("data", {}).get("children", []):
            d = child.get("data", {})
            posts.append({
                "id": d.get("name", ""),
                "title": d.get("title", ""),
                "author": d.get("author", ""),
                "subreddit": d.get("subreddit", ""),
                "score": d.get("score", 0),
                "comments": d.get("num_comments", 0),
                "url": d.get("url", ""),
                "selftext": (d.get("selftext", "") or "")[:200],
            })
        log.info(f"Search '{query}': {len(posts)} results" + (f" in r/{subreddit}" if subreddit else ""))
        return {"query": query, "subreddit": subreddit, "posts": posts}


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "test"

    if action == "test":
        client = RedditClient()
        result = client.test()
        print(json.dumps(result, indent=2))

    elif action == "post":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: reddit.py post <subreddit> <title> [text] [url]"}))
            sys.exit(1)
        client = RedditClient()
        subreddit = sys.argv[2]
        title = sys.argv[3]
        text = sys.argv[4] if len(sys.argv) > 4 else None
        url = sys.argv[5] if len(sys.argv) > 5 else None
        result = client.post(subreddit, title, text=text, url=url)
        print(json.dumps(result, indent=2))

    elif action == "comment":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: reddit.py comment <post_id> <text>"}))
            sys.exit(1)
        client = RedditClient()
        result = client.comment(sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2))

    elif action == "read":
        sub = sys.argv[2] if len(sys.argv) > 2 else "SideProject"
        sort = sys.argv[3] if len(sys.argv) > 3 else "hot"
        limit = int(sys.argv[4]) if len(sys.argv) > 4 else 10
        client = RedditClient()
        result = client.read(sub, sort, limit)
        print(json.dumps(result, indent=2))

    elif action == "search":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: reddit.py search <query> [subreddit]"}))
            sys.exit(1)
        query = sys.argv[2]
        sub = sys.argv[3] if len(sys.argv) > 3 else None
        client = RedditClient()
        result = client.search(query, subreddit=sub)
        print(json.dumps(result, indent=2))

    else:
        print(json.dumps({"error": f"Unknown action: {action}. Use: test, post, comment, read, search"}))
        sys.exit(1)
