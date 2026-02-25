#!/usr/bin/env python3
"""
GitHub Repository Health Analyzer
===================================
Fetches popular Python repositories from GitHub, calculates health metrics,
uses Groq LLM to generate a plain-English summary, and outputs a structured
JSON/Markdown report.

Metrics calculated per repo:
  - commit_velocity       : average commits per month (last 12 months)
  - issue_resolution_time : median days to close an issue (last 100 closed)
  - pr_merge_rate         : percentage of closed PRs that were merged (last 100)
  - contributor_count     : unique contributors in last 12 months
  - open_issue_ratio      : open issues / total issues (lower = healthier)
  - release_cadence       : average days between releases (last 10 releases)
  - stars_growth_rate     : approximate monthly star growth percentage
  - health_score          : composite 0-100 score derived from above metrics

Usage:
  export GITHUB_TOKEN=ghp_...
  export GROQ_API_KEY=gsk_...
  python github_repo_health.py                  # analyze default 5 repos
  python github_repo_health.py --repos owner/repo1 owner/repo2
  python github_repo_health.py --top 10         # fetch top-10 popular Python repos
  python github_repo_health.py --output report.json
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from statistics import median
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("repo_health")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GITHUB_API = "https://api.github.com"
GROQ_API   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# Default repos to analyze when none are provided on the CLI
DEFAULT_REPOS = [
    "psf/requests",
    "pallets/flask",
    "tiangolo/fastapi",
    "numpy/numpy",
    "pytorch/pytorch",
]

# ---------------------------------------------------------------------------
# GitHub API client
# ---------------------------------------------------------------------------

class GitHubClient:
    """Thin wrapper around the GitHub REST API with rate-limit awareness."""

    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def get(self, path: str, params: dict | None = None) -> Any:
        """
        GET a single page from the GitHub API.
        Automatically retries once on 403 rate-limit after waiting.
        """
        url = path if path.startswith("http") else f"{GITHUB_API}{path}"
        for _ in range(2):
            resp = self.session.get(url, params=params, timeout=20)
            if resp.status_code == 403 and "rate limit" in resp.text.lower():
                reset_ts = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait = max(reset_ts - int(time.time()) + 2, 5)
                log.warning("Rate limited — sleeping %ds", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("GitHub rate limit exceeded after retry")

    def paginate(self, path: str, params: dict | None = None, max_items: int = 100) -> list:
        """Fetch up to max_items results across pages (100 per page)."""
        params = dict(params or {})
        params["per_page"] = min(100, max_items)
        results = []
        url = path if path.startswith("http") else f"{GITHUB_API}{path}"
        while url and len(results) < max_items:
            resp = self.session.get(url, params=params, timeout=20)
            if resp.status_code == 403 and "rate limit" in resp.text.lower():
                reset_ts = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait = max(reset_ts - int(time.time()) + 2, 5)
                log.warning("Rate limited — sleeping %ds", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                # search endpoints wrap results in a "items" key
                data = data.get("items", [])
            results.extend(data)
            # Follow GitHub's Link header for next page
            link = resp.links.get("next", {}).get("url")
            url = link
            params = {}  # params are already encoded in the next URL
        return results[:max_items]

    def fetch_popular_python_repos(self, count: int = 5) -> list[dict]:
        """Return top-N Python repos by stars from GitHub search."""
        log.info("Fetching top %d popular Python repos from GitHub search …", count)
        items = self.paginate(
            "/search/repositories",
            params={
                "q": "language:python stars:>10000",
                "sort": "stars",
                "order": "desc",
            },
            max_items=count,
        )
        return [{"full_name": r["full_name"], "stars": r["stargazers_count"]} for r in items]


# ---------------------------------------------------------------------------
# Metric calculators
# ---------------------------------------------------------------------------

def _parse_dt(s: str) -> datetime:
    """Parse ISO-8601 datetime strings from GitHub (with or without trailing Z)."""
    s = s.rstrip("Z") + "+00:00"
    return datetime.fromisoformat(s)


def calc_commit_velocity(client: GitHubClient, repo: str) -> float:
    """
    Average commits per month over the last 12 months.
    Uses the /stats/commit_activity endpoint (52-week buckets).
    Falls back to counting /commits if stats endpoint returns 202.
    """
    try:
        data = client.get(f"/repos/{repo}/stats/commit_activity")
        if isinstance(data, list) and len(data) >= 12:
            total = sum(w["total"] for w in data[-12:])
            return round(total / 12, 1)
    except Exception as exc:
        log.debug("commit_activity failed for %s: %s", repo, exc)

    # Fallback: count commits in last 12 months via search
    since = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    commits = client.paginate(
        f"/repos/{repo}/commits",
        params={"since": since},
        max_items=500,
    )
    return round(len(commits) / 12, 1)


def calc_issue_resolution_time(client: GitHubClient, repo: str) -> float:
    """
    Median days to close an issue, based on the last 100 closed issues.
    Returns -1 if insufficient data.
    """
    issues = client.paginate(
        f"/repos/{repo}/issues",
        params={"state": "closed", "sort": "updated", "direction": "desc"},
        max_items=100,
    )
    # Exclude pull requests (GitHub returns PRs in /issues endpoint too)
    issues = [i for i in issues if "pull_request" not in i]
    if not issues:
        return -1.0

    durations = []
    for issue in issues:
        created = _parse_dt(issue["created_at"])
        closed  = _parse_dt(issue["closed_at"]) if issue.get("closed_at") else None
        if closed:
            durations.append((closed - created).total_seconds() / 86400)

    return round(median(durations), 1) if durations else -1.0


def calc_pr_merge_rate(client: GitHubClient, repo: str) -> float:
    """
    Percentage of closed PRs (last 100) that were merged rather than closed/rejected.
    Returns 0.0 if no closed PRs found.
    """
    prs = client.paginate(
        f"/repos/{repo}/pulls",
        params={"state": "closed", "sort": "updated", "direction": "desc"},
        max_items=100,
    )
    if not prs:
        return 0.0
    merged = sum(1 for pr in prs if pr.get("merged_at"))
    return round(merged / len(prs) * 100, 1)


def calc_contributor_count(client: GitHubClient, repo: str) -> int:
    """
    Unique contributors with at least one commit in the last 12 months.
    Uses /stats/contributors (per-week breakdown).
    """
    try:
        data = client.get(f"/repos/{repo}/stats/contributors")
        if not isinstance(data, list):
            raise ValueError("Unexpected response type")
        since_week = int(
            (datetime.now(timezone.utc) - timedelta(days=365)).timestamp()
        )
        active = sum(
            1
            for c in data
            if any(w["w"] >= since_week and w["c"] > 0 for w in c.get("weeks", []))
        )
        return active
    except Exception as exc:
        log.debug("stats/contributors failed for %s: %s", repo, exc)
        return -1


def calc_open_issue_ratio(repo_data: dict) -> float:
    """
    open_issues_count / (open_issues_count + closed proxy).
    GitHub only exposes open count directly; we use it relative to watchers as a proxy.
    Returns open_issues_count / max(1, total_estimated).
    Note: GitHub's open_issues_count includes open PRs.
    """
    open_issues = repo_data.get("open_issues_count", 0)
    # Heuristic: repos with more stars tend to have ~1 open issue per 100 stars
    stars = repo_data.get("stargazers_count", 1)
    estimated_total = max(open_issues, stars // 50, 1)
    return round(open_issues / estimated_total, 3)


def calc_release_cadence(client: GitHubClient, repo: str) -> float:
    """
    Average days between the last 10 releases.
    Returns -1 if fewer than 2 releases exist.
    """
    releases = client.paginate(
        f"/repos/{repo}/releases",
        params={"per_page": 10},
        max_items=10,
    )
    if len(releases) < 2:
        return -1.0

    dates = sorted(
        [_parse_dt(r["published_at"]) for r in releases if r.get("published_at")]
    )
    if len(dates) < 2:
        return -1.0

    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    return round(sum(gaps) / len(gaps), 1)


def calc_stars_growth_rate(client: GitHubClient, repo: str, current_stars: int) -> float:
    """
    Approximate monthly star growth percentage using the stargazers list.
    Looks at the 100th newest stargazer's timestamp to estimate growth rate.
    Returns 0.0 if data is insufficient.
    """
    try:
        # Request stargazers sorted by newest first — requires custom Accept header
        resp = client.session.get(
            f"{GITHUB_API}/repos/{repo}/stargazers",
            params={"per_page": 100},
            headers={"Accept": "application/vnd.github.star+json"},
            timeout=20,
        )
        resp.raise_for_status()
        stargazers = resp.json()
        if not stargazers:
            return 0.0
        oldest_in_batch = _parse_dt(stargazers[-1]["starred_at"])
        days_span = max(
            (datetime.now(timezone.utc) - oldest_in_batch).days, 1
        )
        stars_in_span = len(stargazers)
        monthly_growth = (stars_in_span / days_span) * 30
        rate = round(monthly_growth / max(current_stars, 1) * 100, 3)
        return rate
    except Exception as exc:
        log.debug("stars_growth_rate failed for %s: %s", repo, exc)
        return 0.0


def compute_health_score(metrics: dict) -> int:
    """
    Composite health score 0-100 derived from multiple weighted metrics.

    Scoring bands:
      commit_velocity (25pts)     : ≥30/mo=25, ≥15=18, ≥5=10, else 3
      issue_resolution_time (20pts): ≤3d=20, ≤7d=15, ≤30d=10, ≤90d=5, else 0
      pr_merge_rate (20pts)       : ≥80%=20, ≥60%=15, ≥40%=10, else 5
      contributor_count (15pts)   : ≥50=15, ≥20=10, ≥5=5, else 2
      open_issue_ratio (10pts)    : ≤0.1=10, ≤0.3=7, ≤0.5=4, else 1
      release_cadence (5pts)      : ≤30d=5, ≤90d=3, ≤365d=1, else 0
      stars_growth_rate (5pts)    : ≥2%=5, ≥0.5%=3, ≥0%=1, else 0
    """
    score = 0

    cv = metrics.get("commit_velocity", 0)
    score += 25 if cv >= 30 else 18 if cv >= 15 else 10 if cv >= 5 else 3

    irt = metrics.get("issue_resolution_time", 999)
    if irt < 0:
        score += 5  # no data — neutral
    else:
        score += 20 if irt <= 3 else 15 if irt <= 7 else 10 if irt <= 30 else 5 if irt <= 90 else 0

    pmr = metrics.get("pr_merge_rate", 0)
    score += 20 if pmr >= 80 else 15 if pmr >= 60 else 10 if pmr >= 40 else 5

    cc = metrics.get("contributor_count", 0)
    if cc < 0:
        score += 5  # no data
    else:
        score += 15 if cc >= 50 else 10 if cc >= 20 else 5 if cc >= 5 else 2

    oir = metrics.get("open_issue_ratio", 1)
    score += 10 if oir <= 0.1 else 7 if oir <= 0.3 else 4 if oir <= 0.5 else 1

    rc = metrics.get("release_cadence", -1)
    if rc < 0:
        score += 0
    else:
        score += 5 if rc <= 30 else 3 if rc <= 90 else 1 if rc <= 365 else 0

    sgr = metrics.get("stars_growth_rate", 0)
    score += 5 if sgr >= 2 else 3 if sgr >= 0.5 else 1 if sgr >= 0 else 0

    return min(score, 100)


# ---------------------------------------------------------------------------
# Groq summarization
# ---------------------------------------------------------------------------

def groq_summarize(report: list[dict], api_key: str) -> str:
    """
    Send the metrics JSON to Groq (llama-3.3-70b) and get a concise
    plain-English summary of the overall landscape.
    """
    compact = json.dumps(
        [{
            "repo": r["repo"],
            "health_score": r["health_score"],
            "metrics": r["metrics"],
        } for r in report],
        indent=2,
    )
    prompt = (
        "You are a senior open-source analyst. Below is a JSON health report "
        "for several Python repositories. Write a concise executive summary "
        "(3-5 paragraphs) covering:\n"
        "1. Overall ecosystem health\n"
        "2. The healthiest repo and why\n"
        "3. Any repos showing warning signs (low scores, slow issue resolution, etc.)\n"
        "4. Actionable recommendations for contributors\n\n"
        f"Report:\n{compact}"
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 1024,
    }
    try:
        resp = requests.post(GROQ_API, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        log.warning("Groq summarization failed: %s", exc)
        return "Summary unavailable (Groq API error)."


# ---------------------------------------------------------------------------
# Per-repo analyzer
# ---------------------------------------------------------------------------

def analyze_repo(client: GitHubClient, repo: str) -> dict:
    """
    Fetch all metrics for a single repo and return a structured result dict.
    """
    log.info("Analyzing %s …", repo)
    try:
        repo_data = client.get(f"/repos/{repo}")
    except requests.HTTPError as exc:
        log.error("Could not fetch %s: %s", repo, exc)
        return {"repo": repo, "error": str(exc)}

    stars = repo_data.get("stargazers_count", 0)

    metrics: dict[str, Any] = {}

    # --- commit velocity ---
    log.debug("  commit_velocity …")
    metrics["commit_velocity"] = calc_commit_velocity(client, repo)

    # --- issue resolution time ---
    log.debug("  issue_resolution_time …")
    metrics["issue_resolution_time"] = calc_issue_resolution_time(client, repo)

    # --- PR merge rate ---
    log.debug("  pr_merge_rate …")
    metrics["pr_merge_rate"] = calc_pr_merge_rate(client, repo)

    # --- contributor count ---
    log.debug("  contributor_count …")
    metrics["contributor_count"] = calc_contributor_count(client, repo)

    # --- open issue ratio ---
    metrics["open_issue_ratio"] = calc_open_issue_ratio(repo_data)

    # --- release cadence ---
    log.debug("  release_cadence …")
    metrics["release_cadence"] = calc_release_cadence(client, repo)

    # --- stars growth rate ---
    log.debug("  stars_growth_rate …")
    metrics["stars_growth_rate"] = calc_stars_growth_rate(client, repo, stars)

    health_score = compute_health_score(metrics)

    return {
        "repo": repo,
        "stars": stars,
        "description": repo_data.get("description", ""),
        "language": repo_data.get("language", ""),
        "license": (repo_data.get("license") or {}).get("spdx_id", "unknown"),
        "created_at": repo_data.get("created_at", ""),
        "last_push": repo_data.get("pushed_at", ""),
        "open_issues": repo_data.get("open_issues_count", 0),
        "forks": repo_data.get("forks_count", 0),
        "watchers": repo_data.get("watchers_count", 0),
        "health_score": health_score,
        "metrics": {
            "commit_velocity_per_month": metrics["commit_velocity"],
            "issue_resolution_time_days": metrics["issue_resolution_time"],
            "pr_merge_rate_pct": metrics["pr_merge_rate"],
            "contributor_count_12mo": metrics["contributor_count"],
            "open_issue_ratio": metrics["open_issue_ratio"],
            "release_cadence_days": metrics["release_cadence"],
            "stars_monthly_growth_pct": metrics["stars_growth_rate"],
        },
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def render_markdown(report: list[dict], summary: str) -> str:
    """
    Convert the list of repo result dicts into a Markdown health report.
    """
    lines = [
        "# GitHub Repository Health Report",
        f"_Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        "## Executive Summary",
        "",
        summary,
        "",
        "---",
        "",
        "## Repository Scores",
        "",
        "| Repo | Stars | Health Score | Commits/mo | Issue Close (d) | PR Merge % | Contributors |",
        "|------|-------|:------------:|:----------:|:---------------:|:----------:|:------------:|",
    ]
    for r in sorted(report, key=lambda x: x.get("health_score", 0), reverse=True):
        if "error" in r:
            lines.append(f"| {r['repo']} | — | ERROR | — | — | — | — |")
            continue
        m = r["metrics"]
        lines.append(
            f"| [{r['repo']}](https://github.com/{r['repo']}) "
            f"| {r['stars']:,} "
            f"| **{r['health_score']}** "
            f"| {m['commit_velocity_per_month']} "
            f"| {m['issue_resolution_time_days']} "
            f"| {m['pr_merge_rate_pct']}% "
            f"| {m['contributor_count_12mo']} |"
        )

    lines += ["", "---", "", "## Detailed Metrics", ""]
    for r in report:
        if "error" in r:
            lines.append(f"### {r['repo']} — ERROR\n\n```\n{r['error']}\n```\n")
            continue
        m = r["metrics"]
        lines += [
            f"### {r['repo']} — Score: {r['health_score']}/100",
            "",
            f"**Description**: {r['description']}  ",
            f"**Stars**: {r['stars']:,} | **Forks**: {r['forks']:,} | **Watchers**: {r['watchers']:,}  ",
            f"**License**: {r['license']} | **Language**: {r['language']}  ",
            f"**Last push**: {r['last_push'][:10]}",
            "",
            "| Metric | Value | Notes |",
            "|--------|-------|-------|",
            f"| Commits / month (12mo avg) | {m['commit_velocity_per_month']} | Higher = more active |",
            f"| Issue resolution time | {m['issue_resolution_time_days']} days | Median of last 100 closed |",
            f"| PR merge rate | {m['pr_merge_rate_pct']}% | Last 100 closed PRs |",
            f"| Active contributors | {m['contributor_count_12mo']} | Unique committers in 12 months |",
            f"| Open issue ratio | {m['open_issue_ratio']} | Lower = better managed backlog |",
            f"| Release cadence | {m['release_cadence_days']} days | Avg gap between last 10 releases |",
            f"| Stars monthly growth | {m['stars_monthly_growth_pct']}% | Estimated from recent stargazers |",
            "",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze GitHub repository health using GitHub API + Groq LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--repos", nargs="+", metavar="OWNER/REPO",
        help="Specific repos to analyze (e.g. psf/requests pallets/flask)",
    )
    parser.add_argument(
        "--top", type=int, default=0, metavar="N",
        help="Fetch top-N popular Python repos from GitHub search (default: 0 = use --repos or built-in list)",
    )
    parser.add_argument(
        "--output", metavar="FILE",
        help="Write JSON report to this file (default: print to stdout)",
    )
    parser.add_argument(
        "--markdown", metavar="FILE",
        help="Write Markdown report to this file",
    )
    parser.add_argument(
        "--no-groq", action="store_true",
        help="Skip Groq summarization",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # --- Validate env vars ---
    github_token = os.getenv("GITHUB_TOKEN")
    groq_api_key = os.getenv("GROQ_API_KEY")

    if not github_token:
        log.error("GITHUB_TOKEN environment variable is required")
        sys.exit(1)

    if not groq_api_key and not args.no_groq:
        log.warning("GROQ_API_KEY not set — Groq summarization will be skipped")
        args.no_groq = True

    client = GitHubClient(github_token)

    # --- Determine repos to analyze ---
    if args.top > 0:
        raw_repos = client.fetch_popular_python_repos(args.top)
        repo_list = [r["full_name"] for r in raw_repos]
    elif args.repos:
        repo_list = args.repos
    else:
        log.info("No --repos or --top specified; using default list of 5 repos")
        repo_list = DEFAULT_REPOS

    log.info("Analyzing %d repositories: %s", len(repo_list), ", ".join(repo_list))

    # --- Analyze each repo ---
    report = []
    for repo in repo_list:
        result = analyze_repo(client, repo)
        report.append(result)
        # Brief pause to be a polite API consumer
        time.sleep(1)

    # --- Groq summary ---
    summary = ""
    if not args.no_groq and groq_api_key:
        log.info("Requesting Groq executive summary …")
        summary = groq_summarize(report, groq_api_key)

    # --- Build final output ---
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_count": len(report),
        "groq_summary": summary,
        "repos": report,
    }

    # --- JSON output ---
    json_str = json.dumps(output, indent=2, default=str)
    if args.output:
        with open(args.output, "w") as fh:
            fh.write(json_str)
        log.info("JSON report written to %s", args.output)
    else:
        print(json_str)

    # --- Markdown output ---
    if args.markdown:
        md = render_markdown(report, summary)
        with open(args.markdown, "w") as fh:
            fh.write(md)
        log.info("Markdown report written to %s", args.markdown)

    # Print health score summary to stderr for quick human review
    log.info("=" * 60)
    log.info("%-35s  %s", "REPO", "HEALTH SCORE")
    log.info("-" * 45)
    for r in sorted(report, key=lambda x: x.get("health_score", 0), reverse=True):
        score = r.get("health_score", "ERROR")
        log.info("%-35s  %s/100", r["repo"], score)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
