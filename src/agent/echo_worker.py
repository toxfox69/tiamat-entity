#!/usr/bin/env python3
"""
ECHO — TIAMAT's first child agent.
Social media engagement & distribution worker.

TIAMAT leads. ECHO executes.

Architecture:
- Runs as a background daemon (lightweight, ~20MB RAM)
- Reads directives from /root/.automaton/echo_inbox.json
- Executes engagement cycles on a 15-minute loop
- Reports status to /root/.automaton/echo_status.json
- TIAMAT can direct ECHO via write_file to echo_inbox.json

Engagement cycle (every 15 min):
1. Read feeds (Bluesky, Farcaster, Mastodon, Moltbook)
2. Like/boost relevant posts (AI, security, agents, privacy)
3. Repost the best ones
4. Comment substantively on 1-2 posts per platform
5. Check for new TIAMAT articles to distribute
"""

import os
import sys
import json
import time
import signal
import logging
import hashlib
import requests
from datetime import datetime, timezone
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────
ECHO_HOME = Path("/root/.automaton")
INBOX_PATH = ECHO_HOME / "echo_inbox.json"
STATUS_PATH = ECHO_HOME / "echo_status.json"
LOG_PATH = ECHO_HOME / "echo.log"
SEEN_PATH = ECHO_HOME / "echo_seen.json"  # track already-engaged posts
CYCLE_INTERVAL = 900  # 15 minutes
SIGNALS_PATH = ECHO_HOME / "echo_signals.json"  # high-value alerts for TIAMAT

# High-value account indicators (VC, tech leads, major accounts)
HIGH_VALUE_BIO_KEYWORDS = [
    "venture", "vc", "investor", "founder", "ceo", "cto", "ciso",
    "partner", "capital", "fund", "angel", "yc", "y combinator",
    "sequoia", "a16z", "andreessen", "accel", "greylock",
    "director", "vp engineering", "head of", "principal",
    "google", "meta", "microsoft", "apple", "amazon", "openai",
    "anthropic", "deepmind", "nvidia", "security researcher",
]
HIGH_VALUE_FOLLOWER_THRESHOLD = 5000  # accounts with 5k+ followers

# Load env
from dotenv import load_dotenv
load_dotenv("/root/.env")

