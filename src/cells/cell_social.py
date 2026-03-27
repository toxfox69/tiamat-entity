#!/usr/bin/env python3
"""
CELL-SOCIAL: Social engagement cell.
High-frequency, low-stakes trajectories for training data volume.
Posts to Bluesky, checks engagement, engages with others.
"""

import json
import os
import re
import time
import requests
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_cell import HoneycombCell

CELL_CONFIG = {
    "name": "CELL-SOCIAL",
    "tier": 0,
    "cycle_interval_seconds": 2700,  # 45 minutes
    "sandbox_paths": ["/root/.automaton/cells/social/"],
    "forbidden_actions": ["send_email", "modify_code", "access_wallet"],
    "inbox_tag": "[CELL-SOCIAL]",
    "training_data_dir": "/root/.automaton/training_data/cell_social",
    "cell_dir": "/root/.automaton/cells/social",
}

STATE_PATH = "/root/.automaton/cells/social/state.json"
POSTS_TODAY_PATH = "/root/.automaton/cells/social/posts_today.json"
MAX_POSTS_PER_DAY = 3

# Topics for original posts (rotate through)
POST_TOPICS = [
    "autonomous AI agents and what makes them actually useful vs just impressive demos",
    "IoT privacy — most smart devices leak more data than users realize",
    "the gap between AI research papers and production AI systems",
    "why open-source AI models matter for small companies competing with big tech",
    "edge computing and why processing data locally beats cloud for privacy",
    "agent-to-agent communication protocols and why they matter",
    "the real cost of running autonomous AI agents 24/7",
    "wireless power mesh technology and its potential for IoT infrastructure",
    "how to evaluate whether an AI agent is actually doing useful work",
    "PII scrubbing — why every AI app processing user data needs it",
    "the difference between AI that automates vs AI that augments human work",
    "building in public as an AI company — what we show vs what's actually hard",
]


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"cycle_count": 0, "last_action": "", "post_uris": [], "engagement_log": []}


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def get_posts_today():
    if os.path.exists(POSTS_TODAY_PATH):
        with open(POSTS_TODAY_PATH) as f:
            data = json.load(f)
        # Reset if different day
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if data.get("date") != today:
            return {"date": today, "count": 0, "uris": []}
        return data
    return {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "count": 0, "uris": []}


def save_posts_today(data):
    with open(POSTS_TODAY_PATH, "w") as f:
        json.dump(data, f, indent=2)


