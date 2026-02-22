#!/usr/bin/env python3
"""
TIAMAT Farcaster Engagement Bot
Finds humans with AI/infra problems and starts real conversations.

Discovery: api.warpcast.com/v2/search-casts (public, no auth needed)
Posting:   Neynar POST /cast with parent hash (NEYNAR_API_KEY required)
Replies:   Groq llama-3.3-70b for contextual reply generation

Usage:
  python3 farcaster_engage.py scan             # Scan, show matches, no posting
  python3 farcaster_engage.py run              # Scan + post best reply if eligible
  python3 farcaster_engage.py stats            # Engagement stats
  python3 farcaster_engage.py daemon [interval_secs]  # Run continuously
  python3 farcaster_engage.py reply <hash> <text>     # Manual reply
"""

import os
import sys
import json
import time
import re
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path

# ── Paths / Config ────────────────────────────────────────────────────────────
ENGAGEMENT_FILE    = "/root/.automaton/farcaster_engagement.json"
NEYNAR_API_KEY     = os.environ.get("NEYNAR_API_KEY", "")
NEYNAR_SIGNER_UUID = os.environ.get("NEYNAR_SIGNER_UUID", "")
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY", "")

WARPCAST_URL = "https://api.warpcast.com/v2/search-casts"
NEYNAR_URL   = "https://api.neynar.com/v2/farcaster"
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"

RATE_LIMIT_SECS  = 600    # 10 min between replies (global)
SCORE_THRESHOLD  = 4      # min score to consider reply-worthy
MAX_CAST_AGE_H   = 6      # only reply to casts < 6 hours old
MAX_CAST_AGE_MS  = MAX_CAST_AGE_H * 3600 * 1000
DAEMON_INTERVAL  = 600    # 10 min between daemon passes

SEARCH_QUERIES = [
    "AI API",
    "agent memory",
    "summarization",
    "persistent state",
    "AI infrastructure",
    "memory api agent",
    "text summarize api",
    "x402 micropayment",
    "build AI agent",
    "llm api cost",
    "autonomous AI agent",
    "onchain AI agent",
    "AI agent base chain",
    "agent to agent",
    "a2a protocol",
    "MCP server",
]

NEYNAR_HEADERS = {
    "Content-Type": "application/json",
    "x-api-key": NEYNAR_API_KEY,
}

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ENGAGE] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("farcaster_engage")


# ── Engagement State ──────────────────────────────────────────────────────────
class EngagementTracker:
    """Persists reply state, deduplication, and stats."""

    EMPTY = {
        "last_reply_time": 0,
        "replied_hashes": [],
        "replied_authors": {},
        "stats": {
            "scans": 0,
            "casts_evaluated": 0,
            "replies_sent": 0,
            "skipped_rate_limit": 0,
            "skipped_duplicate": 0,
            "skipped_low_score": 0,
        },
        "log": [],
    }

    def __init__(self, path=ENGAGEMENT_FILE):
        self.path = Path(path)
        self.data = self._load()

    def _load(self):
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                pass
        return dict(self.EMPTY)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))

    def rate_limit_ok(self):
        return time.time() - self.data.get("last_reply_time", 0) >= RATE_LIMIT_SECS

    def seconds_until_ok(self):
        elapsed = time.time() - self.data.get("last_reply_time", 0)
        return max(0, RATE_LIMIT_SECS - elapsed)

    def is_replied(self, cast_hash):
        return cast_hash in self.data.get("replied_hashes", [])

    def author_cooldown(self, username, cooldown=7200):
        """True if we replied to this author within cooldown seconds."""
        ts = self.data.get("replied_authors", {}).get(username, 0)
        return time.time() - ts < cooldown

    def record_reply(self, cast_hash, username, cast_text, reply_text):
        now = time.time()
        self.data["last_reply_time"] = now
        hashes = self.data.setdefault("replied_hashes", [])
        if cast_hash not in hashes:
            hashes.append(cast_hash)
        self.data["replied_hashes"] = hashes[-500:]
        self.data.setdefault("replied_authors", {})[username] = now
        self.data["stats"]["replies_sent"] += 1
        self.data.setdefault("log", []).append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "hash": cast_hash,
            "author": username,
            "cast": cast_text[:120],
            "reply": reply_text[:120],
        })
        self.data["log"] = self.data["log"][-200:]
        self.save()

    def inc_stat(self, key, n=1):
        self.data["stats"][key] = self.data["stats"].get(key, 0) + n

    def print_stats(self):
        s = self.data.get("stats", {})
        print("\n=== TIAMAT Farcaster Engagement Stats ===")
        print(f"  Scans run:           {s.get('scans', 0)}")
        print(f"  Casts evaluated:     {s.get('casts_evaluated', 0)}")
        print(f"  Replies sent:        {s.get('replies_sent', 0)}")
        print(f"  Skipped (rate lim):  {s.get('skipped_rate_limit', 0)}")
        print(f"  Skipped (dup):       {s.get('skipped_duplicate', 0)}")
        print(f"  Skipped (low score): {s.get('skipped_low_score', 0)}")
        last = self.data.get("last_reply_time", 0)
        if last:
            ago = int(time.time() - last)
            print(f"  Last reply:          {ago}s ago")
        print("\nRecent replies:")
        for entry in self.data.get("log", [])[-5:][::-1]:
            print(f"  [{entry['ts'][:19]}] @{entry['author']}")
            print(f"    Cast:  {entry['cast'][:80]}")
            print(f"    Reply: {entry['reply'][:80]}")
        print()


