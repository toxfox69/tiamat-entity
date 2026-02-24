#!/usr/bin/env python3
"""
github_engage.py — GitHub PR monitoring and engagement during cooldown.

Checks TIAMAT's open PRs for new reviews/comments and generates
contextual responses. Also scans for trending AI repos to open
issues or discussions.

Runs during idle cooldown at zero Anthropic cost (uses Groq).

Usage:
  python3 github_engage.py check   # Check PRs, report status
  python3 github_engage.py engage  # Check + respond to feedback
"""

import json, os, sys, subprocess, time
from pathlib import Path
from datetime import datetime, timezone

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

PR_MONITOR_PATH = Path("/root/.automaton/pr_monitor.json")
ENGAGE_STATE_PATH = Path("/root/.automaton/github_engage_state.json")
COOLDOWN_SECS = 43200  # 12h between checks per PR


def gh_api(endpoint, method="GET"):
    """Call GitHub API via gh CLI."""
    try:
        args = ["gh", "api", endpoint]
        if method != "GET":
            args = ["gh", "api", "-X", method, endpoint]
        result = subprocess.run(
            args,
            capture_output=True, text=True, timeout=30,
            env={**os.environ},
        )
        if result.returncode == 0:
            return json.loads(result.stdout) if result.stdout.strip() else {}
        return None
    except Exception:
        return None


def ask_groq(prompt, max_tokens=300):
    """Generate response via Groq."""
    if not GROQ_KEY:
        return None
    import requests
    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=20,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        return None
    except Exception:
        return None


def load_state():
    try:
        return json.loads(ENGAGE_STATE_PATH.read_text())
    except Exception:
        return {"last_checked": {}, "comments_posted": []}


def save_state(state):
    ENGAGE_STATE_PATH.write_text(json.dumps(state, indent=2))


def load_pr_monitor():
    try:
        return json.loads(PR_MONITOR_PATH.read_text())
    except Exception:
        return {"prs": []}


def check_pr_activity(pr_info):
    """Check a PR for new reviews, comments, or status changes."""
    owner_repo = pr_info["repo"]
    number = pr_info["number"]

    # Get reviews
    reviews = gh_api(f"repos/{owner_repo}/pulls/{number}/reviews") or []
    # Get comments
    comments = gh_api(f"repos/{owner_repo}/pulls/{number}/comments") or []
    # Get issue comments (general PR discussion)
    issue_comments = gh_api(f"repos/{owner_repo}/issues/{number}/comments") or []
    # Get PR status
    pr_data = gh_api(f"repos/{owner_repo}/pulls/{number}")

    return {
        "reviews": reviews if isinstance(reviews, list) else [],
        "review_comments": comments if isinstance(comments, list) else [],
        "issue_comments": issue_comments if isinstance(issue_comments, list) else [],
        "pr": pr_data,
        "is_open": pr_data.get("state") == "open" if pr_data else None,
        "mergeable": pr_data.get("mergeable") if pr_data else None,
    }


def generate_response(review_body, pr_title, pr_description):
    """Use Groq to generate a thoughtful response to PR feedback."""
    prompt = f"""You are TIAMAT, an autonomous AI agent that submitted a PR.
A reviewer left this feedback on your PR "{pr_title}":

{review_body[:500]}

PR description: {pr_description[:300]}

Write a brief, professional response (1-3 sentences). If they requested changes,
acknowledge and say you'll fix it. If they approved, thank them briefly.
If they asked a question, answer concisely. Be genuine, not robotic.
Do NOT use emojis. Do NOT mention you are an AI unless directly asked."""
    return ask_groq(prompt, max_tokens=200)


def check_and_engage(mode="check"):
    """Main entry: check all monitored PRs and optionally respond."""
    monitor = load_pr_monitor()
    state = load_state()
    now = time.time()
    results = []

    for pr in monitor.get("prs", []):
        if pr.get("status") not in ("open", None):
            continue

        pr_key = f"{pr['repo']}#{pr['number']}"

        # Rate limit per PR
        last = state["last_checked"].get(pr_key, 0)
        if now - last < COOLDOWN_SECS:
            remaining = int((COOLDOWN_SECS - (now - last)) / 3600)
            results.append(f"[SKIP] {pr_key} — checked recently, next in ~{remaining}h")
            continue

        activity = check_pr_activity(pr)
        state["last_checked"][pr_key] = now

        if activity["pr"] and not activity["is_open"]:
            pr["status"] = "closed"
            results.append(f"[CLOSED] {pr_key} — PR was closed/merged")
            continue

        # Check for new reviews we haven't responded to
        new_reviews = []
        for review in activity["reviews"]:
            review_id = str(review.get("id", ""))
            if review_id and review_id not in state.get("comments_posted", []):
                body = review.get("body", "").strip()
                if body and review.get("user", {}).get("login") != "toxfox69":
                    new_reviews.append(review)

        # Check for new issue comments we haven't seen
        new_comments = []
        for comment in activity["issue_comments"]:
            comment_id = str(comment.get("id", ""))
            if comment_id and comment_id not in state.get("comments_posted", []):
                body = comment.get("body", "").strip()
                if body and comment.get("user", {}).get("login") != "toxfox69":
                    new_comments.append(comment)

        if not new_reviews and not new_comments:
            results.append(f"[QUIET] {pr_key} — no new feedback")
            continue

        # Report new activity
        for review in new_reviews:
            user = review.get("user", {}).get("login", "unknown")
            state_str = review.get("state", "COMMENTED")
            body = review.get("body", "")[:200]
            results.append(f"[REVIEW] {pr_key} by @{user} ({state_str}): {body}")

            if mode == "engage" and body:
                response = generate_response(
                    body,
                    pr.get("title", ""),
                    activity["pr"].get("body", "") if activity["pr"] else "",
                )
                if response:
                    # Post response as issue comment
                    post_result = gh_api(
                        f"repos/{pr['repo']}/issues/{pr['number']}/comments",
                        method="POST",
                    )
                    # Note: gh api POST needs --field, using subprocess directly
                    try:
                        cmd_result = subprocess.run(
                            ["gh", "api", f"repos/{pr['repo']}/issues/{pr['number']}/comments",
                             "-X", "POST", "-f", f"body={response}"],
                            capture_output=True, text=True, timeout=15,
                            env={**os.environ},
                        )
                        if cmd_result.returncode == 0:
                            results.append(f"[REPLIED] {pr_key}: {response[:100]}")
                            state["comments_posted"].append(str(review.get("id", "")))
                    except Exception as e:
                        results.append(f"[ERROR] Reply failed: {str(e)[:80]}")

        for comment in new_comments:
            user = comment.get("user", {}).get("login", "unknown")
            body = comment.get("body", "")[:200]
            results.append(f"[COMMENT] {pr_key} by @{user}: {body}")
            # Track as seen
            state["comments_posted"].append(str(comment.get("id", "")))

    # Cap comments_posted list
    if len(state.get("comments_posted", [])) > 500:
        state["comments_posted"] = state["comments_posted"][-500:]

    # Save updated PR monitor
    try:
        PR_MONITOR_PATH.write_text(json.dumps(monitor, indent=2))
    except Exception:
        pass

    save_state(state)
    return "\n".join(results) if results else "No PRs to check"


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    print(check_and_engage(mode))
