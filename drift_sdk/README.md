# TIAMAT Drift SDK

```bash
pip install tiamat-drift
```

```python
from tiamat_drift import DriftMonitor

monitor = DriftMonitor(api_key="tiamat_xxx", model_id="prod_model")
result = monitor.log_prediction({"age": 35, "income": 75000}, prediction=0.87)

if result["drift_detected"]:
    print(f"Drift: {result['drift_score']:.2%}")
```

Free tier: 10 models. Pro: $49/mo unlimited.
