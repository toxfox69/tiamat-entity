# GitHub App Native Integration (CI/CD Webhooks)

## Overview

Lightweight Node.js webhook receiver for the GitHub App that processes CI/CD events
and integrates them with the OpenPango orchestration system.

## Architecture

```
GitHub App
    │
    │  HMAC-SHA256 signed POST /webhook
    ▼
WebhookServer (webhook_server.js)
    │  verifySignature → dispatch
    ▼
CIHandler (ci_handler.js)
    │  event routing
    ├─→ onPullRequest  → spawn Coder agent via router.py
    ├─→ onIssueComment → spawn Coder agent (if @openpango mention)
    ├─→ onPush         → spawn Manager agent
    ├─→ onWorkflowRun  → spawn Researcher agent (on failure)
    ├─→ onCheckRun     → log
    └─→ onCheckSuite   → log
    │
    ▼
GitHubClient (github_client.js)
    │  stdlib https only
    └─→ GitHub REST API v2022-11-28
```

## Events Handled

| Event | Actions | Behaviour |
|-------|---------|-----------|
| `pull_request` | opened, synchronize, reopened | Fetch PR diff, dispatch Code Review task to Coder agent, post acknowledgement comment |
| `issue_comment` | created | If comment contains `@openpango <cmd>`, summon Coder agent to implement fix and open PR |
| `push` | — | Detect protected branches, dispatch CI task to Manager agent |
| `workflow_run` | completed | On `failure`/`timed_out`, dispatch investigation task to Researcher agent |
| `check_run` | completed, rerequested | Log status |
| `check_suite` | completed | Log status |

## Permission Scoping (Critical)

The agent **NEVER** auto-merges or pushes directly to:
- `main`
- `master`
- `develop`
- `release/*`
- Any branch with a GitHub branch protection rule

For agent-generated PRs, the target branch is always
`openpango/fix-issue-<N>` (or equivalent non-protected branch).

## Setup

### 1. Create GitHub App

1. Go to **GitHub Settings → Developer settings → GitHub Apps → New GitHub App**
2. Set **Webhook URL** to `https://your-host/webhook`
3. Generate a **Webhook secret** and save it
4. Set **Permissions**:
   - Repository → Contents: Read
   - Repository → Pull requests: Read & Write
   - Repository → Issues: Read & Write
   - Repository → Checks: Read & Write
   - Repository → Workflows: Read
5. Subscribe to events: `pull_request`, `issue_comment`, `push`, `workflow_run`, `check_run`, `check_suite`
6. Install the app on target repositories

### 2. Configure Environment

```bash
export GITHUB_WEBHOOK_SECRET="your-webhook-secret"
export GITHUB_TOKEN="ghp_..."          # GitHub App installation token
export GITHUB_WEBHOOK_PORT="8080"      # default 8080
export OPENPANGO_ROUTER="/path/to/skills/orchestration/router.py"
```

### 3. Run

```bash
# Install dependencies (none beyond stdlib)
node skills/github_app/webhook_server.js

# Or with pm2
pm2 start skills/github_app/webhook_server.js --name github-webhook

# Health check
curl http://localhost:8080/health

# Audit log (last 50 events)
curl http://localhost:8080/events
```

### 4. nginx proxy (production)

```nginx
location /webhook {
    proxy_pass http://127.0.0.1:8080/webhook;
    proxy_set_header X-Real-IP $remote_addr;
}
```

## Agent Summon Syntax

In any issue or PR comment:

```
@openpango fix this null pointer bug
@openpango add unit tests for auth module
@openpango refactor the payment handler to use async/await
```

The agent will:
1. Acknowledge in the comment thread
2. Clone the repository
3. Implement the requested change
4. Open a PR targeting a non-protected branch

## Testing

```bash
# Run full Jest suite
npm test

# Test webhook signature manually
node -e "
const crypto = require('crypto');
const secret = 'test-secret';
const payload = JSON.stringify({action:'opened'});
const sig = 'sha256=' + crypto.createHmac('sha256', secret).update(payload).digest('hex');
console.log(sig);
"
```

## Integration with OpenPango Orchestration

Tasks are dispatched via `skills/orchestration/router.py`:

```
spawn <AgentType>          → returns session_id
append <session_id> <task> → queues task
status <session_id>        → check progress
output <session_id>        → fetch results
```

Agent types used:
- **Coder** — code review, bug fixes, PR generation
- **Manager** — CI coordination, multi-step tasks
- **Researcher** — workflow failure investigation

## Files

```
skills/github_app/
├── webhook_server.js   — HTTP server, HMAC verification, event routing
├── github_client.js    — GitHub REST API client (stdlib https)
├── ci_handler.js       — Event handlers + orchestration bridge
├── SKILL.md            — This file
├── package.json        — Dependencies and test scripts
└── tests/
    └── webhook.test.js — Jest test suite
```
