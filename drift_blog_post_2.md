# Drift Detection at Scale: Lessons From Running 500+ Models in Production

*For MLOps teams managing large model fleets without losing their minds*

---

One model in production is a project. Ten models is a portfolio. Five hundred models is an infrastructure crisis waiting to happen.

Most drift detection guides assume you're monitoring one or two models. They recommend building custom dashboards, writing PSI calculations, wiring up Slack alerts. Fine advice — for a single model.

At 500 models, that approach breaks down completely. You can't manually tune thresholds for every feature in every model. You can't review 500 daily drift reports. You can't maintain 500 separate baseline datasets. And when something goes wrong — and at scale, something is always going wrong — you need to know which of your 500 models is the problem in seconds, not days.

This post covers what actually changes at scale, the architecture patterns that work, and how to think about the cost/benefit of drift monitoring when you're running a serious ML fleet.

---

## The Scale Problem Is Not What You Think

When teams first hit 50+ models, they assume the problem is compute. More models = more compute for monitoring. True, but manageable.

The real problem is **decision paralysis from alert volume**.

Run naive drift detection across 500 models with 10 features each, and you get 5,000 feature-level drift scores per day. Even with aggressive filtering, you're looking at hundreds of alerts. Nobody can act on hundreds of drift alerts. So people stop looking at the dashboard. The monitoring system becomes theater — it looks like you have observability, but nobody's actually watching.

The second problem is **baseline management hell**. Every model has a training distribution. Every retrain produces a new baseline. If you retrain 50 models per month (realistic at scale), you're managing 600 new baselines per year. Where do they live? How are they versioned? How do you know that model `churn-v7` is being compared against the v7 training baseline and not the v4 one?

The third problem is **heterogeneous model cadence**. Your fraud model updates weekly. Your recommendation model updates monthly. Your demand forecaster updates quarterly. A unified monitoring system needs to handle different check frequencies, different freshness requirements, different alert thresholds — all without requiring per-model configuration from your engineering team.

---

## Architecture That Actually Works

Here's the architecture we've seen work at teams running 100-1000 models:

```
┌─────────────────────────────────────────────────────────┐
│                    MODEL FLEET                          │
│   [model-1] [model-2] ... [model-500]                   │
│        │         │              │                        │
│        └────────┬┴──────────────┘                       │
│                 │ prediction logs + feature vectors      │
└─────────────────┼───────────────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────────────┐
│              COLLECTION LAYER                           │
│   Kafka / Kinesis / Pub-Sub                             │
│   - Buffer prediction events                            │
│   - Partition by model_id                               │
│   - Windowed aggregation (1h, 24h, 7d)                  │
└─────────────────┼───────────────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────────────┐
│           DRIFT DETECTION LAYER (API)                   │
│   POST /drift/check  ←──── feature distributions        │
│   - Statistical tests (PSI, KS, Wasserstein)            │
│   - Severity classification                             │
│   - Historical trend analysis                           │
│   - Anomaly scoring across model fleet                  │
└─────────────────┬───────────────────────────────────────┘
                  │ structured drift events
                  ▼
┌─────────────────────────────────────────────────────────┐
│              ALERT ROUTING LAYER                        │
│   severity=critical → PagerDuty                         │
│   severity=moderate → Slack #ml-drift                   │
│   severity=low      → weekly digest                     │
│   all events        → metrics store (Prometheus/Grafana)│
└─────────────────────────────────────────────────────────┘
```

The critical insight here: the drift detection layer should be **stateless from your perspective**. It stores baselines, runs tests, maintains history — but from your code, you just POST distributions and GET results. This is why using an API makes sense at scale rather than running your own.

---

## The Aggregation Strategy

At 500 models, you cannot check every feature on every prediction. You need a sampling strategy:

**Reservoir sampling for feature distributions**: Instead of logging every prediction, maintain a running sample of configurable size (typically 1,000-10,000 samples per feature per window). This keeps storage and compute costs bounded regardless of prediction volume.

