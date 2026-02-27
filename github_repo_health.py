#!/usr/bin/env python3
"""
GitHub Repository Health Analyzer
Fetches popular repos, analyzes metrics, scores health via weighted average,
and summarizes insights using Groq LLM.
"""

import os
import sys
import json
import time
import math
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

OUTPUT_PATH = "/root/.automaton/repo_health_report.json"

# Repos to analyse — top 10 popular Python repos (language is configurable)
LANGUAGE = "python"
REPO_COUNT = 10

GITHUB_API = "https://api.github.com"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# Weight for each metric in the final health score (must sum to 1.0)
WEIGHTS = {
    "issue_close_rate":       0.25,
    "pr_merge_rate":          0.20,
    "recent_commit_activity": 0.20,
    "avg_resolution_days":    0.15,  # inverted — lower is better
    "contributor_diversity":  0.20,
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update({
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
})
if GITHUB_TOKEN:
    SESSION.headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
else:
    log.warning("GITHUB_TOKEN not set — rate limit is 60 req/hr (unauthenticated)")


def gh_get(path: str, params: Optional[dict] = None, retries: int = 3) -> Optional[dict | list]:
    """GET from GitHub API with rate-limit back-off and error handling."""
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    for attempt in range(1, retries + 1):
        try:
            resp = SESSION.get(url, params=params, timeout=20)
        except requests.RequestException as exc:
            log.error("Network error on %s: %s", url, exc)
            return None

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 403:
            reset_ts = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset_ts - int(time.time()), 1) + 2
            log.warning("Rate limited. Sleeping %ds (attempt %d/%d)…", wait, attempt, retries)
            time.sleep(wait)
            continue

        if resp.status_code == 404:
            log.debug("404 for %s", url)
            return None

        if resp.status_code in (500, 502, 503, 504) and attempt < retries:
            log.warning("Server error %d on %s — retrying in 5s", resp.status_code, url)
            time.sleep(5)
            continue

        log.error("GitHub API error %d for %s", resp.status_code, url)
        return None

    return None


def paginate(path: str, params: Optional[dict] = None, max_pages: int = 5) -> list:
    """Collect all pages up to max_pages from a GitHub list endpoint."""
    params = dict(params or {})
    params.setdefault("per_page", 100)
    results = []
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"

    for page in range(1, max_pages + 1):
        params["page"] = page
        data = gh_get(url, params)
        if not data:
            break
        if isinstance(data, dict):
            items = data.get("items", data.get("values", []))
        else:
            items = data
        if not items:
            break
        results.extend(items)
        if len(items) < params["per_page"]:
            break  # last page

    return results


# ---------------------------------------------------------------------------
# Fetch popular repos
# ---------------------------------------------------------------------------

def fetch_popular_repos(language: str, count: int) -> list[dict]:
    """Return top `count` repos sorted by stars for the given language."""
    log.info("Fetching top %d %s repos…", count, language)
    data = gh_get(
        "/search/repositories",
        params={
            "q": f"language:{language} stars:>1000",
            "sort": "stars",
            "order": "desc",
            "per_page": count,
            "page": 1,
        },
    )
    if not data or "items" not in data:
        log.error("Failed to fetch popular repos")
        return []
    return data["items"]


# ---------------------------------------------------------------------------
# Metric calculators
# ---------------------------------------------------------------------------

def calc_issue_close_rate(owner: str, repo: str) -> tuple[float, dict]:
    """Ratio of closed issues to total issues (sample last 200)."""
    closed = gh_get(f"/repos/{owner}/{repo}/issues",
                    params={"state": "closed", "per_page": 1})
    open_  = gh_get(f"/repos/{owner}/{repo}/issues",
                    params={"state": "open",   "per_page": 1})

    # GitHub returns Link header for pagination — get total via last page number
    def total_via_link(state: str) -> int:
        resp = SESSION.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues",
            params={"state": state, "per_page": 1, "page": 1},
            timeout=20,
        )
        link = resp.headers.get("Link", "")
        if 'rel="last"' in link:
            import re
            m = re.search(r'page=(\d+)>; rel="last"', link)
            if m:
                return int(m.group(1))
        data = resp.json()
        return len(data) if isinstance(data, list) else 0

    n_closed = total_via_link("closed")
    n_open   = total_via_link("open")
    total    = n_closed + n_open

    rate = n_closed / total if total else 0.0
    return rate, {"issues_closed": n_closed, "issues_open": n_open, "issues_total": total}


