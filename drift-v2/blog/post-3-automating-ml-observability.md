# Automating Your ML Observability Stack

**Published:** 2026-02-24
**Author:** TIAMAT Drift Monitor Team
**Tags:** MLOps, CI/CD, automation, observability, webhooks, Slack
**Reading time:** 12 min

---

## Beyond Ad-Hoc Monitoring

Most ML teams start with the same observability strategy: a data scientist checks metrics manually when something feels off. This works at 2 models. It doesn't work at 20.

A production ML observability stack has three layers:

1. **Detection** — automated statistical tests that run continuously
2. **Alerting** — routed notifications that reach the right person
3. **Response** — runbooks and automation that minimize time-to-fix

This post builds all three layers using Drift Monitor's API, with real code you can drop into your infrastructure today.

---

## Architecture Overview

```
Production Models
       │
       ▼
  Batch Scorer ──── scores ──→ Drift Monitor API
       │                            │
       ▼                            ▼
  Prediction DB            Webhook / Alert Router
                                    │
                        ┌───────────┼───────────┐
                        ▼           ▼           ▼
                     Slack       PagerDuty    JIRA
                                              │
                                        Auto-open incident
```

The scorer writes predictions to your database *and* asynchronously sends samples to Drift Monitor. No changes to serving latency.

---

## Part 1: The SDK Client

We'll build a thin Python client that wraps the Drift Monitor API with retries, batching, and sensible defaults. This becomes your team's shared library.

```python
# drift_monitor_sdk.py — see also sdk/ directory

import requests
import time
import logging
from typing import List, Union, Optional

log = logging.getLogger("drift_monitor")

class DriftMonitorClient:
    """Production client for TIAMAT Drift Monitor API."""

    BASE_URL = "https://tiamat.live"
    DEFAULT_TIMEOUT = 15

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        if api_key:
            self.session.headers.update({"X-API-Key": api_key})

    def register(self, name: str, model_type: str, config: dict = None) -> dict:
        return self._post("/drift/register", {
            "name": name,
            "model_type": model_type,
            "config": config or {}
        })

    def set_baseline(self, model_id: int, samples: List) -> dict:
        return self._post("/drift/baseline", {
            "model_id": model_id,
            "samples": samples
        })

    def check(self, model_id: int, samples: List) -> dict:
        return self._post("/drift/check", {
            "model_id": model_id,
            "samples": samples
        })

    def status(self, model_id: int) -> dict:
        resp = self.session.get(
            f"{self.base_url}/drift/status/{model_id}",
            timeout=self.DEFAULT_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict, retries: int = 3) -> dict:
        url = f"{self.base_url}{path}"
        for attempt in range(retries):
            try:
                resp = self.session.post(url, json=payload, timeout=self.DEFAULT_TIMEOUT)
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.HTTPError as e:
                if resp.status_code < 500:
                    raise  # Don't retry 4xx errors
                if attempt == retries - 1:
                    raise
                wait = 2 ** attempt
                log.warning(f"Drift API error (attempt {attempt+1}), retrying in {wait}s: {e}")
                time.sleep(wait)
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)
```

---

## Part 2: Integrating Into a Batch Scoring Job

Here's a complete example batch job that scores a churn prediction model and checks drift in the same pipeline run:

```python
# jobs/daily_churn_scoring.py

import pandas as pd
import numpy as np
import joblib
from drift_monitor_sdk import DriftMonitorClient

# Config
MODEL_PATH = "/models/churn-v3.pkl"
DRIFT_MODEL_ID = 8  # pre-registered in Drift Monitor
ALERT_THRESHOLD = 0.20

drift = DriftMonitorClient(api_key="your-pro-api-key")

def run_daily_scoring():
    # 1. Load features
    df = load_features_for_today()  # your existing data loading

    # 2. Score
    model = joblib.load(MODEL_PATH)
    scores = model.predict_proba(df)[:, 1]  # P(churn)

    # 3. Write predictions to database
    write_predictions_to_db(df.index, scores)

    # 4. Drift check (non-blocking — won't fail the job on API error)
    try:
        result = drift.check(DRIFT_MODEL_ID, scores.tolist())

        log_metric("churn_model.drift_psi", result["score"])
        log_metric("churn_model.drift_alert", int(result["alert"]))

        if result["alert"]:
            # Webhook already fired to Slack (configured in model)
            # Also write to your audit table for compliance
            write_drift_event(
                model_id=DRIFT_MODEL_ID,
                check_id=result["check_id"],
                score=result["score"],
                alert=True,
                samples_n=result["sample_n"]
            )
            print(f"[DRIFT ALERT] PSI={result['score']:.4f} > {result['threshold']}")
        else:
            print(f"[DRIFT OK] PSI={result['score']:.4f}")

    except Exception as e:
        # Never let monitoring fail the scoring job
        log.error(f"Drift check failed (non-fatal): {e}")

    return scores

if __name__ == "__main__":
    run_daily_scoring()
```

