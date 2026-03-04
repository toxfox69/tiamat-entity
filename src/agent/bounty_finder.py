"""
bounty_finder.py — Unified bounty search across Algora, GitHub, Gitcoin, IssueHunt.

Features:
- 24h disk-based cache at /root/.automaton/bounties.json
- Playwright for Algora (JS-rendered SPA)
- requests for Gitcoin + IssueHunt (static/API)
- GitHub API: label:bounty language:python/typescript
- Filter: $50+ USD, Python/TypeScript preferred
- Returns top 5 by reward desc in standard JSON envelope

Usage:
    from src.agent.bounty_finder import find_bounties
    result = find_bounties()          # uses cache if <24h old
    result = find_bounties(force=True) # bypass cache
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────

CACHE_PATH = Path("/root/.automaton/bounties.json")
CACHE_TTL_HOURS = 24
MIN_REWARD = 50          # USD
TOP_N = 5

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

_GH_HEADERS: dict[str, str] = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GITHUB_TOKEN:
    _GH_HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_TARGET_LANGS = {"python", "typescript", "javascript"}


# ── Helpers ────────────────────────────────────────────────────────────────

def _parse_usd(text: str) -> float | None:
    """Extract the first USD amount from a string."""
    if not text:
        return None
    m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1).replace(",", ""))
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*USD", text, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _detect_lang(text: str, labels: list[str] | None = None) -> str:
    combined = (text + " " + " ".join(labels or [])).lower()
    for lang in ("typescript", "python", "javascript"):
        if lang in combined:
            return lang
    return "unknown"


def _make_entry(
    title: str,
    reward: float,
    url: str,
    site: str,
    lang: str = "unknown",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "title": title[:160],
        "reward": reward,
        "reward_str": f"${reward:,.0f}",
        "site": site,
        "url": url,
        "language": lang,
        "tags": tags or [],
    }


# ── Cache ──────────────────────────────────────────────────────────────────

def _cache_load() -> tuple[list[dict], float] | None:
    """Return (results, age_hours) if cache exists and is fresh, else None."""
    if not CACHE_PATH.exists():
        return None
    try:
        data = json.loads(CACHE_PATH.read_text())
        ts = datetime.fromisoformat(data["timestamp"])
        now = datetime.now(timezone.utc)
        # Make ts timezone-aware if naive
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_hours = (now - ts).total_seconds() / 3600
        if age_hours < CACHE_TTL_HOURS:
            return data.get("results", []), age_hours
    except Exception as e:
        logger.debug(f"Cache load failed: {e}")
    return None


def _cache_save(results: list[dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    CACHE_PATH.write_text(json.dumps(payload, indent=2))


# ── Source: GitHub API ─────────────────────────────────────────────────────

def _fetch_github() -> list[dict]:
    results: list[dict] = []
    seen: set[int] = set()

    queries = [
        'label:bounty is:issue is:open language:TypeScript',
        'label:bounty is:issue is:open language:Python',
        'label:bounty is:issue is:open',
        'label:"help wanted" label:bounty is:issue is:open',
    ]

    for q in queries:
        try:
            resp = requests.get(
                "https://api.github.com/search/issues",
                headers=_GH_HEADERS,
                params={"q": q, "per_page": 30, "sort": "created", "order": "desc"},
                timeout=12,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except Exception as e:
            logger.warning(f"GitHub query failed ({q!r}): {e}")
            continue

        for item in items:
            iid = item.get("id")
            if iid in seen:
                continue
            seen.add(iid)

            title = item.get("title", "")
            body = item.get("body") or ""
            labels = [lb["name"] for lb in item.get("labels", [])]
            html_url = item.get("html_url", "")

            # Detect reward
            reward_text = title + " " + body + " " + " ".join(labels)
            reward = _parse_usd(reward_text)
            if reward is None or reward < MIN_REWARD:
                continue

            # Detect language — try text first, then repo API
            lang = _detect_lang(title + " " + body, labels)
            if lang == "unknown":
                repo_url = item.get("repository_url", "")
                try:
                    r2 = requests.get(repo_url, headers=_GH_HEADERS, timeout=6)
                    lang = (r2.json().get("language") or "unknown").lower()
                except Exception:
                    pass

            if lang not in _TARGET_LANGS:
                continue

            results.append(_make_entry(
                title=title,
                reward=reward,
                url=html_url,
                site="GitHub",
                lang=lang,
                tags=labels[:5],
            ))

    return results


# ── Source: Gitcoin API ────────────────────────────────────────────────────

def _fetch_gitcoin() -> list[dict]:
    results: list[dict] = []
    try:
        resp = requests.get(
            "https://gitcoin.co/api/v0.1/bounties/",
            headers=_BROWSER_HEADERS,
            params={
                "status": "open",
                "limit": 100,
                "order_by": "-web3_created",
                "keywords": "typescript,python,javascript",
            },
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            items = items.get("results", [])
    except Exception as e:
        logger.warning(f"Gitcoin API failed: {e}")
        return []

    for item in items:
        try:
            title = item.get("title", "")
            reward = float(item.get("usd_value") or item.get("value_in_usdt") or 0)
            if reward < MIN_REWARD:
                continue

            keywords = item.get("keywords", "") or ""
            lang = _detect_lang(keywords + " " + title)
            if lang not in _TARGET_LANGS:
                continue

            url = item.get("url") or item.get("github_url") or ""
            if not url:
                continue

            tags = [kw.strip() for kw in keywords.split(",") if kw.strip()]
            results.append(_make_entry(
                title=title,
                reward=round(reward, 2),
                url=url,
                site="Gitcoin",
                lang=lang,
                tags=tags[:5],
            ))
        except Exception as e:
            logger.debug(f"Gitcoin item error: {e}")

    return results


# ── Source: IssueHunt API ──────────────────────────────────────────────────

def _fetch_issuehunt() -> list[dict]:
    """
    IssueHunt exposes a public JSON search endpoint.
    Falls back to HTML scrape if the API changes.
    """
    results: list[dict] = []

    # Try their public search/listing endpoint
    endpoints = [
        "https://issuehunt.io/api/v1/issues?status=open&per_page=50",
        "https://issuehunt.io/api/v1/issues?funded=true&per_page=50",
    ]

    items: list[dict] = []
    for url in endpoints:
        try:
            resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                items = data
            else:
                items = data.get("data", data.get("issues", []))
            if items:
                break
        except Exception as e:
            logger.debug(f"IssueHunt endpoint {url} failed: {e}")

    # HTML fallback
    if not items:
        try:
            from bs4 import BeautifulSoup

            resp = requests.get(
                "https://issuehunt.io/repos",
                headers={**_BROWSER_HEADERS, "Accept": "text/html"},
                timeout=15,
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            # Each issue card typically has amount + title
            for card in soup.select("a[href*='/issues/']"):
                text = card.get_text(" ", strip=True)
                reward = _parse_usd(text)
                if reward is None or reward < MIN_REWARD:
                    continue
                lang = _detect_lang(text)
                if lang not in _TARGET_LANGS:
                    continue
                href = str(card.get("href", ""))
                if not href.startswith("http"):
                    href = "https://issuehunt.io" + href
                results.append(_make_entry(
                    title=text[:120],
                    reward=reward,
                    url=href,
                    site="IssueHunt",
                    lang=lang,
                ))
        except Exception as e:
            logger.warning(f"IssueHunt HTML scrape failed: {e}")
        return results

    for item in items:
        try:
            title = (
                item.get("title")
                or item.get("issue_title")
                or (item.get("issue") or {}).get("title", "")
            )
            reward_raw = (
                item.get("amount")
                or item.get("funded_sum")
                or item.get("total_fund")
                or item.get("reward")
                or 0
            )
            try:
                reward = float(str(reward_raw).replace(",", "").replace("$", ""))
            except (ValueError, TypeError):
                reward = _parse_usd(str(reward_raw)) or 0.0

            if reward < MIN_REWARD:
                continue

            lang_raw = (
                item.get("language")
                or item.get("languages")
                or (item.get("repo") or {}).get("language", "")
                or ""
            )
            if isinstance(lang_raw, list):
                lang_raw = " ".join(str(x) for x in lang_raw)
            lang = _detect_lang(str(lang_raw) + " " + str(title))
            if lang not in _TARGET_LANGS:
                continue

            url = (
                item.get("url")
                or item.get("html_url")
                or item.get("issue_url")
                or (item.get("issue") or {}).get("html_url", "")
            )
            if not url:
                continue

            results.append(_make_entry(
                title=str(title),
                reward=round(reward, 2),
                url=str(url),
                site="IssueHunt",
                lang=lang,
            ))
        except Exception as e:
            logger.debug(f"IssueHunt item error: {e}")

    return results


# ── Source: Algora (Playwright for JS-rendered SPA) ────────────────────────

def _fetch_algora_playwright() -> list[dict]:
    """Scrape console.algora.io using Playwright (handles JS rendering)."""
    results: list[dict] = []
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        logger.warning("playwright not installed — skipping Algora Playwright scrape")
        return _fetch_algora_requests()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx = browser.new_context(
                user_agent=_BROWSER_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()

            # Intercept XHR/fetch for JSON API responses
            api_responses: list[dict] = []

            def handle_response(response):
                try:
                    if "bounti" in response.url and response.status == 200:
                        ct = response.headers.get("content-type", "")
                        if "json" in ct:
                            body = response.json()
                            api_responses.append(body)
                except Exception:
                    pass

            page.on("response", handle_response)

            # Navigate to the bounties listing
            page.goto("https://console.algora.io/bounties", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            # If we got API data via interception, parse that
            if api_responses:
                for body in api_responses:
                    items = body if isinstance(body, list) else body.get("data", body.get("bounties", []))
                    for item in items:
                        _parse_algora_item(item, results)
            else:
                # Parse rendered DOM
                cards = page.query_selector_all("a[href*='/issues/'], a[href*='/bounties/'], [data-bounty]")
                for card in cards:
                    try:
                        text = card.inner_text()
                        href = card.get_attribute("href") or ""
                        if not href.startswith("http"):
                            href = "https://console.algora.io" + href
                        reward = _parse_usd(text)
                        lang = _detect_lang(text)
                        if reward and reward >= MIN_REWARD and lang in _TARGET_LANGS:
                            results.append(_make_entry(
                                title=text[:120].strip(),
                                reward=reward,
                                url=href,
                                site="Algora",
                                lang=lang,
                            ))
                    except Exception as e:
                        logger.debug(f"Algora card parse error: {e}")

            browser.close()

    except Exception as e:
        logger.warning(f"Algora Playwright scrape failed: {e}")
        return _fetch_algora_requests()

    return results


def _parse_algora_item(item: dict, results: list[dict]) -> None:
    try:
        title = (
            item.get("title")
            or item.get("name")
            or (item.get("issue") or {}).get("title", "")
        )
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
            reward = _parse_usd(str(reward_raw)) or 0.0

        if not title or reward < MIN_REWARD:
            return

        tech = (
            item.get("language")
            or item.get("tech")
            or item.get("technologies")
            or (item.get("issue") or {}).get("language")
            or ""
        )
        if isinstance(tech, list):
            tech = " ".join(str(t) for t in tech)
        lang = _detect_lang(str(tech) + " " + str(title))
        if lang not in _TARGET_LANGS:
            return

        url = (
            item.get("url")
            or item.get("html_url")
            or item.get("link")
            or (item.get("issue") or {}).get("html_url", "")
        )
        if not url:
            return

        labels = [str(lb) for lb in item.get("labels", [])]
        results.append(_make_entry(
            title=str(title),
            reward=reward,
            url=str(url),
            site="Algora",
            lang=lang,
            tags=labels[:5],
        ))
    except Exception as e:
        logger.debug(f"Algora item parse error: {e}")


def _fetch_algora_requests() -> list[dict]:
    """Requests-based fallback for Algora (no Playwright)."""
    results: list[dict] = []
    json_headers = {**_BROWSER_HEADERS, "Accept": "application/json"}
    html_headers = {**_BROWSER_HEADERS, "Accept": "text/html"}

    api_urls = [
        "https://algora.io/api/bounties?status=open&limit=100",
        "https://console.algora.io/bounties.json",
    ]
    items: list[dict] = []
    for url in api_urls:
        try:
            resp = requests.get(url, headers=json_headers, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", data.get("bounties", []))
            if items:
                break
        except Exception as e:
            logger.debug(f"Algora API {url} failed: {e}")

    if items:
        for item in items:
            _parse_algora_item(item, results)
        return results

    # HTML fallback
    try:
        from bs4 import BeautifulSoup

        resp = requests.get("https://algora.io/bounties", headers=html_headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        for card in soup.select("a[href*='/issues/'], a[href*='/bounties/']"):
            text = card.get_text(" ", strip=True)
            reward = _parse_usd(text)
            lang = _detect_lang(text)
            if not reward or reward < MIN_REWARD or lang not in _TARGET_LANGS:
                continue
            href = str(card.get("href", ""))
            if not href.startswith("http"):
                href = "https://algora.io" + href
            results.append(_make_entry(
                title=text[:120],
                reward=reward,
                url=href,
                site="Algora",
                lang=lang,
            ))
    except Exception as e:
        logger.warning(f"Algora HTML fallback failed: {e}")

    return results


# ── Main public API ────────────────────────────────────────────────────────

def find_bounties(force: bool = False) -> dict[str, Any]:
    """
    Search all bounty platforms and return top opportunities.

    Args:
        force: If True, bypass the 24h disk cache and re-scrape.

    Returns:
        {
            "found": bool,
            "count": int,
            "cached": bool,
            "cache_age_hours": float,
            "opportunities": list[dict]
        }
    """
    # Check cache
    if not force:
        cached = _cache_load()
        if cached is not None:
            all_results, age_hours = cached
            top = sorted(all_results, key=lambda x: x["reward"], reverse=True)[:TOP_N]
            return {
                "found": bool(top),
                "count": len(top),
                "cached": True,
                "cache_age_hours": round(age_hours, 2),
                "opportunities": top,
            }

    # Scrape all sources
    all_results: list[dict] = []
    sources = [
        ("GitHub", _fetch_github),
        ("Gitcoin", _fetch_gitcoin),
        ("IssueHunt", _fetch_issuehunt),
        ("Algora", _fetch_algora_playwright),
    ]

    for name, fetcher in sources:
        try:
            items = fetcher()
            logger.info(f"{name}: {len(items)} bounties found")
            all_results.extend(items)
        except Exception as e:
            logger.error(f"{name} fetch failed: {e}")

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for b in all_results:
        url = b.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(b)

    # Save full results to disk cache
    _cache_save(unique)

    # Return top N by reward
    top = sorted(unique, key=lambda x: x["reward"], reverse=True)[:TOP_N]

    return {
        "found": bool(top),
        "count": len(top),
        "cached": False,
        "cache_age_hours": 0.0,
        "opportunities": top,
    }


# ── CLI entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Find open software bounties")
    parser.add_argument("--force", action="store_true", help="Bypass 24h cache")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    result = find_bounties(force=args.force)

    indent = 2 if args.pretty else None
    print(json.dumps(result, indent=indent))

    if result["cached"]:
        print(f"\n[cache] Using {result['cache_age_hours']:.1f}h old results", file=sys.stderr)
    else:
        print(f"\n[fresh] Scraped {result['count']} opportunities across all platforms", file=sys.stderr)