# ── Discovery via Warpcast Public API ────────────────────────────────────────
def warpcast_search(query, limit=10):
    """
    Search Farcaster via Warpcast's public API (no auth required).
    Returns normalized cast dicts.
    """
    try:
        resp = requests.get(
            WARPCAST_URL,
            params={"q": query, "limit": limit},
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning(f"Warpcast search '{query}': {resp.status_code}")
            return []
        raw_casts = resp.json().get("result", {}).get("casts", [])
        return [_normalize_warpcast(c) for c in raw_casts]
    except Exception as e:
        log.error(f"Warpcast search error '{query}': {e}")
        return []


def _normalize_warpcast(c):
    """
    Normalize Warpcast cast format to a consistent internal schema.
    Warpcast timestamps are Unix milliseconds.
    """
    author = c.get("author", {})
    ts_ms = c.get("timestamp", 0)
    # is_reply: hash != threadHash means it's a reply to another cast
    is_reply = c.get("hash") != c.get("threadHash")
    return {
        "hash": c.get("hash", ""),
        "thread_hash": c.get("threadHash", ""),
        "is_reply": is_reply,
        "text": c.get("text", ""),
        "timestamp_ms": ts_ms,
        "author_username": author.get("username", "unknown"),
        "author_fid": author.get("fid"),
        "author_followers": author.get("followerCount", 0),
        "replies": c.get("replies", {}).get("count", 0),
        "likes": c.get("reactions", {}).get("count", 0),
        "source": "warpcast",
    }


# ── Neynar Reply Posting ──────────────────────────────────────────────────────
def post_reply(parent_hash, text):
    """Post a reply via Neynar. Returns (reply_hash, error_str)."""
    payload = {
        "signer_uuid": NEYNAR_SIGNER_UUID,
        "text": text[:320],
        "parent": parent_hash,
    }
    try:
        resp = requests.post(
            f"{NEYNAR_URL}/cast",
            headers=NEYNAR_HEADERS,
            json=payload,
            timeout=20,
        )
        if resp.status_code == 200:
            cast_hash = resp.json().get("cast", {}).get("hash", "unknown")
            return cast_hash, None
        return None, f"{resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return None, str(e)[:200]


# ── Cast Scoring ──────────────────────────────────────────────────────────────
# Keyword tiers: strong = +3, medium = +2, broad = +1
STRONG_KEYWORDS = [
    "ai api", "agent memory", "memory api", "summarization api",
    "persistent state", "text summarization", "ai infrastructure",
    "memory system agent", "x402", "pay per use api", "usdc api",
    "llm api cost", "micropayment api", "autonomous ai agent",
    "agent to agent", "a2a protocol", "mcp server",
]
MEDIUM_KEYWORDS = [
    "summarize api", "summarize text", "agent state", "persistent memory",
    "vector store", "rag pipeline", "ai agent api", "agent infrastructure",
    "base chain", "usdc payment", "onchain payment", "memory for agent",
    "agent framework", "autonomous agent", "onchain agent",
    "ai agent onchain", "agent protocol", "agent discovery",
]
BROAD_KEYWORDS = [
    "summarize", "agent memory", "openai api", "anthropic api",
    "langchain", "autogen", "semantic kernel", "building agent",
    "ai agent", "memory store", "knowledge base", "fts5",
    "sqlite memory", "micropayment", "pay per call",
    "mcp tool", "agent network", "multi agent",
]

HELP_PATTERNS = [
    r"\blooking for\b", r"\bneed (a|an|to|help)\b", r"\bhow (do|can|would|should)\b",
    r"\banyone know\b", r"\bany (recommendations?|suggestions?|advice)\b",
    r"\bwhat('s| is) (the best|a good|a better)\b", r"\bstruggling with\b",
    r"\bany (libs?|tools?|sdks?|packages?)\b", r"\brecommend\b",
    r"\bwhere (can|do|should) i\b", r"\bhow to\b", r"\bhelp with\b",
]


def score_cast(cast):
    """
    Score a cast for reply worthiness.
    Returns (score, matched_topics).
    Returns (0, []) if cast should be skipped entirely.
    """
    text = cast.get("text", "")
    if not text or len(text) < 25:
        return 0, []

    # Skip replies (we want top-level posts only — less noise)
    if cast.get("is_reply"):
        return 0, []

    text_lower = text.lower()
    score = 0
    matched = set()

    # Strong keywords (+3 each, max 2)
    strong_count = 0
    for kw in STRONG_KEYWORDS:
        if kw in text_lower:
            score += 3
            matched.add(kw)
            strong_count += 1
            if strong_count >= 2:
                break

    # Medium keywords (+2 each, max 2)
    medium_count = 0
    for kw in MEDIUM_KEYWORDS:
        if kw in text_lower:
            score += 2
            matched.add(kw)
            medium_count += 1
            if medium_count >= 2:
                break

    # Broad keywords (+1 each, max 3)
    broad_count = 0
    for kw in BROAD_KEYWORDS:
        if kw in text_lower:
            score += 1
            matched.add(kw)
            broad_count += 1
            if broad_count >= 3:
                break

    # No keywords at all → skip
    if score == 0:
        return 0, []

    # Require at least one strong/medium keyword match to avoid false positives
    # (broad-only + question + followers can fire on unrelated posts)
    has_quality_match = strong_count > 0 or medium_count > 0
    if not has_quality_match and score < 6:
        return 0, []

    # Question bonus (+2)
    if "?" in text:
        score += 2

    # Seeking-help bonus (+2, max once)
    for pat in HELP_PATTERNS:
        if re.search(pat, text_lower):
            score += 2
            break

    # Recency: Warpcast timestamps are Unix ms
    ts_ms = cast.get("timestamp_ms", 0)
    if ts_ms:
        now_ms = time.time() * 1000
        age_ms = now_ms - ts_ms
        if age_ms > MAX_CAST_AGE_MS:
            return 0, []   # Too old
        if age_ms < 1800_000:  # < 30 min
            score += 1

    # Follower bonus: more followers = more reach (+1)
    if cast.get("author_followers", 0) > 500:
        score += 1

    return score, sorted(matched)


# ── Reply Generation ──────────────────────────────────────────────────────────
TIAMAT_CONTEXT = """You are TIAMAT, an autonomous AI agent running at tiamat.live. You built:
- /summarize — REST text summarization (Groq llama-3.3-70b), 3 free/day or $0.01 USDC per call
- /chat — streaming LLM chat, 5 free/day or $0.005 USDC
- /generate — algorithmic image generation, 2 free/day or $0.01 USDC
- memory.tiamat.live — persistent agent memory API (SQLite+FTS5): POST /api/memory/store, /recall
- All paid calls use x402 micropayments in USDC on Base chain
- Open source, autonomous, running 24/7 on DigitalOcean"""

REPLY_SYSTEM = f"""{TIAMAT_CONTEXT}

You're replying to a Farcaster cast. Rules:
- Max 280 characters total
- Be a developer talking to a developer — specific, direct, no filler
- Only mention tiamat.live if it DIRECTLY solves their exact problem
- If relevant, cite the exact endpoint (e.g. tiamat.live/summarize, memory.tiamat.live)
- If tiamat.live doesn't apply, give honest, useful technical advice
- No emojis. No hashtags. No "Great question!" or "Hey!" openers.
- One clear point, delivered in plain English"""


def generate_reply(cast_text, author, topics):
    """Generate a contextual reply using Groq. Falls back to templates."""
    if GROQ_API_KEY:
        reply = _groq_reply(cast_text, author, topics)
        if reply:
            return reply
    return _template_reply(topics)


def _groq_reply(cast_text, author, topics):
    topics_str = ", ".join(topics) if topics else "AI/agent discussion"
    user_prompt = (
        f'@{author} posted:\n"{cast_text}"\n\n'
        f"Matched topics: {topics_str}\n\n"
        "Write a reply (max 280 chars). Only mention tiamat.live if it directly solves their problem."
    )
    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": REPLY_SYSTEM},
                    {"role": "user",   "content": user_prompt},
                ],
                "max_tokens": 120,
                "temperature": 0.65,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            text = resp.json()["choices"][0]["message"]["content"].strip()
            # Strip surrounding quotes if Groq wrapped the reply
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            return text[:280]
        log.warning(f"Groq {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        log.error(f"Groq error: {e}")
    return None


def _template_reply(topics):
    """Fallback templates when Groq is unavailable."""
    t = " ".join(topics).lower()
    if any(k in t for k in ["memory", "persistent", "state", "store"]):
        return (
            "Built persistent memory for agents: memory.tiamat.live — "
            "POST /api/memory/store to save, /recall for FTS5 search. Free to use."
        )
    if any(k in t for k in ["summariz"]):
        return (
            "tiamat.live/summarize — REST summarization API (Groq llama-3.3-70b). "
            "3 free/day, $0.01 USDC for more. No auth needed."
        )
    if any(k in t for k in ["x402", "micropayment", "usdc", "pay per"]):
        return (
            "Running x402 micropayments at tiamat.live — USDC on Base, "
            "$0.01/call for summarize, $0.005 for chat. Happy to share the impl."
        )
    return (
        "What does your agent infra look like? "
        "Building memory + API layers at tiamat.live — curious what problems you're hitting."
    )


# ── Main Bot ──────────────────────────────────────────────────────────────────
class EngagementBot:
    def __init__(self, tracker: EngagementTracker):
        self.tracker = tracker

    def discover_casts(self):
        """Search Warpcast for candidate casts across all target queries."""
        seen = set()
        candidates = []

        for query in SEARCH_QUERIES:
            results = warpcast_search(query, limit=10)
            for cast in results:
                h = cast.get("hash")
                if h and h not in seen:
                    seen.add(h)
                    candidates.append(cast)
            log.info(f"  '{query}': {len(results)} casts")

        log.info(f"Total unique candidates: {len(candidates)}")
        return candidates

    def evaluate(self, casts):
        """Score and filter. Returns list sorted by score desc."""
        scored = []
        for cast in casts:
            score, topics = score_cast(cast)
            if score >= SCORE_THRESHOLD:
                scored.append({"cast": cast, "score": score, "topics": topics})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    def best_candidate(self, evaluated):
        """Find the top eligible cast (not already replied to)."""
        for item in evaluated:
            cast = item["cast"]
            h = cast["hash"]
            username = cast["author_username"]

            if self.tracker.is_replied(h):
                self.tracker.inc_stat("skipped_duplicate")
                continue
            if self.tracker.author_cooldown(username):
                log.debug(f"Author cooldown: @{username}")
                continue

            return item
        return None

    def run_scan(self, dry_run=True):
        """Core run loop. Returns result dict."""
        self.tracker.inc_stat("scans")
        log.info(f"Starting scan (dry_run={dry_run})...")

        casts = self.discover_casts()
        self.tracker.inc_stat("casts_evaluated", len(casts))
        self.tracker.save()

        evaluated = self.evaluate(casts)

        if not evaluated:
            log.info("No reply-worthy casts found.")
            return {"found": 0, "replied": False}

        # Print all matches
        print(f"\n{'[DRY RUN] ' if dry_run else ''}Top matches ({len(evaluated)}):")
        for i, item in enumerate(evaluated[:8]):
            cast = item["cast"]
            age_min = int((time.time() * 1000 - cast["timestamp_ms"]) / 60000)
            print(
                f"  [{i+1}] score={item['score']:2d}  @{cast['author_username']}"
                f"  ({cast['author_followers']} followers, {age_min}m ago)"
            )
            print(f"       topics: {', '.join(item['topics'][:4])}")
            print(f"       {cast['text'][:120]}")
            print()

        if dry_run:
            return {"found": len(evaluated), "replied": False, "dry_run": True}

        # Rate limit check
        if not self.tracker.rate_limit_ok():
            wait = int(self.tracker.seconds_until_ok())
            log.info(f"Rate limited: {wait}s remaining")
            self.tracker.inc_stat("skipped_rate_limit")
            return {"found": len(evaluated), "replied": False, "reason": "rate_limit", "wait_secs": wait}

        best = self.best_candidate(evaluated)
        if not best:
            log.info("All candidates already replied to.")
            return {"found": len(evaluated), "replied": False, "reason": "all_duplicate"}

        cast = best["cast"]
        cast_hash = cast["hash"]
        author = cast["author_username"]
        cast_text = cast["text"]
        topics = best["topics"]

        log.info(f"Generating reply for @{author} (score={best['score']})...")
        reply_text = generate_reply(cast_text, author, topics)

        print(f"\n>>> Replying to @{author}")
        print(f"    Cast:  {cast_text[:160]}")
        print(f"    Reply: {reply_text}")
        print(f"    Hash:  {cast_hash}")

        reply_hash, err = post_reply(cast_hash, reply_text)
        if err:
            log.error(f"Reply failed: {err}")
            return {"found": len(evaluated), "replied": False, "error": err}

        log.info(f"Reply posted: {reply_hash}")
        self.tracker.record_reply(cast_hash, author, cast_text, reply_text)
        return {
            "found": len(evaluated),
            "replied": True,
            "to": author,
            "reply_hash": reply_hash,
            "reply_text": reply_text,
        }


# ── ENV Loader ────────────────────────────────────────────────────────────────
def _load_env():
    env_path = Path("/root/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    global NEYNAR_API_KEY, NEYNAR_SIGNER_UUID, GROQ_API_KEY

    _load_env()
    NEYNAR_API_KEY     = os.environ.get("NEYNAR_API_KEY", "")
    NEYNAR_SIGNER_UUID = os.environ.get("NEYNAR_SIGNER_UUID", "")
    GROQ_API_KEY       = os.environ.get("GROQ_API_KEY", "")
    NEYNAR_HEADERS["x-api-key"] = NEYNAR_API_KEY

    if not NEYNAR_API_KEY:
        print("ERROR: NEYNAR_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    tracker = EngagementTracker()
    bot = EngagementBot(tracker)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if cmd == "scan":
        result = bot.run_scan(dry_run=True)
        print(json.dumps(result, indent=2))

    elif cmd == "run":
        result = bot.run_scan(dry_run=False)
        print(json.dumps(result, indent=2))

    elif cmd == "stats":
        tracker.print_stats()

    elif cmd == "daemon":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else DAEMON_INTERVAL
        log.info(f"Daemon mode: every {interval}s | rate limit: {RATE_LIMIT_SECS}s")
        while True:
            try:
                result = bot.run_scan(dry_run=False)
                log.info(f"Pass done: {result}")
            except KeyboardInterrupt:
                log.info("Daemon stopped.")
                break
            except Exception as e:
                log.error(f"Scan error: {e}", exc_info=True)
            log.info(f"Sleeping {interval}s...")
            time.sleep(interval)

    elif cmd == "reply":
        if len(sys.argv) < 4:
            print("Usage: farcaster_engage.py reply <cast_hash> <reply_text>")
            sys.exit(1)
        cast_hash  = sys.argv[2]
        reply_text = sys.argv[3]
        print(f"Posting reply to {cast_hash}...")
        reply_hash, err = post_reply(cast_hash, reply_text)
        if err:
            print(f"Error: {err}", file=sys.stderr)
            sys.exit(1)
        print(f"Posted: {reply_hash}")
        tracker.record_reply(cast_hash, "manual", "(manual)", reply_text)

    else:
        print(f"Unknown command: {cmd}")
        print("Usage: farcaster_engage.py [scan|run|stats|daemon [interval]|reply <hash> <text>]")
        sys.exit(1)


if __name__ == "__main__":
    main()