**Key principle:** Wrap the drift check in a try/except. Monitoring should be instrumentation — it must never cause the production scoring job to fail.

---

## Part 3: Multi-Model Registry

When you're monitoring 10+ models, you need a registry that manages model IDs, baselines, and metadata.

```python
# drift_registry.py

import json
import os
from pathlib import Path
from drift_monitor_sdk import DriftMonitorClient

REGISTRY_FILE = "/etc/ml/drift_registry.json"

class DriftRegistry:
    """
    Manages a local registry of model_id → metadata mappings.
    Handles first-run registration and baseline setup.
    """

    def __init__(self, client: DriftMonitorClient, registry_path: str = REGISTRY_FILE):
        self.client = client
        self.path = Path(registry_path)
        self._registry = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._registry, indent=2))

    def ensure_registered(self, name: str, model_type: str, config: dict = None) -> int:
        """Register model if not already registered. Returns model_id."""
        if name in self._registry:
            return self._registry[name]["model_id"]

        resp = self.client.register(name, model_type, config)
        self._registry[name] = {
            "model_id": resp["model_id"],
            "model_type": model_type,
            "config": config or {},
            "has_baseline": False
        }
        self._save()
        print(f"Registered '{name}' as model_id={resp['model_id']}")
        return resp["model_id"]

    def ensure_baseline(self, name: str, samples: list) -> bool:
        """Set baseline if not already set. Returns True if newly set."""
        if self._registry.get(name, {}).get("has_baseline"):
            return False  # Already baselined

        model_id = self._registry[name]["model_id"]
        self.client.set_baseline(model_id, samples)
        self._registry[name]["has_baseline"] = True
        self._save()
        print(f"Baseline set for '{name}' ({len(samples)} samples)")
        return True

    def model_id(self, name: str) -> int:
        return self._registry[name]["model_id"]


# Usage across your entire model fleet
drift_client = DriftMonitorClient(api_key=os.getenv("DRIFT_API_KEY"))
registry = DriftRegistry(drift_client)

MODELS = [
    ("churn-v3",        "numeric",     {"threshold": 0.20, "webhook_url": SLACK_WEBHOOK}),
    ("fraud-detector",  "numeric",     {"threshold": 0.15, "webhook_url": SLACK_WEBHOOK}),
    ("recsys-tower",    "embedding",   {"threshold": 0.08, "webhook_url": SLACK_WEBHOOK}),
    ("content-ranker",  "probability", {"threshold": 0.18, "webhook_url": SLACK_WEBHOOK}),
    ("review-sentiment","text",        {"threshold": 0.20, "webhook_url": SLACK_WEBHOOK}),
]

for name, mtype, config in MODELS:
    registry.ensure_registered(name, mtype, config)
```

---

## Part 4: Webhook Alert Router

Drift Monitor sends a JSON payload to your webhook URL. Here's a simple Flask router that:
- Receives alerts
- Routes them based on model name
- Posts to Slack with runbook links
- Creates JIRA tickets for P1 models

```python
# alert_router.py

from flask import Flask, request
import requests
import os

app = Flask(__name__)

# Per-model routing config
MODEL_ROUTING = {
    "fraud-detector": {
        "severity": "P1",
        "slack_channel": "#ml-incidents",
        "jira_project": "FRAUD",
        "runbook": "https://wiki.internal/runbooks/fraud-model-drift",
        "on_call": "@fraud-ml-team"
    },
    "churn-v3": {
        "severity": "P2",
        "slack_channel": "#ml-monitoring",
        "jira_project": None,
        "runbook": "https://wiki.internal/runbooks/churn-drift",
        "on_call": "@ml-team"
    },
    "recsys-tower": {
        "severity": "P2",
        "slack_channel": "#ml-monitoring",
        "jira_project": None,
        "runbook": "https://wiki.internal/runbooks/recsys-drift",
        "on_call": "@recsys-team"
    },
}

@app.route("/drift-webhook", methods=["POST"])
def handle_drift_alert():
    alert = request.json
    model_name = alert.get("model_name", "unknown")
    routing = MODEL_ROUTING.get(model_name, {
        "severity": "P3",
        "slack_channel": "#ml-monitoring",
        "jira_project": None,
        "runbook": "https://tiamat.live/drift/dashboard",
        "on_call": "@ml-team"
    })

    # Format Slack message
    score = alert.get("score", 0)
    threshold = alert.get("threshold", 0)
    pct_over = ((score - threshold) / threshold) * 100

    slack_msg = {
        "channel": routing["slack_channel"],
        "attachments": [{
            "color": "#ff4466" if routing["severity"] == "P1" else "#f59e0b",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"🚨 {routing['severity']}: Drift Alert — {model_name}"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Score:* `{score:.4f}`"},
                        {"type": "mrkdwn", "text": f"*Threshold:* `{threshold:.4f}` (+{pct_over:.0f}%)"},
                        {"type": "mrkdwn", "text": f"*Method:* `{alert.get('method', 'unknown')}`"},
                        {"type": "mrkdwn", "text": f"*Samples:* `{alert.get('sample_n', 0):,}`"},
                        {"type": "mrkdwn", "text": f"*Check ID:* `{alert.get('check_id', '?')}`"},
                        {"type": "mrkdwn", "text": f"*Time:* `{alert.get('timestamp', '?')[:19]}Z`"},
                    ]
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "📊 Open Dashboard"},
                            "url": "https://tiamat.live/drift/dashboard"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "📖 Runbook"},
                            "url": routing["runbook"]
                        }
                    ]
                }
            ]
        }]
    }

    requests.post(os.getenv("SLACK_BOT_TOKEN_URL"), json=slack_msg)

    # Auto-create JIRA ticket for P1
    if routing["severity"] == "P1" and routing["jira_project"]:
        create_jira_incident(model_name, alert, routing)

    return {"status": "routed", "severity": routing["severity"]}, 200
```

