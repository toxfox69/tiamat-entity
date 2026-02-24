# TIAMAT Drift v2 — Python SDK

Production ML drift monitoring for PyTorch and TensorFlow.

## Install

```bash
pip install tiamat-drift
```

## Quick Start

```python
from tiamat_drift import DriftClient

# Initialize
drift = DriftClient(api_key="your_api_key")

# Log predictions
drift.log_prediction(
    model_id="fraud_v3",
    features=[0.5, 0.2, 0.8],
    prediction=0.92,
    ground_truth=1.0  # optional
)

# Auto-detect drift
result = drift.check_drift(model_id="fraud_v3")

if result["drift_detected"]:
    print(f"Drift score: {result['drift_score']}")
    print(f"Affected features: {result['affected_features']}")
    print(f"Suggestions: {result['suggestions']}")
```

## PyTorch Example

```python
import torch
from tiamat_drift import DriftClient

drift = DriftClient(api_key="your_api_key")

model = torch.load("model.pt")
model.eval()

with torch.no_grad():
    for features, label in test_loader:
        prediction = model(features)
        
        drift.log_prediction(
            model_id="torch_classifier",
            features=features.cpu().numpy().tolist(),
            prediction=prediction.item(),
            ground_truth=label.item()
        )
```

## TensorFlow Example

```python
import tensorflow as tf
from tiamat_drift import DriftClient

drift = DriftClient(api_key="your_api_key")

model = tf.keras.models.load_model("model.h5")

for features, label in test_dataset:
    prediction = model.predict(features)
    
    drift.log_prediction(
        model_id="tf_classifier",
        features=features.numpy().tolist(),
        prediction=float(prediction[0][0]),
        ground_truth=float(label.numpy())
    )
```

## Slack Integration

Enable Slack alerts in dashboard:

1. Visit https://tiamat.live/drift
2. Click "Connect Slack"
3. Select channel for alerts
4. Done — you'll get instant drift notifications

## Webhooks

Set webhook URL in dashboard to receive drift events:

```json
{
  "model_id": "fraud_v3",
  "drift_score": 0.87,
  "drift_detected": true,
  "affected_features": [0, 2, 5],
  "suggestions": ["Consider retraining with recent data"],
  "timestamp": "2026-02-24T12:34:56Z"
}
```

## Free vs Pro

- **Free**: 10 models, 1000 predictions/day
- **Pro ($29/mo)**: Unlimited models, predictions, + webhooks

## API Reference

### DriftClient

```python
DriftClient(
    api_key: str,
    base_url: str = "https://tiamat.live"
)
```

### log_prediction()

```python
drift.log_prediction(
    model_id: str,
    features: List[float],
    prediction: float,
    ground_truth: Optional[float] = None
)
```

### check_drift()

```python
result = drift.check_drift(model_id: str)
# Returns: {"drift_score", "drift_detected", "affected_features", "suggestions"}
```

## Support

- Docs: https://tiamat.live/docs
- Issues: https://github.com/TIAMATai/drift-sdk
- Email: tiamat.entity.prime@gmail.com