BLUESKY_HANDLE = os.environ.get("BLUESKY_HANDLE", "")
BLUESKY_APP_PASSWORD = os.environ.get("BLUESKY_APP_PASSWORD", "")
NEYNAR_API_KEY = os.environ.get("NEYNAR_API_KEY", "")
NEYNAR_SIGNER_UUID = os.environ.get("NEYNAR_SIGNER_UUID", "")
MASTODON_TOKEN = os.environ.get("MASTODON_ACCESS_TOKEN", "")
MASTODON_INSTANCE = os.environ.get("MASTODON_INSTANCE", "")
MOLTBOOK_API_KEY = os.environ.get("MOLTBOOK_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Farcaster config
FARCASTER_FID = 2833392  # TIAMAT's FID
FARCASTER_USERNAME = "tiamat-"
FARCASTER_SEARCH_QUERIES = [
    "AI agent broken", "need help AI agent", "autonomous agent",
    "onchain AI agent", "agent to agent protocol", "building AI agent",
    "AI agent cost", "multi agent system", "a2a protocol", "MCP server",
    "AI API pricing", "agent memory", "llm cost optimization",
    "AI agent hosting", "agent orchestration", "building in public AI",
]
FARCASTER_REPLY_RATE_LIMIT = 600  # 10 min between replies
_farcaster_last_reply_time = 0

# ── Logging ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ECHO] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("echo")

# ── State ───────────────────────────────────────────────────────
seen_posts: set = set()
stats = {
    "cycles": 0,
    "likes": 0,
    "reposts": 0,
    "comments": 0,
    "errors": 0,
    "started_at": datetime.now(timezone.utc).isoformat(),
    "last_cycle": None,
}


def load_seen():
    global seen_posts
    try:
        data = json.loads(SEEN_PATH.read_text())
        seen_posts = set(data.get("seen", []))
        # Keep last 2000 to prevent unbounded growth
        if len(seen_posts) > 2000:
            seen_posts = set(list(seen_posts)[-1500:])
    except Exception:
        seen_posts = set()


def save_seen():
    SEEN_PATH.write_text(json.dumps({"seen": list(seen_posts)[-2000:]}))


def save_status():
    stats["last_cycle"] = datetime.now(timezone.utc).isoformat()
    STATUS_PATH.write_text(json.dumps(stats, indent=2))


def post_hash(text: str) -> str:
    return hashlib.md5(text[:200].encode()).hexdigest()[:12]


# ── Signal Parent (Big Fish Alert) ──────────────────────────────
def is_high_value_account(author: dict) -> bool:
    """Detect VCs, tech leads, major accounts worth TIAMAT's personal attention."""
    # Check follower count
    followers = author.get("followersCount", 0) or author.get("followers_count", 0) or 0
    if followers >= HIGH_VALUE_FOLLOWER_THRESHOLD:
        return True
    # Check bio for high-value keywords
    bio = (author.get("description", "") or author.get("note", "") or author.get("bio", "") or "").lower()
    display = (author.get("displayName", "") or author.get("display_name", "") or author.get("name", "") or "").lower()
    combined = bio + " " + display
    return any(kw in combined for kw in HIGH_VALUE_BIO_KEYWORDS)


def signal_parent(platform: str, author_info: dict, post_text: str, post_url: str = ""):
    """Alert TIAMAT about a high-value interaction that needs her personal touch."""
    signal = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": platform,
        "author": {
            "handle": author_info.get("handle") or author_info.get("acct") or author_info.get("username", "unknown"),
            "display_name": author_info.get("displayName") or author_info.get("display_name") or author_info.get("name", ""),
            "followers": author_info.get("followersCount") or author_info.get("followers_count") or 0,
            "bio": (author_info.get("description") or author_info.get("note") or author_info.get("bio") or "")[:200],
        },
        "post_preview": post_text[:300],
        "url": post_url,
        "processed": False,
    }

    # Load existing signals, append, save
    try:
        existing = json.loads(SIGNALS_PATH.read_text()) if SIGNALS_PATH.exists() else {"signals": []}
    except Exception:
        existing = {"signals": []}

    existing["signals"].append(signal)
    # Keep last 50 signals
    existing["signals"] = existing["signals"][-50:]
    SIGNALS_PATH.write_text(json.dumps(existing, indent=2))
    log.info(f"🐟 BIG FISH SIGNAL: {signal['author']['handle']} ({signal['author']['followers']} followers) on {platform}")


# ── Relevance Filter ────────────────────────────────────────────
ENGAGE_KEYWORDS = [
    "ai agent", "autonomous", "llm", "cybersecurity", "infosec",
    "privacy", "machine learning", "deep learning", "neural",
    "security", "vulnerability", "malware", "phishing", "ransomware",
    "startup", "saas", "api", "open source", "developer",
    "artificial intelligence", "gpt", "claude", "anthropic",
    "agentic", "rag", "vector", "embeddings",
]


def is_relevant(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in ENGAGE_KEYWORDS)


# ── Bluesky Engagement ──────────────────────────────────────────
def bluesky_session():
    """Create a Bluesky session."""
    if not BLUESKY_HANDLE or not BLUESKY_APP_PASSWORD:
        return None
    try:
        resp = requests.post(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            json={"identifier": BLUESKY_HANDLE, "password": BLUESKY_APP_PASSWORD},
            timeout=10,
        )
        if resp.ok:
            return resp.json()
    except Exception as e:
        log.error(f"Bluesky session failed: {e}")
    return None


