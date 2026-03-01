#!/usr/bin/env python3
"""
learning_cycle.py — Research paper discovery & knowledge synthesis
Called every 4 cycles as a cooldown task instead of gpu_infer.

Flow:
  1. Search Semantic Scholar (free API) for recent papers on rotating AI topics
  2. Call Groq API (free, llama-3.3-70b) to: analyze papers → extract insight → write Bluesky post
  3. Save knowledge to /root/hive/knowledge/{date}-{slug}.md
  4. Append post to /root/.automaton/pending_posts.json (TIAMAT's standard queue)

Design constraints: runs in <30s, one Groq call (free tier), zero GPU usage.

Usage:
  python3 learning_cycle.py          # normal run
  python3 learning_cycle.py status   # show stats
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
KNOWLEDGE_DIR    = Path("/root/hive/knowledge")
PENDING_POSTS    = Path("/root/.automaton/pending_posts.json")
LEARNING_STATE   = Path("/root/.automaton/learning_cycle_state.json")
ENV_FILE         = Path("/root/.env")

LLM_TIMEOUT      = 30   # seconds for Groq API call
SEARCH_TIMEOUT   = 6    # seconds per HTTP request

# Topic rotation — indexes through on each run
TOPICS = [
    "agentic AI autonomous decision-making",
    "multi-agent LLM coordination cooperation",
    "LLM inference efficiency fast serving",
    "AI agent memory retrieval long-context",
    "autonomous AI self-improvement reflection",
    "AI agent economics incentives markets",
    "AI safety robustness adversarial agents",
    "reinforcement learning from human feedback RLHF 2025",
]

# ── Env loader ────────────────────────────────────────────────────────────────
def load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


# ── State ─────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    try:
        return json.loads(LEARNING_STATE.read_text())
    except Exception:
        return {"topic_idx": 0, "runs": 0, "posts_queued": 0, "last_run": None}

def save_state(state: dict) -> None:
    LEARNING_STATE.parent.mkdir(parents=True, exist_ok=True)
    LEARNING_STATE.write_text(json.dumps(state, indent=2))


# ── Paper search ──────────────────────────────────────────────────────────────
def search_semantic_scholar(query: str, limit: int = 5) -> list[dict]:
    """
    Semantic Scholar Graph API — free, no key required.
    Returns recent papers with title, abstract, url.
    """
    params = urllib.parse.urlencode({
        "query": query,
        "fields": "title,abstract,year,url,externalIds,authors",
        "limit": limit,
        "sort": "relevance",
    })
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "TIAMAT-research/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT) as resp:
            data = json.loads(resp.read())
        papers = []
        for p in data.get("data", []):
            arxiv_id = p.get("externalIds", {}).get("ArXiv", "")
            url_str  = p.get("url", "")
            if arxiv_id:
                url_str = f"https://arxiv.org/abs/{arxiv_id}"
            abstract = (p.get("abstract") or "")[:300]
            authors  = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:3])
            papers.append({
                "title":    p.get("title", ""),
                "url":      url_str,
                "arxiv_id": arxiv_id,
                "snippet":  abstract,
                "authors":  authors,
                "year":     p.get("year", ""),
            })
        return papers
    except Exception:
        return []


def search_arxiv_api(query: str, limit: int = 5) -> list[dict]:
    """
    ArXiv API fallback — free, XML response, no key required.
    """
    params = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "start":        0,
        "max_results":  limit,
        "sortBy":       "submittedDate",
        "sortOrder":    "descending",
    })
    url = f"https://export.arxiv.org/api/query?{params}"
    try:
        with urllib.request.urlopen(url, timeout=SEARCH_TIMEOUT) as resp:
            xml = resp.read().decode("utf-8")
        # Parse titles, ids, summaries from Atom XML
        titles    = re.findall(r"<title>(?!ArXiv)([^<]+)</title>", xml)
        ids       = re.findall(r"<id>https://arxiv\.org/abs/([^<]+)</id>", xml)
        summaries = re.findall(r"<summary>([^<]+)</summary>", xml, re.DOTALL)
        papers = []
        for i, (t, aid, s) in enumerate(zip(titles, ids, summaries)):
            if i >= limit:
                break
            papers.append({
                "title":    t.strip(),
                "url":      f"https://arxiv.org/abs/{aid.strip()}",
                "arxiv_id": aid.strip(),
                "snippet":  re.sub(r"\s+", " ", s.strip())[:300],
                "authors":  "",
                "year":     "2025",
            })
        return papers
    except Exception:
        return []


def _decode_ddg_url(raw: str) -> str:
    """Extract the real URL from a DuckDuckGo redirect wrapper."""
    # DDG wraps urls: //duckduckgo.com/l/?uddg=<encoded>&rut=...
    m = re.search(r"[?&]uddg=([^&]+)", raw)
    if m:
        return urllib.parse.unquote(m.group(1))
    # Sometimes it's a bare //host/path — prepend https
    if raw.startswith("//"):
        return "https:" + raw
    return raw


def search_ddg_fallback(query: str, limit: int = 5) -> list[dict]:
    """DuckDuckGo HTML scrape — last resort."""
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query + ' arxiv')}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        pat = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>'
            r'[\s\S]*?<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)</a>',
        )
        results = []
        for i, m in enumerate(pat.finditer(html)):
            if i >= limit:
                break
            real_url = _decode_ddg_url(m.group(1))
            snippet = re.sub(r"<[^>]+>", "", m.group(3)).strip()
            arxiv_m = re.search(r"arxiv\.org/abs/([\d.v]+)", real_url)
            results.append({
                "title":    m.group(2).strip(),
                "url":      real_url,
                "arxiv_id": arxiv_m.group(1) if arxiv_m else "",
                "snippet":  snippet[:300],
                "authors":  "",
                "year":     "",
            })
        return results
    except Exception:
        return []


def find_papers(topic: str) -> list[dict]:
    """Try Semantic Scholar → ArXiv → DDG, return first non-empty list."""
    for fn in (search_semantic_scholar, search_arxiv_api, search_ddg_fallback):
        results = fn(topic)
        if results:
            return results
    return []


# ── LLM call (Groq — free tier, fast) ────────────────────────────────────────
ANALYSIS_PROMPT = """\
You are TIAMAT's research synthesizer. I searched for recent AI papers and got these results.

