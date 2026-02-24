"""
Drift Monitor SDK v2 — Configuration
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class ModelType(str, Enum):
    """Supported model framework types."""
    PYTORCH = "pytorch"
    TENSORFLOW = "tensorflow"
    HUGGINGFACE = "huggingface"
    SKLEARN = "sklearn"
    GENERIC = "generic"


class TaskType(str, Enum):
    """Supported ML task types."""
    CLASSIFICATION = "classification"
    REGRESSION = "regression"
    EMBEDDING = "embedding"


class DriftMetric(str, Enum):
    """Available drift metrics."""
    KL_DIVERGENCE = "kl_divergence"
    KOLMOGOROV_SMIRNOV = "kolmogorov_smirnov"
    JENSEN_SHANNON = "jensen_shannon"
    POPULATION_STABILITY_INDEX = "psi"
    CHI_SQUARED = "chi_squared"
    WASSERSTEIN = "wasserstein"


@dataclass
class AlertConfig:
    """Per-severity alert threshold configuration."""
    low_threshold: float = 0.50
    medium_threshold: float = 0.70
    high_threshold: float = 0.85
    critical_threshold: float = 0.95


@dataclass
class DriftConfig:
    """
    Top-level configuration for a DriftMonitor instance.

    Parameters
    ----------
    model_name : str
        Human-readable identifier for the monitored model.
    model_type : ModelType
        Framework the model is built with.
    task_type : TaskType
        Classification, regression, or embedding.
    drift_threshold : float
        Composite drift score that triggers an alert (0-1). Default 0.85.
    feature_metrics : list[DriftMetric]
        Metrics used to measure input feature drift.
    output_metric : DriftMetric
        Metric used to measure output/prediction drift.
    alert : AlertConfig
        Fine-grained severity thresholds.
    enable_slack : bool
        Send drift alerts to Slack.
    slack_webhook : str | None
        Incoming-webhook URL for Slack.
    slack_channel : str
        Slack channel to post to.
    enable_webhook : bool
        POST drift events to a custom webhook.
    webhook_url : str | None
        URL to POST drift event payloads.
    webhook_headers : dict
        Extra headers for webhook requests.
    enable_dashboard : bool
        Sync drift events to tiamat.live dashboard.
    dashboard_url : str
        Dashboard ingest endpoint.
    n_bins : int
        Number of histogram bins for density estimation.
    min_reference_samples : int
        Minimum samples required before drift detection is active.
    window_size : int | None
        Rolling window for recent data (None = use all data).
    feature_names : list[str] | None
        Optional list of feature names for richer reports.
    tags : dict
        Arbitrary metadata tags attached to every drift report.
    """

    # Model identity
    model_name: str = "unnamed_model"
    model_type: ModelType = ModelType.GENERIC
    task_type: TaskType = TaskType.CLASSIFICATION

    # Drift detection
    drift_threshold: float = 0.85
    feature_metrics: List[DriftMetric] = field(
        default_factory=lambda: [DriftMetric.KOLMOGOROV_SMIRNOV]
    )
    output_metric: DriftMetric = DriftMetric.JENSEN_SHANNON
    alert: AlertConfig = field(default_factory=AlertConfig)

    # Slack
    enable_slack: bool = False
    slack_webhook: Optional[str] = None
    slack_channel: str = "#ml-alerts"

    # Custom webhook
    enable_webhook: bool = False
    webhook_url: Optional[str] = None
    webhook_headers: Dict[str, str] = field(default_factory=dict)

    # Dashboard sync
    enable_dashboard: bool = True
    dashboard_url: str = "https://tiamat.live/api/drift/events"

    # Estimation parameters
    n_bins: int = 50
    min_reference_samples: int = 100
    window_size: Optional[int] = None

    # Metadata
    feature_names: Optional[List[str]] = None
    tags: Dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ #

    def __post_init__(self) -> None:
        if not 0.0 < self.drift_threshold <= 1.0:
            raise ValueError(
                f"drift_threshold must be in (0, 1], got {self.drift_threshold}"
            )
        if self.enable_slack and not self.slack_webhook:
            self.slack_webhook = os.getenv("DRIFT_SLACK_WEBHOOK")
            if not self.slack_webhook:
                raise ValueError(
                    "enable_slack=True but no slack_webhook provided "
                    "and DRIFT_SLACK_WEBHOOK env var is not set."
                )
        if self.enable_webhook and not self.webhook_url:
            self.webhook_url = os.getenv("DRIFT_WEBHOOK_URL")
            if not self.webhook_url:
                raise ValueError(
                    "enable_webhook=True but no webhook_url provided "
                    "and DRIFT_WEBHOOK_URL env var is not set."
                )

    def severity(self, score: float) -> str:
        """Map a composite drift score to a severity label."""
        if score >= self.alert.critical_threshold:
            return "CRITICAL"
        if score >= self.alert.high_threshold:
            return "HIGH"
        if score >= self.alert.medium_threshold:
            return "MEDIUM"
        if score >= self.alert.low_threshold:
            return "LOW"
        return "NONE"