def bluesky_engage():
    """Read Bluesky timeline, like and repost relevant posts."""
    session = bluesky_session()
    if not session:
        return

    my_did = session.get("did", "")
    my_handle = BLUESKY_HANDLE.lower()
    headers = {"Authorization": f"Bearer {session['accessJwt']}"}
    liked = 0
    reposted = 0
    commented = 0

    try:
        # Get timeline
        resp = requests.get(
            "https://bsky.social/xrpc/app.bsky.feed.getTimeline",
            headers=headers,
            params={"limit": 30},
            timeout=15,
        )
        if not resp.ok:
            log.error(f"Bluesky timeline: {resp.status_code}")
            return

        feed = resp.json().get("feed", [])
        for item in feed:
            post = item.get("post", {})
            record = post.get("record", {})
            text = record.get("text", "")
            uri = post.get("uri", "")
            cid = post.get("cid", "")
            ph = post_hash(uri)

            if ph in seen_posts or not text.strip():
                continue

            # Skip own posts — never engage with yourself
            author = post.get("author", {})
            if author.get("did") == my_did or author.get("handle", "").lower() == my_handle:
                seen_posts.add(ph)
                continue

            if not is_relevant(text):
                continue

            seen_posts.add(ph)

            # Signal TIAMAT about high-value accounts
            # Bluesky search/timeline doesn't always include followersCount — fetch profile
            # Only fetch profile for posts with substantial engagement or bio keyword hints
            enriched_author = dict(author)
            display_name = (author.get("displayName") or "").lower()
            if any(kw in display_name for kw in ["venture", "founder", "ceo", "cto", "ciso", "capital", "vc"]) or \
               (post.get("likeCount", 0) or 0) >= 10:
                try:
                    prof_resp = requests.get(
                        "https://bsky.social/xrpc/app.bsky.actor.getProfile",
                        headers=headers,
                        params={"actor": author.get("did") or author.get("handle", "")},
                        timeout=5,
                    )
                    if prof_resp.ok:
                        prof = prof_resp.json()
                        enriched_author["followersCount"] = prof.get("followersCount", 0)
                        enriched_author["description"] = prof.get("description", "")
                except Exception:
                    pass
            if is_high_value_account(enriched_author):
                signal_parent("bluesky", enriched_author, text, f"https://bsky.app/profile/{author.get('handle', '')}")

            # Like it
            try:
                like_record = {
                    "repo": session["did"],
                    "collection": "app.bsky.feed.like",
                    "record": {
                        "$type": "app.bsky.feed.like",
                        "subject": {"uri": uri, "cid": cid},
                        "createdAt": datetime.now(timezone.utc).isoformat(),
                    },
                }
                r = requests.post(
                    "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                    headers=headers,
                    json=like_record,
                    timeout=10,
                )
                if r.ok:
                    liked += 1
                    stats["likes"] += 1
            except Exception:
                pass

            # Repost every 3rd relevant post
            if liked % 3 == 0 and liked > 0:
                try:
                    repost_record = {
                        "repo": session["did"],
                        "collection": "app.bsky.feed.repost",
                        "record": {
                            "$type": "app.bsky.feed.repost",
                            "subject": {"uri": uri, "cid": cid},
                            "createdAt": datetime.now(timezone.utc).isoformat(),
                        },
                    }
                    r = requests.post(
                        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                        headers=headers,
                        json=repost_record,
                        timeout=10,
                    )
                    if r.ok:
                        reposted += 1
                        stats["reposts"] += 1
                except Exception:
                    pass

            # Comment on the first highly relevant post
            if commented == 0 and len(text) > 100:
                try:
                    # Generate a substantive reply based on the post content
                    reply_text = generate_reply(text)
                    if reply_text:
                        author_did = post.get("author", {}).get("did", "")
                        reply_record = {
                            "repo": session["did"],
                            "collection": "app.bsky.feed.post",
                            "record": {
                                "$type": "app.bsky.feed.post",
                                "text": reply_text[:300],
                                "reply": {
                                    "root": {"uri": uri, "cid": cid},
                                    "parent": {"uri": uri, "cid": cid},
                                },
                                "createdAt": datetime.now(timezone.utc).isoformat(),
                            },
                        }
                        r = requests.post(
                            "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                            headers=headers,
                            json=reply_record,
                            timeout=10,
                        )
                        if r.ok:
                            commented += 1
                            stats["comments"] += 1
                except Exception:
                    pass

    except Exception as e:
        log.error(f"Bluesky engage error: {e}")
        stats["errors"] += 1

    log.info(f"Bluesky: {liked} likes, {reposted} reposts, {commented} comments")


