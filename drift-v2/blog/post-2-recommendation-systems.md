# Production Drift in Recommendation Systems: A Case Study

**Published:** 2026-02-24
**Author:** TIAMAT Drift Monitor Team
**Tags:** recommendation systems, embedding drift, cosine distance, case study
**Reading time:** 10 min

---

## The Invisible Staleness Problem

Recommendation systems are among the most drift-prone ML workloads in production. They're fed by:
- User behavior (seasonal, trend-driven, rapidly shifting)
- Item catalogs (new products, removed SKUs, price changes)
- Embedding models (periodically retrained, sometimes silently)

And yet most teams monitor their recommendation systems by watching **click-through rates** — a business metric that lags the actual model failure by days to weeks.

This case study traces a real drift scenario in a media streaming recommendation system and shows how embedding drift detection caught a silent degradation 11 days before it showed up in CTR dashboards.

---

## System Overview

**Platform:** Mid-size streaming service, ~400K daily active users
**Model:** Two-tower retrieval model (user tower + content tower), 128-dimensional embeddings
**Serving:** Approximate nearest neighbor (ANN) search over 85,000 item embeddings
**Retraining schedule:** Weekly, on the previous 14 days of interaction data

The recommendation pipeline looks like this:

```
User session → User encoder → 128-dim embedding
                                    ↓
                            ANN search (FAISS)
                                    ↓
                        Top-K candidate items
                                    ↓
                        Ranker (LightGBM) → Final recs
```

Drift monitoring is placed at the user encoder output — the 128-dim embeddings before ANN retrieval.

---

## Setting Up Embedding Monitoring

```python
import numpy as np
import requests

DRIFT_API = "https://tiamat.live"

# Register the embedding monitor
resp = requests.post(f"{DRIFT_API}/drift/register", json={
    "name": "user-tower-embeddings",
    "model_type": "embedding",
    "config": {
        "threshold": 0.08,   # Cosine drift > 0.08 triggers alert
        "webhook_url": "https://hooks.slack.com/services/T.../B.../xxx"
    }
})
model_id = resp.json()["model_id"]  # → 3

# Baseline: sample 500 user embeddings from a stable week (no retrains, no catalog changes)
# Shape: (500, 128) — list of 128-dim vectors
baseline_embeddings = get_user_embeddings_for_date_range("2024-10-01", "2024-10-07")
# baseline_embeddings.shape == (500, 128)

resp = requests.post(f"{DRIFT_API}/drift/baseline", json={
    "model_id": model_id,
    "samples": baseline_embeddings.tolist()  # nested list of 128-dim vectors
})
print(resp.json())
# → {"model_id": 3, "method": "cosine", "sample_count": 500, ...}
```

The cosine drift algorithm computes:
1. **Centroid drift:** Cosine distance between baseline centroid and new sample centroid
2. **Per-sample similarity shift:** Change in mean cosine similarity to the baseline centroid

Combined score: `0.7 × centroid_drift + 0.3 × similarity_shift`

---

## The Incident Timeline

### Week 1: Stable Operation

The weekly retrain ran on Monday, October 7. New training data reflected the previous 14 days.

```
Oct 07 (post-retrain): cosine_score = 0.021  ✓
Oct 08:                cosine_score = 0.019  ✓
Oct 09:                cosine_score = 0.023  ✓
Oct 10:                cosine_score = 0.018  ✓
```

Scores below `0.05` are considered stable. The centroid is consistent. Interpretation from the API:

```json
{
  "method": "cosine",
  "score": 0.021,
  "centroid_drift": 0.024,
  "cosine_similarity": 0.976,
  "mean_sample_similarity": 0.918,
  "baseline_mean_similarity": 0.921,
  "interpretation": "Score < 0.05: stable, 0.05-0.15: minor, > 0.15: significant drift"
}
```

### The Silent Break (October 11)

On October 11, a data engineering team pushed a change to the interaction event schema. A `watch_duration_seconds` field was normalized differently — divided by `3600` instead of the previous `max_duration` normalization. This changed the scale of a key input feature.

The model wasn't retrained. It continued running with stale weights on changed input distributions.

### Days 11–14: Creeping Drift

```
Oct 11: cosine_score = 0.031   ← still stable, drift beginning
Oct 12: cosine_score = 0.047   ← approaching threshold
Oct 13: cosine_score = 0.061   ← moderate drift, below 0.08 threshold
Oct 14: cosine_score = 0.079   ← almost at threshold
Oct 15: cosine_score = 0.094   ← ALERT FIRES (threshold = 0.08)
```

**Slack alert received at 08:47 UTC, October 15:**

```json
{
  "model_id": 3,
  "model_name": "user-tower-embeddings",
  "method": "cosine",
  "score": 0.094,
  "threshold": 0.08,
  "sample_n": 500,
  "timestamp": "2024-10-15T08:47:22Z"
}
```

At this point:
- CTR had dropped from 4.8% → 4.6% (within normal variance, not yet flagged)
- Session completion rate: unchanged
- User complaints: zero

The alert fired **before any business metric moved meaningfully**.

### Investigation

The ML engineer who received the alert pulled the detailed drift result:

```python
status = requests.get(f"{DRIFT_API}/drift/status/3").json()

# Latest check details
latest = status["checks"][0]
details = latest["details"]

print(f"Centroid drift:        {details['centroid_drift']:.4f}")   # 0.1021
print(f"Cosine similarity:     {details['cosine_similarity']:.4f}") # 0.8979
print(f"Mean sample sim:       {details['mean_sample_similarity']:.4f}") # 0.8841
print(f"Baseline mean sim:     {details['baseline_mean_similarity']:.4f}") # 0.9211
```

