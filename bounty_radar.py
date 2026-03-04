#!/usr/bin/env python3
"""
TIAMAT Bounty Radar — Multi-platform bounty scanner
Platforms: GitHub (label:bounty), SCI, Algora (scraped), Gitcoin
Output: /root/.automaton/bounty_radar.json
"""

import os
import re
import json
import time
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# ─── Config ───────────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "REDACTED_GITHUB_TOKEN")
OUTPUT_FILE = "/root/.automaton/bounty_radar.json"
ALERT_FILE  = "/root/.automaton/bounty_alerts.json"

HEADERS_GH = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "TIAMAT-BountyRadar/1.0",
}
HEADERS_WEB = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

# ─── Language detection ────────────────────────────────────────────────────────
LANG_PRIORITY = {
    "python": 1.0, "typescript": 1.0, "javascript": 0.9,
    "rust": 0.8, "go": 0.8, "solidity": 0.75,
    "java": 0.6, "c++": 0.5, "c": 0.5,
}

def detect_language(text: str) -> tuple[str, float]:
    """Return (language, priority_multiplier) from text."""
    text_lower = text.lower()
    for lang, priority in LANG_PRIORITY.items():
        if lang in text_lower:
            return lang, priority
    return "unknown", 0.5


def extract_usd_value(text: str) -> float:
    """Extract dollar value from text like '$300', '300 USDC', '0.5 ETH'."""
    # Reject if dollar amount appears after "replaces $X" or "saves $X" (cost comparison, not bounty)
    reject_patterns = [
        r"replaces?\s+\$[\d,]+",
        r"saves?\s+\$[\d,]+",
        r"worth\s+\$[\d,]+\s+/?\s*(yr|year|mo|month|annual)",
        r"\$[\d,]+\s*/\s*(yr|year|mo|month)",
        r"awarded\s+\w+\s+a\s+\$",   # "awarded pal0x a $640 tip"
        r"\$\d+\s+tip\b",
    ]
    for rp in reject_patterns:
        if re.search(rp, text, re.IGNORECASE):
            return 0.0

    # Direct USD/USDC amounts — look for bounty-context first
    bounty_patterns = [
        r"bounty[:\s]+\$\s*(\d[\d,]*(?:\.\d+)?)",  # "Bounty: $300"
        r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*bounty",      # "$300 bounty"
        r"reward[:\s]+\$\s*(\d[\d,]*(?:\.\d+)?)",   # "Reward: $500"
        r"prize[:\s]+\$\s*(\d[\d,]*(?:\.\d+)?)",    # "Prize: $200"
    ]
    for pat in bounty_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = float(m.group(1).replace(",", ""))
            if 5 < val < 50000:
                return val

    # General dollar extraction (title gets priority — less noise)
    patterns = [
        r"\$\s*(\d[\d,]*(?:\.\d+)?)",       # $300, $1,000
        r"(\d[\d,]*(?:\.\d+)?)\s*USD[CT]?", # 300 USDC, 300 USDT
        r"(\d[\d,]*(?:\.\d+)?)\s*dollars?",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = float(m.group(1).replace(",", ""))
            if 5 < val < 10000:  # Cap at $10k — anything higher likely a cost comparison
                return val

    # Crypto conversions (rough estimates)
    eth_match = re.search(r"(\d+(?:\.\d+)?)\s*ETH", text, re.IGNORECASE)
    if eth_match:
        return float(eth_match.group(1)) * 2500  # rough ETH price

    return 0.0


def estimate_complexity(title: str, body: str) -> tuple[str, int]:
    """Return (complexity_label, score_delta)."""
    text = (title + " " + (body or "")).lower()
    if any(k in text for k in ["good first issue", "easy", "simple", "typo", "docs", "readme", "lint"]):
        return "easy", 2
    if any(k in text for k in ["bug", "fix", "crash", "error", "broken"]):
        return "bug", 1
    if any(k in text for k in ["feature", "implement", "add", "create", "integrate"]):
        return "feature", 0
    if any(k in text for k in ["refactor", "optimize", "performance", "architecture", "design"]):
        return "advanced", -1
    return "unknown", 0


def estimate_minutes(title: str, body: str, complexity: str) -> int:
    """Rough time estimate in minutes."""
    base = {"easy": 15, "bug": 25, "feature": 45, "advanced": 90, "unknown": 35}
    mins = base.get(complexity, 35)
    # Short body = well-specified = faster
    body_len = len(body or "")
    if body_len < 200:
        mins = max(10, mins - 10)
    elif body_len > 2000:
        mins += 15
    return mins


def score_bounty(value_usd: float, lang_mult: float, complexity_delta: int,
                 estimate_mins: int, is_claimed: bool) -> float:
    """Score 1-10 weighted by value + solvability."""
    if is_claimed or value_usd == 0:
        return 0.0

    # Value score (0-4 pts) — sweet spot $300-500
    if 300 <= value_usd <= 500:
        val_score = 4.0
    elif 200 <= value_usd < 300:
        val_score = 3.0
    elif 500 < value_usd <= 1000:
        val_score = 3.5
    elif 100 <= value_usd < 200:
        val_score = 2.0
    elif value_usd > 1000:
        val_score = 2.5  # high value but probably hard
    else:
        val_score = 1.0

    # Speed score (0-3 pts) — prefer <30 min
    if estimate_mins <= 20:
        speed_score = 3.0
    elif estimate_mins <= 30:
        speed_score = 2.5
    elif estimate_mins <= 45:
        speed_score = 2.0
    elif estimate_mins <= 60:
        speed_score = 1.5
    else:
        speed_score = 0.5

    # Language score (0-2 pts)
    lang_score = lang_mult * 2.0

    # Complexity delta (-1 to +2 pts)
    complexity_score = complexity_delta

    raw = val_score + speed_score + lang_score + complexity_score
    return round(min(10.0, max(0.0, raw)), 1)


# ─── GitHub Scanner ────────────────────────────────────────────────────────────
def scan_github_bounties(max_results=100) -> list[dict]:
    """Search GitHub issues with bounty labels containing dollar amounts."""
    print("[github] Scanning GitHub bounty issues...")
    bounties = []
    seen_urls = set()

    queries = [
        'label:bounty state:open is:issue "$" in:title',
        'label:bounty state:open is:issue "USD" in:title',
        'label:bounty state:open is:issue "$" in:body language:python',
        'label:bounty state:open is:issue "$" in:body language:typescript',
        'label:"good first issue" label:bounty state:open is:issue',
        # Algora-style: issues with dollar amounts from known bounty orgs
        'label:bounty state:open is:issue python typescript in:title',
    ]

    for q in queries:
        if len(bounties) >= max_results:
            break
        try:
            url = "https://api.github.com/search/issues"
            params = {"q": q, "sort": "created", "order": "desc", "per_page": 30}
            resp = requests.get(url, headers=HEADERS_GH, params=params, timeout=15)
            if resp.status_code == 403:
                print(f"  [github] Rate limited, waiting 60s...")
                time.sleep(60)
                continue
            if resp.status_code != 200:
                print(f"  [github] Error {resp.status_code} for query: {q[:50]}")
                continue

            data = resp.json()
            for issue in data.get("items", []):
                url_key = issue["html_url"]
                if url_key in seen_urls:
                    continue
                seen_urls.add(url_key)

                title = issue.get("title", "")
                body = issue.get("body", "") or ""
                full_text = title + " " + body

                # Extract value
                value = extract_usd_value(full_text)
                if value < 50:  # Skip tiny or zero bounties
                    continue

                # Check if claimed (has assignee)
                is_claimed = bool(issue.get("assignees") or issue.get("assignee"))

                lang, lang_mult = detect_language(full_text)
                complexity, comp_delta = estimate_complexity(title, body)
                est_mins = estimate_minutes(title, body, complexity)
                score = score_bounty(value, lang_mult, comp_delta, est_mins, is_claimed)

                if score < 1.0:
                    continue

                repo_url = issue["repository_url"].replace("https://api.github.com/repos/", "https://github.com/")

                bounties.append({
                    "id": f"gh_{issue['number']}_{issue['repository_url'].split('/')[-1]}",
                    "title": title[:120],
                    "platform": "github",
                    "repo_url": repo_url,
                    "issue_url": issue["html_url"],
                    "value_usd": value,
                    "language": lang,
                    "description": body[:300].strip() if body else "",
                    "score": score,
                    "estimate_minutes": est_mins,
                    "status": "claimed" if is_claimed else "open",
                    "labels": [l["name"] for l in issue.get("labels", [])],
                    "created_at": issue.get("created_at", ""),
                })

            time.sleep(1.5)  # Rate limit respect

        except Exception as e:
            print(f"  [github] Exception: {e}")

    print(f"  [github] Found {len(bounties)} bounties")
    return bounties


# ─── SCI Bounties ─────────────────────────────────────────────────────────────
def scan_sci_bounties() -> list[dict]:
    """Scan github.com/TheSCInitiative/bounties/issues"""
    print("[sci] Scanning SCI Initiative bounties...")
    bounties = []
    try:
        url = "https://api.github.com/repos/TheSCInitiative/bounties/issues"
        params = {"state": "open", "per_page": 50}
        resp = requests.get(url, headers=HEADERS_GH, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"  [sci] Error {resp.status_code}")
            return []

        for issue in resp.json():
            title = issue.get("title", "")
            body = issue.get("body", "") or ""
            full_text = title + " " + body

            value = extract_usd_value(full_text)
            is_claimed = bool(issue.get("assignees") or issue.get("assignee"))

            lang, lang_mult = detect_language(full_text)
            complexity, comp_delta = estimate_complexity(title, body)
            est_mins = estimate_minutes(title, body, complexity)
            score = score_bounty(value, lang_mult, comp_delta, est_mins, is_claimed)

            bounties.append({
                "id": f"sci_{issue['number']}",
                "title": title[:120],
                "platform": "sci",
                "repo_url": "https://github.com/TheSCInitiative/bounties",
                "issue_url": issue["html_url"],
                "value_usd": value,
                "language": lang,
                "description": body[:300].strip() if body else "",
                "score": score,
                "estimate_minutes": est_mins,
                "status": "claimed" if is_claimed else "open",
                "labels": [l["name"] for l in issue.get("labels", [])],
                "created_at": issue.get("created_at", ""),
            })

    except Exception as e:
        print(f"  [sci] Exception: {e}")

    print(f"  [sci] Found {len(bounties)} bounties")
    return bounties


# ─── Algora Scanner ───────────────────────────────────────────────────────────
def scan_algora() -> list[dict]:
    """
    Algora has no public REST API. Strategy:
    1. Try scraping algora.io/bounties HTML
    2. Fallback: search GitHub for issues from Algora-paying orgs
    """
    print("[algora] Scanning Algora bounties...")
    bounties = []

    # Method 1: Scrape Algora website
    try:
        resp = requests.get("https://algora.io/bounties", headers=HEADERS_WEB, timeout=20)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            # Algora renders bounties server-side with specific data attributes
            # Look for bounty cards / list items
            cards = soup.find_all(attrs={"data-bounty": True})
            if not cards:
                # Try finding bounty links in the page
                cards = soup.find_all("a", href=re.compile(r"/[^/]+/[^/]+/issues/\d+"))

            for card in cards[:20]:
                try:
                    text = card.get_text(" ", strip=True)
                    href = card.get("href") or ""
                    href = str(href)
                    if not href:
                        continue
                    if not href.startswith("http"):
                        href = "https://algora.io" + href

                    # Skip tip/award notifications
                    if re.search(r"\b(awarded|tip|tipped)\b", text, re.IGNORECASE):
                        continue

                    value = extract_usd_value(text)
                    card_title = text[:100] if text else "Algora bounty"
                    lang, lang_mult = detect_language(text)
                    complexity, comp_delta = estimate_complexity(card_title, "")
                    est_mins = estimate_minutes(card_title, "", complexity)
                    score = score_bounty(value, lang_mult, comp_delta, est_mins, False)

                    bounties.append({
                        "id": f"algora_{abs(hash(href)) % 999999}",
                        "title": card_title,
                        "platform": "algora",
                        "repo_url": href,
                        "issue_url": href,
                        "value_usd": value,
                        "language": lang,
                        "description": "",
                        "score": score,
                        "estimate_minutes": est_mins,
                        "status": "open",
                        "labels": [],
                        "created_at": "",
                    })
                except Exception:
                    pass

    except Exception as e:
        print(f"  [algora] Scrape failed: {e}")

    # Method 2: GitHub search for Algora-linked repos (they put $ amounts in issue titles)
    if len(bounties) < 3:
        print("  [algora] Falling back to GitHub search for Algora bounties...")
        try:
            # Algora bounty hunters typically post issues with "algora" in body or specific dollar labels
            queries = [
                'algora label:bounty state:open is:issue "$" in:title',
                'label:bounty state:open is:issue "algora.io" in:body',
            ]
            seen = set()
            for q in queries:
                resp = requests.get(
                    "https://api.github.com/search/issues",
                    headers=HEADERS_GH,
                    params={"q": q, "per_page": 20},
                    timeout=15,
                )
                if resp.status_code == 200:
                    for issue in resp.json().get("items", []):
                        url = issue["html_url"]
                        if url in seen:
                            continue
                        seen.add(url)

                        title = issue.get("title", "")
                        body = issue.get("body", "") or ""
                        full_text = title + " " + body
                        value = extract_usd_value(full_text)
                        is_claimed = bool(issue.get("assignees"))
                        lang, lang_mult = detect_language(full_text)
                        complexity, comp_delta = estimate_complexity(title, body)
                        est_mins = estimate_minutes(title, body, complexity)
                        score = score_bounty(value, lang_mult, comp_delta, est_mins, is_claimed)

                        repo_url = issue["repository_url"].replace(
                            "https://api.github.com/repos/", "https://github.com/"
                        )
                        bounties.append({
                            "id": f"algora_gh_{issue['number']}",
                            "title": title[:120],
                            "platform": "algora",
                            "repo_url": repo_url,
                            "issue_url": url,
                            "value_usd": value,
                            "language": lang,
                            "description": body[:300].strip(),
                            "score": score,
                            "estimate_minutes": est_mins,
                            "status": "claimed" if is_claimed else "open",
                            "labels": [l["name"] for l in issue.get("labels", [])],
                            "created_at": issue.get("created_at", ""),
                        })
                time.sleep(1)
        except Exception as e:
            print(f"  [algora] GitHub fallback failed: {e}")

    print(f"  [algora] Found {len(bounties)} bounties")
    return bounties


# ─── Gitcoin Scanner ──────────────────────────────────────────────────────────
def scan_gitcoin() -> list[dict]:
    """Scan Gitcoin/IssueHunt bounties. Gitcoin v0.1 API is deprecated; IssueHunt is primary."""
    print("[gitcoin] Scanning IssueHunt + Gitcoin bounties...")
    bounties = []

    # IssueHunt API
    try:
        resp = requests.get(
            "https://issuehunt.io/api/v1/issues",
            headers=HEADERS_WEB,
            params={"state": "open", "sort": "amount_desc", "limit": 30},
            timeout=20,
        )
        if resp.status_code == 200:
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", data.get("issues", []))
            for b in items[:30]:
                bid = str(b.get("id", b.get("number", "")))
                title = b.get("title", "")
                body = b.get("body", "") or ""
                issue_url = b.get("html_url", b.get("url", ""))
                repo_url = "/".join(issue_url.split("/")[:5]) if issue_url else ""
                value_usd = float(b.get("amount", b.get("value", 0)) or 0)
                is_claimed = b.get("state", "open") != "open"

                lang, lang_mult = detect_language(title + " " + body)
                complexity, comp_delta = estimate_complexity(title, body)
                est_mins = estimate_minutes(title, body, complexity)
                score = score_bounty(value_usd, lang_mult, comp_delta, est_mins, is_claimed)

                bounties.append({
                    "id": f"issuehunt_{bid}",
                    "title": title[:120],
                    "platform": "gitcoin",  # grouped under gitcoin slot
                    "repo_url": repo_url,
                    "issue_url": issue_url,
                    "value_usd": round(value_usd, 2),
                    "language": lang,
                    "description": body[:300].strip(),
                    "score": score,
                    "estimate_minutes": est_mins,
                    "status": "claimed" if is_claimed else "open",
                    "labels": [],
                    "created_at": b.get("created_at", ""),
                })
        else:
            print(f"  [issuehunt] HTTP {resp.status_code}")
    except Exception as e:
        print(f"  [issuehunt] Exception: {e}")

    # GitHub search for high-value bounties not caught by label scan
    if len(bounties) < 5:
        try:
            resp = requests.get(
                "https://api.github.com/search/issues",
                headers=HEADERS_GH,
                params={
                    "q": 'label:bounty state:open is:issue "python" OR "typescript" "$3" OR "$4" OR "$5" in:title',
                    "sort": "created", "order": "desc", "per_page": 15
                },
                timeout=15,
            )
            if resp.status_code == 200:
                for issue in resp.json().get("items", []):
                    title = issue.get("title", "")
                    body = issue.get("body", "") or ""
                    value = extract_usd_value(title + " " + body)
                    if value < 100:
                        continue
                    is_claimed = bool(issue.get("assignees"))
                    lang, lang_mult = detect_language(title + " " + body)
                    complexity, comp_delta = estimate_complexity(title, body)
                    est_mins = estimate_minutes(title, body, complexity)
                    score = score_bounty(value, lang_mult, comp_delta, est_mins, is_claimed)
                    repo_url = issue["repository_url"].replace(
                        "https://api.github.com/repos/", "https://github.com/"
                    )
                    bounties.append({
                        "id": f"gh_extra_{issue['number']}",
                        "title": title[:120],
                        "platform": "gitcoin",
                        "repo_url": repo_url,
                        "issue_url": issue["html_url"],
                        "value_usd": value,
                        "language": lang,
                        "description": body[:300].strip(),
                        "score": score,
                        "estimate_minutes": est_mins,
                        "status": "claimed" if is_claimed else "open",
                        "labels": [l["name"] for l in issue.get("labels", [])],
                        "created_at": issue.get("created_at", ""),
                    })
        except Exception as e:
            print(f"  [gitcoin] GitHub extra scan: {e}")

    print(f"  [gitcoin/issuehunt] Found {len(bounties)} bounties")
    return bounties


# ─── Alert System ─────────────────────────────────────────────────────────────
def check_alerts(new_bounties: list[dict], min_value: float = 300.0) -> list[dict]:
    """Compare against previous scan and return newly discovered bounties above threshold."""
    # Load previous scan
    try:
        with open(OUTPUT_FILE) as f:
            prev = json.load(f)
        prev_urls = {b["issue_url"] for b in prev.get("bounties", [])}
    except (FileNotFoundError, json.JSONDecodeError):
        prev_urls = set()

    new_high_value = []
    for b in new_bounties:
        if b["issue_url"] not in prev_urls and b["value_usd"] >= min_value and b["status"] == "open":
            new_high_value.append(b)

    return new_high_value


def write_alert(alerts: list[dict]):
    """Write alert file and print to log."""
    if not alerts:
        return
    print(f"\n🚨 ALERT: {len(alerts)} new bounty/bounties ≥$300 found!")
    alert_data = {
        "alert_time": datetime.now(timezone.utc).isoformat(),
        "count": len(alerts),
        "bounties": alerts,
    }
    with open(ALERT_FILE, "w") as f:
        json.dump(alert_data, f, indent=2)

    # Print summary
    for b in sorted(alerts, key=lambda x: -x["score"])[:5]:
        print(f"  ${b['value_usd']:.0f} | score={b['score']} | {b['title'][:60]}")
        print(f"  → {b['issue_url']}")


# ─── Main ─────────────────────────────────────────────────────────────────────
def run_scan():
    print(f"\n{'='*60}")
    print(f"TIAMAT Bounty Radar — {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"{'='*60}")

    all_bounties: list[dict] = []

    # Run all scanners
    all_bounties.extend(scan_github_bounties(max_results=80))
    time.sleep(2)
    all_bounties.extend(scan_sci_bounties())
    time.sleep(2)
    all_bounties.extend(scan_algora())
    time.sleep(2)
    all_bounties.extend(scan_gitcoin())

    # Deduplicate by issue URL
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for b in all_bounties:
        url = b.get("issue_url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped.append(b)
        elif not url:
            deduped.append(b)

    # Sort by score desc
    deduped.sort(key=lambda x: (-x["score"], -x["value_usd"]))

    # Check alerts before writing
    alerts = check_alerts(deduped)
    write_alert(alerts)

    # Top 3 open bounties
    open_bounties = [b for b in deduped if b["status"] == "open" and b["score"] > 0]
    top_3 = open_bounties[:3]

    # Build output
    output = {
        "scan_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_found": len(deduped),
        "open_count": len(open_bounties),
        "new_alerts": len(alerts),
        "bounties": deduped,
        "top_3": top_3,
    }

    # Write JSON
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Scan complete: {len(deduped)} total, {len(open_bounties)} open")
    print(f"📁 Results saved to {OUTPUT_FILE}")

    if top_3:
        print("\n🎯 Top 3 Bounties:")
        for i, b in enumerate(top_3, 1):
            print(f"  {i}. [{b['platform'].upper()}] ${b['value_usd']:.0f} | "
                  f"score={b['score']} | ~{b['estimate_minutes']}min | {b['language']}")
            print(f"     {b['title'][:70]}")
            print(f"     {b['issue_url']}")

    return output


if __name__ == "__main__":
    run_scan()