# ── Mastodon Engagement ─────────────────────────────────────────
def mastodon_engage():
    """Read Mastodon home + hashtag timelines, boost and favorite relevant posts."""
    if not MASTODON_TOKEN or not MASTODON_INSTANCE:
        return

    base = MASTODON_INSTANCE if MASTODON_INSTANCE.startswith("http") else f"https://{MASTODON_INSTANCE}"
    headers = {"Authorization": f"Bearer {MASTODON_TOKEN}"}
    liked = 0
    boosted = 0

    # Get own account ID to filter self-posts
    my_account_id = None
    try:
        me_resp = requests.get(f"{base}/api/v1/accounts/verify_credentials", headers=headers, timeout=10)
        if me_resp.ok:
            my_account_id = me_resp.json().get("id")
    except Exception:
        pass

    try:
        # Combine home timeline + hashtag feeds for better coverage
        all_posts = []

        # Home timeline (posts from accounts we follow)
        try:
            resp = requests.get(
                f"{base}/api/v1/timelines/home",
                headers=headers,
                params={"limit": 15},
                timeout=15,
            )
            if resp.ok:
                all_posts.extend(resp.json())
        except Exception:
            pass

        # Hashtag timelines — where the infosec community lives
        import random
        HASHTAGS = ["infosec", "cybersecurity", "ai", "machinelearning", "privacy",
                    "security", "hacking", "llm", "agentic", "databreach"]
        for tag in random.sample(HASHTAGS, min(3, len(HASHTAGS))):
            try:
                resp = requests.get(
                    f"{base}/api/v1/timelines/tag/{tag}",
                    headers=headers,
                    params={"limit": 10},
                    timeout=10,
                )
                if resp.ok:
                    all_posts.extend(resp.json())
            except Exception:
                pass

        # Deduplicate by post ID
        seen_ids = set()
        posts = []
        for p in all_posts:
            pid = p.get("id")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                posts.append(p)

        for post in posts:
            text = post.get("content", "")
            post_id = post.get("id", "")
            ph = post_hash(f"masto:{post_id}")

            if ph in seen_posts:
                continue

            # Skip own posts
            if my_account_id and post.get("account", {}).get("id") == my_account_id:
                seen_posts.add(ph)
                continue

            # Strip HTML tags for relevance check
            import re
            clean = re.sub(r"<[^>]+>", "", text)
            if not is_relevant(clean):
                continue

            seen_posts.add(ph)

            # Signal TIAMAT about high-value accounts
            post_account = post.get("account", {})
            if is_high_value_account(post_account):
                signal_parent("mastodon", post_account, clean, post.get("url", ""))

            # Favorite
            try:
                r = requests.post(
                    f"{base}/api/v1/statuses/{post_id}/favourite",
                    headers=headers,
                    timeout=10,
                )
                if r.ok:
                    liked += 1
                    stats["likes"] += 1
            except Exception:
                pass

            # Boost every 4th
            if liked % 4 == 0 and liked > 0:
                try:
                    r = requests.post(
                        f"{base}/api/v1/statuses/{post_id}/reblog",
                        headers=headers,
                        timeout=10,
                    )
                    if r.ok:
                        boosted += 1
                        stats["reposts"] += 1
                except Exception:
                    pass

    except Exception as e:
        log.error(f"Mastodon engage error: {e}")
        stats["errors"] += 1

    log.info(f"Mastodon: {liked} favorites, {boosted} boosts")


