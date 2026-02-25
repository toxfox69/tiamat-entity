#!/usr/bin/env python3
"""
TIK-066 — GitHub Repository Health Analyzer
============================================
Fetches popular Python repos (language:python stars:>1000), calculates health
metrics, uses Groq llama-3.3-70b-versatile for per-repo AI analysis, and uses
Neynar to attempt Farcaster entity resolution on top contributors.

Metrics per repo:
  commit_frequency_per_week  — avg commits/week over last 90 days
  activity_trend             — ratio: recent 45d vs prior 45d commit count
  issue_resolution_hrs       — median hours to close an issue (last 100)
  pr_merge_rate_pct          — % of closed PRs that were merged (last 100)
  avg_pr_merge_hrs           — median hours from PR open → merge
  contributor_count          — unique contributors (last 100 commits)
  top10_contributor_share    — % of commits by top 10 contributors (bus factor)
  open_issue_ratio           — open issues / (open + estimated closed)
  release_cadence_days       — avg days between last 10 releases
  health_score               — composite 0-100 score

Usage:
  python github_repo_health.py                 # analyse 30 repos
  python github_repo_health.py -n 10           # analyse 10 repos
  python github_repo_health.py --no-groq       # skip AI summaries
  python github_repo_health.py --no-neynar     # skip Farcaster lookup
"""

import argparse
import json
import logging
import math
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from statistics import median
from typing import Any, Optional

import requests

# ─── Load environment ─────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv("/root/.env")
except ImportError:
    pass  # dotenv optional; fall through to os.getenv

GITHUB_TOKEN   = os.getenv("GITHUB_TOKEN", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
NEYNAR_API_KEY = os.getenv("NEYNAR_API_KEY", "")

OUTPUT_PATH    = "/root/.automaton/repo_health_results.json"
LOG_PATH       = "/root/.automaton/repo_health.log"

# ─── Tunables ─────────────────────────────────────────────────────────────────
DEFAULT_REPO_COUNT   = 30
COMMIT_WINDOW_DAYS   = 90
COMMITS_PER_REPO     = 100
ISSUES_PER_REPO      = 100
PRS_PER_REPO         = 100
NEYNAR_LOOKUP_TOP_N  = 5     # top N contributors to look up on Farcaster
GROQ_MODEL           = "llama-3.3-70b-versatile"
MAX_RETRIES          = 3
BACKOFF_BASE         = 2.0   # seconds

GITHUB_API   = "https://api.github.com"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
NEYNAR_URL   = "https://api.neynar.com/v2/farcaster/user/search"


# ─── Logging ──────────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("repo_health")


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.rstrip("Z") + "+00:00")
    except ValueError:
        return None


def _get(url: str, params: dict = None, headers: dict = None,
         retries: int = MAX_RETRIES) -> Optional[requests.Response]:
    """GET with exponential back-off and GitHub / Groq rate-limit awareness."""
    params  = params or {}
    headers = headers or {}
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=25)

            # GitHub primary rate limit
            if resp.status_code == 403:
                reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait  = max(reset - int(time.time()) + 2, 5)
                log.warning("GitHub 403 rate limit — sleeping %ds", wait)
                time.sleep(min(wait, 130))
                continue

            # Generic 429
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 30))
                log.warning("429 Too Many Requests — sleeping %ds", wait)
                time.sleep(wait)
                continue

            # Transient server errors
            if resp.status_code >= 500:
                wait = BACKOFF_BASE ** attempt
                log.warning("Server %d on %s — retry %d/%d in %.1fs",
                             resp.status_code, url, attempt + 1, retries, wait)
                time.sleep(wait)
                continue

            return resp

        except requests.RequestException as exc:
            wait = BACKOFF_BASE ** attempt
            log.error("Request error (%s) — retry %d/%d in %.1fs", exc, attempt + 1, retries, wait)
            time.sleep(wait)

    log.error("Giving up on %s after %d attempts", url, retries)
    return None


