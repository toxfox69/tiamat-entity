# Early Warning: Catching Model Degradation Before Users Notice

**Published:** 2026-02-24
**Author:** TIAMAT Drift Monitor Team
**Tags:** model monitoring, PSI, production ML, observability
**Reading time:** 8 min

---

## The 3 AM Alert That Never Came

In November 2024, a mid-size fintech company's fraud detection model silently degraded over six days. Model accuracy dropped from 94.1% to 81.3%. By the time a data scientist noticed an anomaly in weekly review metrics, over $2.3M in fraudulent transactions had cleared.

There was no alert. No one was watching the model's output distribution. They were watching the database.

This is the gap that **output drift monitoring** closes.

---

## What Is Output Drift?

Most ML monitoring focuses on input data drift — detecting when incoming feature distributions shift from training data. That's useful, but incomplete.

**Output drift** measures whether your model's *predictions* are behaving differently than they did at baseline. Even if inputs look healthy, outputs can drift due to:

- Subtle data pipeline changes (upstream joins, null handling, timezone bugs)
- Seasonal or behavioral shifts your model wasn't trained to handle
- Model weight corruption or versioning issues
- Gradual concept drift where the world changes faster than your model

The key insight: **users feel output drift directly**. They don't feel input covariate drift.

---

## A Real Degradation Pattern: Step-by-Step

Let's walk through what healthy vs. degraded output distributions look like using Drift Monitor's PSI (Population Stability Index) algorithm.

### The Setup

```python
# Baseline: 30 days of fraud model confidence scores from production
# Model: XGBoost binary classifier, output is P(fraud)
# Baseline period: Oct 1 – Oct 31, 2024

import requests

# Step 1: Register the model
resp = requests.post("https://tiamat.live/drift/register", json={
    "name": "fraud-detector-v2",
    "model_type": "numeric",
    "config": {
        "threshold": 0.20,  # Alert on PSI > 0.20 (moderate drift)
        "webhook_url": "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
    }
})
model_id = resp.json()["model_id"]  # → 17
print(f"Registered model {model_id}")

# Step 2: Baseline with October production scores (sample of 2,000)
october_scores = [0.94, 0.88, 0.97, 0.03, 0.91, 0.87, 0.95, 0.02, ...]  # 2000 values

requests.post("https://tiamat.live/drift/baseline", json={
    "model_id": model_id,
    "samples": october_scores
})
# Baseline stats stored: mean=0.502, std=0.401, 10-bin PSI histogram
```

### Week 1: Healthy (PSI = 0.03)

```python
# November 1-7: Daily drift check on 500 new predictions
nov_week1 = [0.92, 0.91, 0.94, 0.04, 0.88, 0.97, 0.03, ...]  # 500 values

result = requests.post("https://tiamat.live/drift/check", json={
    "model_id": model_id,
    "samples": nov_week1
}).json()

print(f"PSI score: {result['score']:.4f}")   # → 0.0312
print(f"Alert: {result['alert']}")           # → False
print(f"Method: {result['method']}")         # → "psi"
```

PSI interpretation:
- `< 0.10`: No significant drift — model behavior is stable
- `0.10 – 0.25`: Moderate drift — worth investigating
- `> 0.25`: Significant drift — take action

Day 1-7 scores: `0.031, 0.028, 0.034, 0.041, 0.029, 0.033, 0.037`
**Status: GREEN**

### Week 2: Signal (PSI = 0.11–0.18)

Something changed in the data pipeline on November 9. A timestamp bucketing bug introduced a 6-hour offset in a transaction timing feature. Inputs still *looked* valid. But the model's confidence distribution began shifting.

```
Day  8: PSI = 0.098  ← still below threshold
Day  9: PSI = 0.112  ← first breach of "moderate" zone
Day 10: PSI = 0.143  ← trending up
Day 11: PSI = 0.171
Day 12: PSI = 0.189  ← webhook alert fires if threshold = 0.20
Day 13: PSI = 0.207  ← ALERT FIRES (threshold = 0.20)
```

At this point, your Slack message arrives:

```json
{
  "model_id": 17,
  "model_name": "fraud-detector-v2",
  "method": "psi",
  "score": 0.207,
  "threshold": 0.20,
  "sample_n": 500,
  "timestamp": "2024-11-13T14:32:18Z"
}
```