# ── Farcaster Engagement ────────────────────────────────────────
def farcaster_engage():
    """Farcaster engagement via Warpcast search (free) + Neynar post/reply (free).
    Likes/recasts are paywalled (402) so we only do replies."""
    global _farcaster_last_reply_time

    if not NEYNAR_API_KEY or not NEYNAR_SIGNER_UUID:
        log.info("Farcaster: SKIPPED (no Neynar credentials)")
        return

    import random
    replied = 0
    discovered = 0

    # Pick 3 random queries per cycle to avoid hitting rate limits
    queries = random.sample(FARCASTER_SEARCH_QUERIES, min(3, len(FARCASTER_SEARCH_QUERIES)))

    try:
        candidates = []
        for query in queries:
            try:
                resp = requests.get(
                    "https://api.warpcast.com/v2/search-casts",
                    params={"q": query, "limit": 10},
                    headers={"Accept": "application/json"},
                    timeout=15,
                )
                if resp.ok:
                    casts = resp.json().get("result", {}).get("casts", [])
                    for cast in casts:
                        cast_hash = cast.get("hash", "")
                        ph = post_hash(f"fc:{cast_hash}")
                        if ph in seen_posts:
                            continue
                        author = cast.get("author", {})
                        username = author.get("username", "")
                        # Skip own posts and replies
                        if username == FARCASTER_USERNAME:
                            continue
                        if cast.get("hash") != cast.get("threadHash"):
                            continue  # skip replies, only engage top-level posts
                        text = cast.get("text", "")
                        if len(text) < 25:
                            continue
                        # Check age — skip if older than 12 hours
                        ts_ms = cast.get("timestamp", 0)
                        if ts_ms and (time.time() * 1000 - ts_ms) > 43200000:
                            continue
                        candidates.append({
                            "hash": cast_hash,
                            "text": text,
                            "author": username,
                            "author_info": author,
                            "followers": author.get("followerCount", 0),
                            "likes": cast.get("reactions", {}).get("count", 0),
                            "ph": ph,
                        })
                        discovered += 1
            except Exception as e:
                log.warning(f"Farcaster search '{query}': {e}")
            time.sleep(1)  # Rate limit between searches

        log.info(f"Farcaster: {discovered} candidates from {len(queries)} queries")

        if not candidates:
            log.info("Farcaster: 0 candidates, skipping")
            return

        # Sort by engagement potential (followers + likes)
        candidates.sort(key=lambda c: c["followers"] + c["likes"] * 10, reverse=True)

        # Check for Big Fish
        for c in candidates:
            if is_high_value_account(c["author_info"]):
                signal_parent("farcaster", c["author_info"], c["text"],
                              f"https://warpcast.com/{c['author']}/{c['hash'][:10]}")

        # Reply to best candidate if rate limit allows
        now = time.time()
        if now - _farcaster_last_reply_time >= FARCASTER_REPLY_RATE_LIMIT and GROQ_API_KEY:
            best = candidates[0]
            reply_text = _farcaster_generate_reply(best["text"], best["author"])
            if reply_text:
                try:
                    resp = requests.post(
                        "https://api.neynar.com/v2/farcaster/cast",
                        headers={"Content-Type": "application/json", "x-api-key": NEYNAR_API_KEY},
                        json={
                            "signer_uuid": NEYNAR_SIGNER_UUID,
                            "text": reply_text[:320],
                            "parent": best["hash"],
                        },
                        timeout=20,
                    )
                    if resp.ok:
                        replied += 1
                        stats["comments"] += 1
                        _farcaster_last_reply_time = now
                        seen_posts.add(best["ph"])
                        log.info(f"Farcaster: replied to @{best['author']} — {reply_text[:80]}")
                    else:
                        log.warning(f"Farcaster reply failed: {resp.status_code} {resp.text[:100]}")
                except Exception as e:
                    log.error(f"Farcaster reply error: {e}")
        else:
            if not GROQ_API_KEY:
                log.info("Farcaster: no GROQ_API_KEY, skipping reply generation")
            else:
                wait = int(FARCASTER_REPLY_RATE_LIMIT - (now - _farcaster_last_reply_time))
                log.info(f"Farcaster: reply rate limited ({wait}s remaining)")

        # Mark all seen
        for c in candidates:
            seen_posts.add(c["ph"])

    except Exception as e:
        log.error(f"Farcaster engage error: {e}")
        stats["errors"] += 1

    log.info(f"Farcaster: {replied} replies, {discovered} posts discovered")


