"""
Drift Monitor SDK v2
====================
Real-time model drift detection for PyTorch, TensorFlow, and HuggingFace.

Quick usage::

    from drift_monitor import DriftMonitor, DriftConfig, SlackNotifier

    config = DriftConfig(
        model_name="my_classifier",
        drift_threshold=0.85,
        enable_slack=True,
        slack_webhook="https://hooks.slack.com/...",
    )
    monitor = DriftMonitor(config=config, api_key="sk_drift_xxx")
    monitor.track_reference(X_baseline, y_baseline)
    report = monitor.check_drift(X_new, y_new)
"""

from config import DriftConfig, ModelType, TaskType, DriftMetric, AlertConfig  # noqa: F401
from drift_monitor import DriftMonitor, DriftReport  # noqa: F401
from slack import SlackNotifier  # noqa: F401
from webhook import WebhookNotifier, DashboardSync  # noqa: F401
from metrics import (  # noqa: F401
    kolmogorov_smirnov,
    kl_divergence,
    jensen_shannon,
    wasserstein,
    population_stability_index,
    chi_squared,
    categorical_drift,
    compute_feature_drift,
)

__version__ = "2.0.0"
__author__ = "Drift Monitor"
__all__ = [
    # Config
    "DriftConfig",
    "ModelType",
    "TaskType",
    "DriftMetric",
    "AlertConfig",
    # Core
    "DriftMonitor",
    "DriftReport",
    # Notifiers
    "SlackNotifier",
    "WebhookNotifier",
    "DashboardSync",
    # Metrics (advanced usage)
    "kolmogorov_smirnov",
    "kl_divergence",
    "jensen_shannon",
    "wasserstein",
    "population_stability_index",
    "chi_squared",
    "categorical_drift",
    "compute_feature_drift",
]