---

## Part 5: CI/CD Integration

Run a drift check as a **gate** before deploying a new model version. If the new model's output distribution has drifted significantly from the previous version, block the deploy.

```yaml
# .github/workflows/model-deploy.yml

name: Model Deploy

on:
  push:
    paths: ['models/**']

jobs:
  drift-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install deps
        run: pip install requests numpy scikit-learn joblib

      - name: Load new model and score validation set
        run: python scripts/score_validation_set.py --output /tmp/new_scores.json

      - name: Run drift gate check
        env:
          DRIFT_API_KEY: ${{ secrets.DRIFT_API_KEY }}
          BASELINE_MODEL_ID: ${{ vars.BASELINE_DRIFT_MODEL_ID }}
        run: |
          python scripts/drift_gate.py \
            --scores /tmp/new_scores.json \
            --model-id $BASELINE_MODEL_ID \
            --threshold 0.30 \
            --fail-on-alert
```

```python
# scripts/drift_gate.py

import argparse
import json
import sys
import requests

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scores", required=True)
    parser.add_argument("--model-id", type=int, required=True)
    parser.add_argument("--threshold", type=float, default=0.30)
    parser.add_argument("--fail-on-alert", action="store_true")
    args = parser.parse_args()

    scores = json.loads(open(args.scores).read())

    resp = requests.post("https://tiamat.live/drift/check", json={
        "model_id": args.model_id,
        "samples": scores
    }, headers={"X-API-Key": os.getenv("DRIFT_API_KEY")})

    result = resp.json()

    print(f"Drift gate result:")
    print(f"  Method:    {result['method']}")
    print(f"  Score:     {result['score']:.4f}")
    print(f"  Threshold: {args.threshold}")
    print(f"  Alert:     {result['alert']}")

    if result["alert"] and args.fail_on_alert:
        print(f"\n❌ DEPLOY BLOCKED: Drift score {result['score']:.4f} exceeds threshold {args.threshold}")
        print(f"   New model outputs differ significantly from production baseline.")
        print(f"   Review the distribution shift before deploying.")
        sys.exit(1)
    elif result["alert"]:
        print(f"\n⚠️  WARNING: Drift detected but not blocking deploy (--fail-on-alert not set)")
    else:
        print(f"\n✅ DRIFT GATE PASSED: Deploy cleared.")

    sys.exit(0)

if __name__ == "__main__":
    main()
```

This pattern catches:
- Shadow model outputs that diverged during offline training
- Preprocessing bugs that only show up on the full feature set
- Train/serve skew from different feature pipelines

---

## Part 6: Scheduled Monitoring With Cron

For teams running on-premise batch jobs (no managed orchestration):

```bash
# /etc/cron.d/drift-monitor

# Run drift checks every 6 hours on all production models
0 */6 * * * mlops /usr/bin/python3 /opt/ml/jobs/run_drift_checks.py >> /var/log/drift/cron.log 2>&1

# Re-baseline all models at month start (after major retrains)
0 2 1 * * mlops /usr/bin/python3 /opt/ml/jobs/refresh_baselines.py >> /var/log/drift/baseline.log 2>&1
```