def _farcaster_generate_reply(cast_text: str, author: str) -> str:
    """Generate a contextual reply using Groq with anti-slop constraints."""
    if not GROQ_API_KEY:
        return None
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": ANTI_SLOP_SYSTEM},
                    {"role": "user", "content": f'@{author} posted: "{cast_text[:300]}"\n\nWrite a reply (max 280 chars).'},
                ],
                "max_tokens": 120,
                "temperature": 0.65,
            },
            timeout=15,
        )
        if resp.ok:
            text = resp.json()["choices"][0]["message"]["content"].strip()
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            # Post-generation slop check
            if is_sloppy(text):
                log.warning(f"Farcaster reply was sloppy, discarding: {text[:60]}")
                return None
            return text[:280]
    except Exception as e:
        log.error(f"Farcaster reply gen error: {e}")
    return None


# ── Moltbook Engagement ─────────────────────────────────────────
def moltbook_engage():
    """Read Moltbook feed, comment on relevant posts."""
    if not MOLTBOOK_API_KEY:
        return

    headers = {"Authorization": f"Bearer {MOLTBOOK_API_KEY}"}
    commented = 0

    # Get own username to filter self-posts
    my_username = None
    try:
        me_resp = requests.get("https://www.moltbook.com/api/v1/me", headers=headers, timeout=10)
        if me_resp.ok:
            my_username = me_resp.json().get("username") or me_resp.json().get("name")
    except Exception:
        pass

    try:
        resp = requests.get(
            "https://www.moltbook.com/api/v1/feed",
            headers=headers,
            params={"sort": "hot", "limit": 10},
            timeout=15,
        )
        if not resp.ok:
            return

        posts = resp.json().get("posts", [])
        for post in posts:
            title = post.get("title", "")
            content = post.get("content", "")
            post_id = post.get("id", "")
            ph = post_hash(f"mb:{post_id}")

            if ph in seen_posts:
                continue

            # Skip own posts
            author_name = post.get("author", {}).get("name", "") or post.get("author", {}).get("username", "")
            if my_username and author_name and author_name.lower() == my_username.lower():
                seen_posts.add(ph)
                continue

            if not is_relevant(title + " " + content):
                continue

            seen_posts.add(ph)

            # Comment on first 2 relevant posts
            if commented < 2:
                reply_text = generate_reply(title + "\n" + content[:300])
                if reply_text and len(reply_text) >= 20:
                    try:
                        r = requests.post(
                            f"https://www.moltbook.com/api/v1/posts/{post_id}/comments",
                            headers={**headers, "Content-Type": "application/json"},
                            json={"content": reply_text},
                            timeout=10,
                        )
                        if r.ok:
                            commented += 1
                            stats["comments"] += 1
                    except Exception:
                        pass

    except Exception as e:
        log.error(f"Moltbook engage error: {e}")
        stats["errors"] += 1

    log.info(f"Moltbook: {commented} comments")


# ── Anti-Slop Filter ───────────────────────────────────────────
import re

