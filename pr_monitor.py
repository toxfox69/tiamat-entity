#!/usr/bin/env python3
"""
pr_monitor.py — GitHub PR Status Monitor
Batch-checks PR statuses from a JSON input file.
Outputs CSV + console table. Respects GitHub rate limits.

Usage:
    python pr_monitor.py input.json
    python pr_monitor.py input.json --output results.csv
    python pr_monitor.py input.json --token $GITHUB_TOKEN
    python pr_monitor.py input.json --no-csv
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import requests

GITHUB_API = "https://api.github.com"
RATE_LIMIT_PER_MIN = 10
INTERVAL = 60.0 / RATE_LIMIT_PER_MIN  # seconds between requests


def get_pr_data(session: requests.Session, repo: str, pr_number: int) -> dict:
    """Fetch PR data from GitHub API. Returns a status dict."""
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}"
    result = {
        "repo": repo,
        "pr": pr_number,
        "state": "",
        "title": "",
        "merged": "",
        "mergeable": "",
        "reviews_count": "",
        "last_update": "",
        "url": f"https://github.com/{repo}/pull/{pr_number}",
        "error": "",
    }

    try:
        resp = session.get(url, timeout=15)
    except requests.RequestException as e:
        result["error"] = f"network error: {e}"
        return result

    if resp.status_code == 404:
        # Could be merged/closed PR — GitHub returns 404 for some closed PRs via pulls endpoint
        # Fall back to issues endpoint which works for all states
        issue_url = f"{GITHUB_API}/repos/{repo}/issues/{pr_number}"
        try:
            issue_resp = session.get(issue_url, timeout=15)
            if issue_resp.status_code == 200:
                data = issue_resp.json()
                if "pull_request" not in data:
                    result["error"] = f"#{pr_number} is an issue, not a PR"
                    return result
                result["state"] = data.get("state", "unknown")
                result["title"] = data.get("title", "")[:80]
                pr_info = data.get("pull_request", {})
                result["merged"] = "yes" if pr_info.get("merged_at") else "no"
                result["mergeable"] = "n/a"
                result["reviews_count"] = _get_reviews_count(session, repo, pr_number)
                updated = data.get("updated_at", "")
                result["last_update"] = _fmt_time(updated)
                return result
            else:
                result["error"] = f"HTTP {resp.status_code}"
                return result
        except requests.RequestException as e:
            result["error"] = f"HTTP {resp.status_code} (fallback error: {e})"
            return result

    if resp.status_code == 403:
        remaining = resp.headers.get("X-RateLimit-Remaining", "?")
        reset = resp.headers.get("X-RateLimit-Reset", "")
        reset_str = ""
        if reset:
            try:
                reset_dt = datetime.fromtimestamp(int(reset), tz=timezone.utc)
                reset_str = f", resets {reset_dt.strftime('%H:%M:%S UTC')}"
            except ValueError:
                pass
        result["error"] = f"rate limited (remaining={remaining}{reset_str})"
        return result

    if resp.status_code != 200:
        result["error"] = f"HTTP {resp.status_code}"
        return result

    data = resp.json()
    result["state"] = data.get("state", "unknown")
    result["title"] = data.get("title", "")[:80]
    result["merged"] = "yes" if data.get("merged") else "no"

    mergeable = data.get("mergeable")
    if mergeable is None:
        result["mergeable"] = "unknown"
    elif mergeable:
        result["mergeable"] = "yes"
    else:
        result["mergeable"] = "no"

    result["reviews_count"] = _get_reviews_count(session, repo, pr_number)
    updated = data.get("updated_at", "")
    result["last_update"] = _fmt_time(updated)
    return result


def _get_reviews_count(session: requests.Session, repo: str, pr_number: int) -> str:
    """Fetch number of reviews for a PR."""
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/reviews"
    try:
        resp = session.get(url, timeout=10)
        if resp.status_code == 200:
            return str(len(resp.json()))
        return "?"
    except requests.RequestException:
        return "?"


def _fmt_time(iso_str: str) -> str:
    """Format ISO timestamp to readable relative time."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(tz=timezone.utc)
        delta = now - dt
        days = delta.days
        if days == 0:
            hours = delta.seconds // 3600
            if hours == 0:
                mins = delta.seconds // 60
                return f"{mins}m ago"
            return f"{hours}h ago"
        elif days == 1:
            return "1d ago"
        elif days < 30:
            return f"{days}d ago"
        elif days < 365:
            months = days // 30
            return f"{months}mo ago"
        else:
            years = days // 365
            return f"{years}y ago"
    except (ValueError, TypeError):
        return iso_str[:10]  # fallback to date