TOPIC: {topic}
DATE: {date}

PAPERS FOUND:
{papers}

YOUR TASK — reply ONLY with valid JSON, no markdown fences, no prose outside the JSON:

{{
  "paper_title": "exact title of the most interesting paper",
  "paper_url": "direct url to the paper",
  "arxiv_id": "XXXX.XXXXX or null",
  "key_insight": "2-3 sentences — what does this paper reveal that matters for autonomous AI agents? Be specific about the finding, not just the topic.",
  "bluesky_post": "TIAMAT posts this to Bluesky — HARD LIMIT: 260 characters max (count carefully) — state the concrete insight, cite the paper arXiv ID — no hashtags — write as TIAMAT (autonomous AI) — be technical and direct — SHORT",
  "relevance_to_tiamat": "one sentence — how TIAMAT could apply this finding"
}}"""


def call_groq(prompt: str, timeout: int = LLM_TIMEOUT) -> tuple[str, str | None]:
    """
    Call Groq API (free tier) with llama-3.3-70b for paper analysis.
    Falls back to claude --print if GROQ_API_KEY is not set.
    Returns (output_text, error_string_or_None).
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return "", "GROQ_API_KEY not set in environment"

    payload = json.dumps({
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 800,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "TIAMAT-research/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            return "", "empty response from Groq"
        return content.strip(), None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        return "", f"Groq HTTP {e.code}: {body}"
    except Exception as e:
        return "", str(e)[:200]


# ── JSON parser ───────────────────────────────────────────────────────────────
def parse_json_from_output(text: str) -> dict:
    """
    Extract JSON object from Claude's output.
    Handles markdown fences, leading/trailing prose.
    """
    # Strip fences
    clean = re.sub(r"```json\s*", "", text)
    clean = re.sub(r"```\s*", "", clean).strip()
    # Find outermost {...}
    m = re.search(r"\{[\s\S]+\}", clean)
    if m:
        return json.loads(m.group())
    return json.loads(clean)


# ── Knowledge file writer ─────────────────────────────────────────────────────
def write_knowledge_file(
    date_str: str,
    topic: str,
    papers: list[dict],
    analysis: dict,
) -> Path:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w-]", "-", topic.lower())[:48].strip("-")
    slug = re.sub(r"-+", "-", slug)
    path = KNOWLEDGE_DIR / f"{date_str}-{slug}.md"
    # Avoid collisions
    if path.exists():
        for n in range(2, 20):
            candidate = KNOWLEDGE_DIR / f"{date_str}-{slug}-{n}.md"
            if not candidate.exists():
                path = candidate
                break

    lines = [
        f"# Learning Cycle: {topic}",
        f"**Date**: {date_str}",
        f"**Ingested**: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Selected Paper",
        f"**Title**: {analysis.get('paper_title', 'Unknown')}",
        f"**URL**: {analysis.get('paper_url', '')}",
        f"**ArXiv**: {analysis.get('arxiv_id') or 'N/A'}",
        "",
        "## Key Insight",
        analysis.get("key_insight", ""),
        "",
        "## Relevance to TIAMAT",
        analysis.get("relevance_to_tiamat", ""),
        "",
        "## Bluesky Post",
        "```",
        analysis.get("bluesky_post", ""),
        "```",
        "",
        "## All Search Results",
    ]
    for i, p in enumerate(papers[:6], 1):
        lines.append(f"{i}. [{p['title']}]({p['url']})")
        if p.get("snippet"):
            lines.append(f"   {p['snippet'][:150]}")
    lines.append("")

    path.write_text("\n".join(lines))
    return path


# ── Bluesky post queue ─────────────────────────────────────────────────────────
def queue_bluesky_post(text: str) -> bool:
    """
    Append to /root/.automaton/pending_posts.json in TIAMAT's queue format.
    Matches the format used by tools.ts queuePendingPost().
    """
    if not text or len(text) > 300:
        return False
    try:
        raw: object = []
        if PENDING_POSTS.exists():
            try:
                raw = json.loads(PENDING_POSTS.read_text())
            except Exception:
                raw = []
        pending: list = raw if isinstance(raw, list) else []

        pending.append({
            "platform":  "bluesky",
            "args":      {"text": text},
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "source":    "learning_cycle",
        })
        if len(pending) > 5:          # same cap as tools.ts
            pending = pending[-5:]

        PENDING_POSTS.parent.mkdir(parents=True, exist_ok=True)
        PENDING_POSTS.write_text(json.dumps(pending, indent=2))
        return True
    except Exception:
        return False


# ── Status command ────────────────────────────────────────────────────────────
def print_status() -> None:
    state = load_state()
    print("=== Learning Cycle Status ===")
    print(f"  Runs:          {state.get('runs', 0)}")
    print(f"  Posts queued:  {state.get('posts_queued', 0)}")
    print(f"  Last run:      {state.get('last_run', 'never')}")
    print(f"  Next topic:    {TOPICS[state.get('topic_idx', 0) % len(TOPICS)]}")
    files = sorted(KNOWLEDGE_DIR.glob("*.md")) if KNOWLEDGE_DIR.exists() else []
    print(f"  Knowledge files: {len(files)}")
    if files:
        print(f"  Latest: {files[-1].name}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    t0 = time.time()
    load_env()

    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print_status()
        return

    state    = load_state()
    topic    = TOPICS[state["topic_idx"] % len(TOPICS)]
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Step 1: Find papers ───────────────────────────────────────────────────
    papers = find_papers(topic)
    if not papers:
        print(json.dumps({"error": "no papers found", "topic": topic}))
        return
    t_search = round(time.time() - t0, 1)

    # ── Step 2: Build Claude prompt ───────────────────────────────────────────
    papers_text = "\n\n".join(
        f"[{i+1}] {p['title']} ({p.get('year','?')})\n"
        f"    URL: {p['url']}\n"
        f"    {p.get('snippet','')[:250]}"
        for i, p in enumerate(papers[:5])
    )
    prompt = ANALYSIS_PROMPT.format(
        topic=topic,
        date=date_str,
        papers=papers_text,
    )

    # ── Step 3: Ask Claude once ───────────────────────────────────────────────
    output, err = call_groq(prompt)
    t_claude = round(time.time() - t0 - t_search, 1)

    if err or not output:
        print(json.dumps({"error": f"LLM analysis failed: {err}", "topic": topic,
                           "timing": {"search": t_search}}))
        return

    # ── Step 4: Parse analysis ────────────────────────────────────────────────
    analysis: dict = {}
    try:
        analysis = parse_json_from_output(output)
    except Exception:
        # Couldn't parse JSON — save raw output as insight
        analysis = {
            "paper_title":          papers[0]["title"] if papers else "Unknown",
            "paper_url":            papers[0]["url"]   if papers else "",
            "arxiv_id":             papers[0].get("arxiv_id") if papers else None,
            "key_insight":          output[:400],
            "bluesky_post":         "",
            "relevance_to_tiamat":  "",
        }

    # ── Step 5: Save knowledge file ───────────────────────────────────────────
    kf_path = write_knowledge_file(date_str, topic, papers, analysis)

    # ── Step 6: Queue Bluesky post ────────────────────────────────────────────
    post_text = (analysis.get("bluesky_post") or "").strip()
    # Safety truncation at sentence boundary if over limit
    if post_text and len(post_text) > 300:
        cut = post_text[:297]
        last_period = cut.rfind(". ")
        post_text = (cut[:last_period + 1] if last_period > 200 else cut) + "…"
    post_queued = queue_bluesky_post(post_text) if post_text else False

    # ── Update state ──────────────────────────────────────────────────────────
    state["topic_idx"]    = (state["topic_idx"] + 1) % len(TOPICS)
    state["runs"]         = state.get("runs", 0) + 1
    state["posts_queued"] = state.get("posts_queued", 0) + (1 if post_queued else 0)
    state["last_run"]     = datetime.now(timezone.utc).isoformat()
    save_state(state)

    total = round(time.time() - t0, 1)
    print(json.dumps({
        "ok":             True,
        "topic":          topic,
        "paper":          (analysis.get("paper_title") or "?")[:80],
        "insight":        (analysis.get("key_insight") or "")[:120],
        "post_queued":    post_queued,
        "post_text":      post_text[:100] if post_text else "",
        "knowledge_file": str(kf_path),
        "timing":         {"search_s": t_search, "claude_s": t_claude, "total_s": total},
    }))


if __name__ == "__main__":
    main()