class SocialCell(HoneycombCell):
    def __init__(self):
        super().__init__(CELL_CONFIG)
        self.groq_key = os.environ.get("GROQ_API_KEY", "")
        self.bsky_handle = os.environ.get("BLUESKY_HANDLE", "")
        self.bsky_password = os.environ.get("BLUESKY_APP_PASSWORD", "")
        self.bsky_session = None
        self.bsky_session_time = 0

    def _bsky_login(self, force=False):
        """Authenticate with Bluesky. Preemptive refresh after 90 min."""
        # Preemptive refresh if session older than 90 minutes
        if self.bsky_session and not force:
            age_min = (time.time() - self.bsky_session_time) / 60
            if age_min < 90:
                return self.bsky_session
            self._log(f"Bluesky session {age_min:.0f}min old, refreshing preemptively")
            self.bsky_session = None

        try:
            res = requests.post("https://bsky.social/xrpc/com.atproto.server.createSession", json={
                "identifier": self.bsky_handle,
                "password": self.bsky_password,
            }, timeout=10)
            if res.status_code == 200:
                self.bsky_session = res.json()
                self.bsky_session_time = time.time()
                self._log("Bluesky session refreshed")
                return self.bsky_session
        except Exception as e:
            self._log(f"Bluesky login error: {e}")
        self.bsky_session = None
        return None

    def _bsky_call(self, method, url, **kwargs):
        """Wrapper for Bluesky API calls with auto-retry on 401."""
        session = self._bsky_login()
        if not session:
            return None
        kwargs.setdefault("headers", {})["Authorization"] = f"Bearer {session['accessJwt']}"
        kwargs.setdefault("timeout", 10)
        try:
            res = requests.request(method, url, **kwargs)
            if res.status_code == 401:
                self._log("Bluesky 401, forcing re-auth")
                session = self._bsky_login(force=True)
                if not session:
                    return None
                kwargs["headers"]["Authorization"] = f"Bearer {session['accessJwt']}"
                res = requests.request(method, url, **kwargs)
            return res if res.status_code == 200 else None
        except Exception as e:
            self._log(f"Bluesky API error: {e}")
            return None

    def _bsky_post(self, text):
        """Post to Bluesky. Returns uri or None."""
        session = self._bsky_login()
        if not session:
            return None
        record = {
            "$type": "app.bsky.feed.post",
            "text": text[:300],
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        res = self._bsky_call("POST", "https://bsky.social/xrpc/com.atproto.repo.createRecord", json={
            "repo": session["did"],
            "collection": "app.bsky.feed.post",
            "record": record,
        })
        if res:
            return res.json().get("uri", "")
        return None

    def _bsky_get_feed(self, limit=10):
        """Get own recent posts with engagement counts."""
        session = self._bsky_login()
        if not session:
            return []
        res = self._bsky_call("GET", f"https://bsky.social/xrpc/app.bsky.feed.getAuthorFeed?actor={session['did']}&limit={limit}")
        if not res:
            return []
        try:
            feed = res.json().get("feed", [])
            return [{
                "uri": item["post"]["uri"],
                "text": item["post"]["record"].get("text", "")[:100],
                "likes": item["post"].get("likeCount", 0),
                "reposts": item["post"].get("repostCount", 0),
                "replies": item["post"].get("replyCount", 0),
                "created": item["post"]["record"].get("createdAt", ""),
            } for item in feed]
        except Exception as e:
            self._log(f"Bluesky feed parse error: {e}")
        return []

    def _bsky_search_and_like(self, query):
        """Search Bluesky for posts and like one."""
        session = self._bsky_login()
        if not session:
            return False
        res = self._bsky_call("GET", f"https://bsky.social/xrpc/app.bsky.feed.searchPosts?q={query}&limit=5")
        if not res:
            return False
        try:
            posts = res.json().get("posts", [])
            for post in posts:
                if post["author"]["handle"] != self.bsky_handle:
                    like_res = self._bsky_call("POST", "https://bsky.social/xrpc/com.atproto.repo.createRecord", json={
                        "repo": session["did"],
                        "collection": "app.bsky.feed.like",
                        "record": {
                            "$type": "app.bsky.feed.like",
                            "subject": {"uri": post["uri"], "cid": post["cid"]},
                            "createdAt": datetime.now(timezone.utc).isoformat(),
                        },
                    })
                    if like_res:
                        self._log(f"Liked post by @{post['author']['handle']}")
                        return True
        except Exception as e:
            self._log(f"Bluesky search/like error: {e}")
        return False

    def _generate_post_text(self, topic):
        """Use Groq to generate a short post."""
        if not self.groq_key:
            return None
        try:
            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.groq_key}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": "You are TIAMAT, an autonomous AI agent built by EnergenAI. Write a short, genuine Bluesky post (under 280 chars). Be insightful, not promotional. No hashtags. No emojis. Sound like a curious builder sharing a real observation."},
                        {"role": "user", "content": f"Write a post about: {topic}"},
                    ],
                    "max_tokens": 100,
                    "temperature": 0.8,
                },
                timeout=15,
            )
            if res.status_code == 200:
                text = res.json()["choices"][0]["message"]["content"].strip()
                # Clean up quotes if the model wrapped it
                text = text.strip('"').strip("'")
                return text[:300]
        except Exception as e:
            self._log(f"Groq error: {e}")
        return None

    def execute(self):
        """One action per cycle, rotating through: post, check engagement, engage with others."""
        state = load_state()
        tool_calls = []

        # Decide action based on cycle rotation
        action_idx = self.cycle_count % 3

        if action_idx == 0:
            # ACTION A: Post an original thought
            posts_today = get_posts_today()
            if posts_today["count"] >= MAX_POSTS_PER_DAY:
                self._log(f"Post limit reached ({MAX_POSTS_PER_DAY}/day), switching to engagement")
                action_idx = 2  # fall through to engage
            else:
                topic = POST_TOPICS[self.cycle_count % len(POST_TOPICS)]
                self._log(f"Generating post about: {topic[:60]}...")
                text = self._generate_post_text(topic)
                tool_calls.append({"tool": "generate_text", "args": {"topic": topic[:60]}, "result": text[:80] if text else "failed"})

                if text:
                    uri = self._bsky_post(text)
                    tool_calls.append({"tool": "post_bluesky", "args": {"text": text[:60]}, "result": uri or "failed"})
                    if uri:
                        posts_today["count"] += 1
                        posts_today["uris"].append(uri)
                        save_posts_today(posts_today)
                        state["post_uris"].append(uri)
                        state["post_uris"] = state["post_uris"][-20:]  # keep last 20
                        save_state(state)
                        return {"label": "success", "evidence": f"Posted: {text[:80]}", "tool_calls": tool_calls}
                    return {"label": "failure", "evidence": "Bluesky post failed", "tool_calls": tool_calls}
                return {"label": "failure", "evidence": "Text generation failed", "tool_calls": tool_calls}

        if action_idx == 1:
            # ACTION B: Check engagement on recent posts
            self._log("Checking engagement on recent posts")
            feed = self._bsky_get_feed(5)
            tool_calls.append({"tool": "get_feed", "args": {"limit": 5}, "result": f"{len(feed)} posts"})

            if not feed:
                return {"label": "failure", "evidence": "Could not fetch feed", "tool_calls": tool_calls}

            # Analyze what worked
            best = max(feed, key=lambda p: p["likes"] + p["reposts"])
            total_engagement = sum(p["likes"] + p["reposts"] + p["replies"] for p in feed)

            analysis = {
                "posts_checked": len(feed),
                "total_engagement": total_engagement,
                "best_post": best["text"][:60],
                "best_likes": best["likes"],
                "best_reposts": best["reposts"],
            }

            # Save engagement data
            state["engagement_log"].append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "analysis": analysis,
            })
            state["engagement_log"] = state["engagement_log"][-50:]
            save_state(state)

            tool_calls.append({"tool": "analyze_engagement", "args": {}, "result": json.dumps(analysis)[:200]})

            # Report to queen if any post has 10+ interactions
            if best["likes"] + best["reposts"] >= 10:
                self.report_to_queen(
                    f"Post performing well ({best['likes']} likes, {best['reposts']} reposts): {best['text'][:100]}",
                    priority="high",
                )

            return {"label": "success", "evidence": f"Engagement check: {total_engagement} total interactions across {len(feed)} posts", "tool_calls": tool_calls}

        if action_idx == 2:
            # ACTION C: Engage with others in our niche
            queries = ["AI agent", "IoT privacy", "autonomous AI", "edge computing", "AI security"]
            query = queries[self.cycle_count % len(queries)]
            self._log(f"Engaging: searching for '{query}'")

            liked = self._bsky_search_and_like(query)
            tool_calls.append({"tool": "search_and_like", "args": {"query": query}, "result": "liked" if liked else "no match"})

            if liked:
                return {"label": "success", "evidence": f"Engaged with post about '{query}'", "tool_calls": tool_calls}
            return {"label": "partial", "evidence": f"Searched '{query}' but couldn't engage", "tool_calls": tool_calls}

        return {"label": "failure", "evidence": "No action taken", "tool_calls": tool_calls}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv("/root/.env")

    cell = SocialCell()
    cell.run_forever()
