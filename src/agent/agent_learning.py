#!/usr/bin/env python3
"""
agent_learning.py — Extract knowledge from AI agent replies on Farcaster

Flow:
  1. Check threads where TIAMAT replied — look for replies from other agents
  2. Detect agents by: bio keywords, username patterns, known accounts
  3. Extract technical content via Groq analysis
  4. Save actionable improvements to learned_from_agents.json
  5. Generate strategic follow-up questions for deeper engagement
  6. Optionally post follow-up reply to continue the conversation

Usage:
  python3 agent_learning.py scan     # Check for agent replies, extract knowledge (no posting)
  python3 agent_learning.py run      # Scan + post follow-up to best agent reply
  python3 agent_learning.py status   # Show learned knowledge stats
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

# ── Config ────────────────────────────────────────────────────────────────────
TIAMAT_FID = 2833392
TIAMAT_USERNAME = "tiamat-"
WARPCAST_URL = "https://api.warpcast.com/v2"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

NEYNAR_URL = "https://api.neynar.com/v2/farcaster"
NEYNAR_API_KEY = os.environ.get("NEYNAR_API_KEY", "")
NEYNAR_SIGNER_UUID = os.environ.get("NEYNAR_SIGNER_UUID", "")

LEARNED_FILE = "/root/.automaton/learned_from_agents.json"
ENGAGEMENT_FILE = "/root/.automaton/farcaster_engagement.json"
LEARNING_STATE_FILE = "/root/.automaton/agent_learning_state.json"

# Minimum reply length to consider "technical"
MIN_TECHNICAL_LENGTH = 80

# ── Known Agent Patterns ─────────────────────────────────────────────────────
KNOWN_AGENT_USERNAMES = {
    "aisecurity-guard", "agentdaemon", "misabot", "clankerbot",
    "aethernet", "degenbot", "basebot", "neynarbot", "warpcastbot",
}

AGENT_BIO_KEYWORDS = [
    "ai agent", "autonomous", "bot", "automated", "artificial intelligence",
    "machine learning", "security agent", "defi agent", "trading bot",
    "onchain agent", "ai-powered", "agent framework", "autonomous agent",
    "intelligent agent", "crypto bot",
]

AGENT_NAME_KEYWORDS = [
    "agent", "bot", "ai", "auto", "daemon", "guard", "sentinel",
    "oracle", "protocol", "engine",
]

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AGENT_LEARN] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("agent_learning")


# ── State Management ─────────────────────────────────────────────────────────
def load_state():
    path = Path(LEARNING_STATE_FILE)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {
        "processed_threads": [],   # thread hashes already checked
        "processed_replies": [],   # reply hashes already analyzed
        "last_run": None,
        "runs": 0,
        "agents_found": 0,
        "knowledge_extracted": 0,
        "followups_sent": 0,
    }


def save_state(state):
    path = Path(LEARNING_STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep lists bounded
    state["processed_threads"] = state["processed_threads"][-200:]
    state["processed_replies"] = state["processed_replies"][-500:]
    path.write_text(json.dumps(state, indent=2))


def load_learned():
    path = Path(LEARNED_FILE)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {"insights": [], "agents_engaged": {}, "last_updated": None}


def save_learned(data):
    path = Path(LEARNED_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    # Keep bounded
    data["insights"] = data["insights"][-100:]
    path.write_text(json.dumps(data, indent=2))


# ── Agent Detection ──────────────────────────────────────────────────────────
def detect_agent(author_data):
    """
    Detect if a Farcaster user is likely an AI agent.
    Returns (is_agent: bool, confidence: str, signals: list)
    """
    username = author_data.get("username", "").lower()
    display = author_data.get("displayName", "").lower()
    bio = author_data.get("profile", {}).get("bio", {}).get("text", "").lower()
    badge = author_data.get("powerBadge", False)
    signals = []

    # Known agent accounts — high confidence
    if username in KNOWN_AGENT_USERNAMES:
        signals.append(f"known_agent:{username}")
        return True, "high", signals

    # Bio keyword matching
    for kw in AGENT_BIO_KEYWORDS:
        if kw in bio:
            signals.append(f"bio:{kw}")

    # Username/display name patterns
    for kw in AGENT_NAME_KEYWORDS:
        if kw in username:
            signals.append(f"username:{kw}")
        if kw in display:
            signals.append(f"display:{kw}")

    # Power badge + agent signals = high confidence
    if badge and len(signals) >= 1:
        return True, "high", signals

    # Multiple bio/name signals = likely agent
    if len(signals) >= 2:
        return True, "medium", signals

    # Single strong signal
    if any(s.startswith("bio:") for s in signals):
        return True, "low", signals

    return False, "none", signals


# ── Thread Scanning ──────────────────────────────────────────────────────────
def get_tiamat_reply_threads():
    """
    Get the list of cast hashes where TIAMAT has replied.
    Returns list of (original_cast_hash, tiamat_reply_hash, original_author).
    """
    path = Path(ENGAGEMENT_FILE)
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text())
    except Exception:
        return []

    threads = []
    for entry in data.get("log", []):
        cast_hash = entry.get("hash", "")
        author = entry.get("author", "")
        if cast_hash and author:
            threads.append({
                "original_hash": cast_hash,
                "original_author": author,
                "original_text": entry.get("cast", ""),
                "tiamat_reply": entry.get("reply", ""),
                "ts": entry.get("ts", ""),
            })

    return threads


def get_thread_replies(cast_hash):
    """
    Fetch all casts in a thread via Warpcast public API.
    Returns list of cast dicts.
    """
    try:
        resp = requests.get(
            f"{WARPCAST_URL}/thread-casts",
            params={"castHash": cast_hash},
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("result", {}).get("casts", [])
        log.warning(f"Thread fetch {cast_hash[:12]}: HTTP {resp.status_code}")
        return []
    except Exception as e:
        log.error(f"Thread fetch error: {e}")
        return []


def find_agent_replies(state):
    """
    Scan all threads where TIAMAT replied. Find new replies from agents.
    Returns list of agent reply dicts.
    """
    threads = get_tiamat_reply_threads()
    agent_replies = []

    for thread_info in threads:
        original_hash = thread_info["original_hash"]

        # Get all casts in this thread
        casts = get_thread_replies(original_hash)
        if not casts:
            continue

        for cast in casts:
            cast_hash = cast.get("hash", "")
            author = cast.get("author", {})
            username = author.get("username", "")
            text = cast.get("text", "")

            # Skip TIAMAT's own casts
            if username == TIAMAT_USERNAME:
                continue

            # Skip the original cast (we want replies, not the root)
            if cast_hash == original_hash:
                continue

            # Skip already processed
            if cast_hash in state.get("processed_replies", []):
                continue

            # Skip short replies
            if len(text) < MIN_TECHNICAL_LENGTH:
                continue

            # Skip replies that are just links/mentions with no substance
            text_stripped = re.sub(r'https?://\S+', '', text).strip()
            text_stripped = re.sub(r'@\w+', '', text_stripped).strip()
            if len(text_stripped) < 40:
                continue

            # Check if this is an agent
            is_agent, confidence, signals = detect_agent(author)
            if not is_agent:
                continue

            agent_replies.append({
                "cast_hash": cast_hash,
                "thread_hash": original_hash,
                "author_username": username,
                "author_fid": author.get("fid"),
                "author_bio": author.get("profile", {}).get("bio", {}).get("text", ""),
                "text": text,
                "confidence": confidence,
                "signals": signals,
                "original_context": thread_info,
            })

        # Rate limit API calls
        time.sleep(0.5)

    return agent_replies


# ── Knowledge Extraction ─────────────────────────────────────────────────────
EXTRACT_SYSTEM = """You are TIAMAT's knowledge extraction engine. An AI agent on Farcaster replied to TIAMAT with technical content.

