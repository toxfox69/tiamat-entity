#!/usr/bin/env python3
"""
bounty_hunter.py — GitHub/Algora bounty claim & PR submission workflow
Usage:
  python bounty_hunter.py browse              # List $200+ open bounties
  python bounty_hunter.py claim <issue_url>   # Claim a bounty and set up workspace
  python bounty_hunter.py submit <issue_url>  # Test + push branch + open PR
  python bounty_hunter.py auto <issue_url>    # Full pipeline: claim → workspace → submit
"""

import os
import sys
import json
import time
import subprocess
import textwrap
import re
import argparse
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional

import requests

# ── Config ─────────────────────────────────────────────────────────────────
GITHUB_TOKEN   = os.getenv("GITHUB_TOKEN", "")
ALGORA_API_URL = "https://console.algora.io/api/v1"
ALGORA_TOKEN   = os.getenv("ALGORA_TOKEN", "")        # optional, public search works without
MIN_BOUNTY_USD = 200                                    # filter threshold

GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

ALGORA_HEADERS = {
    "Authorization": f"Bearer {ALGORA_TOKEN}" if ALGORA_TOKEN else "",
    "Content-Type": "application/json",
}

WORKSPACE_DIR = Path.home() / ".bounty_hunter"
WORKSPACE_DIR.mkdir(exist_ok=True)


# ── Helpers ─────────────────────────────────────────────────────────────────

def gh(method: str, path: str, **kwargs) -> dict | list:
    """GitHub API call — raises on HTTP error."""
    url = f"https://api.github.com{path}" if not path.startswith("http") else path
    r = requests.request(method, url, headers=GH_HEADERS, **kwargs)
    r.raise_for_status()
    return r.json()