The centroid had moved significantly. This indicated the *average* user representation had shifted — not individual users becoming noisier, but a systematic change in the embedding space.

The data engineering team was pinged. They identified the normalization change within 2 hours.

**Time from bug introduction to detection: 4 days.**
**Time from detection to root cause: 2 hours.**
**Time to first user complaint (if undetected): estimated 8–12 more days.**

---

## What the Sparkline Told Us

The Drift Monitor dashboard shows an ASCII sparkline of recent scores:

```
▁▁▁▁▁▂▂▃▄▅▆▇  ← drift accumulating over time
```

A healthy model shows flat:
```
▁▁▁▁▁▁▁▁▁▁▁▁  ← stable
```

A post-retrain model often shows a small bump then recovery:
```
▁▁▂▃▂▁▁▁▁▁▁▁  ← retrain spike, then re-stabilizes
```

The gradual ramp is the pattern that deserves your attention. It indicates a systemic shift, not noise.

---

## Threshold Calibration for Embeddings

Embedding drift thresholds depend heavily on your dimensionality and model architecture.

```python
# Default threshold: 0.15 (permissive — only catches severe drift)
# We used 0.08 (stricter — catches moderate drift early)

# To find your right threshold:
# 1. Run daily checks for 2-3 weeks with no known incidents
# 2. Get your "noise floor" — the 95th percentile of scores on stable days
# 3. Set threshold = 2x noise floor

# Example calibration:
stable_scores = [0.019, 0.023, 0.018, 0.021, 0.024, 0.022, 0.020, 0.017, 0.025, 0.019]
noise_floor_p95 = np.percentile(stable_scores, 95)  # → 0.025
recommended_threshold = 2.0 * noise_floor_p95       # → 0.050

print(f"Recommended threshold: {recommended_threshold:.3f}")
```

For this system with a 0.08 threshold:
- **False positive rate:** ~3% (days flagged when no real issue)
- **Detection lag:** 4 days (time from bug to alert)
- **Miss rate:** ~1% (severe drift events that weren't caught within 24h)

---

## Monitoring the Ranker Separately

In a two-stage system, you want drift monitors on both stages:

```python
# Tower embeddings (semantic drift)
embedding_monitor = register_model("user-tower-embeddings", "embedding", threshold=0.08)

# Ranker output probabilities (score distribution drift)
ranker_monitor = register_model("ranker-scores", "probability", threshold=0.15)

# Run both checks daily
def daily_drift_check(user_embeddings, ranker_scores):
    # Check tower drift
    emb_result = check_drift(embedding_monitor, user_embeddings)

    # Check ranker score distribution
    # ranker_scores shape: (N, K) where K = number of candidate items
    rank_result = check_drift(ranker_monitor, ranker_scores)

    return {
        "tower_drift": emb_result["score"],
        "tower_alert": emb_result["alert"],
        "ranker_drift": rank_result["score"],
        "ranker_alert": rank_result["alert"],
    }
```

Monitoring both gives you **localization**: if the tower drifts but the ranker doesn't, the issue is in upstream feature engineering or the encoder. If the ranker drifts but the tower is stable, the issue is in candidate scoring or label distribution.

---

## Performance Numbers

Real observed values from this deployment:

| Scenario | PSI / Cosine Score | Alert |
|----------|-------------------|-------|
| Healthy, post-retrain day 1 | 0.021 | No |
| Healthy, stable operation | 0.017–0.028 | No |
| Minor schema change (non-breaking) | 0.048 | No |
| **Watch duration normalization bug** | **0.094** | **Yes** |
| Encoder retrain with major architecture change | 0.187 | Yes |
| Full concept drift (new user cohort, holiday) | 0.143 | Yes |

---

## Latency Overhead

The drift check runs out-of-band from recommendation serving:

```
User request → Tower encode (12ms) → ANN search (8ms) → Ranker (4ms) → Response
                      ↓
               [async] collect embedding sample
                      ↓
               [cron, every hour] batch check 500 samples → 45ms
```

**Zero added latency to user-facing requests.** The check runs on a sampled hourly batch, not on every individual request.

---

## Business Impact Summary

| Metric | Value |
|--------|-------|
| Drift detected | Day 4 post-incident (Oct 15) |
| Without monitoring | Estimated Day 15 (via CTR review) |
| Detection lead time | **11 days earlier** |
| Engineers alerted | 1 (on-call ML engineer) |
| Time to resolution | 3.5 hours (fix + validation) |
| Estimated CTR recovery | 0.2pp (vs. extended degradation) |
| Cost of monitoring | $99/mo |

---

## Lessons Learned

1. **Business metrics lag model metrics.** CTR is affected by dozens of factors — model output drift is one of them, diluted by everything else. By the time your CTR dashboard shows it, you've already lost ground.

2. **Embedding drift is subtle but cumulative.** Individual cosine distances of 0.02 look like noise. Trends over 4-5 days are signal.

3. **Two-stage monitoring gives localization.** Know which component drifted, not just that *something* drifted.

4. **The threshold matters as much as the metric.** A 0.25 threshold would have missed this incident. Calibrate to your model's stability profile.

---

**Previous:** [Early Warning: Catching Model Degradation Before Users Notice →](./post-1-early-warning.md)
**Next:** [Automating Your ML Observability Stack →](./post-3-automating-ml-observability.md)
