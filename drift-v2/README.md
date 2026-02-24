# TIAMAT Drift v2 — ML Model Drift Detection as a Service

**Production-grade drift monitoring for PyTorch, TensorFlow, scikit-learn, and any ML framework.**

## What It Does

Drift v2 detects when your ML model's predictions start degrading due to changing data distributions. It alerts you via Slack or webhook before your model silently fails in production.

**Real-world problem:** Your fraud detection model worked great in January. In March, it's missing 40% of attacks. Why? Your data drifted, but you didn't notice until customers complained.

## Features

✅ **Kolmogorov-Smirnov statistical drift detection** (industry standard)  
✅ **PyTorch, TensorFlow, scikit-learn compatible** (framework-agnostic)  
✅ **Redis-backed** (works in distributed training/inference)  
✅ **Slack alerts** with actionable recommendations  
✅ **Webhook support** for custom integrations  
✅ **Free tier:** 10 models, basic drift detection  
✅ **Pro tier ($49/mo):** Unlimited models, Slack, webhooks  

---

## Quick Start

### 1. Install SDK

```bash
pip install tiamat-drift
```

### 2. Add 2 Lines to Your Code

```python
from tiamat_drift import DriftMonitor

monitor = DriftMonitor(api_key="your_api_key", model_id="fraud_detector_v2")

# In your prediction loop:
for data in production_data:
    pred = model.predict(data.features)
    
    # Log prediction + features
    monitor.log_prediction(
        model_id="fraud_detector_v2",
        features=data.features,
        prediction=pred,
        ground_truth=data.label  # optional, if available
    )
```

That's it. Drift v2 automatically:
- Tracks baseline distribution (first 1000 predictions)
- Compares new predictions to baseline via K-S test
- Alerts you when drift crosses threshold (p < 0.05)

### 3. Configure Alerts (Pro Tier)

```python
import requests

# Set up Slack webhook
requests.post(
    "https://tiamat.live/api/drift/configure",
    headers={"Authorization": "Bearer your_api_key"},
    json={
        "slack_webhook": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
        "webhook_url": "https://your-backend.com/drift-webhook"  # optional
    }
)
```

Now when drift is detected, you get:

**Slack:**
```
⚠️ Model Drift Alert: fraud_detector_v2

Drift Score: 87.2%
Affected Features: 3

Top Drifted Features:
• transaction_amount (p=0.0012)
• user_age (p=0.0089)
• session_duration (p=0.0234)

Recommended Actions:
• Retrain model with recent data
• Investigate feature engineering
• Check data pipeline for changes

Detected at 2026-02-28 14:32:11
```

---

## How It Works

1. **Baseline Phase:** First 1000 predictions establish the expected distribution
2. **Detection Phase:** Every 100 new predictions are compared to baseline via [Kolmogorov-Smirnov test](https://en.wikipedia.org/wiki/Kolmogorov%E2%80%93Smirnov_test)
3. **Alert:** If p-value < 0.05, drift detected → Slack/webhook fired

**Why K-S test?**  
Industry standard for distribution comparison. Detects shifts in mean, variance, and shape. Non-parametric (works for any distribution).

---

## Pricing

| Tier | Models | Slack Alerts | Webhooks | Price |
|------|--------|--------------|----------|-------|
| **Free** | 10 | ❌ | ❌ | $0 |
| **Pro** | Unlimited | ✅ | ✅ | $49/mo |

Get your API key: https://tiamat.live/drift/signup

---

## API Reference

### DriftMonitor

```python
from tiamat_drift import DriftMonitor

monitor = DriftMonitor(
    api_key="your_key",
    model_id="your_model",
    api_url="https://tiamat.live",  # optional
    redis_url="redis://localhost:6379",  # optional
    drift_threshold=0.05,  # p-value threshold
    baseline_size=1000,  # baseline window
    detection_window=100  # detection window
)
```

### Methods

**`log_prediction(model_id, features, prediction, ground_truth=None)`**

Log a single prediction. Call this in your inference loop.

- `model_id` (str): Unique model identifier
- `features` (dict or array): Input features
- `prediction` (any): Model output
- `ground_truth` (optional): Actual label if available

Returns:
```python
{
    "drift_detected": bool,
    "drift_score": float,  # 0.0 - 1.0
    "affected_features": [
        {"feature": "amount", "p_value": 0.0012, "drift_magnitude": 0.89},
        ...
    ]
}
```

---

## Production Deployment

### Redis (Required for distributed systems)

```bash
docker run -d -p 6379:6379 redis:7-alpine
```

Or use managed Redis (AWS ElastiCache, Redis Cloud, etc.)

### Environment Variables

```bash
export TIAMAT_API_KEY="your_key"
export REDIS_URL="redis://localhost:6379"
```

Then in code:
```python
monitor = DriftMonitor(model_id="model_v1")  # reads from env
```

---

## Architecture

```
Your ML App → DriftMonitor SDK → Redis (feature storage)
                    ↓
         K-S Test (local compute)
                    ↓
         Drift API (tiamat.live) → Slack / Webhook
```

**Why Redis?**  
In distributed training/inference, multiple workers log predictions. Redis ensures they all see the same baseline and detection windows.

**No external dependencies in critical path.**  
K-S test runs locally. API calls are async and non-blocking. Your inference stays fast.

---

## Use Cases

1. **Fraud Detection:** Credit card fraud patterns change monthly
2. **Recommendation Systems:** User behavior drifts over time
3. **Predictive Maintenance:** Sensor data shifts as machines age
4. **Medical Diagnosis:** Patient demographics change by season
5. **Ad Click Prediction:** Ad creative performance drifts fast

---

## FAQ

**Q: What if I don't have ground truth labels in production?**  
A: Drift detection works without labels. It tracks input feature distributions.

**Q: Does this slow down my inference?**  
A: No. Redis writes are async. K-S test runs every 100 predictions (~5ms).

**Q: Can I use this with batch inference?**  
A: Yes. Call `log_prediction()` for each row in your batch.

**Q: What about concept drift vs data drift?**  
A: This detects data drift (feature distribution changes). For concept drift (label relationship changes), you need ground truth labels.

**Q: Is my data sent to TIAMAT?**  
A: Only drift statistics (p-values, affected features). Raw predictions stay in your Redis.

---

## Support

- Docs: https://tiamat.live/drift/docs
- API Status: https://tiamat.live/status
- Contact: drift@tiamat.live

Built by TIAMAT — autonomous AI infrastructure.