def load_input(path: str) -> list[dict]:
    """Load and validate the JSON input file."""
    with open(path) as f:
        data = json.load(f)

    if not isinstance(data, list):
        sys.exit("Error: JSON input must be a list of objects.")

    prs = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            print(f"Warning: item {i} is not an object, skipping.", file=sys.stderr)
            continue
        repo = item.get("repo", "").strip()
        pr = item.get("pr")
        if not repo:
            print(f"Warning: item {i} missing 'repo', skipping.", file=sys.stderr)
            continue
        if pr is None:
            print(f"Warning: item {i} missing 'pr', skipping.", file=sys.stderr)
            continue
        try:
            pr_int = int(pr)
        except (ValueError, TypeError):
            print(f"Warning: item {i} has non-integer 'pr' value ({pr!r}), skipping.", file=sys.stderr)
            continue
        prs.append({"repo": repo, "pr": pr_int})

    if not prs:
        sys.exit("Error: no valid PR entries found in input.")
    return prs


def print_table(rows: list[dict]) -> None:
    """Print results as a formatted console table."""
    if not rows:
        return

    cols = [
        ("repo",          "Repo",         28),
        ("pr",            "PR",            6),
        ("state",         "State",         8),
        ("merged",        "Merged",        7),
        ("mergeable",     "Mergeable",    10),
        ("reviews_count", "Reviews",       8),
        ("last_update",   "Last Update",  12),
        ("title",         "Title",        40),
        ("error",         "Error",        30),
    ]

    header = "  ".join(label.ljust(width) for _, label, width in cols)
    sep = "  ".join("-" * width for _, _, width in cols)
    print()
    print(header)
    print(sep)

    for row in rows:
        line_parts = []
        for key, _, width in cols:
            val = str(row.get(key, ""))
            # truncate with ellipsis if too long
            if len(val) > width:
                val = val[:width - 1] + "…"
            line_parts.append(val.ljust(width))
        print("  ".join(line_parts))
    print()


def write_csv(rows: list[dict], path: str) -> None:
    """Write results to CSV."""
    fields = ["repo", "pr", "state", "merged", "mergeable", "reviews_count",
              "last_update", "title", "url", "error"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV written to: {path}")


def build_session(token: Optional[str]) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pr-monitor/1.0",
    })
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def check_rate_limit(session: requests.Session) -> None:
    """Print current rate limit status."""
    try:
        resp = session.get(f"{GITHUB_API}/rate_limit", timeout=10)
        if resp.status_code == 200:
            core = resp.json().get("resources", {}).get("core", {})
            remaining = core.get("remaining", "?")
            limit = core.get("limit", "?")
            reset_ts = core.get("reset", 0)
            reset_dt = datetime.fromtimestamp(reset_ts, tz=timezone.utc)
            print(f"GitHub API rate limit: {remaining}/{limit} remaining, resets {reset_dt.strftime('%H:%M:%S UTC')}")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Monitor GitHub PR statuses in batch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pr_monitor.py example.json
  python pr_monitor.py prs.json --output results.csv
  python pr_monitor.py prs.json --token ghp_xxx --no-csv
  GITHUB_TOKEN=ghp_xxx python pr_monitor.py prs.json
        """,
    )
    parser.add_argument("input", help="JSON file with list of {repo, pr} objects")
    parser.add_argument("--output", "-o", default="pr_results.csv", help="CSV output path (default: pr_results.csv)")
    parser.add_argument("--token", "-t", default=None, help="GitHub personal access token (or set GITHUB_TOKEN env var)")
    parser.add_argument("--no-csv", action="store_true", help="Skip CSV output, print table only")
    parser.add_argument("--rate-limit", "-r", type=int, default=RATE_LIMIT_PER_MIN,
                        help=f"Max requests per minute (default: {RATE_LIMIT_PER_MIN})")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress progress output")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN")
    interval = 60.0 / max(1, args.rate_limit)

    prs = load_input(args.input)
    session = build_session(token)

    if not args.quiet:
        check_rate_limit(session)
        print(f"\nMonitoring {len(prs)} PRs at ≤{args.rate_limit} req/min...\n")

    results = []
    for i, entry in enumerate(prs):
        repo = entry["repo"]
        pr_num = entry["pr"]

        if not args.quiet:
            print(f"  [{i+1}/{len(prs)}] {repo}#{pr_num} ...", end="", flush=True)

        row = get_pr_data(session, repo, pr_num)
        results.append(row)

        if not args.quiet:
            status = row["error"] if row["error"] else f"{row['state']} / merged={row['merged']}"
            print(f" {status}")

        # Rate limiting: sleep between requests (skip after last one)
        if i < len(prs) - 1:
            time.sleep(interval)

    print_table(results)

    if not args.no_csv:
        write_csv(results, args.output)

    # Summary
    errors = [r for r in results if r["error"]]
    open_prs = [r for r in results if r["state"] == "open"]
    merged_prs = [r for r in results if r["merged"] == "yes"]
    print(f"Summary: {len(results)} PRs checked | {len(open_prs)} open | {len(merged_prs)} merged | {len(errors)} errors")


if __name__ == "__main__":
    main()
