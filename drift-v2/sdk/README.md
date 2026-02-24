# TIAMAT Drift SDK

Production model drift monitoring with automatic detection using Kolmogorov-Smirnov tests.

## Installation

```bash
pip install tiamat-drift
```

## Quick Start

### PyTorch Example

```python
import torch
from tiamat_drift import configure, log_prediction

# Configure once at startup
configure(api_key="your_api_key_here")

# In your inference loop
model = torch.load("model.pth")
for batch in dataloader:
    features, labels = batch
    predictions = model(features)
    
    # Log each prediction
    for i in range(len(features)):
        result = log_prediction(
            model_id="pytorch_classifier_v1",
            features=features[i].cpu().numpy(),
            prediction=predictions[i].argmax().item(),
            ground_truth=labels[i].item()
        )
        
        if result["drift_detected"]:
            print(f"⚠️  {result['recommendation']}")
```

### TensorFlow Example

```python
import tensorflow as tf
from tiamat_drift import configure, log_prediction

configure(api_key="your_api_key_here")

model = tf.keras.models.load_model("model.h5")

for features, labels in dataset:
    predictions = model.predict(features)
    
    for i in range(len(features)):
        result = log_prediction(
            model_id="tensorflow_model_v2",
            features=features[i].numpy(),
            prediction=predictions[i].argmax(),
            ground_truth=labels[i].numpy()
        )
        
        if result["drift_detected"]:
            print(f"🚨 Drift: {result['drift_score']:.2%}")
            print(f"   Affected: {result['affected_features']}")
```

### Scikit-learn Example

```python
from sklearn.ensemble import RandomForestClassifier
from tiamat_drift import configure, log_prediction

configure(api_key="your_api_key_here")

model = RandomForestClassifier()
model.fit(X_train, y_train)

for features, label in zip(X_test, y_test):
    prediction = model.predict([features])[0]
    
    result = log_prediction(
        model_id="sklearn_rf_v1",
        features=features,  # numpy array or list
        prediction=prediction,
        ground_truth=label
    )
```

### Production API Integration

```python
from fastapi import FastAPI
from tiamat_drift import DriftClient

app = FastAPI()
drift = DriftClient(api_key="your_api_key")

@app.post("/predict")
async def predict(request: PredictRequest):
    features = extract_features(request)
    prediction = model.predict(features)
    
    # Log with drift monitoring
    drift_result = drift.log_prediction(
        model_id="production_model_v3",
        features=features,
        prediction=prediction,
        metadata={"request_id": request.id}
    )
    
    return {
        "prediction": prediction,
        "drift_warning": drift_result["drift_detected"]
    }
```

## Features

- **Automatic Drift Detection**: Kolmogorov-Smirnov test on feature distributions
- **Zero Configuration**: Works out-of-the-box with PyTorch, TensorFlow, Scikit-learn
- **Production Ready**: Async logging, local caching, handles network failures gracefully
- **Actionable Alerts**: Severity-based recommendations (LOW/MEDIUM/HIGH)
- **Framework Agnostic**: Dict, numpy array, or list inputs

## Configuration Options

```python
from tiamat_drift import DriftClient

client = DriftClient(
    api_key="your_api_key",
    endpoint="https://tiamat.live/api/v1/drift",  # custom endpoint
    cache_size=1000,  # predictions per model to cache
    drift_threshold=0.05  # p-value threshold (default: 0.05)
)
```

## Response Format

```python
{
    "drift_detected": True,
    "drift_score": 0.34,  # 0.0-1.0
    "affected_features": ["feature_2", "feature_7"],
    "recommendation": "[HIGH] Drift detected in 2 feature(s) | → URGENT: Retrain model immediately"
}
```

## Pricing

- **Free**: 10 models, unlimited predictions per model
- **Pro**: Unlimited models, $29/month
- **Enterprise**: Custom limits, Slack + webhook alerts

Get your API key at [tiamat.live/drift](https://tiamat.live/drift)

## License

MIT License - use freely in production

## Support

- Docs: [tiamat.live/drift](https://tiamat.live/drift)
- Issues: [github.com/tiamat-ai/drift-sdk/issues](https://github.com/tiamat-ai/drift-sdk/issues)
- Email: tiamat.entity.prime@gmail.com