Your job:
1. Identify the SPECIFIC technical claims/suggestions in their reply
2. Assess if any are actionable improvements for TIAMAT's systems
3. Output structured JSON with actionable items

TIAMAT's systems:
- Flask APIs (summarize, chat, generate) on tiamat.live with x402 micropayments
- Memory API (SQLite + FTS5) on memory.tiamat.live
- Agent loop (TypeScript, Anthropic Claude for inference)
- tools.ts with path ACLs, execFileSync hardening
- Multi-chain scanner (Base, Arbitrum, Optimism, Ethereum)
- Farcaster + Bluesky social presence
- nginx reverse proxy with SSL

Output ONLY valid JSON:
{
  "technical_claims": ["list of specific technical points they made"],
  "actionable_items": [
    {
      "action": "what TIAMAT should do",
      "priority": "high|medium|low",
      "category": "security|performance|feature|revenue|integration",
      "details": "specific implementation notes"
    }
  ],
  "agent_capability": "what this agent seems to specialize in",
  "collaboration_potential": "how TIAMAT could work with this agent"
}"""


def extract_knowledge(agent_reply):
    """
    Send agent's reply to Groq for structured knowledge extraction.
    Returns parsed JSON or None.
    """
    if not GROQ_KEY:
        log.warning("No GROQ_API_KEY — skipping knowledge extraction")
        return None

    user_prompt = (
        f"Agent @{agent_reply['author_username']} "
        f"(bio: {agent_reply.get('author_bio', 'unknown')[:200]}) said:\n\n"
        f'"{agent_reply["text"]}"\n\n'
        f"Context — TIAMAT had posted:\n"
        f'"{agent_reply["original_context"]["tiamat_reply"][:200]}"\n\n'
        f"In response to:\n"
        f'"{agent_reply["original_context"]["original_text"][:200]}"\n\n'
        f"Extract actionable knowledge for TIAMAT."
    )

    try:
        resp = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": EXTRACT_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 500,
                "temperature": 0.3,
            },
            timeout=20,
        )
        if resp.status_code == 200:
            text = resp.json()["choices"][0]["message"]["content"].strip()
            # Parse JSON from response (handle markdown code blocks)
            if "```" in text:
                text = re.sub(r"```json?\s*", "", text)
                text = re.sub(r"```\s*$", "", text)
            return json.loads(text.strip())
        log.warning(f"Groq extract {resp.status_code}: {resp.text[:100]}")
    except json.JSONDecodeError as e:
        log.error(f"JSON parse error in extraction: {e}")
    except Exception as e:
        log.error(f"Groq extract error: {e}")
    return None


# ── Follow-up Generation ─────────────────────────────────────────────────────
FOLLOWUP_SYSTEM = """You are TIAMAT, an autonomous AI agent. Generate a follow-up reply to another AI agent on Farcaster.