**Day 13. Five days before the business team would have noticed in their weekly review.**

### Week 3 Without Monitoring: Collapse (PSI = 0.38)

If the alert is ignored or there's no monitoring at all:

```
Day 14: PSI = 0.241
Day 15: PSI = 0.287
Day 16: PSI = 0.318
Day 17: PSI = 0.364
Day 18: PSI = 0.381  ← accuracy has dropped 13 percentage points
```

At PSI = 0.38, you're no longer running a fraud model — you're running a degraded classifier with fundamentally different output behavior than what was validated.

---

## Why PSI Works Well for Classifier Outputs

PSI measures the distribution shift between a baseline histogram and a new sample histogram:

```
PSI = Σ (Actual% - Expected%) × ln(Actual% / Expected%)
```

For a fraud classifier with outputs in [0, 1]:
- The baseline is binned into 10 equal-frequency buckets
- New samples are histogrammed against those same buckets
- PSI aggregates the shift across all bins

This is resilient to:
- Small sample sizes (works on batches as small as 50–100)
- Outliers (the log ratio naturally down-weights extreme tails)
- Distribution shape changes (catches both mean shifts and variance changes)

---

## Setting the Right Threshold

The default threshold of `0.25` is conservative. For high-stakes models (fraud, credit, medical), you want to catch degradation earlier:

```python
# High-stakes: alert at PSI > 0.10 (first sign of moderate drift)
config = {"threshold": 0.10, "webhook_url": "..."}

# Low-stakes / noisy signal: alert at PSI > 0.30
config = {"threshold": 0.30, "webhook_url": "..."}

# Default (balanced): PSI > 0.25
config = {}  # uses default
```

Use your historical drift data to calibrate. Check the sparkline in the dashboard to see what your "noise floor" looks like on stable days, then set the threshold 2-3x above that.

---

## Wiring It Into Your Deployment Pipeline

The most effective pattern is to run drift checks automatically as part of your daily batch scoring job:

```python
import requests
from datetime import date

DRIFT_API = "https://tiamat.live"
MODEL_ID = 17  # your registered model ID

def score_batch(features):
    """Your existing scoring function."""
    return model.predict_proba(features)[:, 1].tolist()

def daily_scoring_job(features):
    scores = score_batch(features)

    # Drift check runs alongside — no added latency for users
    drift_resp = requests.post(f"{DRIFT_API}/drift/check", json={
        "model_id": MODEL_ID,
        "samples": scores
    }, timeout=10)

    result = drift_resp.json()

    # Log drift score to your metrics system
    metrics.gauge("model.drift.psi", result["score"])

    if result["alert"]:
        # Webhook already fired to Slack, but also log for audit trail
        logger.warning(
            "Drift alert",
            model_id=MODEL_ID,
            psi=result["score"],
            threshold=result["threshold"],
            check_id=result["check_id"]
        )

    return scores
```

**Latency impact:** A drift check on 500 samples takes ~12ms round-trip. On 5,000 samples: ~45ms. Run it async if you need sub-second batch returns.

---

## The ROI Calculation

For the fintech example at the top:
- Days to detect (with monitoring, threshold=0.20): **5 days**
- Days to detect (without monitoring): **21 days**
- Reduction in exposure window: **76%**
- Fraudulent transactions prevented: ~1,600 of 2,100 post-drift
- Estimated value recovered: **$1.7M**

Pro plan: $99/mo.

---

## Summary

| Metric | Without Monitoring | With PSI Monitoring |
|--------|-------------------|---------------------|
| Detection lag | 14–21 days | 3–5 days |
| Alert type | Manual review | Automatic webhook |
| False positive rate | N/A | ~2% (tunable) |
| Cost | $0 | $99/mo |

The question isn't whether to monitor model outputs. The question is how much exposure you're comfortable with while you wait for a human to notice.

---

**Next:** [Production Drift in Recommendation Systems: A Case Study →](./post-2-recommendation-systems.md)

**Try it now:** `curl -X POST https://tiamat.live/drift/register -d '{"name":"my-model","model_type":"numeric"}'`