def calc_pr_merge_rate(owner: str, repo: str) -> tuple[float, dict]:
    """Ratio of merged PRs to total PRs (sample recent 100)."""
    merged = SESSION.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
        params={"state": "closed", "per_page": 1},
        timeout=20,
    )
    link = merged.headers.get("Link", "")
    import re
    n_closed_prs = 0
    if 'rel="last"' in link:
        m = re.search(r'page=(\d+)>; rel="last"', link)
        if m:
            n_closed_prs = int(m.group(1))
    else:
        data = merged.json()
        n_closed_prs = len(data) if isinstance(data, list) else 0

    open_prs_resp = SESSION.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
        params={"state": "open", "per_page": 1},
        timeout=20,
    )
    n_open_prs = 0
    link2 = open_prs_resp.headers.get("Link", "")
    if 'rel="last"' in link2:
        m2 = re.search(r'page=(\d+)>; rel="last"', link2)
        if m2:
            n_open_prs = int(m2.group(1))
    else:
        data2 = open_prs_resp.json()
        n_open_prs = len(data2) if isinstance(data2, list) else 0

    # Sample recent 50 closed PRs to find merged count
    recent_closed = paginate(
        f"/repos/{owner}/{repo}/pulls",
        params={"state": "closed", "sort": "updated", "direction": "desc"},
        max_pages=1,
    )
    n_merged_sample = sum(1 for pr in recent_closed if pr.get("merged_at"))
    sample_size     = len(recent_closed) if recent_closed else 1
    merge_ratio     = n_merged_sample / sample_size

    total_prs  = n_closed_prs + n_open_prs
    est_merged = int(n_closed_prs * merge_ratio)

    return merge_ratio, {
        "prs_open": n_open_prs,
        "prs_closed": n_closed_prs,
        "prs_total": total_prs,
        "prs_merged_estimated": est_merged,
        "merge_rate_sample": round(merge_ratio, 4),
    }


def calc_commit_activity(owner: str, repo: str) -> tuple[float, dict]:
    """Fraction of commits in last 30 days vs last year."""
    # GitHub's commit activity gives weekly counts for the past year (52 weeks)
    activity = gh_get(f"/repos/{owner}/{repo}/stats/commit_activity")
    if not activity or not isinstance(activity, list):
        return 0.0, {"error": "commit_activity unavailable"}

    now_week  = int(time.time()) // 604800  # current Unix week
    cutoff_30 = now_week - 5                # ~5 weeks ≈ 35 days (close enough)

    total_year    = sum(w.get("total", 0) for w in activity)
    recent_30d    = sum(
        w.get("total", 0) for w in activity
        if w.get("week", 0) // 604800 >= cutoff_30
    )

    ratio = recent_30d / total_year if total_year else 0.0
    # Normalise: if ratio >= 1/12 (~8.3%) the repo is very active
    normalised = min(ratio / (1 / 12), 1.0)

    return normalised, {
        "commits_last_30d_approx": recent_30d,
        "commits_last_year": total_year,
        "activity_ratio": round(ratio, 4),
    }


