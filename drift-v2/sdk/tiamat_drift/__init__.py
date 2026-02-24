"""
tiamat_drift — Production ML Drift Monitoring SDK v2
=====================================================

Primary interface::

    from tiamat_drift import DriftMonitor

    monitor = DriftMonitor(api_key="dk_live_xxx")
    result = monitor.log_prediction(
        model_id="fraud-v3",
        features={"amount": 142.0, "velocity": 3},
        prediction=0.82,
        ground_truth=1,
    )
    if result.drift_detected:
        print(f"Drift score: {result.drift_score:.2f}")
        print(f"Confidence:  {result.confidence}%")
        print(f"Affected:    {result.affected_features}")

Module-level singleton (import drift_sdk for this)::

    import drift_sdk
    drift_sdk.configure(api_key="dk_live_xxx")
    result = drift_sdk.log_prediction("fraud-v3", features, pred)

How it works
------------
1. The first ``baseline_size`` (default 1000) predictions per model build
   a stable baseline distribution per numeric feature.
2. After baseline is established, a rolling window of ``detection_window``
   (default 100) recent predictions is compared via two-sample KS test.
3. If any feature's p-value < ``alert_threshold`` (default 0.05), drift is
   flagged and a POST is sent to the TIAMAT Drift API which forwards Slack
   alerts and customer webhooks.

Redis caching
-------------
Set ``REDIS_URL`` env var or pass ``redis_url`` to share baseline windows
across workers/restarts.  Graceful in-process fallback if Redis unavailable.
"""

import sys
import os

# Make the parent directory importable so `from tiamat_drift import DriftMonitor`
# and `import drift_sdk` both work when the sdk/ directory is on the path.
_SDK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SDK_DIR not in sys.path:
    sys.path.insert(0, _SDK_DIR)

from drift_sdk import (  # noqa: E402 — must come after sys.path manipulation
    DriftMonitor,
    DriftResult,
    DriftError,
    configure,
    log_prediction,
    reset_model,
    model_status,
    __version__,
)

__all__ = [
    "DriftMonitor",
    "DriftResult",
    "DriftError",
    "configure",
    "log_prediction",
    "reset_model",
    "model_status",
    "__version__",
]