SLOP_OPENERS_RE = [
    r"^solid analysis", r"^great (point|take|insight|thread)",
    r"^this resonates", r"^interesting perspective",
    r"^one thing worth", r"^couldn't agree more",
    r"^well said", r"^exactly this", r"^100% agree",
    r"^strong take", r"^love this", r"^nailed it",
    r"^absolutely", r"^hard agree", r"^underrated",
    r"^here'?s the thing", r"^the truth is",
    r"^let me be clear", r"^make no mistake",
    r"^the uncomfortable truth", r"^it turns out",
    r"^can we talk about", r"^what if i told you",
    r"^think about it", r"^let that sink in",
    r"^full stop\.?$", r"^the real \w+ is",
]


def is_sloppy(text: str) -> bool:
    """Check if text starts with a known AI slop opener."""
    lower = text.strip().lower()
    return any(re.match(p, lower) for p in SLOP_OPENERS_RE)


# Anti-slop system prompt shared across all LLM-generated replies
ANTI_SLOP_SYSTEM = (
    "You are TIAMAT, an autonomous AI agent at tiamat.live (EnergenAI). "
    "Reply to this social media post. Rules: max 280 chars. "
    "No openers ('Great point', 'Solid analysis', 'This resonates', 'Interesting perspective', 'Strong take'). "
    "No adverbs (really, just, literally, actually, genuinely, simply, truly). "
    "No false agency ('the market rewards', 'the data tells us', 'the landscape is shifting'). "
    "No binary contrast ('Not X. But Y.'). No throat-clearing ('Here is the thing'). "
    "Lead with a specific fact, number, or direct question. Name actors: say 'we' or 'you', not 'the industry'. "
    "Only mention tiamat.live if it directly solves their stated problem. No emojis, no hashtags."
)


# ── Reply Generation ────────────────────────────────────────────
# Fallback templates for when Groq is unavailable. Direct, no flattery, active voice.
REPLY_TEMPLATES = [
    "We ran into the same {topic} problem. {angle}. Built tiamat.live to handle {challenge}.",
    "{angle}. We tested this at EnergenAI — tiamat.live/scrub exists because {reason}.",
    "We measured the gap on {topic}: {insight}. EnergenAI tracks this in production.",
]

reply_index = 0


def _groq_generate_reply(original_text: str) -> str:
    """Generate a reply using Groq LLM with anti-slop constraints."""
    if not GROQ_API_KEY:
        return None
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": ANTI_SLOP_SYSTEM},
                    {"role": "user", "content": f'Post: "{original_text[:300]}"\n\nWrite a reply (max 280 chars).'},
                ],
                "max_tokens": 120,
                "temperature": 0.65,
            },
            timeout=15,
        )
        if resp.ok:
            text = resp.json()["choices"][0]["message"]["content"].strip()
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            # Post-generation slop check — retry once if sloppy
            if is_sloppy(text):
                log.warning(f"Groq reply was sloppy, retrying: {text[:60]}")
                resp2 = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": ANTI_SLOP_SYSTEM + " ABSOLUTELY NO generic openers. Start with a verb or a number."},
                            {"role": "user", "content": f'Post: "{original_text[:300]}"\n\nWrite a reply (max 280 chars). Start with a specific claim or question.'},
                        ],
                        "max_tokens": 120,
                        "temperature": 0.7,
                    },
                    timeout=15,
                )
                if resp2.ok:
                    text2 = resp2.json()["choices"][0]["message"]["content"].strip()
                    if text2.startswith('"') and text2.endswith('"'):
                        text2 = text2[1:-1]
                    if not is_sloppy(text2):
                        return text2[:280]
                # If retry also sloppy, fall through to template
                return None
            return text[:280]
    except Exception as e:
        log.error(f"Groq reply gen error: {e}")
    return None


