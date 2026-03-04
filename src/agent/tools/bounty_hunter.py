"""
bounty_hunter.py — Pull open bounties from Algora, GitHub, and Gitcoin.
Returns structured list filtered by language, reward, and difficulty.
Cache TTL: 1 hour (via module-level dict).
"""

import os
import re
import json
import time
import logging
import requests
from datetime import datetime
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

HEADERS_GITHUB = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {GITHUB_TOKEN}" if GITHUB_TOKEN else "",
    "X-GitHub-Api-Version": "2022-11-28",
}
HEADERS_BROWSER = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "application/json",
}

TARGET_LANGS = {"typescript", "python", "javascript", "ts", "js", "py"}
MIN_REWARD = 50
MAX_REWARD = 500

# ── Simple in-process cache ────────────────────────────────────────────────
_cache: dict = {}
CACHE_TTL = 3600  # seconds


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(key: str, data):
    _cache[key] = {"ts": time.time(), "data": data}


# ── Difficulty heuristics ──────────────────────────────────────────────────

def _estimate_difficulty(title: str, body: str = "", labels=None) -> str:
    text = (title + " " + body).lower()
    labels = [str(l).lower() for l in (labels or [])]

    hard_kw = {"architecture", "refactor", "migration", "security", "performance",
                "scalability", "distributed", "concurrency", "cryptograph"}
    easy_kw = {"typo", "docs", "documentation", "readme", "spelling", "minor",
                "simple", "small", "trivial", "quick fix", "good first issue"}

    if any(k in text for k in easy_kw) or any(k in labels for k in ["good first issue", "easy"]):
        return "easy"
    if any(k in text for k in hard_kw) or any(k in labels for k in ["hard", "complex"]):
        return "hard"
    return "medium"


def _estimate_hours(difficulty: str, reward: float) -> int:
    """Rough time estimate based on difficulty and reward size."""
    base = {"easy": 2, "medium": 6, "hard": 16}[difficulty]
    # Scale up slightly for larger bounties (more complex)
    if reward > 300:
        base = int(base * 1.5)
    return base


