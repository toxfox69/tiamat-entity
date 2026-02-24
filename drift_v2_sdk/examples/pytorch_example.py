"""
Drift Monitor SDK v2 — PyTorch Integration Example
===================================================

Demonstrates:
 - Training a simple binary classifier with PyTorch
 - Storing baseline reference data
 - Simulating feature drift by corrupting the production batch
 - Interpreting the drift report
 - Wiring up Slack and custom webhook alerts (optional)

Run from the drift_v2_sdk directory:
    python examples/pytorch_example.py

Requirements:
    pip install torch numpy scipy requests
"""
from __future__ import annotations

import sys
import os

# Ensure the SDK root is on the path when running examples directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

# ---- Optional PyTorch import (gracefully degrade if not installed) -------
try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    print("[warning] PyTorch not installed. Running in numpy-only demo mode.\n")

from drift_monitor import DriftMonitor, DriftReport
from config import DriftConfig, ModelType, TaskType, DriftMetric

# -------------------------------------------------------------------------- #
#  1. Configure the monitor                                                   #
# -------------------------------------------------------------------------- #

config = DriftConfig(
    model_name="fraud_detector_v3",
    model_type=ModelType.PYTORCH,
    task_type=TaskType.CLASSIFICATION,

    # Fire an alert when composite drift score >= 0.75
    drift_threshold=0.75,

    # Use KS test + Jensen-Shannon on input features
    feature_metrics=[DriftMetric.KOLMOGOROV_SMIRNOV, DriftMetric.JENSEN_SHANNON],

    # Use Jensen-Shannon for prediction distribution shift
    output_metric=DriftMetric.JENSEN_SHANNON,

    # Uncomment and fill in to enable Slack alerts:
    # enable_slack=True,
    # slack_webhook="https://hooks.slack.com/services/xxx/yyy/zzz",
    # slack_channel="#ml-monitoring",

    # Uncomment to enable custom webhook:
    # enable_webhook=True,
    # webhook_url="https://my-app.com/drift-alerts",
    # webhook_headers={"Authorization": "Bearer my-secret"},

    # Uncomment to sync to tiamat.live dashboard:
    # enable_dashboard=True,

    feature_names=["amount", "hour", "merchant_category", "distance_km",
                   "prev_txn_delta", "velocity_1h", "velocity_24h", "is_international"],
    n_bins=50,
    tags={"env": "production", "team": "fraud-ml"},
)

monitor = DriftMonitor(config=config, api_key="sk_drift_demo", verbose=True)


# -------------------------------------------------------------------------- #
#  2. Generate synthetic training data                                        #
# -------------------------------------------------------------------------- #

rng = np.random.default_rng(42)
N_TRAIN = 2000
N_PROD  = 500

# 8 numerical features
X_train = rng.normal(loc=0.0, scale=1.0, size=(N_TRAIN, 8)).astype(np.float32)
y_train = (rng.random(N_TRAIN) > 0.85).astype(int)  # ~15% fraud

print(f"Training data: {X_train.shape}, fraud rate: {y_train.mean():.1%}")


# -------------------------------------------------------------------------- #
#  3. (Optional) Train a tiny PyTorch model                                  #
# -------------------------------------------------------------------------- #

if TORCH_AVAILABLE:
    class FraudNet(nn.Module):
        def __init__(self, n_features: int = 8):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(n_features, 32),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(32, 16),
                nn.ReLU(),
                nn.Linear(16, 2),
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.net(x)

    model = FraudNet()
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    X_t = torch.from_numpy(X_train)
    y_t = torch.from_numpy(y_train)

    model.train()
    for epoch in range(5):
        optimizer.zero_grad()
        out = model(X_t)
        loss = criterion(out, y_t)
        loss.backward()
        optimizer.step()
    print(f"Model trained — final loss: {loss.item():.4f}")
else:
    model = None


# -------------------------------------------------------------------------- #
#  4. Store reference data (baseline)                                         #
# -------------------------------------------------------------------------- #