def _gh_headers() -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def _paginate(url: str, params: dict = None, extra_headers: dict = None,
              max_items: int = 500, page_size: int = 100,
              result_key: str = None) -> list:
    """
    Iterate GitHub Link-header pagination up to max_items.
    result_key: if set, unwrap data[result_key] from each page (e.g. 'items').
    """
    items   = []
    params  = dict(params or {})
    params.setdefault("per_page", min(page_size, 100))
    headers = {**_gh_headers(), **(extra_headers or {})}
    cur_url = url if url.startswith("http") else GITHUB_API + url

    while cur_url and len(items) < max_items:
        resp = _get(cur_url, params=params, headers=headers)
        if resp is None or resp.status_code != 200:
            break

        data = resp.json()
        if isinstance(data, dict):
            batch = data.get(result_key or "items", data if not result_key else [])
        else:
            batch = data

        if not batch:
            break
        items.extend(batch)

        next_url = resp.links.get("next", {}).get("url")
        cur_url  = next_url
        params   = {}  # already encoded in next_url
        time.sleep(0.25)

    return items[:max_items]


# ─── GitHub data fetchers ─────────────────────────────────────────────────────

def fetch_popular_repos(count: int = DEFAULT_REPO_COUNT) -> list[dict]:
    log.info("Fetching top %d popular Python repos (stars:>1000) …", count)
    items = _paginate(
        "/search/repositories",
        params={"q": "language:python stars:>1000", "sort": "stars", "order": "desc"},
        max_items=count,
        result_key="items",
    )
    log.info("Fetched %d repos", len(items))
    return items[:count]


def fetch_commits(owner: str, repo: str) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=COMMIT_WINDOW_DAYS)).isoformat()
    return _paginate(
        f"/repos/{owner}/{repo}/commits",
        params={"since": since},
        max_items=COMMITS_PER_REPO,
    )


def fetch_issues(owner: str, repo: str) -> list[dict]:
    return _paginate(
        f"/repos/{owner}/{repo}/issues",
        params={"state": "closed", "sort": "updated", "direction": "desc"},
        max_items=ISSUES_PER_REPO,
    )


def fetch_pulls(owner: str, repo: str) -> list[dict]:
    return _paginate(
        f"/repos/{owner}/{repo}/pulls",
        params={"state": "closed", "sort": "updated", "direction": "desc"},
        max_items=PRS_PER_REPO,
    )


def fetch_contributors(owner: str, repo: str) -> list[dict]:
    return _paginate(
        f"/repos/{owner}/{repo}/contributors",
        params={"anon": "false"},
        max_items=100,
    )


def fetch_releases(owner: str, repo: str) -> list[dict]:
    return _paginate(
        f"/repos/{owner}/{repo}/releases",
        max_items=10,
    )


# ─── Metric calculators ───────────────────────────────────────────────────────