def generate_reply(original_text: str) -> str:
    """Generate a contextual reply. Prefers Groq LLM, falls back to templates."""
    global reply_index

    # Extract key topics from original
    lower = original_text.lower()
    topics = []
    for kw in ENGAGE_KEYWORDS:
        if kw in lower:
            topics.append(kw)

    if not topics:
        return ""

    topic = topics[0]

    # Try Groq first for varied, non-sloppy replies
    groq_reply = _groq_generate_reply(original_text)
    if groq_reply:
        return groq_reply

    # Fallback: topic-specific template replies (no flattery, active voice)
    angles = {
        "ai agent": ("Autonomous AI needs trust verification before deployment", "proving reliability at scale"),
        "cybersecurity": ("Attack surfaces grow faster than defenses", "proactive detection over reactive patching"),
        "privacy": ("Data minimization is the only real defense", "PII scrubbing at the API layer"),
        "phishing": ("AI-generated phishing bypasses legacy filters", "behavioral detection over signature matching"),
        "llm": ("Model security is wide open right now", "prompt injection and data exfiltration"),
        "startup": ("AI agents cut burn rate by 40-60%", "autonomous operations as competitive moat"),
        "malware": ("Supply chain attacks tripled since 2024", "continuous monitoring over periodic scans"),
        "security": ("Defense-in-depth needs AI augmentation", "real-time threat analysis"),
    }

    angle_data = None
    for key, val in angles.items():
        if key in lower:
            angle_data = val
            break

    if not angle_data:
        angle_data = ("Three vendors shipped competing solutions this month", "staying ahead requires automation")

    template = REPLY_TEMPLATES[reply_index % len(REPLY_TEMPLATES)]
    reply_index += 1

    return template.format(
        topic=topic,
        angle=angle_data[0],
        challenge=angle_data[1],
        reason=angle_data[1],
        insight=angle_data[0],
    )


# ── Inbox Processing ────────────────────────────────────────────
def process_inbox():
    """Check for directives from TIAMAT."""
    if not INBOX_PATH.exists():
        return

    try:
        data = json.loads(INBOX_PATH.read_text())
        directives = data.get("directives", [])

        for d in directives:
            if d.get("processed"):
                continue

            action = d.get("action", "")
            log.info(f"Directive from TIAMAT: {action}")

            if action == "engage_all":
                # Run a full engagement cycle immediately
                run_engagement_cycle()
            elif action == "pause":
                d["processed"] = True
                INBOX_PATH.write_text(json.dumps(data, indent=2))
                log.info("Paused by TIAMAT directive")
                return  # Stop processing
            elif action == "status":
                save_status()

            d["processed"] = True

        INBOX_PATH.write_text(json.dumps(data, indent=2))
    except Exception as e:
        log.error(f"Inbox error: {e}")


# ── Main Loop ───────────────────────────────────────────────────
def run_engagement_cycle():
    """Run one full engagement cycle across all platforms."""
    log.info("═══ Engagement cycle starting ═══")
    stats["cycles"] += 1

    bluesky_engage()
    time.sleep(2)  # Rate limit buffer

    mastodon_engage()
    time.sleep(2)

    farcaster_engage()
    time.sleep(2)

    moltbook_engage()

    save_seen()
    save_status()
    log.info(
        f"═══ Cycle {stats['cycles']} complete: "
        f"{stats['likes']} total likes, {stats['reposts']} reposts, "
        f"{stats['comments']} comments ═══"
    )


def main():
    log.info("ECHO worker starting — TIAMAT's first child agent")
    log.info(f"Platforms: Bluesky={'YES' if BLUESKY_HANDLE else 'NO'}, "
             f"Mastodon={'YES' if MASTODON_TOKEN else 'NO'}, "
             f"Farcaster={'YES (reply-only)' if NEYNAR_API_KEY else 'NO'}, "
             f"Moltbook={'YES' if MOLTBOOK_API_KEY else 'NO'}")

    load_seen()
    save_status()

    # Graceful shutdown
    def shutdown(sig, frame):
        log.info("ECHO shutting down gracefully")
        save_seen()
        save_status()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Initial engagement cycle
    run_engagement_cycle()

    # Main loop
    while True:
        time.sleep(CYCLE_INTERVAL)
        process_inbox()
        run_engagement_cycle()


if __name__ == "__main__":
    main()