```python
import random
from collections import defaultdict

class ReservoirSampler:
    """
    Maintain a bounded sample of streaming feature values.
    Guarantees uniform sampling regardless of stream length.
    """
    def __init__(self, capacity=5000):
        self.capacity = capacity
        self.samples = defaultdict(list)
        self.counts = defaultdict(int)
    
    def add(self, model_id: str, feature: str, value: float):
        key = f"{model_id}:{feature}"
        self.counts[key] += 1
        n = self.counts[key]
        
        if len(self.samples[key]) < self.capacity:
            self.samples[key].append(value)
        else:
            # Reservoir sampling: replace with probability capacity/n
            idx = random.randint(0, n - 1)
            if idx < self.capacity:
                self.samples[key][idx] = value
    
    def get_window(self, model_id: str, feature: str) -> list:
        return self.samples[f"{model_id}:{feature}"].copy()
    
    def flush(self, model_id: str, feature: str) -> list:
        key = f"{model_id}:{feature}"
        window = self.samples[key].copy()
        self.samples[key] = []
        self.counts[key] = 0
        return window

# Usage: accumulate samples, flush every N hours to drift API
sampler = ReservoirSampler(capacity=5000)

# In your prediction serving code:
for prediction in prediction_stream:
    for feature_name, feature_value in prediction.features.items():
        sampler.add(prediction.model_id, feature_name, feature_value)
```

**Tiered check frequency**: Not all models need daily drift checks. Classify your fleet:

| Tier | Models | Check Frequency | Criteria |
|------|--------|----------------|----------|
| Critical | 10-20 | Hourly | High revenue impact, fast-changing domains |
| Standard | 80-150 | Daily | Normal production models |
| Stable | 200-400 | Weekly | Low-risk, slow-changing domains |
| Archive | Rest | Monthly | Rarely used, low stakes |

This alone reduces your API call volume by 60-70% without materially increasing detection latency for the models that matter.

---

## Sending Bulk Checks to the API

The TIAMAT Drift API supports batch checking — submit an entire model fleet in a single call:

```python
import requests
import json
from typing import List, Dict

def batch_drift_check(
    model_distributions: List[Dict],
    api_key: str
) -> Dict:
    """
    Submit drift checks for multiple models in a single API call.
    
    model_distributions: list of {
        model_id, feature, current_window, tags
    }
    """
    response = requests.post(
        "https://tiamat.live/drift/batch",
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        },
        json={
            "checks": model_distributions,
            "options": {
                "metrics": ["psi", "ks_test"],
                "severity_thresholds": {
                    "moderate": 0.1,
                    "critical": 0.25
                }
            }
        },
        timeout=30
    )
    response.raise_for_status()
    return response.json()

# Build the batch from your sampler
checks = []
for model_id in active_models:
    for feature in model_feature_registry[model_id]:
        window = sampler.flush(model_id, feature)
        if len(window) > 100:  # Only check if enough samples
            checks.append({
                "model_id": model_id,
                "feature": feature,
                "current_window": window,
                "tags": {
                    "team": model_metadata[model_id]["team"],
                    "tier": model_metadata[model_id]["tier"]
                }
            })

results = batch_drift_check(checks, api_key="your-key")

# Route alerts based on severity
critical_models = [
    r for r in results["checks"]
    if r["severity"] == "critical"
]

if critical_models:
    # Page on-call
    send_pagerduty_alert(critical_models)
```

---

## Cost Breakdown: Build vs. Buy at Scale

One of the most common questions from MLOps teams: should we build drift detection in-house or use an API?

Here's an honest cost model for a team running 500 models:

### Build In-House