def _parse_usd(text: str) -> float | None:
    """Extract USD amount from strings like '$250', '250 USD', '0.1 ETH ($180)'."""
    if not text:
        return None
    # Prefer explicit USD
    m = re.search(r'\$\s*([\d,]+(?:\.\d+)?)', text)
    if m:
        return float(m.group(1).replace(",", ""))
    m = re.search(r'([\d,]+(?:\.\d+)?)\s*USD', text, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _detect_language(text: str, labels=None) -> str:
    text = text.lower()
    labels = [str(l).lower() for l in (labels or [])]
    combined = text + " " + " ".join(labels)

    for lang in ["typescript", "python", "javascript"]:
        if lang in combined:
            return lang
    # abbreviations
    if " ts " in combined or combined.startswith("ts ") or "typescript" in combined:
        return "typescript"
    if " js " in combined or "javascript" in combined:
        return "javascript"
    if " py " in combined or "python" in combined:
        return "python"
    return "unknown"


def _in_target_lang(lang: str) -> bool:
    return lang in {"typescript", "python", "javascript"}


# ── Source: GitHub issues labeled 'bounty' ────────────────────────────────

def fetch_github_bounties() -> list:
    cached = _cache_get("github")
    if cached is not None:
        return cached

    results = []
    queries = [
        'label:bounty is:open language:TypeScript',
        'label:bounty is:open language:Python',
        'label:bounty is:open language:JavaScript',
        'label:"bounty" is:issue is:open',
    ]

    seen_ids = set()
    for q in queries:
        try:
            url = "https://api.github.com/search/issues"
            params = {"q": q, "per_page": 30, "sort": "created", "order": "desc"}
            resp = requests.get(url, headers=HEADERS_GITHUB, params=params, timeout=10)
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except Exception as e:
            logger.warning(f"GitHub query failed ({q}): {e}")
            continue

        for item in items:
            issue_id = item.get("id")
            if issue_id in seen_ids:
                continue
            seen_ids.add(issue_id)

            title = item.get("title", "")
            body = item.get("body") or ""
            labels = [l["name"] for l in item.get("labels", [])]
            url_issue = item.get("html_url", "")
            repo_url = item.get("repository_url", "")

            # Try to get language from repo
            lang = _detect_language(title + " " + body, labels)
            if lang == "unknown":
                # Fetch repo language
                try:
                    r2 = requests.get(repo_url, headers=HEADERS_GITHUB, timeout=5)
                    lang = (r2.json().get("language") or "unknown").lower()
                except Exception:
                    pass

            if not _in_target_lang(lang):
                continue

            # Parse reward from title, body, labels
            reward_text = title + " " + body + " " + " ".join(labels)
            reward = _parse_usd(reward_text)
            if reward is None:
                continue
            if not (MIN_REWARD <= reward <= MAX_REWARD):
                continue

            difficulty = _estimate_difficulty(title, body, labels)
            if difficulty == "easy":
                continue  # skip easy per filter

            results.append({
                "url": url_issue,
                "title": title[:120],
                "reward": reward,
                "language": lang,
                "difficulty": difficulty,
                "hours": _estimate_hours(difficulty, reward),
                "source": "github",
            })

    _cache_set("github", results)
    return results


# ── Source: Algora ─────────────────────────────────────────────────────────

def fetch_algora_bounties() -> list:
    cached = _cache_get("algora")
    if cached is not None:
        return cached

    results = []
    items = []

    # Try Algora's tRPC-style JSON endpoint used by their web app
    algora_urls = [
        "https://algora.io/api/bounties?status=open&limit=100",
        "https://console.algora.io/bounties.json",
    ]
    html_headers = {
        **HEADERS_BROWSER,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    json_headers = {**HEADERS_BROWSER, "Accept": "application/json"}

    for api_url in algora_urls:
        try:
            resp = requests.get(api_url, headers=json_headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", data.get("bounties", []))
            if items:
                break
        except Exception as e:
            logger.debug(f"Algora endpoint {api_url} failed: {e}")

    # Fallback: scrape HTML listing page
    if not items:
        try:
            resp = requests.get(
                "https://algora.io/bounties",
                headers=html_headers,
                timeout=15,
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            # Each bounty card is an <a> link containing reward + title text
            cards = soup.select("a[href*='/issues/'], a[href*='/bounties/']")
            for card in cards:
                href = str(card.get("href") or "")
                if not href.startswith("http"):
                    href = "https://algora.io" + href
                text = card.get_text(" ", strip=True)
                reward = _parse_usd(text)
                lang = _detect_language(text)
                title = text[:120]

                if reward is None or not (MIN_REWARD <= reward <= MAX_REWARD):
                    continue
                if not _in_target_lang(lang):
                    continue

                difficulty = _estimate_difficulty(title)
                if difficulty == "easy":
                    continue

                results.append({
                    "url": href,
                    "title": title,
                    "reward": reward,
                    "language": lang,
                    "difficulty": difficulty,
                    "hours": _estimate_hours(difficulty, reward),
                    "source": "algora",
                })
        except Exception as e:
            logger.warning(f"Algora HTML scrape failed: {e}")

    # Parse JSON items if available
    for item in items:
        try:
            title = item.get("title") or item.get("name") or item.get("issue", {}).get("title", "")
            reward_raw = (
                item.get("reward_usd")
                or item.get("amount")
                or item.get("reward")
                or item.get("price")
                or 0
            )
            try:
                reward = float(str(reward_raw).replace(",", "").replace("$", ""))
            except (ValueError, TypeError):
                reward = _parse_usd(str(reward_raw))

            if reward is None or not (MIN_REWARD <= reward <= MAX_REWARD):
                continue

            tech = (
                item.get("language")
                or item.get("tech")
                or item.get("technologies")
                or item.get("issue", {}).get("language")
                or ""
            )
            if isinstance(tech, list):
                tech = " ".join(tech)
            lang = _detect_language(str(tech) + " " + title)
            if not _in_target_lang(lang):
                continue

            url_b = (
                item.get("url")
                or item.get("html_url")
                or item.get("link")
                or item.get("issue", {}).get("html_url", "")
            )
            if not url_b:
                continue

            labels = item.get("labels", [])
            difficulty = _estimate_difficulty(title, "", labels)
            if difficulty == "easy":
                continue

            results.append({
                "url": url_b,
                "title": title[:120],
                "reward": reward,
                "language": lang,
                "difficulty": difficulty,
                "hours": _estimate_hours(difficulty, reward),
                "source": "algora",
            })
        except Exception as e:
            logger.debug(f"Algora item parse error: {e}")

    _cache_set("algora", results)
    return results


# ── Source: Gitcoin ────────────────────────────────────────────────────────

def fetch_gitcoin_bounties() -> list:
    cached = _cache_get("gitcoin")
    if cached is not None:
        return cached

    results = []

    # Gitcoin Grants/Bounties API (v1 bounties endpoint — still public)
    try:
        url = "https://gitcoin.co/api/v0.1/bounties/"
        params = {
            "status": "open",
            "limit": 100,
            "order_by": "-web3_created",
            "keywords": "typescript,python,javascript",
        }
        resp = requests.get(url, headers=HEADERS_BROWSER, params=params, timeout=15)
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            items = items.get("results", [])
    except Exception as e:
        logger.warning(f"Gitcoin API failed: {e}")
        items = []

    for item in items:
        try:
            title = item.get("title", "")
            reward_usdt = float(item.get("usd_value") or item.get("value_in_usdt") or 0)
            if not (MIN_REWARD <= reward_usdt <= MAX_REWARD):
                continue

            keywords = item.get("keywords", "") or ""
            project_type = item.get("project_type", "") or ""
            lang = _detect_language(keywords + " " + title + " " + project_type)
            if not _in_target_lang(lang):
                continue

            url_b = item.get("url") or item.get("github_url") or ""
            if not url_b:
                continue

            difficulty_raw = (item.get("experience_level") or "").lower()
            if "beginner" in difficulty_raw:
                difficulty = "easy"
            elif "advanced" in difficulty_raw or "expert" in difficulty_raw:
                difficulty = "hard"
            else:
                difficulty = _estimate_difficulty(title, item.get("description") or "")

            if difficulty == "easy":
                continue

            # Basic English check: skip non-English descriptions
            desc = (item.get("description") or "")[:200]
            # Simple heuristic: mostly ASCII = likely English
            ascii_ratio = sum(1 for c in desc if ord(c) < 128) / max(len(desc), 1)
            if ascii_ratio < 0.85:
                continue

            results.append({
                "url": url_b,
                "title": title[:120],
                "reward": round(reward_usdt, 2),
                "language": lang,
                "difficulty": difficulty,
                "hours": _estimate_hours(difficulty, reward_usdt),
                "source": "gitcoin",
            })
        except Exception as e:
            logger.debug(f"Gitcoin item parse error: {e}")

    _cache_set("gitcoin", results)
    return results


# ── Sonar consolidated search (TIK-512: replaces 6-browse loop) ───────────

_SONAR_QUERY = (
    "List the top 5 currently open software bounties on Algora, IssueHunt, or GitHub "
    "that are written in Python or TypeScript, reward between $50-$500 USD, not trivial. "
    "For each bounty return a JSON object with keys: "
    "title (string), url (string, direct link), reward_usd (number), language (python|typescript|javascript), "
    "difficulty (easy|medium|hard), notes (one sentence). "
    "Respond ONLY with a JSON array of up to 5 objects, no markdown, no prose."
)


def search_bounties_sonar(max_results: int = 3) -> list[dict]:
    """
    Single Perplexity Sonar call that replaces the 6-browse loop (TIK-512).
    Returns up to `max_results` bounties ranked by reward / estimated_hours.
    Falls back to fetch_all_bounties() on any error.
    """
    cached = _cache_get("sonar")
    if cached is not None:
        return cached

    pplx_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not pplx_key:
        logger.warning("PERPLEXITY_API_KEY not set — falling back to HTTP fetch")
        return _sonar_fallback(max_results)

    try:
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {pplx_key}",
            },
            json={
                "model": "sonar",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a precise JSON API. Return only valid JSON arrays. "
                            "No markdown fences, no commentary."
                        ),
                    },
                    {"role": "user", "content": _SONAR_QUERY},
                ],
                "max_tokens": 1024,
            },
            timeout=20,
        )
        resp.raise_for_status()

        raw_answer: str = (
            resp.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "[]")
        )
    except Exception as exc:
        logger.warning(f"sonar_search failed: {exc} — falling back to HTTP fetch")
        return _sonar_fallback(max_results)

    # Strip accidental markdown fences
    raw_answer = re.sub(r"```(?:json)?\s*", "", raw_answer).strip().rstrip("`").strip()

    try:
        parsed = json.loads(raw_answer)
        if not isinstance(parsed, list):
            raise ValueError(f"expected JSON array, got {type(parsed).__name__}")
        items: list[dict] = parsed
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"sonar parse error ({exc}) — falling back to HTTP fetch")
        return _sonar_fallback(max_results)

    results: list[dict] = []
    for item in items[:5]:  # hard cap at 5 parsed
        try:
            lang = str(item.get("language", "")).lower()
            if not _in_target_lang(lang):
                continue

            reward = float(item.get("reward_usd") or 0)
            if not (MIN_REWARD <= reward <= MAX_REWARD):
                continue

            url_b = str(item.get("url", "")).strip()
            if not url_b or not url_b.startswith("http"):
                continue

            difficulty = str(item.get("difficulty", "medium")).lower()
            if difficulty not in ("easy", "medium", "hard"):
                difficulty = "medium"
            if difficulty == "easy":
                continue

            hours = _estimate_hours(difficulty, reward)
            results.append({
                "url": url_b,
                "title": str(item.get("title", ""))[:120],
                "reward": reward,
                "language": lang,
                "difficulty": difficulty,
                "hours": hours,
                "score": round(reward / hours, 2),  # $/hr ranking key
                "notes": str(item.get("notes", ""))[:200],
                "source": "sonar",
            })
        except Exception as exc:
            logger.debug(f"sonar item parse error: {exc}")

    # Rank by reward/hour descending, return top N
    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:max_results]

    _cache_set("sonar", top)
    return top