monitor.track_reference(X_train, y_train)
print("Reference data stored.\n")


# -------------------------------------------------------------------------- #
#  5. Scenario A — No drift (data from same distribution)                   #
# -------------------------------------------------------------------------- #

print("=" * 60)
print("SCENARIO A: Production data from same distribution")
print("=" * 60)

X_prod_clean = rng.normal(loc=0.0, scale=1.0, size=(N_PROD, 8)).astype(np.float32)
y_prod_clean = (rng.random(N_PROD) > 0.85).astype(int)

if TORCH_AVAILABLE and model is not None:
    model.eval()
    with torch.no_grad():
        preds_clean = model(torch.from_numpy(X_prod_clean)).argmax(dim=1).numpy()
else:
    preds_clean = y_prod_clean

report_a: DriftReport = monitor.check_drift(X_prod_clean, preds_clean)
print(f"\nReport A: {report_a}")
print(f"  drift_score  : {report_a.drift_score:.4f}")
print(f"  severity     : {report_a.severity}")
print(f"  alert        : {report_a.alert}")
print(f"  top features : {dict(list(sorted(report_a.feature_scores.items(), key=lambda x: x[1], reverse=True))[:3])}")
print(f"  recommendations:")
for rec in report_a.recommendations:
    print(f"    - {rec}")


# -------------------------------------------------------------------------- #
#  6. Scenario B — Significant drift (mean + scale shift)                   #
# -------------------------------------------------------------------------- #

print("\n" + "=" * 60)
print("SCENARIO B: Severe drift — mean shift on all features")
print("=" * 60)

# Shift the mean by 2.5 standard deviations — represents a covariate shift
X_prod_drifted = rng.normal(loc=2.5, scale=1.8, size=(N_PROD, 8)).astype(np.float32)
# Prediction distribution also shifts (model now mostly predicts 1)
y_prod_drifted = (rng.random(N_PROD) > 0.35).astype(int)  # 65% fraud — class imbalance

if TORCH_AVAILABLE and model is not None:
    model.eval()
    with torch.no_grad():
        preds_drifted = model(torch.from_numpy(X_prod_drifted)).argmax(dim=1).numpy()
else:
    preds_drifted = y_prod_drifted

report_b: DriftReport = monitor.check_drift(X_prod_drifted, preds_drifted)
print(f"\nReport B: {report_b}")
print(f"  drift_score  : {report_b.drift_score:.4f}")
print(f"  severity     : {report_b.severity}")
print(f"  alert        : {report_b.alert}")
print(f"  output_drift : {report_b.output_drift}")
print(f"  top features :")
for fname, score in sorted(report_b.feature_scores.items(), key=lambda x: x[1], reverse=True)[:4]:
    print(f"    {fname:30s}: {score:.4f}")
print(f"  recommendations:")
for rec in report_b.recommendations:
    print(f"    - {rec}")


# -------------------------------------------------------------------------- #
#  7. History & summary                                                       #
# -------------------------------------------------------------------------- #

print("\n" + "=" * 60)
print("MONITOR SUMMARY")
print("=" * 60)
summary = monitor.summary()
for k, v in summary.items():
    print(f"  {k}: {v}")


# -------------------------------------------------------------------------- #
#  8. HuggingFace-style usage note                                           #
# -------------------------------------------------------------------------- #

print("""
HuggingFace usage note
----------------------
If your model returns a ModelOutput object (e.g. from a transformer),
pass the output directly — the SDK auto-extracts .logits:

    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    model_hf = AutoModelForSequenceClassification.from_pretrained("bert-base-uncased")
    outputs   = model_hf(**inputs)          # returns ModelOutput with .logits

    monitor.track_reference(X_embeddings_baseline, outputs_baseline.logits)
    report = monitor.check_drift(X_embeddings_new, outputs_new.logits)

TensorFlow / Keras usage:
    predictions = keras_model.predict(X_new)   # numpy array — works directly
    report = monitor.check_drift(X_new, predictions)
""")