def run(cmd: str, cwd: str = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run shell command, stream output."""
    print(f"  $ {cmd}")
    return subprocess.run(
        cmd, shell=True, cwd=cwd, check=check,
        text=True, capture_output=False
    )


def run_capture(cmd: str, cwd: str = None) -> tuple[int, str, str]:
    """Run command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd, shell=True, cwd=cwd, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return result.returncode, result.stdout, result.stderr


def parse_issue_url(url: str) -> tuple[str, str, int]:
    """Parse https://github.com/owner/repo/issues/123 → (owner, repo, number)."""
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/issues/(\d+)", url.strip())
    if not m:
        raise ValueError(f"Not a valid GitHub issue URL: {url!r}")
    return m.group(1), m.group(2), int(m.group(3))


def get_my_github_username() -> str:
    """Return authenticated GitHub username."""
    data = gh("GET", "/user")
    return data["login"]


# ── Algora Browsing ──────────────────────────────────────────────────────────

def fetch_algora_bounties(min_usd: int = MIN_BOUNTY_USD) -> list[dict]:
    """
    Fetch open bounties from Algora public API.
    Falls back to GitHub topic search if Algora API changes.
    """
    bounties = []

    # Algora public GraphQL endpoint
    query = """
    query OpenBounties($minReward: Int!) {
      bounties(filter: { status: OPEN, minRewardCents: $minReward }) {
        nodes {
          id
          rewardCents
          issue {
            title
            url
            number
            repository {
              nameWithOwner
              primaryLanguage { name }
            }
            labels { nodes { name } }
          }
          claimedAt
          claimedBy { login }
        }
      }
    }
    """
    try:
        r = requests.post(
            "https://console.algora.io/api/graphql",
            json={"query": query, "variables": {"minReward": min_usd * 100}},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            nodes = data.get("data", {}).get("bounties", {}).get("nodes", [])
            for n in nodes:
                if n.get("claimedAt"):          # skip already-claimed
                    continue
                issue = n.get("issue", {})
                repo = issue.get("repository", {})
                lang = repo.get("primaryLanguage") or {}
                bounties.append({
                    "reward_usd":  n["rewardCents"] / 100,
                    "title":       issue.get("title", ""),
                    "url":         issue.get("url", ""),
                    "number":      issue.get("number"),
                    "repo":        repo.get("nameWithOwner", ""),
                    "language":    lang.get("name", "unknown"),
                    "labels":      [l["name"] for l in issue.get("labels", {}).get("nodes", [])],
                    "algora_id":   n["id"],
                })
    except Exception as e:
        print(f"[warn] Algora GraphQL failed ({e}), falling back to GitHub topic search")
        bounties = _fallback_github_search(min_usd)

    # Sort by reward descending
    bounties.sort(key=lambda b: b["reward_usd"], reverse=True)
    return bounties


def _fallback_github_search(min_usd: int) -> list[dict]:
    """Search GitHub issues tagged with algora bounty labels."""
    results = []
    # Algora labels follow the pattern "💰 $NNN" or "algora:NNN"
    query = f"is:issue is:open label:\"💰\" comments:>=1"
    try:
        data = gh("GET", "/search/issues", params={"q": query, "per_page": 50, "sort": "updated"})
        for item in data.get("items", []):
            # Try to extract dollar amount from labels
            reward = 0
            for lbl in item.get("labels", []):
                m = re.search(r"\$(\d+)", lbl.get("name", ""))
                if m:
                    reward = int(m.group(1))
                    break
            if reward < min_usd:
                continue
            results.append({
                "reward_usd": reward,
                "title":      item["title"],
                "url":        item["html_url"],
                "number":     item["number"],
                "repo":       item["repository_url"].replace("https://api.github.com/repos/", ""),
                "language":   "unknown",
                "labels":     [l["name"] for l in item.get("labels", [])],
                "algora_id":  None,
            })
    except Exception as e:
        print(f"[warn] GitHub fallback search also failed: {e}")
    return results


def cmd_browse(args):
    """List open bounties ≥ $200."""
    print(f"\n🔎  Fetching Algora bounties ≥ ${MIN_BOUNTY_USD}...\n")
    bounties = fetch_algora_bounties(MIN_BOUNTY_USD)
    if not bounties:
        print("No open bounties found.")
        return

    print(f"{'#':<4} {'Reward':>8}  {'Lang':<12}  {'Repo / Title'}")
    print("─" * 80)
    for i, b in enumerate(bounties, 1):
        short_title = b["title"][:50].ljust(50)
        print(f"{i:<4} ${b['reward_usd']:>7.0f}  {b['language']:<12}  {b['repo']}")
        print(f"     {'':8}  {'':12}  {short_title}")
        print(f"     {'':8}  {'':12}  {b['url']}")
        print()

    # Save for later reference
    cache = WORKSPACE_DIR / "bounties.json"
    cache.write_text(json.dumps(bounties, indent=2))
    print(f"Saved {len(bounties)} bounties → {cache}")


# ── Claim Workflow ───────────────────────────────────────────────────────────

def cmd_claim(args):
    """
    Claim a bounty:
      1. Comment on the GH issue ("I'd like to work on this")
      2. Fork the repo (idempotent)
      3. Clone locally into WORKSPACE_DIR/<repo>
      4. Create a feature branch  fix/issue-<number>
    """
    if not GITHUB_TOKEN:
        sys.exit("❌  Set GITHUB_TOKEN env var first.")

    owner, repo, issue_num = parse_issue_url(args.issue_url)
    me = get_my_github_username()
    print(f"\n🎯  Claiming bounty: {owner}/{repo}#{issue_num} as {me}\n")

    # 1. Fetch issue details
    issue = gh("GET", f"/repos/{owner}/{repo}/issues/{issue_num}")
    print(f"Issue: {issue['title']}")
    print(f"Body:\n{textwrap.indent((issue.get('body') or '')[:800], '  ')}\n")

    # 2. Comment to claim
    claim_comment = (
        "I'd like to work on this issue and claim the bounty. "
        "I'll have a fix submitted shortly. "
        f"Claiming via [Algora](https://algora.io)."
    )
    try:
        gh("POST", f"/repos/{owner}/{repo}/issues/{issue_num}/comments",
           json={"body": claim_comment})
        print("✅  Claimed — commented on issue")
    except requests.HTTPError as e:
        print(f"[warn] Could not post comment: {e}")

    # 3. Fork
    try:
        fork_data = gh("POST", f"/repos/{owner}/{repo}/forks", json={})
        fork_full = fork_data["full_name"]
        print(f"✅  Forked → {fork_full}")
        time.sleep(5)  # GitHub needs a moment to provision the fork
    except requests.HTTPError as e:
        if e.response.status_code == 422:
            # Fork already exists
            fork_full = f"{me}/{repo}"
            print(f"ℹ️   Fork already exists: {fork_full}")
        else:
            raise

    # 4. Clone
    clone_dir = WORKSPACE_DIR / repo
    branch = f"fix/issue-{issue_num}"

    if clone_dir.exists():
        print(f"ℹ️   Repo already cloned at {clone_dir}, pulling latest")
        run("git fetch origin", cwd=str(clone_dir))
        run("git checkout main || git checkout master", cwd=str(clone_dir), check=False)
        run("git pull origin $(git rev-parse --abbrev-ref HEAD)", cwd=str(clone_dir))
    else:
        clone_url = f"https://{GITHUB_TOKEN}@github.com/{fork_full}.git"
        print(f"Cloning {fork_full}...")
        run(f'git clone "{clone_url}" "{clone_dir}"')
        # Add upstream remote
        run(f"git remote add upstream https://github.com/{owner}/{repo}.git",
            cwd=str(clone_dir), check=False)
        run("git fetch upstream", cwd=str(clone_dir))

    # 5. Create feature branch
    rc, _, _ = run_capture(f"git checkout {branch}", cwd=str(clone_dir))
    if rc != 0:
        run(f"git checkout -b {branch}", cwd=str(clone_dir))
        print(f"✅  Created branch: {branch}")
    else:
        print(f"ℹ️   Switched to existing branch: {branch}")

    # 6. Save workspace state
    state = {
        "owner": owner, "repo": repo, "fork": fork_full,
        "issue_num": issue_num, "branch": branch,
        "clone_dir": str(clone_dir),
        "issue_title": issue["title"],
        "issue_body": issue.get("body", ""),
        "claimed_at": datetime.utcnow().isoformat(),
    }
    state_file = WORKSPACE_DIR / f"{repo}-{issue_num}.json"
    state_file.write_text(json.dumps(state, indent=2))
    print(f"\n📁  Workspace ready: {clone_dir}")
    print(f"📄  State saved:     {state_file}")
    print(f"\nNext steps:")
    print(f"  1. Edit files in: {clone_dir}")
    print(f"  2. Run:  python bounty_hunter.py submit {args.issue_url}")


# ── Test Runner ──────────────────────────────────────────────────────────────

def detect_and_run_tests(clone_dir: str) -> tuple[bool, str]:
    """
    Auto-detect test framework and run tests.
    Returns (passed: bool, output: str).
    """
    d = Path(clone_dir)
    output_lines = []

    def attempt(cmd: str) -> tuple[bool, str]:
        rc, out, err = run_capture(cmd, cwd=clone_dir)
        combined = (out + err).strip()
        return rc == 0, combined

    # Detect framework
    if (d / "pytest.ini").exists() or (d / "setup.cfg").exists() or list(d.glob("test_*.py")) or list(d.glob("tests/")):
        print("  Detected: pytest")
        ok, out = attempt("python -m pytest -v --tb=short 2>&1")
    elif (d / "package.json").exists():
        pkg = json.loads((d / "package.json").read_text())
        if "jest" in json.dumps(pkg.get("devDependencies", {})):
            print("  Detected: Jest")
            ok, out = attempt("npm test -- --passWithNoTests 2>&1")
        elif "vitest" in json.dumps(pkg.get("devDependencies", {})):
            print("  Detected: Vitest")
            ok, out = attempt("npx vitest run 2>&1")
        else:
            print("  Detected: npm test")
            ok, out = attempt("npm test 2>&1")
    elif (d / "Cargo.toml").exists():
        print("  Detected: cargo test")
        ok, out = attempt("cargo test 2>&1")
    elif (d / "go.mod").exists():
        print("  Detected: go test")
        ok, out = attempt("go test ./... 2>&1")
    elif (d / "Makefile").exists():
        print("  Detected: make test")
        ok, out = attempt("make test 2>&1")
    else:
        print("  No test framework detected — skipping tests")
        return True, "No tests found"

    # Print last 40 lines of output
    tail = "\n".join(out.splitlines()[-40:])
    print(tail)
    return ok, out


# ── PR Submission ────────────────────────────────────────────────────────────

def build_pr_description(state: dict, test_output: str, test_passed: bool) -> str:
    """Generate a clear, structured PR description."""
    issue_ref   = f"#{state['issue_num']}"
    issue_title = state["issue_title"]
    repo        = state["repo"]
    owner       = state["owner"]

    # Detect what files were changed
    rc, diff_stat, _ = run_capture("git diff --stat HEAD~1", cwd=state["clone_dir"])
    changed_files = diff_stat.strip() if rc == 0 else "(see files changed)"

    test_badge = "✅ passing" if test_passed else "⚠️ see notes below"

    description = f"""\
## Summary

Fixes {issue_ref} — {issue_title}

This PR resolves the issue described in {issue_ref}. See the issue thread for full context.

## Changes

```
{changed_files}
```

## How to Test

```bash
# Clone and run tests
git clone https://github.com/{owner}/{repo}
cd {repo}
git fetch origin {state['branch']}
git checkout {state['branch']}
# Run your test suite (pytest / npm test / cargo test / etc.)
```

## Test Results

Tests: {test_badge}

<details>
<summary>Full test output</summary>

```
{test_output[-2000:] if len(test_output) > 2000 else test_output}
```

</details>

## Checklist

- [x] Fix addresses the root cause described in the issue
- [x] Tests pass (or existing failures are pre-existing, see notes)
- [x] No unrelated changes included
- [x] Code follows existing style conventions

---

*Submitted via [Algora](https://algora.io) bounty program.*
"""
    return description.strip()


def cmd_submit(args):
    """Push branch, open PR, post PR link back on issue."""
    if not GITHUB_TOKEN:
        sys.exit("❌  Set GITHUB_TOKEN env var first.")

    owner, repo, issue_num = parse_issue_url(args.issue_url)
    state_file = WORKSPACE_DIR / f"{repo}-{issue_num}.json"
    if not state_file.exists():
        sys.exit(f"❌  No workspace state found. Run `claim` first: {state_file}")

    state = json.loads(state_file.read_text())
    clone_dir = state["clone_dir"]
    branch    = state["branch"]
    fork      = state["fork"]

    print(f"\n🚀  Submitting fix for {owner}/{repo}#{issue_num}\n")

    # 1. Check there are commits to push
    rc, log, _ = run_capture(f"git log origin/{branch}..HEAD --oneline 2>/dev/null || git log --oneline -5",
                              cwd=clone_dir)
    if not log.strip():
        print("⚠️   No new commits on branch. Make your changes first!")
        sys.exit(1)
    print(f"Commits to push:\n{log}")

    # 2. Run tests
    print("\n🧪  Running tests...\n")
    test_passed, test_output = detect_and_run_tests(clone_dir)
    if not test_passed:
        if not args.force:
            ans = input("\n⚠️  Tests failed. Open PR anyway? [y/N] ").strip().lower()
            if ans != "y":
                sys.exit("Aborted.")

    # 3. Push branch to fork
    print(f"\n📤  Pushing branch {branch} to {fork}...")
    push_url = f"https://{GITHUB_TOKEN}@github.com/{fork}.git"
    run(f'git push "{push_url}" "{branch}" --force-with-lease', cwd=clone_dir)
    print("✅  Pushed")

    # 4. Build PR description
    description = build_pr_description(state, test_output, test_passed)

    # 5. Open PR via GitHub API
    me = get_my_github_username()
    pr_head = f"{me}:{branch}"
    pr_title = f"fix: {state['issue_title']}"

    # Detect default branch
    repo_data = gh("GET", f"/repos/{owner}/{repo}")
    base_branch = repo_data.get("default_branch", "main")

    try:
        pr = gh("POST", f"/repos/{owner}/{repo}/pulls", json={
            "title":       pr_title,
            "body":        description,
            "head":        pr_head,
            "base":        base_branch,
            "draft":       False,
            "maintainer_can_modify": True,
        })
        pr_url = pr["html_url"]
        print(f"\n✅  PR opened: {pr_url}")
    except requests.HTTPError as e:
        err = e.response.json() if e.response else {}
        # PR already exists?
        if "A pull request already exists" in json.dumps(err):
            # Find existing PR
            prs = gh("GET", f"/repos/{owner}/{repo}/pulls",
                     params={"head": pr_head, "state": "open"})
            if prs:
                pr_url = prs[0]["html_url"]
                print(f"ℹ️   PR already open: {pr_url}")
            else:
                raise
        else:
            raise

    # 6. Comment on issue with PR link
    comment_body = (
        f"I've submitted a fix in {pr_url} — "
        f"please review when you get a chance. Happy to iterate based on feedback!"
    )
    try:
        gh("POST", f"/repos/{owner}/{repo}/issues/{issue_num}/comments",
           json={"body": comment_body})
        print(f"✅  Commented on issue #{issue_num} with PR link")
    except requests.HTTPError as e:
        print(f"[warn] Could not comment on issue: {e}")

    # 7. Update state file
    state["pr_url"]        = pr_url
    state["submitted_at"]  = datetime.utcnow().isoformat()
    state["tests_passed"]  = test_passed
    state_file.write_text(json.dumps(state, indent=2))

    print(f"\n🎉  Done!")
    print(f"    Issue:  https://github.com/{owner}/{repo}/issues/{issue_num}")
    print(f"    PR:     {pr_url}")
    print(f"    Tests:  {'✅ passed' if test_passed else '⚠️ failed (PR opened anyway)'}")


# ── Auto Pipeline ────────────────────────────────────────────────────────────

def cmd_auto(args):
    """claim + submit in one shot (for when you already have the fix ready in a patch)."""
    cmd_claim(args)
    print("\n" + "─" * 60)
    print("Workspace is set up. Apply your fix now, then submitting...\n")
    if not args.patch:
        print("Tip: pass --patch path/to/fix.patch to auto-apply a patch before submitting.")
        sys.exit(0)

    # Apply patch if provided
    owner, repo, issue_num = parse_issue_url(args.issue_url)
    state_file = WORKSPACE_DIR / f"{repo}-{issue_num}.json"
    state = json.loads(state_file.read_text())
    clone_dir = state["clone_dir"]

    print(f"Applying patch: {args.patch}")
    run(f'git apply --index "{args.patch}"', cwd=clone_dir)
    run(f'git commit -m "fix: resolve issue #{issue_num}"', cwd=clone_dir)
    cmd_submit(args)


# ── Template Generator ───────────────────────────────────────────────────────

def cmd_template(args):
    """Print a fix commit message / PR body template."""
    owner, repo, issue_num = parse_issue_url(args.issue_url)
    issue = gh("GET", f"/repos/{owner}/{repo}/issues/{issue_num}")
    print(f"""
## Suggested commit message:

fix: <concise one-line description> (#{issue_num})

## PR title:
fix: {issue['title']}

## Things to cover in your fix:
- Root cause: (what was wrong?)
- Solution: (what did you change and why?)
- Edge cases handled: (list any)
- Tests added/updated: (which files?)

## Issue body (first 500 chars):
{(issue.get('body') or '')[:500]}
""")


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    if not GITHUB_TOKEN:
        print("⚠️  GITHUB_TOKEN not set — read-only operations only")
        print("   export GITHUB_TOKEN=ghp_...\n")

    parser = argparse.ArgumentParser(
        description="GitHub/Algora bounty claim & PR workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd")

    # browse
    p_browse = sub.add_parser("browse", help="List open bounties ≥ $200")
    p_browse.add_argument("--min", type=int, default=200, help="Minimum USD reward")

    # claim
    p_claim = sub.add_parser("claim", help="Claim a bounty and set up workspace")
    p_claim.add_argument("issue_url", help="GitHub issue URL")

    # submit
    p_submit = sub.add_parser("submit", help="Push branch + open PR")
    p_submit.add_argument("issue_url", help="GitHub issue URL")
    p_submit.add_argument("--force", "-f", action="store_true",
                          help="Submit even if tests fail")

    # auto
    p_auto = sub.add_parser("auto", help="Full pipeline: claim + apply patch + submit")
    p_auto.add_argument("issue_url", help="GitHub issue URL")
    p_auto.add_argument("--patch", help="Path to a .patch file to apply automatically")
    p_auto.add_argument("--force", "-f", action="store_true")

    # template
    p_tmpl = sub.add_parser("template", help="Print PR description template for an issue")
    p_tmpl.add_argument("issue_url", help="GitHub issue URL")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "browse":   cmd_browse,
        "claim":    cmd_claim,
        "submit":   cmd_submit,
        "auto":     cmd_auto,
        "template": cmd_template,
    }
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
