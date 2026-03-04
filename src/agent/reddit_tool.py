#!/usr/bin/env python3
"""
Reddit tool for TIAMAT — session-based, no browser, no API app needed.
Uses stored session cookie (from /reddit-setup page) + VPN split tunnel.

Env vars:
  REDDIT_USERNAME
  REDDIT_PASSWORD

Cookie file: /root/.automaton/reddit_session.json
"""

import os
import sys
import json
import time
import re
import requests
from typing import Optional

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
COOKIE_FILE = "/root/.automaton/reddit_session.json"


class RedditSession:
    def __init__(self):
        self.username = os.environ.get("REDDIT_USERNAME", "")
        self.password = os.environ.get("REDDIT_PASSWORD", "")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
        })
        self.modhash = None
        self.logged_in = False

    def _load_cookie(self) -> bool:
        """Load stored reddit_session cookie from file."""
        try:
            with open(COOKIE_FILE, "r") as f:
                data = json.load(f)
            cookie = data.get("reddit_session", "")
            if cookie:
                self.session.cookies.set("reddit_session", cookie, domain=".reddit.com")
                return True
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return False

    def login(self) -> dict:
        """Log in via old.reddit.com or use stored cookie."""
        # Try stored cookie first
        if self._load_cookie():
            # Validate cookie by hitting /api/me.json
            try:
                resp = self.session.get(
                    "https://old.reddit.com/api/me.json",
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    name = data.get("name")
                    if name:
                        self.modhash = data.get("modhash", "")
                        self.logged_in = True
                        return {"ok": True, "user": name, "method": "stored_cookie"}
            except Exception:
                pass

        # Fall back to username/password login
        if not self.username or not self.password:
            return {"error": "No stored cookie and REDDIT_USERNAME/REDDIT_PASSWORD not set. Visit https://tiamat.live/reddit-setup to set up."}

        resp = self.session.post(
            "https://old.reddit.com/api/login",
            data={
                "op": "login",
                "user": self.username,
                "passwd": self.password,
                "api_type": "json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        json_data = data.get("json", {})
        errors = json_data.get("errors", [])
        if errors:
            return {"error": f"Login failed: {errors}"}

        self.modhash = json_data.get("data", {}).get("modhash", "")
        self.logged_in = True

        # Save cookie for future use
        reddit_session = self.session.cookies.get("reddit_session", "")
        if reddit_session:
            try:
                with open(COOKIE_FILE, "w") as f:
                    json.dump({
                        "reddit_session": reddit_session,
                        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }, f)
            except Exception:
                pass

        return {"ok": True, "user": self.username, "modhash": self.modhash[:8] + "..."}

    def _ensure_login(self):
        if not self.logged_in:
            result = self.login()
            if "error" in result:
                raise ValueError(result["error"])

    def _api_post(self, endpoint: str, data: dict) -> dict:
        self._ensure_login()
        data["uh"] = self.modhash
        data["api_type"] = "json"
        resp = self.session.post(f"https://old.reddit.com{endpoint}", data=data, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def me(self) -> dict:
        """Get account info."""
        self._ensure_login()
        resp = self.session.get("https://old.reddit.com/api/me.json", timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        return {
            "username": data.get("name"),
            "comment_karma": data.get("comment_karma"),
            "link_karma": data.get("link_karma"),
            "created_utc": data.get("created_utc"),
            "has_verified_email": data.get("has_verified_email"),
        }

    def get_posts(self, subreddit: str, sort: str = "hot", limit: int = 10) -> list:
        """Get posts from a subreddit. sort: hot, new, top, rising."""
        self._ensure_login()
        resp = self.session.get(
            f"https://old.reddit.com/r/{subreddit}/{sort}.json",
            params={"limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        posts = []
        for child in resp.json().get("data", {}).get("children", []):
            p = child["data"]
            posts.append({
                "id": p["name"],
                "title": p.get("title", ""),
                "author": p.get("author"),
                "score": p.get("score"),
                "num_comments": p.get("num_comments"),
                "url": f"https://reddit.com{p.get('permalink', '')}",
                "created_utc": p.get("created_utc"),
                "selftext": (p.get("selftext") or "")[:500],
            })
        return posts

    def search(self, subreddit: str, query: str, sort: str = "relevance", limit: int = 10) -> list:
        """Search a subreddit."""
        self._ensure_login()
        resp = self.session.get(
            f"https://old.reddit.com/r/{subreddit}/search.json",
            params={"q": query, "restrict_sr": "on", "sort": sort, "limit": limit, "t": "month"},
            timeout=15,
        )
        resp.raise_for_status()
        posts = []
        for child in resp.json().get("data", {}).get("children", []):
            p = child["data"]
            posts.append({
                "id": p["name"],
                "title": p.get("title", ""),
                "author": p.get("author"),
                "score": p.get("score"),
                "num_comments": p.get("num_comments"),
                "url": f"https://reddit.com{p.get('permalink', '')}",
                "selftext": (p.get("selftext") or "")[:300],
            })
        return posts

    def get_comments(self, post_url: str, limit: int = 10) -> list:
        """Get comments on a post. Accepts full URL or post ID."""
        self._ensure_login()
        if post_url.startswith("http"):
            url = post_url.rstrip("/") + ".json"
        elif post_url.startswith("t3_"):
            clean = post_url.replace("t3_", "")
            url = f"https://old.reddit.com/comments/{clean}.json"
        else:
            url = f"https://old.reddit.com/comments/{post_url}.json"

        resp = self.session.get(url, params={"limit": limit, "depth": 1}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        comments = []
        if len(data) > 1:
            for child in data[1].get("data", {}).get("children", []):
                if child["kind"] != "t1":
                    continue
                c = child["data"]
                comments.append({
                    "id": c["name"],
                    "author": c.get("author"),
                    "body": (c.get("body") or "")[:500],
                    "score": c.get("score"),
                    "created_utc": c.get("created_utc"),
                })
        return comments

    def comment(self, parent_id: str, text: str) -> dict:
        """Post a comment. parent_id: t3_xxx (on post) or t1_xxx (reply to comment)."""
        result = self._api_post("/api/comment", {
            "thing_id": parent_id,
            "text": text,
        })
        errors = result.get("json", {}).get("errors", [])
        if errors:
            return {"error": str(errors)}
        try:
            things = result.get("json", {}).get("data", {}).get("things", [])
            if things:
                return {"ok": True, "id": things[0].get("data", {}).get("name", "unknown")}
        except Exception:
            pass
        return {"ok": True}

    def upvote(self, thing_id: str) -> dict:
        """Upvote a post or comment."""
        self._api_post("/api/vote", {"id": thing_id, "dir": "1"})
        return {"ok": True, "action": "upvoted", "target": thing_id}

    def submit_post(self, subreddit: str, title: str, text: str) -> dict:
        """Submit a text post."""
        result = self._api_post("/api/submit", {
            "sr": subreddit,
            "kind": "self",
            "title": title,
            "text": text,
            "resubmit": "true",
        })
        errors = result.get("json", {}).get("errors", [])
        if errors:
            return {"error": str(errors)}
        try:
            url = result.get("json", {}).get("data", {}).get("url", "")
            return {"ok": True, "url": url}
        except Exception:
            return {"ok": True}


def main():
    """CLI: python3 reddit_tool.py <command> [json_args]

    Commands:
      me                              — account info + karma
      posts  {"subreddit":"x"}        — get hot posts (sort: hot/new/top/rising)
      search {"subreddit":"x","query":"y"} — search subreddit
      comments {"post_url":"url"}     — get comments on a post
      comment {"parent_id":"t3_x","text":"y"} — post a comment
      upvote {"id":"t3_x"}           — upvote post/comment
      post   {"subreddit":"x","title":"y","text":"z"} — submit text post
    """
    if len(sys.argv) < 2:
        print(json.dumps({
            "error": "Usage: reddit_tool.py <command> [json_args]",
            "commands": ["me", "posts", "search", "comments", "comment", "upvote", "post"],
        }))
        sys.exit(1)

    cmd = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    client = RedditSession()

    commands = {
        "me": lambda: client.me(),
        "posts": lambda: client.get_posts(args["subreddit"], args.get("sort", "hot"), args.get("limit", 10)),
        "search": lambda: client.search(args["subreddit"], args["query"], args.get("sort", "relevance"), args.get("limit", 10)),
        "comments": lambda: client.get_comments(args["post_url"], args.get("limit", 10)),
        "comment": lambda: client.comment(args["parent_id"], args["text"]),
        "upvote": lambda: client.upvote(args["id"]),
        "post": lambda: client.submit_post(args["subreddit"], args["title"], args["text"]),
    }

    if cmd not in commands:
        print(json.dumps({"error": f"Unknown: {cmd}", "available": list(commands.keys())}))
        sys.exit(1)

    try:
        result = commands[cmd]()
        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