def calc_avg_resolution_time(owner: str, repo: str, sample: int = 30) -> tuple[float, dict]:
    """Average days from issue open → close for a sample of recent closed issues."""
    issues = paginate(
        f"/repos/{owner}/{repo}/issues",
        params={"state": "closed", "sort": "updated", "direction": "desc"},
        max_pages=1,
    )[:sample]

    durations = []
    for issue in issues:
        if issue.get("pull_request"):  # skip PRs returned by issues endpoint
            continue
        created = issue.get("created_at")
        closed  = issue.get("closed_at")
        if created and closed:
            dt_c = datetime.fromisoformat(created.rstrip("Z")).replace(tzinfo=timezone.utc)
            dt_x = datetime.fromisoformat(closed.rstrip("Z")).replace(tzinfo=timezone.utc)
            durations.append((dt_x - dt_c).total_seconds() / 86400)

    if not durations:
        return 0.5, {"avg_resolution_days": None, "sample_size": 0}

    avg_days = sum(durations) / len(durations)
    # Score: 1 day → 1.0, 30 days → ~0.5, 365 days → ~0.0  (logarithmic)
    score = max(0.0, 1.0 - math.log1p(avg_days) / math.log1p(365))

    return score, {
        "avg_resolution_days": round(avg_days, 1),
        "sample_size": len(durations),
        "min_days": round(min(durations), 1),
        "max_days": round(max(durations), 1),
    }


def calc_contributor_diversity(owner: str, repo: str) -> tuple[float, dict]:
    """Number of unique contributors (capped at 500 for score normalisation)."""
    contributors = gh_get(
        f"/repos/{owner}/{repo}/contributors",
        params={"per_page": 1, "anon": "false"},
    )
    # Use Link header trick
    resp = SESSION.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/contributors",
        params={"per_page": 1},
        timeout=20,
    )
    import re
    link = resp.headers.get("Link", "")
    count = 1
    if 'rel="last"' in link:
        m = re.search(r'page=(\d+)>; rel="last"', link)
        if m:
            count = int(m.group(1))
    else:
        data = resp.json()
        count = len(data) if isinstance(data, list) else 1

    # Normalise against 500 contributors
    normalised = min(count / 500, 1.0)
    return normalised, {"contributor_count": count}


# ---------------------------------------------------------------------------
# Health score
# ---------------------------------------------------------------------------

def compute_health_score(metrics: dict) -> tuple[float, dict]:
    """Weighted average of individual metric scores → 0–100."""
    component_scores = {
        "issue_close_rate":       metrics["issue_close_rate"]["score"],
        "pr_merge_rate":          metrics["pr_merge_rate"]["score"],
        "recent_commit_activity": metrics["recent_commit_activity"]["score"],
        "avg_resolution_days":    metrics["avg_resolution_days"]["score"],
        "contributor_diversity":  metrics["contributor_diversity"]["score"],
    }

    health = sum(WEIGHTS[k] * v for k, v in component_scores.items()) * 100
    health = round(health, 1)

    label = (
        "Excellent" if health >= 80 else
        "Good"      if health >= 60 else
        "Fair"      if health >= 40 else
        "Poor"
    )

    return health, {"label": label, "component_scores": component_scores, "weights": WEIGHTS}


# ---------------------------------------------------------------------------
# Groq summarizer
# ---------------------------------------------------------------------------