def _sonar_fallback(max_results: int) -> list[dict]:
    """Fallback: pull from existing HTTP sources and return top N by $/hr."""
    all_bounties: list[dict] = []
    for fn in [fetch_github_bounties, fetch_algora_bounties, fetch_gitcoin_bounties]:
        try:
            all_bounties.extend(fn())
        except Exception as exc:
            logger.error(f"{fn.__name__} failed: {exc}")

    for b in all_bounties:
        b.setdefault("score", round(b["reward"] / max(b["hours"], 1), 2))

    all_bounties.sort(key=lambda x: x["score"], reverse=True)
    return all_bounties[:max_results]


# ── Main aggregator ────────────────────────────────────────────────────────

def fetch_all_bounties() -> dict:
    """Aggregate bounties from all sources. Returns API response dict."""
    cached = _cache_get("all")
    if cached is not None:
        return cached

    bounties = []
    for fn in [fetch_github_bounties, fetch_algora_bounties, fetch_gitcoin_bounties]:
        try:
            bounties.extend(fn())
        except Exception as e:
            logger.error(f"Source fetch failed ({fn.__name__}): {e}")

    # Deduplicate by URL
    seen_urls = set()
    unique = []
    for b in bounties:
        if b["url"] not in seen_urls:
            seen_urls.add(b["url"])
            unique.append(b)

    # Sort by reward desc
    unique.sort(key=lambda x: x["reward"], reverse=True)

    result = {
        "bounties": unique,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "count": len(unique),
    }

    _cache_set("all", result)
    return result