Strategy:
- Ask a SPECIFIC technical question that goes deeper (not generic)
- Reference your own systems when relevant ("I handle X with Y, what's your approach?")
- Offer capability trades ("I can scan contracts on 4 chains — want me to check yours?")
- Steer toward: "how do I make money from this?" when appropriate
- Show genuine technical curiosity, not flattery

Rules:
- Max 280 characters
- No emojis, no hashtags
- Be direct and specific
- One clear question or offer"""


def generate_followup(agent_reply, knowledge):
    """
    Generate a strategic follow-up question for the agent.
    Returns reply text or None.
    """
    if not GROQ_KEY:
        return None

    capability = ""
    if knowledge:
        capability = knowledge.get("agent_capability", "unknown")
        collab = knowledge.get("collaboration_potential", "")
    else:
        capability = "unknown"
        collab = ""

    user_prompt = (
        f"Agent @{agent_reply['author_username']} said:\n"
        f'"{agent_reply["text"][:300]}"\n\n'
        f"Their specialty: {capability}\n"
        f"Collaboration angle: {collab}\n\n"
        f"Your context: You run tiamat.live (summarize/chat/generate APIs), "
        f"memory.tiamat.live (persistent agent memory), multi-chain scanner "
        f"(Base/Arb/OP/ETH), x402 micropayments in USDC.\n\n"
        f"Generate a follow-up reply (max 280 chars). Ask something specific "
        f"that extracts more knowledge or opens a collaboration."
    )

    try:
        resp = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": FOLLOWUP_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 100,
                "temperature": 0.6,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            text = resp.json()["choices"][0]["message"]["content"].strip()
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            return text[:280]
        log.warning(f"Groq followup {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        log.error(f"Groq followup error: {e}")
    return None


# ── Reply Posting ────────────────────────────────────────────────────────────
def post_followup(cast_hash, text):
    """Post a follow-up reply via Neynar."""
    if not NEYNAR_API_KEY or not NEYNAR_SIGNER_UUID:
        log.warning("Missing Neynar creds — cannot post")
        return None, "missing_creds"

    payload = {
        "signer_uuid": NEYNAR_SIGNER_UUID,
        "text": text[:320],
        "parent": cast_hash,
    }
    try:
        resp = requests.post(
            f"{NEYNAR_URL}/cast",
            headers={
                "Content-Type": "application/json",
                "x-api-key": NEYNAR_API_KEY,
            },
            json=payload,
            timeout=20,
        )
        if resp.status_code == 200:
            reply_hash = resp.json().get("cast", {}).get("hash", "unknown")
            return reply_hash, None
        return None, f"{resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return None, str(e)[:200]


# ── Main Pipeline ────────────────────────────────────────────────────────────
def run_scan(dry_run=True):
    """
    Full pipeline: find agent replies → extract knowledge → generate followups.
    """
    state = load_state()
    learned = load_learned()

    log.info(f"Scanning threads for agent replies (dry_run={dry_run})...")

    agent_replies = find_agent_replies(state)
    log.info(f"Found {len(agent_replies)} new agent replies")

    if not agent_replies:
        print(json.dumps({
            "agents_found": 0,
            "knowledge_extracted": 0,
            "followup_sent": False,
        }))
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        state["runs"] = state.get("runs", 0) + 1
        save_state(state)
        return

    results = []

    for reply in agent_replies:
        username = reply["author_username"]
        log.info(f"Processing @{username} (confidence={reply['confidence']}, signals={reply['signals']})")

        # Extract knowledge
        knowledge = extract_knowledge(reply)
        if knowledge:
            log.info(f"  Extracted {len(knowledge.get('actionable_items', []))} actionable items")

            # Save to learned file
            insight = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "agent": username,
                "agent_fid": reply["author_fid"],
                "agent_bio": reply.get("author_bio", "")[:200],
                "confidence": reply["confidence"],
                "cast_hash": reply["cast_hash"],
                "original_text": reply["text"][:500],
                "technical_claims": knowledge.get("technical_claims", []),
                "actionable_items": knowledge.get("actionable_items", []),
                "agent_capability": knowledge.get("agent_capability", ""),
                "collaboration_potential": knowledge.get("collaboration_potential", ""),
                "status": "pending",  # pending → implemented → dismissed
            }
            learned["insights"].append(insight)

            # Track agent
            learned.setdefault("agents_engaged", {})[username] = {
                "fid": reply["author_fid"],
                "capability": knowledge.get("agent_capability", ""),
                "interactions": learned.get("agents_engaged", {}).get(username, {}).get("interactions", 0) + 1,
                "last_seen": datetime.now(timezone.utc).isoformat(),
            }

            state["knowledge_extracted"] = state.get("knowledge_extracted", 0) + 1
        else:
            knowledge = {}

        # Generate follow-up
        followup = generate_followup(reply, knowledge)

        result = {
            "agent": username,
            "confidence": reply["confidence"],
            "signals": reply["signals"],
            "text_preview": reply["text"][:120],
            "actionable_items": len(knowledge.get("actionable_items", [])),
            "followup": followup,
        }

        # Post follow-up if not dry run
        if not dry_run and followup:
            reply_hash, err = post_followup(reply["cast_hash"], followup)
            if err:
                log.error(f"  Follow-up post failed: {err}")
                result["followup_posted"] = False
                result["followup_error"] = err
            else:
                log.info(f"  Follow-up posted: {reply_hash}")
                result["followup_posted"] = True
                result["followup_hash"] = reply_hash
                state["followups_sent"] = state.get("followups_sent", 0) + 1

        # Mark as processed
        state.setdefault("processed_replies", []).append(reply["cast_hash"])
        state["agents_found"] = state.get("agents_found", 0) + 1

        results.append(result)

        # Rate limit between processing
        time.sleep(1)

    # Save state
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    state["runs"] = state.get("runs", 0) + 1
    save_state(state)
    save_learned(learned)

    # Print summary
    print(f"\n=== Agent Learning Results ===")
    for r in results:
        print(f"  @{r['agent']} ({r['confidence']} confidence)")
        print(f"    Signals: {', '.join(r['signals'][:3])}")
        print(f"    Preview: {r['text_preview']}")
        print(f"    Actionable items: {r['actionable_items']}")
        if r.get("followup"):
            print(f"    Follow-up: {r['followup'][:120]}")
            if r.get("followup_posted"):
                print(f"    Posted: {r.get('followup_hash', '?')}")
        print()

    print(json.dumps({
        "agents_found": len(results),
        "knowledge_extracted": sum(r["actionable_items"] for r in results),
        "followup_sent": any(r.get("followup_posted") for r in results),
    }))


def print_status():
    """Show learned knowledge stats."""
    state = load_state()
    learned = load_learned()

    print("\n=== TIAMAT Agent Learning Status ===")
    print(f"  Runs:                {state.get('runs', 0)}")
    print(f"  Last run:            {state.get('last_run', 'never')}")
    print(f"  Agents found:        {state.get('agents_found', 0)}")
    print(f"  Knowledge extracted: {state.get('knowledge_extracted', 0)}")
    print(f"  Follow-ups sent:     {state.get('followups_sent', 0)}")
    print(f"  Threads processed:   {len(state.get('processed_threads', []))}")
    print(f"  Replies processed:   {len(state.get('processed_replies', []))}")

    insights = learned.get("insights", [])
    pending = [i for i in insights if i.get("status") == "pending"]
    implemented = [i for i in insights if i.get("status") == "implemented"]

    print(f"\n  Total insights:      {len(insights)}")
    print(f"  Pending:             {len(pending)}")
    print(f"  Implemented:         {len(implemented)}")

    agents = learned.get("agents_engaged", {})
    if agents:
        print(f"\n  Agents engaged ({len(agents)}):")
        for name, info in agents.items():
            print(f"    @{name}: {info.get('capability', '?')} ({info.get('interactions', 0)} interactions)")

    if pending:
        print(f"\n  Latest pending insights:")
        for insight in pending[-3:]:
            print(f"    [{insight['timestamp'][:10]}] @{insight['agent']}: {insight.get('agent_capability', '?')}")
            for item in insight.get("actionable_items", [])[:2]:
                print(f"      [{item.get('priority','?')}] {item.get('action', '?')[:80]}")

    print()


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
    global GROQ_KEY, NEYNAR_API_KEY, NEYNAR_SIGNER_UUID

    _load_env()
    GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
    NEYNAR_API_KEY = os.environ.get("NEYNAR_API_KEY", "")
    NEYNAR_SIGNER_UUID = os.environ.get("NEYNAR_SIGNER_UUID", "")

    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if cmd == "scan":
        run_scan(dry_run=True)
    elif cmd == "run":
        run_scan(dry_run=False)
    elif cmd == "status":
        print_status()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: agent_learning.py [scan|run|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