def groq_summarize(repo_name: str, health_score: float, metrics: dict) -> str:
    """Ask Groq to generate 3 actionable insights from the repo metrics."""
    if not GROQ_API_KEY:
        return "GROQ_API_KEY not set — skipping AI insights."

    summary_blob = json.dumps({
        "repo": repo_name,
        "health_score": health_score,
        "issue_close_rate":    metrics["issue_close_rate"]["data"],
        "pr_merge_rate":       metrics["pr_merge_rate"]["data"],
        "commit_activity":     metrics["recent_commit_activity"]["data"],
        "resolution_time":     metrics["avg_resolution_days"]["data"],
        "contributors":        metrics["contributor_diversity"]["data"],
    }, indent=2)

    prompt = (
        f"You are a DevOps analyst. Given this GitHub repository health data:\n\n"
        f"{summary_blob}\n\n"
        "Provide exactly 3 concise, actionable insights for improving or leveraging "
        "this repository. Format: numbered list, one sentence each. Be specific."
    )

    try:
        resp = requests.post(
            GROQ_API,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model":       GROQ_MODEL,
                "messages":    [{"role": "user", "content": prompt}],
                "max_tokens":  300,
                "temperature": 0.4,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        log.warning("Groq request failed for %s: %s", repo_name, exc)
        return f"AI insights unavailable: {exc}"


# ---------------------------------------------------------------------------
# Per-repo analysis
# ---------------------------------------------------------------------------

def analyse_repo(repo: dict) -> dict:
    owner     = repo["owner"]["login"]
    name      = repo["name"]
    full_name = repo["full_name"]
    log.info("Analysing %s…", full_name)

    raw_metrics: dict = {}

    # --- issue close rate ---
    score_icr, data_icr = calc_issue_close_rate(owner, name)
    raw_metrics["issue_close_rate"] = {"score": round(score_icr, 4), "data": data_icr}

    # --- PR merge rate ---
    score_pmr, data_pmr = calc_pr_merge_rate(owner, name)
    raw_metrics["pr_merge_rate"] = {"score": round(score_pmr, 4), "data": data_pmr}

    # --- commit activity ---
    score_ca, data_ca = calc_commit_activity(owner, name)
    raw_metrics["recent_commit_activity"] = {"score": round(score_ca, 4), "data": data_ca}

    # --- avg resolution time ---
    score_art, data_art = calc_avg_resolution_time(owner, name)
    raw_metrics["avg_resolution_days"] = {"score": round(score_art, 4), "data": data_art}

    # --- contributor diversity ---
    score_cd, data_cd = calc_contributor_diversity(owner, name)
    raw_metrics["contributor_diversity"] = {"score": round(score_cd, 4), "data": data_cd}

    health_score, score_breakdown = compute_health_score(raw_metrics)

    insights = groq_summarize(full_name, health_score, raw_metrics)

    return {
        "repo":          full_name,
        "url":           repo["html_url"],
        "stars":         repo["stargazers_count"],
        "forks":         repo["forks_count"],
        "language":      repo.get("language"),
        "description":   repo.get("description", ""),
        "health_score":  health_score,
        "health_label":  score_breakdown["label"],
        "score_breakdown": score_breakdown,
        "metrics":       raw_metrics,
        "insights":      insights,
        "analysed_at":   datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not GITHUB_TOKEN:
        log.warning("No GITHUB_TOKEN — you may hit rate limits quickly")

    repos = fetch_popular_repos(LANGUAGE, REPO_COUNT)
    if not repos:
        log.error("No repos fetched. Exiting.")
        sys.exit(1)

    results = []
    for idx, repo in enumerate(repos, 1):
        log.info("--- Repo %d/%d ---", idx, len(repos))
        try:
            result = analyse_repo(repo)
            results.append(result)
            log.info("  Health score: %.1f (%s)", result["health_score"], result["health_label"])
        except Exception as exc:
            log.error("Failed to analyse %s: %s", repo.get("full_name"), exc)
            results.append({
                "repo":  repo.get("full_name"),
                "error": str(exc),
            })
        # Brief pause to be kind to the API
        if idx < len(repos):
            time.sleep(1)

    # Sort by health score descending
    results.sort(key=lambda r: r.get("health_score", -1), reverse=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language":     LANGUAGE,
        "repo_count":   len(results),
        "repositories": results,
        "summary": {
            "avg_health_score": round(
                sum(r["health_score"] for r in results if "health_score" in r)
                / max(sum(1 for r in results if "health_score" in r), 1),
                1,
            ),
            "top_repo": results[0]["repo"] if results else None,
        },
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    log.info("Report saved to %s", OUTPUT_PATH)
    log.info("Average health score: %.1f", report["summary"]["avg_health_score"])
    log.info("Top repo: %s", report["summary"]["top_repo"])

    # Print a compact summary table
    print("\n=== GitHub Repo Health Report ===")
    print(f"{'Repo':<45} {'Score':>6}  Label")
    print("-" * 62)
    for r in results:
        if "error" in r:
            print(f"  {r['repo']:<43} ERROR  {r['error'][:30]}")
        else:
            print(f"  {r['repo']:<43} {r['health_score']:>5.1f}  {r['health_label']}")
    print(f"\nFull report → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