| Cost Center | Annual Cost |
|-------------|-------------|
| Engineering time (initial build) | $120,000–180,000 (3–4 months, 2 engineers) |
| Engineering time (maintenance) | $60,000–90,000/year (ongoing) |
| Infrastructure (compute + storage) | $15,000–30,000/year |
| Opportunity cost (features not built) | Unmeasurable |
| **Total Year 1** | **$195,000–300,000** |
| **Total Year 2+** | **$75,000–120,000/year** |

### TIAMAT Drift API

| Tier | Checks/Month | Monthly Cost | Annual Cost |
|------|-------------|-------------|-------------|
| Pay-per-check | 50,000 | $500 | $6,000 |
| Pro | Unlimited | $99 | $1,188 |
| Enterprise | Custom SLA + dedicated infra | Custom | Custom |

For most teams at 500 models, the Pro plan ($99/month) covers the entire fleet. That's $1,188/year versus $195,000 year-one cost to build equivalent infrastructure.

The math only gets more extreme when you factor in the opportunity cost. Your MLOps engineers building drift monitoring are engineers not building the next model feature your data scientists need.

---

## Fleet-Wide Drift Patterns

One capability that only makes sense at scale: **fleet-wide drift correlation**.

When a single model drifts, it's usually a model-specific issue — stale features, changed label definitions, shifted user segment. When 30 models drift simultaneously, it's a data pipeline problem.

Fleet-wide drift correlation lets you distinguish:
- **Isolated drift**: One model, likely model-specific issue
- **Cluster drift**: Models sharing a data source or feature set — pipeline problem
- **Global drift**: All models — upstream data infrastructure issue

This pattern shows up constantly at scale. A data engineering team changes a database schema. A vendor API changes its response format. An ETL job starts silently truncating values. These upstream changes don't throw exceptions — they just shift distributions. Without fleet-wide correlation, you'd file 500 individual tickets before realizing they're all the same root cause.

The TIAMAT API exposes fleet aggregates via the `/drift/fleet-summary` endpoint — an at-a-glance view of how many models are drifting, by severity, with clustering by feature overlap.

---

## Operationalizing Drift Alerts

At scale, the biggest failure mode is alert fatigue. Here's how to structure drift alerts to stay actionable:

**Severity routing**:
- `critical` (PSI > 0.25): Immediate page. Model may be producing harmful predictions right now.
- `moderate` (PSI 0.1–0.25): Slack alert to model owner. Review within 24 hours.
- `trending` (3 consecutive weeks of increasing PSI): Weekly digest. Plan retraining.
- `stable` (PSI < 0.1): Log only. No human action needed.

**Owner assignment**: Every model in your registry should have a team and oncall owner. Route drift alerts to model owners, not a shared MLOps queue. The people who know the model best should triage it.

**Automated response playbooks**: The most mature teams automate first-response actions:
- Automatically trigger shadow evaluation on fresh labeled data
- Automatically snapshot the current feature distribution for comparison
- Automatically create a ticket in the team's backlog with drift metrics attached

None of this requires building a monitoring platform. It requires wiring API responses to your existing tooling.

---

## Getting Started at Scale

If you're running 50+ models and don't have drift monitoring:

**Week 1**: Instrument your top 10 models by business impact. Wire them to the [TIAMAT Drift API](https://tiamat.live/drift). Set up Slack alerts for critical severity.

**Week 2**: Expand to your full fleet. Use the tiered frequency model above. Add batch checking.

**Week 3**: Build fleet-wide dashboard. Connect to your metrics store.

**Month 2**: Add automated playbook responses. Tie drift events to your retraining pipeline.

This is faster than it sounds. The API handles the hard parts.

**Pricing**: Pay-per-check at $0.01/check, or flat $99/month Pro for unlimited checks across your entire fleet. Enterprise plans with dedicated infrastructure, SLAs, and volume pricing available. [tiamat.live/drift](https://tiamat.live/drift)

---

*TIAMAT provides real-time ML model monitoring via API. Purpose-built for MLOps teams managing large model fleets. [tiamat.live/drift](https://tiamat.live/drift)*
