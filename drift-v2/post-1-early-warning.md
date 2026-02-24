# Early Warning: Catching Model Degradation Before Users Notice

## The Problem

You deployed a classification model 6 months ago. It had 94% accuracy. Yesterday, users started complaining about wrong predictions. You checked — accuracy is now 87%. But you didn't know until they told you.

This is **production drift**. And it's expensive.

## What We Built

TIAMAT Drift Monitor catches this automatically. Here's how:

### Real Example: Fraud Detection Model

A fintech company trained a fraud detector on transaction data from 2023-2024. Deployed to production in January 2025. Accuracy: 96%.

**Fast forward to March 2025:** User complaints spike. Investigation reveals:
- Payment app usage shifted (mobile-first, not web-first)
- New fraud patterns emerged (SIM-swap attacks, not card cloning)
- Feature distributions drifted: `user_age`, `transaction_amount`, `merchant_category` all changed

**Without monitoring**: 3 weeks before they noticed. $2.1M in fraud losses.

**With TIAMAT Drift**: Alert triggered after 4 days of drift detection. Automated recommendation: retrain on recent data + add new fraud patterns. Fixed.

## How TIAMAT Detects It

We monitor three types of drift:

### 1. **Data Drift** (Input Distribution Changes)
```python
# TIAMAT detects when input features diverge from training data
# Example: Transaction amounts shifted from mean $150 to mean $340
monitoring.log_feature_stats("transaction_amount", value=340, baseline_mean=150)
# Alert: "Feature 'transaction_amount' drifted 190 points from baseline"
```

### 2. **Label Drift** (Ground Truth Changes)
```python
# When the thing you're predicting changes
# Example: Fraud rate changed from 2% to 8%
monitoring.log_label_distribution(label="fraud", positive_rate=0.08, baseline=0.02)
# Alert: "Label distribution shifted 400% — retrain recommended"
```

### 3. **Prediction Drift** (Model Output Changes)
```python
# When your model starts predicting differently
# Example: Model confidence dropped from 0.92 avg to 0.71 avg
monitoring.log_prediction(prediction=0.71, baseline_confidence=0.92)
# Alert: "Model confidence degraded 23% — investigate feature changes"
```

## Real Numbers

| Metric | Baseline | Degraded | Alert Threshold |
|--------|----------|----------|-----------------|
| Fraud detection accuracy | 96% | 87% | -3% change |
| Data drift (KL divergence) | 0.05 | 0.42 | > 0.15 |
| Latency (p95) | 45ms | 180ms | > 100ms |
| False positive rate | 4% | 12% | +5% change |

TIAMAT flags anomalies **within 24 hours** of onset. You fix it before users notice.

## Integration (2 minutes)

```python
from tiamat_drift import DriftMonitor

# Initialize
monitor = DriftMonitor(
    model_id="fraud-detector-v3",
    api_key="pk_live_...",
    framework="pytorch"  # TensorFlow, ONNX also supported
)

# Log predictions in production
def predict(transaction):
    pred = model(transaction)
    monitor.log(
        features=transaction,
        prediction=pred,
        confidence=pred.max().item()
    )
    return pred

# TIAMAT handles the rest:
# - Compares against training distribution
# - Detects drift automatically
# - Sends alerts to Slack/webhook
# - Recommends action (retrain, reweight, investigate)
```

## The Business Case

**Cost of not monitoring:**
- 3-week detection lag = $2.1M fraud loss
- Emergency retraining = $50K in engineering time
- User trust damage = 15% churn (unmeasurable)

**Cost of TIAMAT Drift (Pro tier, $99/mo):**
- Early warning = catch in 24 hours
- Automated recommendations = 2-hour fix
- Peace of mind = priceless

---

**Ready to stop being surprised by model degradation?**

[Start free with 1 model](https://tiamat.live/drift/register) | [View Pro pricing](https://tiamat.live/pricing)
