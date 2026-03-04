#!/usr/bin/env python3
"""
find_bounties.py — One-shot bounty finder.

Searches Algora + Gitcoin + IssueHunt for Python/TypeScript bounties ≥$50.
Saves all results to /root/.automaton/bounties.json and prints top 3.
Safe to run repeatedly (idempotent). Target: <30s wall time.

Usage:
    python3 find_bounties.py
    python3 find_bounties.py --min 100        # raise minimum
    python3 find_bounties.py --json           # machine-readable output only
"""

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeout
from datetime import datetime, timezone

import requests

# ── Config ──────────────────────────────────────────────────────────────────

OUTPUT_PATH = "/root/.automaton/bounties.json"
PER_SOURCE_TIMEOUT = 12       # seconds per HTTP call
TOTAL_TIMEOUT = 25            # wall-clock budget (leave margin for save/print)
TARGET_LANGS = {"python", "typescript", "javascript"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _detect_lang(text: str) -> str:
    t = text.lower()
    if "typescript" in t or " ts " in t:
        return "typescript"
    if "javascript" in t or " js " in t:
        return "javascript"
    if "python" in t or " py " in t:
        return "python"
    return "unknown"


def _difficulty(title: str, body: str = "") -> str:
    text = (title + " " + body).lower()
    easy = {"typo", "docs", "readme", "minor", "trivial", "simple", "small", "quick fix"}
    hard = {"architecture", "refactor", "migration", "security", "performance",
             "distributed", "concurrency", "cryptograph", "overhaul"}
    if any(k in text for k in hard):
        return "hard"
    if any(k in text for k in easy):
        return "easy"
    return "medium"


def _make(url: str, title: str, reward: float, lang: str, source: str, body: str = "") -> dict:
    diff = _difficulty(title, body)
    base_hrs = {"easy": 2, "medium": 6, "hard": 16}[diff]
    if reward > 300:
        base_hrs = int(base_hrs * 1.5)
    return {
        "url": url,
        "title": title[:120],
        "reward_usd": round(reward, 2),
        "language": lang,
        "difficulty": diff,
        "est_hours": base_hrs,
        "score": round(reward / base_hrs, 2),   # $/hr ranking key
        "source": source,
    }


# ── Source: Algora ───────────────────────────────────────────────────────────
# Algora is a Phoenix LiveView app — no public JSON API.
# Scrape the server-rendered HTML bounties page.

def fetch_algora(min_reward: float) -> list[dict]:
    results: list[dict] = []
    try:
        resp = requests.get(
            "https://algora.io/bounties",
            headers={**HEADERS, "Accept": "text/html,*/*"},
            timeout=PER_SOURCE_TIMEOUT,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception:
        return results

    # Each bounty row is an <a href="GITHUB_URL"> wrapping:
    #   <span class="...text-success...">$AMOUNT</span>
    #   <span class="text-foreground">TITLE</span>
    # We extract them as parallel lists from the raw HTML.
    anchors = re.findall(
        r'<a href="(https://github\.com/[^"]+)"[^>]*>([\s\S]*?)</a>',
        html,
    )

    for href, inner in anchors:
        reward_m = re.search(r'\$([\d,]+(?:\.\d+)?)', inner)
        if not reward_m:
            continue
        reward = float(reward_m.group(1).replace(",", ""))
        if reward < min_reward:
            continue

        # Strip all tags to get title text
        title_raw = re.sub(r'<[^>]+>', ' ', inner)
        title_raw = re.sub(r'\s+', ' ', title_raw).strip()
        # Remove the dollar amount from title text
        title = re.sub(r'\$[\d,]+(?:\.\d+)?', '', title_raw).strip()
        if not title:
            continue

        lang = _detect_lang(href + " " + title)
        if lang not in TARGET_LANGS:
            # Try to resolve from repo language via GitHub API (best-effort, 3s budget)
            repo_match = re.match(r'https://github\.com/([^/]+/[^/]+)', href)
            if repo_match:
                try:
                    gh_tok = os.environ.get("GITHUB_TOKEN", "")
                    gh_h = {"Accept": "application/vnd.github+json"}
                    if gh_tok:
                        gh_h["Authorization"] = f"Bearer {gh_tok}"
                    repo_resp = requests.get(
                        f"https://api.github.com/repos/{repo_match.group(1)}",
                        headers=gh_h, timeout=3,
                    )
                    lang = (repo_resp.json().get("language") or "unknown").lower()
                except Exception:
                    pass
            if lang not in TARGET_LANGS:
                continue

        results.append(_make(href, title, reward, lang, "algora"))

    return results


# ── Source: Gitcoin ──────────────────────────────────────────────────────────
# Gitcoin deprecated their bounty platform in 2023. The v0.1 API is dead.
# We scrape their explorer page for any surviving bounty data.

def fetch_gitcoin(min_reward: float) -> list[dict]:
    results: list[dict] = []

    # Attempt the legacy API (occasionally restored for archived data)
    try:
        resp = requests.get(
            "https://gitcoin.co/api/v0.1/bounties/",
            params={
                "status": "open",
                "limit": 100,
                "keywords": "python,typescript,javascript",
                "order_by": "-usd_value",
            },
            headers=HEADERS,
            timeout=PER_SOURCE_TIMEOUT,
        )
        if resp.status_code == 200:
            items = resp.json()
            if not isinstance(items, list):
                items = items.get("results", [])
        else:
            items = []
    except Exception:
        items = []

    for item in items:
        try:
            reward = float(item.get("usd_value") or item.get("value_in_usdt") or 0)
            if reward < min_reward:
                continue
            title = str(item.get("title", ""))
            keywords = str(item.get("keywords", "") or "")
            lang = _detect_lang(keywords + " " + title)
            if lang not in TARGET_LANGS:
                continue
            url = str(item.get("url") or item.get("github_url") or "")
            if not url.startswith("http"):
                continue
            body = str(item.get("description") or "")
            results.append(_make(url, title, reward, lang, "gitcoin", body))
        except Exception:
            continue

    return results


# ── Source: IssueHunt ────────────────────────────────────────────────────────
# Real working API discovered from their Next.js bundle.
# Endpoint: https://oss.issuehunt.io/apis/pages/repos/browse
# depositAmount is in cents (÷100 = USD).

def fetch_issuehunt(min_reward: float) -> list[dict]:
    results: list[dict] = []
    seen_ids: set[str] = set()

    for lang_filter in ["python", "typescript"]:
        try:
            resp = requests.get(
                "https://oss.issuehunt.io/apis/pages/repos/browse",
                params={
                    "language": lang_filter,
                    "status": "open",
                    "sortBy": "fundedAt",
                    "page": 1,
                },
                headers=HEADERS,
                timeout=PER_SOURCE_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue

        issues = data.get("issues", [])
        for item in issues:
            issue_id = str(item.get("_id", ""))
            if issue_id in seen_ids:
                continue
            seen_ids.add(issue_id)

            try:
                # depositAmount is in cents
                deposit_cents = item.get("depositAmount") or 0
                reward = float(deposit_cents) / 100.0
                if reward < min_reward:
                    continue

                title = str(item.get("title", "")).strip()
                if not title:
                    continue

                owner = item.get("repositoryOwnerName", "")
                repo = item.get("repositoryName", "")
                number = item.get("number")
                if not (owner and repo and number):
                    continue

                url = f"https://github.com/{owner}/{repo}/issues/{number}"
                body = str(item.get("body") or "")

                # Language: use the filter we queried with (augmented by title/body)
                lang_hint = lang_filter + " " + title
                lang = _detect_lang(lang_hint)
                if lang not in TARGET_LANGS:
                    lang = lang_filter  # trust the filter

                results.append(_make(url, title, reward, lang, "issuehunt", body))
            except Exception:
                continue

    return results


# ── Aggregator ───────────────────────────────────────────────────────────────

def find_bounties(min_reward: float = 50.0) -> dict:
    start = time.time()
    all_bounties: list[dict] = []
    source_counts: dict[str, int] = {}
    errors: list[str] = []

    sources = {
        "algora": lambda: fetch_algora(min_reward),
        "gitcoin": lambda: fetch_gitcoin(min_reward),
        "issuehunt": lambda: fetch_issuehunt(min_reward),
    }

    remaining = TOTAL_TIMEOUT - 3  # leave buffer for file I/O and print
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fn): name for name, fn in sources.items()}
        try:
            for future in as_completed(futures, timeout=remaining):
                name = futures[future]
                try:
                    bounties = future.result()
                    source_counts[name] = len(bounties)
                    all_bounties.extend(bounties)
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
                    source_counts[name] = 0
        except FutureTimeout:
            errors.append("parallel fetch timed out")

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for b in all_bounties:
        if b["url"] not in seen_urls:
            seen_urls.add(b["url"])
            unique.append(b)

    # Sort by $/hr score descending
    unique.sort(key=lambda x: x["score"], reverse=True)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": round(time.time() - start, 1),
        "min_reward_usd": min_reward,
        "total_found": len(unique),
        "source_counts": source_counts,
        "errors": errors,
        "top3": unique[:3],
        "all": unique,
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Find Python/TS bounties ≥$50")
    parser.add_argument("--min", type=float, default=50.0,
                        help="Minimum reward in USD (default: 50)")
    parser.add_argument("--json", action="store_true", dest="json_only",
                        help="Print JSON only (machine-readable)")
    args = parser.parse_args()

    if not args.json_only:
        print(f"Searching Algora, Gitcoin, IssueHunt for Python/TS bounties ≥${args.min:.0f}...")
        sys.stdout.flush()

    data = find_bounties(min_reward=args.min)

    # Save (idempotent — overwrites each run)
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as fh:
        json.dump(data, fh, indent=2)

    if args.json_only:
        print(json.dumps(data["top3"], indent=2))
        return

    # Human-readable output
    counts = " | ".join(f"{s}: {n}" for s, n in data["source_counts"].items())
    print(f"Done in {data['elapsed_s']}s — {data['total_found']} bounties "
          f"({counts})")
    print(f"Saved → {OUTPUT_PATH}\n")

    if data["errors"]:
        print(f"Warnings: {'; '.join(data['errors'])}\n")

    if not data["top3"]:
        print("No bounties matched the filters.")
        sys.exit(0)

    print("=" * 62)
    print("TOP 3 OPPORTUNITIES  (ranked by $/hr)")
    print("=" * 62)

    for i, b in enumerate(data["top3"], 1):
        print(f"\n#{i}  [{b['source'].upper()}] {b['title']}")
        print(f"     Reward : ${b['reward_usd']:.0f}   Language: {b['language']}")
        print(f"     Effort : {b['difficulty']}, ~{b['est_hours']}h "
              f"→ ${b['score']:.1f}/hr")
        print(f"     URL    : {b['url']}")

    print()


if __name__ == "__main__":
    main()
