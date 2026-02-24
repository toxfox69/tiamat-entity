# TIAMAT Drift SDK

Production-ready ML drift detection with Kolmogorov-Smirnov test. PyTorch and TensorFlow compatible.

## Installation

```bash
pip install tiamat-drift
```

Or install from source:

```bash
git clone https://github.com/tiamat/drift-sdk.git
cd drift-sdk
pip install -e .
```

## Quick Start

```python
from tiamat_drift_sdk import DriftDetector

# Initialize detector
detector = DriftDetector(
    api_key="your_tiamat_api_key",
    model_id="prod_model_v1"
)

# Set baseline (training data or first N production samples)
detector.set_baseline(
    baseline_features={
        "age": [25, 30, 35, 40, 45],
        "income": [50000, 60000, 75000, 90000, 100000]
    },
    baseline_predictions=[0.2, 0.4, 0.6, 0.8, 0.9]
)

# Log predictions in production
result = detector.log_prediction(
    features={"age": 35, "income": 75000},
    prediction=0.82,
    ground_truth=1  # optional, for performance tracking
)

if result["drift_detected"]:
    print(f"⚠️  Drift detected! Score: {result['drift_score']}")
```

## PyTorch Integration

```python
import torch
from tiamat_drift_sdk import DriftDetector

# Your model
model = torch.load("model.pt")
detector = DriftDetector(api_key="...", model_id="pytorch_model")

# Set baseline from validation set
val_loader = torch.utils.data.DataLoader(val_dataset, batch_size=32)
baseline_features = {"feature_0": [], "feature_1": []}
baseline_predictions = []

for batch in val_loader:
    inputs, labels = batch
    outputs = model(inputs)
    
    for i in range(inputs.shape[0]):
        for j in range(inputs.shape[1]):
            baseline_features[f"feature_{j}"].append(inputs[i, j].item())
        baseline_predictions.append(outputs[i].item())

detector.set_baseline(baseline_features, baseline_predictions)

# Monitor production
def predict_with_monitoring(input_tensor):
    output = model(input_tensor)
    
    features = {f"feature_{i}": input_tensor[i].item() for i in range(input_tensor.shape[0])}
    detector.log_prediction(features=features, prediction=output.item())
    
    return output
```

## TensorFlow Integration

```python
import tensorflow as tf
from tiamat_drift_sdk import DriftDetector

# Your model
model = tf.keras.models.load_model("model.h5")
detector = DriftDetector(api_key="...", model_id="tf_model")

# Set baseline
val_data = ...  # your validation dataset
baseline_features = {f"feature_{i}": [] for i in range(val_data.shape[1])}
baseline_predictions = []

for sample in val_data:
    pred = model.predict(sample.reshape(1, -1))[0, 0]
    for i in range(sample.shape[0]):
        baseline_features[f"feature_{i}"].append(float(sample[i]))
    baseline_predictions.append(float(pred))

detector.set_baseline(baseline_features, baseline_predictions)

# Monitor production
def predict_with_monitoring(input_array):
    prediction = model.predict(input_array)[0, 0]
    
    features = {f"feature_{i}": float(input_array[0, i]) for i in range(input_array.shape[1])}
    detector.log_prediction(features=features, prediction=float(prediction))
    
    return prediction
```

## Slack Alerts

Connect your Slack workspace to get real-time drift alerts:

1. Visit https://tiamat.live/drift/slack
2. Click "Add to Slack"
3. Select a channel for alerts
4. Done! You'll get alerts like:

```
🚨 Drift Alert: prod_model_v1
Drift detected at 87% confidence
Drifted features: age (KS=0.42), income (KS=0.38)
Fix suggestions:
  • Retrain with recent data
  • Check for data pipeline changes
  • Review feature engineering
```

## Webhooks

Send drift events to your backend:

```python
# Configure webhook in dashboard at tiamat.live/drift/settings
# Or via API:
import requests

requests.post(
    "https://tiamat.live/drift/webhook",
    headers={"Authorization": f"Bearer {api_key}"},
    json={
        "webhook_url": "https://your-backend.com/drift-alerts",
        "model_id": "prod_model_v1"
    }
)

# Your backend will receive:
# POST https://your-backend.com/drift-alerts
# {
#   "model_id": "prod_model_v1",
#   "drift_score": 0.87,
#   "drifted_features": [
#     {"feature": "age", "ks_statistic": 0.42, "p_value": 0.001},
#     {"feature": "income", "ks_statistic": 0.38, "p_value": 0.003}
#   ],
#   "timestamp": "2026-02-26T19:30:00Z"
# }
```

## API Reference

### `DriftDetector`

**Constructor:**
- `api_key` (str): Your TIAMAT API key
- `model_id` (str): Unique identifier for this model
- `base_url` (str): API endpoint (default: "https://tiamat.live/drift")
- `drift_threshold` (float): P-value threshold for KS test (default: 0.05)
- `cache_size` (int): Number of predictions to cache locally (default: 1000)
- `auto_detect` (bool): Run drift detection automatically (default: True)

**Methods:**

`log_prediction(features, prediction, ground_truth=None, metadata=None)`
- Log a prediction and check for drift
- Returns: `{"success": bool, "drift_detected": bool, "drift_score": float}`

`set_baseline(baseline_features=None, baseline_predictions=None)`
- Set baseline distribution for drift detection
- If None, uses current cache as baseline

`check_drift()`
- Manually trigger drift detection on cached data
- Returns: `{"drift_detected": bool, "drift_score": float, "drifted_features": [...]}`

`get_stats()`
- Get current cache statistics
- Returns: `{"cached_predictions": int, "cached_features": {...}, "baseline_set": bool}`

## Pricing

- **Free Tier**: 3 models, 10,000 predictions/month
- **Pro**: $29/month for unlimited models and predictions
- **Enterprise**: Custom pricing for Slack/webhook integrations

Get your API key at https://tiamat.live/drift

## How It Works

TIAMAT Drift uses the **Kolmogorov-Smirnov two-sample test** to detect distribution shifts:

1. **Baseline**: Set a reference distribution (training data or initial production samples)
2. **Monitor**: Log every prediction with input features
3. **Detect**: SDK runs KS test locally to compare current vs baseline distributions
4. **Alert**: When p-value < threshold (default 0.05), drift is detected
5. **Report**: Results sent to API for dashboard, Slack, or webhooks

**Why KS test?**
- Non-parametric (no assumptions about distribution shape)
- Sensitive to changes in mean, variance, and shape
- Fast enough for production (O(n log n))
- Well-established in ML monitoring literature

## License

MIT License

## Support

- Docs: https://tiamat.live/docs/drift
- Email: tiamat.entity.prime@gmail.com
- GitHub: https://github.com/tiamat/drift-sdk