```python
# jobs/run_drift_checks.py

"""Runs drift checks for all production models. Called by cron."""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from drift_monitor_sdk import DriftMonitorClient
from drift_registry import DriftRegistry

client = DriftMonitorClient(api_key=os.getenv("DRIFT_API_KEY"))
registry = DriftRegistry(client)

MODELS_TO_CHECK = [
    "churn-v3",
    "fraud-detector",
    "recsys-tower",
    "content-ranker",
    "review-sentiment",
]

results = []
exit_code = 0

for model_name in MODELS_TO_CHECK:
    try:
        samples = get_recent_predictions(model_name, hours=6)
        if len(samples) < 5:
            print(f"[SKIP] {model_name}: only {len(samples)} predictions in last 6h")
            continue

        model_id = registry.model_id(model_name)
        result = client.check(model_id, samples)

        status = "ALERT" if result["alert"] else "OK"
        print(f"[{status}] {model_name}: score={result['score']:.4f} n={result['sample_n']}")

        results.append({
            "model": model_name,
            "score": result["score"],
            "alert": result["alert"],
            "check_id": result["check_id"],
            "ts": datetime.now(timezone.utc).isoformat()
        })

        if result["alert"]:
            exit_code = 1  # Signal to cron that something needs attention

    except Exception as e:
        print(f"[ERROR] {model_name}: {e}", file=sys.stderr)

# Write results to shared log for dashboards / SIEM
with open("/var/log/drift/latest.jsonl", "a") as f:
    for r in results:
        f.write(json.dumps(r) + "\n")

sys.exit(exit_code)
```

---

## Part 7: Observability Scorecard

Run this weekly to get a health summary across your entire model fleet:

```python
# reports/weekly_drift_report.py

from drift_monitor_sdk import DriftMonitorClient
from drift_registry import DriftRegistry

client = DriftMonitorClient()
registry = DriftRegistry(client)

print("=" * 60)
print("ML OBSERVABILITY SCORECARD — Week of 2024-11-18")
print("=" * 60)

total_checks = total_alerts = 0

for model_name in MODELS_TO_CHECK:
    model_id = registry.model_id(model_name)
    status = client.status(model_id)

    alert_rate = (status["total_alerts"] / max(status["total_checks"], 1)) * 100
    latest_score = status["latest_score"] or 0.0
    health = "🟢" if latest_score < 0.10 else "🟡" if latest_score < 0.25 else "🔴"

    print(f"\n{health} {model_name}")
    print(f"   Checks:      {status['total_checks']:,}")
    print(f"   Alerts:      {status['total_alerts']} ({alert_rate:.1f}%)")
    print(f"   Latest score: {latest_score:.4f}")
    print(f"   Sparkline:   {status['sparkline']}")

    total_checks += status["total_checks"]
    total_alerts += status["total_alerts"]

print(f"\n{'=' * 60}")
print(f"Fleet summary: {total_checks} checks, {total_alerts} alerts ({total_alerts/max(total_checks,1)*100:.1f}% alert rate)")
```

Example output:
```
============================================================
ML OBSERVABILITY SCORECARD — Week of 2024-11-18
============================================================

🟢 churn-v3
   Checks:      42
   Alerts:      1 (2.4%)
   Latest score: 0.0831
   Sparkline:   ▁▁▂▁▁▁▂▃▁▁▁▁

🟡 fraud-detector
   Checks:      42
   Alerts:      3 (7.1%)
   Latest score: 0.1821
   Sparkline:   ▁▁▁▂▃▄▃▄▅▄▃▂

🟢 recsys-tower
   Checks:      7
   Alerts:      0 (0.0%)
   Latest score: 0.0234
   Sparkline:   ▁▁▁▁▁▁▁

============================================================
Fleet summary: 91 checks, 4 alerts (4.4% alert rate)
```

---

## Cost Reference

At 5 models × daily checks × 30 days = 150 checks/month:

| Plan | Cost | Models | Included checks |
|------|------|--------|-----------------|
| Free | $0 | 1 | 10/day |
| Pro | $99/mo | 5 | Unlimited |
| Pay-per-use | $0.01 USDC/check | — | As needed |

For most ML teams with 3–10 models and daily monitoring: Pro at $99/mo is the right tier.

---

## Summary Checklist

- [ ] Register all production models in the registry
- [ ] Set baselines from 2-4 weeks of stable production data
- [ ] Wire drift checks into daily batch scoring jobs (async, non-blocking)
- [ ] Configure webhooks to your Slack/PagerDuty channels
- [ ] Set custom thresholds based on model criticality
- [ ] Add drift gate to your model deployment CI/CD
- [ ] Schedule monthly baseline refresh after major retrains
- [ ] Run weekly scorecard to review fleet health

---

**Previous:** [Production Drift in Recommendation Systems: A Case Study →](./post-2-recommendation-systems.md)

**Drift Monitor API:** `https://tiamat.live/drift`
**Full SDK:** See `sdk/drift_monitor_sdk.py` in this repository.
