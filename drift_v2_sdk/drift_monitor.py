"""
Drift Monitor SDK v2
====================
Real-time model drift detection for PyTorch, TensorFlow, and HuggingFace models.

Quickstart
----------
::

    from drift_monitor import DriftMonitor, DriftConfig

    config = DriftConfig(
        model_name="my_classifier",
        drift_threshold=0.85,
        enable_slack=True,
        slack_webhook="https://hooks.slack.com/...",
    )

    monitor = DriftMonitor(config=config, api_key="sk_drift_xxx")
    monitor.track_reference(X_baseline, y_baseline)

    report = monitor.check_drift(X_new, y_new)
    print(report.drift_score, report.severity, report.alert)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from config import DriftConfig, DriftMetric, TaskType
from metrics import (
    categorical_drift,
    compute_feature_drift,
    jensen_shannon,
    kolmogorov_smirnov,
    wasserstein,
)
from slack import SlackNotifier
from webhook import DashboardSync, WebhookNotifier

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  DriftReport — the return value of check_drift()                            #
# --------------------------------------------------------------------------- #

@dataclass
class DriftReport:
    """
    Encapsulates the result of a single drift check.

    Attributes
    ----------
    model_name : str
    drift_score : float
        Composite score in [0, 1]. Higher = more drift.
    severity : str
        "NONE" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    alert : bool
        True if drift_score >= config.drift_threshold.
    timestamp : str
        ISO-8601 UTC timestamp.
    ref_samples : int
        Size of the reference dataset used.
    cur_samples : int
        Size of the current dataset checked.
    feature_scores : dict[str, float]
        Per-feature max drift score across all configured metrics.
    feature_details : dict[str, dict]
        Per-feature, per-metric raw results.
    output_drift : dict[str, float]
        Drift metrics for model output / predictions.
    components : dict[str, float]
        Named sub-scores that were averaged into drift_score.
    recommendations : list[str]
        Actionable next steps based on detected drift patterns.
    metadata : dict
        Arbitrary user-supplied tags + SDK version.
    """

    model_name: str
    drift_score: float
    severity: str
    alert: bool
    timestamp: str
    ref_samples: int
    cur_samples: int
    feature_scores: Dict[str, float] = field(default_factory=dict)
    feature_details: Dict[str, Dict] = field(default_factory=dict)
    output_drift: Dict[str, float] = field(default_factory=dict)
    components: Dict[str, float] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        """Serialise the report to a plain dict."""
        return {
            "model_name": self.model_name,
            "drift_score": self.drift_score,
            "severity": self.severity,
            "alert": self.alert,
            "timestamp": self.timestamp,
            "ref_samples": self.ref_samples,
            "cur_samples": self.cur_samples,
            "feature_scores": self.feature_scores,
            "feature_details": self.feature_details,
            "output_drift": self.output_drift,
            "components": self.components,
            "recommendations": self.recommendations,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        return (
            f"DriftReport(model={self.model_name!r}, "
            f"score={self.drift_score:.4f}, "
            f"severity={self.severity!r}, "
            f"alert={self.alert})"
        )


# --------------------------------------------------------------------------- #
#  Framework-agnostic tensor → ndarray conversion                             #
# --------------------------------------------------------------------------- #

def _to_numpy(data: Any) -> np.ndarray:
    """
    Convert PyTorch tensors, TF tensors, HuggingFace outputs, or plain
    array-likes to a NumPy ndarray.
    """
    # PyTorch
    try:
        import torch  # type: ignore[import]
        if isinstance(data, torch.Tensor):
            return data.detach().cpu().numpy()
    except ImportError:
        pass

    # TensorFlow / Keras
    try:
        import tensorflow as tf  # type: ignore[import]
        if isinstance(data, tf.Tensor):
            return data.numpy()
    except ImportError:
        pass

    # HuggingFace ModelOutput (dict-like with .logits / .last_hidden_state)
    if hasattr(data, "logits"):
        return _to_numpy(data.logits)
    if hasattr(data, "last_hidden_state"):
        return _to_numpy(data.last_hidden_state)

    # pandas DataFrame / Series
    try:
        import pandas as pd  # type: ignore[import]
        if isinstance(data, (pd.DataFrame, pd.Series)):
            return data.to_numpy()
    except ImportError:
        pass

    # Fall back to numpy
    return np.asarray(data)


# --------------------------------------------------------------------------- #
#  DriftMonitor                                                                #
# --------------------------------------------------------------------------- #

class DriftMonitor:
    """
    Real-time model drift monitor.

    Parameters
    ----------
    config : DriftConfig
        Full configuration object.
    api_key : str | None
        Drift Monitor API key (used for dashboard sync and future rate limits).
    verbose : bool
        If True, emit INFO-level logs about each check.

    Examples
    --------
    ::

        monitor = DriftMonitor(
            config=DriftConfig(model_name="fraud_v3", drift_threshold=0.80),
            api_key="sk_drift_xxx",
        )
        monitor.track_reference(X_train, y_train)
        report = monitor.check_drift(X_prod_batch, y_pred_batch)
        if report.alert:
            print("DRIFT:", report.severity, report.drift_score)
    """

    SDK_VERSION = "2.0.0"

    def __init__(
        self,
        config: Optional[DriftConfig] = None,
        api_key: Optional[str] = None,
        verbose: bool = False,
    ) -> None:
        self.config = config or DriftConfig()
        self.api_key = api_key

        if verbose:
            logging.basicConfig(level=logging.INFO)

        # Reference data storage
        self._ref_X: Optional[np.ndarray] = None
        self._ref_y: Optional[np.ndarray] = None
        self._ref_timestamp: Optional[str] = None

        # Rolling window buffer (if window_size is set)
        self._window_X: List[np.ndarray] = []
        self._window_y: List[np.ndarray] = []

        # Notification clients (lazy init)
        self._slack: Optional[SlackNotifier] = None
        self._webhook: Optional[WebhookNotifier] = None
        self._dashboard: Optional[DashboardSync] = None

        self._init_notifiers()

        # History
        self._history: List[DriftReport] = []

    # ------------------------------------------------------------------ #
    #  Notifier initialisation                                            #
    # ------------------------------------------------------------------ #

    def _init_notifiers(self) -> None:
        cfg = self.config

        if cfg.enable_slack and cfg.slack_webhook:
            self._slack = SlackNotifier(
                webhook_url=cfg.slack_webhook,
                channel=cfg.slack_channel,
            )
            logger.info("Slack notifier initialised → %s", cfg.slack_channel)

        if cfg.enable_webhook and cfg.webhook_url:
            self._webhook = WebhookNotifier(
                url=cfg.webhook_url,
                headers=cfg.webhook_headers,
            )
            logger.info("Webhook notifier initialised → %s", cfg.webhook_url)

        if cfg.enable_dashboard and self.api_key:
            self._dashboard = DashboardSync(
                api_key=self.api_key,
                dashboard_url=cfg.dashboard_url,
            )
            logger.info("Dashboard sync initialised → %s", cfg.dashboard_url)

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def track_reference(
        self,
        X: Any,
        y: Optional[Any] = None,
        *,
        overwrite: bool = False,
    ) -> "DriftMonitor":
        """
        Store the reference (baseline) distribution.

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features) or (n_samples,)
            Input features from the baseline period.
        y : array-like or None, shape (n_samples,)
            Labels or predictions from the baseline period.
        overwrite : bool
            If False (default), raises if reference is already set.

        Returns
        -------
        self — for chaining.
        """
        if self._ref_X is not None and not overwrite:
            raise RuntimeError(
                "Reference data already set. Pass overwrite=True to replace it."
            )

        ref_X = _to_numpy(X)
        if ref_X.ndim == 1:
            ref_X = ref_X.reshape(-1, 1)

        n = ref_X.shape[0]
        if n < self.config.min_reference_samples:
            raise ValueError(
                f"Reference dataset has {n} samples, minimum required is "
                f"{self.config.min_reference_samples}. "
                "Increase the dataset or lower config.min_reference_samples."
            )

        self._ref_X = ref_X
        self._ref_y = _to_numpy(y).ravel() if y is not None else None
        self._ref_timestamp = _utc_now()

        logger.info(
            "Reference data stored: %d samples, %d features.",
            n,
            ref_X.shape[1],
        )
        return self

    # ------------------------------------------------------------------ #

    def check_drift(
        self,
        X: Any,
        y: Optional[Any] = None,
        *,
        send_notifications: bool = True,
    ) -> DriftReport:
        """
        Compare current data against the reference and compute a drift report.

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features) or (n_samples,)
            Current input features to check.
        y : array-like or None, shape (n_samples,)
            Current labels / predictions.
        send_notifications : bool
            If False, suppress Slack/webhook/dashboard even if alert fires.

        Returns
        -------
        DriftReport
        """
        if self._ref_X is None:
            raise RuntimeError(
                "No reference data. Call track_reference() first."
            )

        cur_X = _to_numpy(X)
        if cur_X.ndim == 1:
            cur_X = cur_X.reshape(-1, 1)

        cur_y = _to_numpy(y).ravel() if y is not None else None

        # Optionally maintain rolling window
        if self.config.window_size is not None:
            self._window_X.append(cur_X)
            if cur_y is not None:
                self._window_y.append(cur_y)
            self._window_X = self._window_X[-self.config.window_size :]
            self._window_y = self._window_y[-self.config.window_size :]
            cur_X = np.vstack(self._window_X)
            if self._window_y:
                cur_y = np.concatenate(self._window_y)

        # ---- Feature drift ------------------------------------------- #
        feature_details = compute_feature_drift(
            self._ref_X,
            cur_X,
            metrics=self.config.feature_metrics,
            n_bins=self.config.n_bins,
            feature_names=self.config.feature_names,
        )

        feature_scores: Dict[str, float] = {}
        for fname, metric_results in feature_details.items():
            scores = [
                float(v.get("score", 0.0))
                for v in metric_results.values()
                if isinstance(v, dict)
            ]
            feature_scores[fname] = max(scores) if scores else 0.0

        # ---- Output drift -------------------------------------------- #
        output_drift: Dict[str, float] = {}
        if cur_y is not None and self._ref_y is not None:
            output_drift = self._compute_output_drift(self._ref_y, cur_y)

        # ---- Composite drift score ------------------------------------ #
        components: Dict[str, float] = {}

        if feature_scores:
            components["feature_drift"] = float(np.mean(list(feature_scores.values())))

        if output_drift:
            components["output_drift"] = output_drift.get("score", 0.0)

        drift_score = float(np.mean(list(components.values()))) if components else 0.0

        # ---- Severity / alert ---------------------------------------- #
        severity = self.config.severity(drift_score)
        alert = drift_score >= self.config.drift_threshold

        # ---- Recommendations ----------------------------------------- #
        recommendations = _build_recommendations(
            drift_score=drift_score,
            feature_scores=feature_scores,
            output_drift=output_drift,
            config=self.config,
        )

        report = DriftReport(
            model_name=self.config.model_name,
            drift_score=round(drift_score, 6),
            severity=severity,
            alert=alert,
            timestamp=_utc_now(),
            ref_samples=self._ref_X.shape[0],
            cur_samples=cur_X.shape[0],
            feature_scores=feature_scores,
            feature_details=feature_details,
            output_drift=output_drift,
            components=components,
            recommendations=recommendations,
            metadata={
                "sdk_version": self.SDK_VERSION,
                "model_type": self.config.model_type.value,
                "task_type": self.config.task_type.value,
                "tags": self.config.tags,
            },
        )

        self._history.append(report)
        logger.info(
            "Drift check complete: score=%.4f severity=%s alert=%s",
            drift_score,
            severity,
            alert,
        )

        if send_notifications and alert:
            self._dispatch(report)

        return report

    # ------------------------------------------------------------------ #

    def reset_reference(self) -> None:
        """Clear the stored reference data and rolling window."""
        self._ref_X = None
        self._ref_y = None
        self._ref_timestamp = None
        self._window_X.clear()
        self._window_y.clear()
        logger.info("Reference data cleared.")

    # ------------------------------------------------------------------ #

    @property
    def history(self) -> List[DriftReport]:
        """All drift reports generated since this monitor was created."""
        return list(self._history)

    # ------------------------------------------------------------------ #

    def summary(self) -> Dict[str, Any]:
        """
        Return a high-level summary of drift history.

        Includes: total checks, alerts, mean/max drift score,
        most-drifted features.
        """
        if not self._history:
            return {"checks": 0, "alerts": 0}

        scores = [r.drift_score for r in self._history]
        alerts = [r for r in self._history if r.alert]

        all_features: Dict[str, List[float]] = {}
        for r in self._history:
            for fname, fscore in r.feature_scores.items():
                all_features.setdefault(fname, []).append(fscore)

        feature_means = {
            k: round(float(np.mean(v)), 4) for k, v in all_features.items()
        }
        top_features = sorted(
            feature_means.items(), key=lambda kv: kv[1], reverse=True
        )[:10]

        return {
            "checks": len(self._history),
            "alerts": len(alerts),
            "mean_drift_score": round(float(np.mean(scores)), 4),
            "max_drift_score": round(float(np.max(scores)), 4),
            "last_check": self._history[-1].timestamp,
            "top_drifted_features": dict(top_features),
        }

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _compute_output_drift(
        self,
        ref_y: np.ndarray,
        cur_y: np.ndarray,
    ) -> Dict[str, Any]:
        """Compute output drift appropriate for the configured task type."""
        metric_key = self.config.output_metric.value

        task = self.config.task_type

        if task == TaskType.CLASSIFICATION:
            # Use categorical distribution shift
            result = categorical_drift(ref_y, cur_y)
            return {
                "score": float(result.get("score", 0.0)),
                "js_dist": float(result.get("js_dist", 0.0)),
                "method": "categorical_js",
            }

        # Regression / embedding — treat as continuous
        if metric_key == DriftMetric.KOLMOGOROV_SMIRNOV.value:
            result = kolmogorov_smirnov(ref_y, cur_y)
        elif metric_key == DriftMetric.WASSERSTEIN.value:
            result = wasserstein(ref_y, cur_y)
        else:
            result = jensen_shannon(
                ref_y, cur_y, n_bins=self.config.n_bins
            )

        return {
            "score": float(result.get("score", 0.0)),
            "method": metric_key,
        }

    # ------------------------------------------------------------------ #

    def _dispatch(self, report: DriftReport) -> None:
        """Fire all configured notifiers for the given report."""
        if self._slack:
            ok = self._slack.notify(report)
            logger.info("Slack notification: %s", "sent" if ok else "FAILED")

        if self._webhook:
            ok = self._webhook.notify(report)
            logger.info("Webhook notification: %s", "sent" if ok else "FAILED")

        if self._dashboard:
            ok = self._dashboard.sync(report)
            logger.info("Dashboard sync: %s", "sent" if ok else "FAILED")


# --------------------------------------------------------------------------- #
#  Recommendation engine                                                       #
# --------------------------------------------------------------------------- #

def _build_recommendations(
    drift_score: float,
    feature_scores: Dict[str, float],
    output_drift: Dict[str, float],
    config: DriftConfig,
) -> List[str]:
    """Generate actionable recommendations from a drift analysis."""
    recs: List[str] = []

    if drift_score >= config.alert.critical_threshold:
        recs.append(
            "CRITICAL: Halt automated decisions and trigger emergency model review."
        )
        recs.append(
            "Collect recent production data immediately for retraining."
        )

    elif drift_score >= config.alert.high_threshold:
        recs.append(
            "HIGH severity: Schedule immediate model retraining or rollback."
        )
        recs.append(
            "Enable A/B testing with fallback model while investigating drift cause."
        )

    elif drift_score >= config.alert.medium_threshold:
        recs.append(
            "MEDIUM severity: Monitor closely — consider retraining within 24–48 h."
        )

    elif drift_score >= config.alert.low_threshold:
        recs.append(
            "LOW severity: Continue monitoring; flag for next scheduled retraining cycle."
        )

    # Feature-level advice
    bad_features = [
        fname for fname, score in feature_scores.items()
        if score >= config.alert.medium_threshold
    ]
    if bad_features:
        top = bad_features[:3]
        recs.append(
            f"Top drifted features: {', '.join(top)}. "
            "Investigate upstream data pipeline for these inputs."
        )

    # Output-specific advice
    out_score = output_drift.get("score", 0.0)
    if out_score >= config.alert.high_threshold:
        if config.task_type == TaskType.CLASSIFICATION:
            recs.append(
                "Prediction class distribution has shifted significantly. "
                "Check for label imbalance in new data or covariate shift."
            )
        else:
            recs.append(
                "Regression output distribution has shifted. "
                "Verify target encoding and feature scaling in the serving pipeline."
            )

    if not recs:
        recs.append("No significant drift detected. System operating normally.")

    return recs


# --------------------------------------------------------------------------- #
#  Utility                                                                     #
# --------------------------------------------------------------------------- #

def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