def _commit_metrics(commits: list[dict]) -> dict:
    now   = datetime.now(timezone.utc)
    mid   = now - timedelta(days=COMMIT_WINDOW_DAYS // 2)
    dates = [
        _parse_dt(c.get("commit", {}).get("author", {}).get("date"))
        for c in commits
    ]
    dates = [d for d in dates if d]

    freq_per_week = (len(dates) / COMMIT_WINDOW_DAYS) * 7 if dates else 0.0

    recent = sum(1 for d in dates if d >= mid)
    older  = sum(1 for d in dates if d < mid)
    if older == 0:
        trend = 1.0 if recent > 0 else 0.0
    else:
        trend = (recent - older) / older

    return {
        "commit_frequency_per_week": round(freq_per_week, 2),
        "commits_sampled":           len(dates),
        "activity_trend":            round(trend, 3),
    }


def _issue_metrics(issues: list[dict]) -> dict:
    """Median issue resolution time from closed non-PR issues."""
    resolution_hrs = []
    for iss in issues:
        if iss.get("pull_request"):
            continue
        created = _parse_dt(iss.get("created_at"))
        closed  = _parse_dt(iss.get("closed_at"))
        if created and closed:
            resolution_hrs.append((closed - created).total_seconds() / 3600)

    return {
        "issue_resolution_hrs":   round(median(resolution_hrs), 1) if resolution_hrs else None,
        "issues_sampled":         len(resolution_hrs),
    }


def _pr_metrics(pulls: list[dict]) -> dict:
    """PR merge rate and median merge time from closed PRs."""
    closed = [p for p in pulls if p.get("state") == "closed"]
    merged = [p for p in closed  if p.get("merged_at")]

    merge_hrs = []
    for pr in merged:
        created = _parse_dt(pr.get("created_at"))
        merged_at = _parse_dt(pr.get("merged_at"))
        if created and merged_at:
            merge_hrs.append((merged_at - created).total_seconds() / 3600)

    return {
        "pr_merge_rate_pct":  round(len(merged) / len(closed) * 100, 1) if closed else None,
        "avg_pr_merge_hrs":   round(median(merge_hrs), 1) if merge_hrs else None,
        "prs_sampled":        len(closed),
        "prs_merged":         len(merged),
    }


def _contributor_metrics(contributors: list[dict], commits: list[dict]) -> dict:
    """Contributor count and bus-factor concentration."""
    contributor_count = len(contributors)

    # Build login → commit count from fetched commits
    login_counts: Counter = Counter()
    for c in commits:
        login = (c.get("author") or {}).get("login")
        if login:
            login_counts[login] += 1

    total   = sum(login_counts.values()) or 1
    top10   = sum(v for _, v in login_counts.most_common(10))
    bus_pct = round(top10 / total * 100, 1) if total else None

    return {
        "contributor_count":          contributor_count,
        "top10_contributor_share_pct": bus_pct,
    }


def _release_cadence(releases: list[dict]) -> Optional[float]:
    dates = sorted(
        [_parse_dt(r.get("published_at")) for r in releases if r.get("published_at")]
    )
    if len(dates) < 2:
        return None
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    return round(sum(gaps) / len(gaps), 1)


def _open_issue_ratio(repo_meta: dict) -> float:
    open_cnt = repo_meta.get("open_issues_count", 0)
    stars    = max(repo_meta.get("stargazers_count", 1), 1)
    est_total = max(open_cnt, stars // 50, 1)
    return round(open_cnt / est_total, 3)


def compute_health_score(m: dict) -> float:
    """
    Composite 0-100 score.

    Weights:
      commit_frequency_per_week  25 pts  (≥10=25, ≥5=18, ≥2=10, else 3)
      activity_trend             10 pts  (≥0.5=10, ≥0=7, ≥-0.3=3, else 0)
      issue_resolution_hrs       20 pts  (<24h=20, <72h=15, <168h=10, <720h=5, else 0)
      pr_merge_rate_pct          20 pts  (≥80=20, ≥60=15, ≥40=10, else 5)
      contributor_count          15 pts  (≥50=15, ≥20=10, ≥5=5, else 2)
      release_cadence_days        5 pts  (≤30=5, ≤90=3, ≤365=1, else 0)
      stars (log scale)           5 pts  (normalised log10)
    """
    score = 0.0

    cf = m.get("commit_frequency_per_week", 0)
    score += 25 if cf >= 10 else 18 if cf >= 5 else 10 if cf >= 2 else 3

    at = m.get("activity_trend", 0)
    score += 10 if at >= 0.5 else 7 if at >= 0 else 3 if at >= -0.3 else 0

    irt = m.get("issue_resolution_hrs")
    if irt is None:
        score += 5  # no data — neutral
    else:
        score += 20 if irt < 24 else 15 if irt < 72 else 10 if irt < 168 else 5 if irt < 720 else 0

    pmr = m.get("pr_merge_rate_pct")
    if pmr is None:
        score += 5
    else:
        score += 20 if pmr >= 80 else 15 if pmr >= 60 else 10 if pmr >= 40 else 5

    cc = m.get("contributor_count", 0)
    score += 15 if cc >= 50 else 10 if cc >= 20 else 5 if cc >= 5 else 2

    rc = m.get("release_cadence_days")
    if rc is not None:
        score += 5 if rc <= 30 else 3 if rc <= 90 else 1 if rc <= 365 else 0

    stars = m.get("stars", 0)
    score += min(math.log10(max(stars, 1)) / 5, 1.0) * 5

    return round(min(score, 100), 1)


# ─── Neynar entity recognition ───────────────────────────────────────────────

def _neynar_lookup(username: str) -> Optional[dict]:
    if not NEYNAR_API_KEY:
        return None
    resp = _get(
        NEYNAR_URL,
        params={"q": username, "limit": 1},
        headers={"accept": "application/json", "api_key": NEYNAR_API_KEY},
    )
    if resp is None or resp.status_code != 200:
        return None
    users = resp.json().get("result", {}).get("users", [])
    return users[0] if users else None


def enrich_contributors(contributors: list[dict], skip: bool = False) -> list[dict]:
    """
    Return enriched contributor list (top NEYNAR_LOOKUP_TOP_N) with Farcaster
    identity data where available.
    """
    enriched = []
    for c in contributors[:NEYNAR_LOOKUP_TOP_N]:
        login = c.get("login", "")
        entry = {
            "github_login":        login,
            "github_contributions": c.get("contributions", 0),
            "farcaster":           None,
        }
        if not skip and login:
            fc = _neynar_lookup(login)
            if fc:
                entry["farcaster"] = {
                    "username":     fc.get("username"),
                    "display_name": fc.get("display_name"),
                    "fid":          fc.get("fid"),
                    "bio":          (fc.get("profile") or {}).get("bio", {}).get("text", ""),
                    "follower_count": fc.get("follower_count", 0),
                }
            time.sleep(0.2)
    return enriched


# ─── Groq AI analysis ─────────────────────────────────────────────────────────

def _groq_post(messages: list[dict], max_tokens: int = 350) -> str:
    if not GROQ_API_KEY:
        return "Groq API key not configured."

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       GROQ_MODEL,
                    "messages":    messages,
                    "max_tokens":  max_tokens,
                    "temperature": 0.3,
                },
                timeout=35,
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 20))
                log.warning("Groq 429 — sleeping %ds", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except requests.RequestException as exc:
            wait = BACKOFF_BASE ** attempt
            log.error("Groq error: %s — retry %d/%d in %.1fs", exc, attempt + 1, MAX_RETRIES, wait)
            time.sleep(wait)

    return "Groq analysis unavailable after retries."


def groq_analyse_repo(full_name: str, description: str, metrics: dict) -> str:
    prompt = (
        f"You are a senior open-source analyst. Evaluate the health of the GitHub "
        f"repository '{full_name}'.\n\n"
        f"Description: {description or 'N/A'}\n\n"
        "Key metrics:\n"
        f"  Stars:                        {metrics.get('stars', 'N/A'):,}\n"
        f"  Commit frequency:             {metrics.get('commit_frequency_per_week')} commits/week\n"
        f"  Activity trend (last 90d):    {metrics.get('activity_trend'):+.2f} "
        "(positive = growing, negative = declining)\n"
        f"  Median issue close time:      {metrics.get('issue_resolution_hrs')} hours\n"
        f"  PR merge rate:                {metrics.get('pr_merge_rate_pct')}%\n"
        f"  Avg PR merge time:            {metrics.get('avg_pr_merge_hrs')} hours\n"
        f"  Active contributors:          {metrics.get('contributor_count')}\n"
        f"  Top-10 contributor share:     {metrics.get('top10_contributor_share_pct')}%\n"
        f"  Release cadence:              {metrics.get('release_cadence_days')} days\n"
        f"  Health score:                 {metrics.get('health_score')}/100\n\n"
        "In exactly 3 sentences: (1) overall health verdict, "
        "(2) strongest signal, (3) one actionable recommendation."
    )
    return _groq_post([{"role": "user", "content": prompt}], max_tokens=300)


def groq_ecosystem_summary(results: list[dict]) -> str:
    compact = json.dumps(
        [
            {
                "repo":         r["repo"]["full_name"],
                "health_score": r["metrics"]["health_score"],
                "stars":        r["repo"]["stars"],
                "commit_freq":  r["metrics"]["commit_frequency_per_week"],
                "pr_merge_pct": r["metrics"]["pr_merge_rate_pct"],
                "issue_close_hrs": r["metrics"]["issue_resolution_hrs"],
                "contributors": r["metrics"]["contributor_count"],
            }
            for r in results
        ],
        indent=2,
    )
    prompt = (
        "You are a senior open-source analyst. Below is a health report for the "
        "top Python repositories on GitHub. Write a concise executive summary "
        "(4-5 sentences) covering: ecosystem-wide health, standout repos, "
        "warning signs, and one key recommendation for the OSS community.\n\n"
        f"Data:\n{compact}"
    )
    return _groq_post([{"role": "user", "content": prompt}], max_tokens=512)


# ─── Main analysis pipeline ───────────────────────────────────────────────────

def analyse_repo(repo_meta: dict, skip_groq: bool = False,
                 skip_neynar: bool = False) -> dict:
    owner = repo_meta["owner"]["login"]
    name  = repo_meta["name"]
    full  = repo_meta["full_name"]

    log.info("  Analysing %s (★ %s) …", full, f"{repo_meta.get('stargazers_count', 0):,}")

    # Parallel-style: fetch all data before computing metrics
    commits      = fetch_commits(owner, name)
    issues       = fetch_issues(owner, name)
    pulls        = fetch_pulls(owner, name)
    contributors = fetch_contributors(owner, name)
    releases     = fetch_releases(owner, name)

    # --- Metrics ---
    cm  = _commit_metrics(commits)
    ism = _issue_metrics(issues)
    prm = _pr_metrics(pulls)
    ctm = _contributor_metrics(contributors, commits)
    rc  = _release_cadence(releases)
    oir = _open_issue_ratio(repo_meta)

    stars = repo_meta.get("stargazers_count", 0)

    metrics = {
        "stars":                      stars,
        "commit_frequency_per_week":  cm["commit_frequency_per_week"],
        "commits_sampled_90d":        cm["commits_sampled"],
        "activity_trend":             cm["activity_trend"],
        "issue_resolution_hrs":       ism["issue_resolution_hrs"],
        "issues_sampled":             ism["issues_sampled"],
        "pr_merge_rate_pct":          prm["pr_merge_rate_pct"],
        "avg_pr_merge_hrs":           prm["avg_pr_merge_hrs"],
        "prs_sampled":                prm["prs_sampled"],
        "prs_merged":                 prm["prs_merged"],
        "contributor_count":          ctm["contributor_count"],
        "top10_contributor_share_pct": ctm["top10_contributor_share_pct"],
        "open_issue_ratio":           oir,
        "release_cadence_days":       rc,
    }
    metrics["health_score"] = compute_health_score(metrics)

    # --- Neynar enrichment ---
    enriched_contributors = enrich_contributors(contributors, skip=skip_neynar)

    # --- Groq per-repo analysis ---
    ai_analysis = (
        groq_analyse_repo(full, repo_meta.get("description", ""), metrics)
        if not skip_groq else None
    )

    return {
        "repo": {
            "full_name":   full,
            "owner":       owner,
            "name":        name,
            "description": repo_meta.get("description", ""),
            "url":         repo_meta.get("html_url", ""),
            "stars":       stars,
            "forks":       repo_meta.get("forks_count", 0),
            "watchers":    repo_meta.get("watchers_count", 0),
            "open_issues": repo_meta.get("open_issues_count", 0),
            "language":    repo_meta.get("language", "Python"),
            "license":     (repo_meta.get("license") or {}).get("spdx_id"),
            "topics":      repo_meta.get("topics", []),
            "created_at":  repo_meta.get("created_at"),
            "pushed_at":   repo_meta.get("pushed_at"),
        },
        "metrics":               metrics,
        "top_contributors":      enriched_contributors,
        "ai_analysis":           ai_analysis,
        "analysed_at":           datetime.now(timezone.utc).isoformat(),
    }


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="TIK-066 GitHub Repo Health Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-n", "--repos", type=int, default=DEFAULT_REPO_COUNT,
                        metavar="N",
                        help=f"Number of repos to analyse (default: {DEFAULT_REPO_COUNT})")
    parser.add_argument("--output", default=OUTPUT_PATH, metavar="FILE",
                        help=f"JSON output path (default: {OUTPUT_PATH})")
    parser.add_argument("--no-groq",   action="store_true",
                        help="Skip Groq AI analysis")
    parser.add_argument("--no-neynar", action="store_true",
                        help="Skip Neynar/Farcaster contributor lookup")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable DEBUG logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not GITHUB_TOKEN:
        log.error("GITHUB_TOKEN not set — GitHub API rate limits will be very low")

    if not GROQ_API_KEY and not args.no_groq:
        log.warning("GROQ_API_KEY not set — skipping AI analysis")
        args.no_groq = True

    if not NEYNAR_API_KEY and not args.no_neynar:
        log.warning("NEYNAR_API_KEY not set — skipping Farcaster lookup")
        args.no_neynar = True

    # ── Fetch repo list ────────────────────────────────────────────────────────
    repos   = fetch_popular_repos(args.repos)
    results = []
    errors  = []
    t_start = time.time()

    log.info("=" * 62)
    log.info("Analysing %d repositories …", len(repos))
    log.info("=" * 62)

    for i, repo_meta in enumerate(repos, 1):
        full = repo_meta.get("full_name", "unknown")
        log.info("[%d/%d] %s", i, len(repos), full)
        try:
            result = analyse_repo(repo_meta,
                                  skip_groq=args.no_groq,
                                  skip_neynar=args.no_neynar)
            results.append(result)
            m = result["metrics"]
            log.info("       score=%.1f  commits/wk=%.1f  trend=%+.2f  contributors=%d",
                     m["health_score"], m["commit_frequency_per_week"],
                     m["activity_trend"], m["contributor_count"])
        except Exception as exc:
            log.error("Failed to analyse %s: %s", full, exc, exc_info=args.verbose)
            errors.append({"repo": full, "error": str(exc)})

        time.sleep(0.8)  # polite inter-repo pause

    # Sort by health score descending
    results.sort(key=lambda r: r["metrics"]["health_score"], reverse=True)

    # ── Ecosystem summary ──────────────────────────────────────────────────────
    ecosystem_summary = None
    if not args.no_groq and results:
        log.info("Generating Groq ecosystem summary …")
        ecosystem_summary = groq_ecosystem_summary(results)

    # ── Write output ───────────────────────────────────────────────────────────
    elapsed = round(time.time() - t_start, 1)
    output  = {
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": elapsed,
        "query":           "language:python stars:>1000",
        "repos_analysed":  len(results),
        "repos_failed":    len(errors),
        "ecosystem_summary": ecosystem_summary,
        "results":         results,
        "errors":          errors,
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False, default=str)

    # ── Terminal summary ───────────────────────────────────────────────────────
    log.info("=" * 62)
    log.info("DONE — %d repos in %.1fs  |  output: %s", len(results), elapsed, args.output)
    log.info("=" * 62)

    top = results[:10]
    col_w = max((len(r["repo"]["full_name"]) for r in top), default=20) + 2

    print(f"\n{'REPO':<{col_w}} {'SCORE':>6}  {'COMMITS/WK':>11}  {'TREND':>7}  {'CONTRIBS':>9}")
    print("─" * (col_w + 42))
    for r in top:
        m = r["metrics"]
        print(
            f"{r['repo']['full_name']:<{col_w}}"
            f" {m['health_score']:>6.1f}"
            f"  {m['commit_frequency_per_week']:>11.1f}"
            f"  {m['activity_trend']:>+7.2f}"
            f"  {m['contributor_count']:>9}"
        )
    print(f"\nFull JSON → {args.output}")

    if ecosystem_summary:
        print(f"\n── Ecosystem Summary ──\n{ecosystem_summary}\n")


if __name__ == "__main__":
    main()
