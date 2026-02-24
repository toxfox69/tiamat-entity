#!/usr/bin/env python3
"""
TIAMAT Drift Monitor SDK v2
============================
Embedded Python SDK for real-time ML model drift detection.
Runs entirely client-side — no network required for core detection.

Uses Kolmogorov-Smirnov test (scipy.stats.ks_2samp) to detect statistical
drift between a reference distribution and a sliding window of recent predictions.

Requirements:
    pip install tiamat-drift  # or: pip install scipy numpy requests

Compatibility:
    - Python 3.8+
    - Works with any ML framework (PyTorch, TensorFlow, sklearn, etc.)
    - Predictions are plain floats — no framework coupling

Quick Start:
    from drift_v2_sdk import DriftMonitor

    monitor = DriftMonitor(api_key="your-key", model_id="fraud-detector-v2")
    monitor.configure_slack("https://hooks.slack.com/services/...")

    # In your inference loop:
    for features, prediction in predictions:
        result = monitor.log_prediction(features, prediction)
        if result["drift_detected"]:
            print(f"Drift! score={result['score']:.3f}")

Full example in __main__ block at the bottom.

Integrates with: https://tiamat.live/drift (v2 API — coming soon)
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
import urllib.error
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

try:
    from scipy.stats import ks_2samp
except ImportError:
    raise ImportError(
        "scipy is required: pip install scipy"
    )

# ---------------------------------------------------------------------------
# Module logger
# ---------------------------------------------------------------------------
log = logging.getLogger("tiamat.drift")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SDK_VERSION = "2.0.0"

# Minimum samples before KS test runs
_MIN_REFERENCE_SIZE = 30   # need 30 predictions to establish baseline
_MIN_WINDOW_SIZE    = 20   # need 20 recent predictions to compare against

# KS test p-value threshold: < 0.05 = statistically significant drift
_DEFAULT_PVALUE_THRESHOLD = 0.05

# Sliding window capacity
_DEFAULT_WINDOW_SIZE = 100

# Slack alert cooldown: don't spam more than once per N seconds
_DEFAULT_ALERT_COOLDOWN_SEC = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DriftSDKError(Exception):
    """Base exception for Drift SDK errors."""


class InsufficientDataError(DriftSDKError):
    """Raised when there isn't enough data to compute drift."""


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

class DriftResult:
    """
    Result from a drift check.

    Attributes
    ----------
    drift_detected : bool
        True if KS test p-value < threshold (statistically significant drift).
    score : float
        Drift score in [0, 1]. Computed as (1 - p_value).
        0.0 = distributions identical, 1.0 = maximum divergence.
    alert : str
        Human-readable alert message, empty string if no drift.
    ks_stat : float
        Kolmogorov-Smirnov test statistic (max absolute difference between CDFs).
    p_value : float
        KS test p-value. Low p-value = evidence of drift.
    window_size : int
        Number of recent predictions in the comparison window.
    reference_size : int
        Number of predictions in the reference (baseline) distribution.
    feature_drift : dict
        Per-feature KS results for numeric features in the features dict.
        Only populated when features contain numeric values.
    timestamp : str
        ISO-8601 UTC timestamp of this check.
    """

    __slots__ = (
        "drift_detected", "score", "alert",
        "ks_stat", "p_value",
        "window_size", "reference_size",
        "feature_drift", "timestamp",
    )

    def __init__(
        self,
        drift_detected: bool,
        score: float,
        alert: str,
        ks_stat: float,
        p_value: float,
        window_size: int,
        reference_size: int,
        feature_drift: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None,
    ):
        self.drift_detected   = drift_detected
        self.score            = score
        self.alert            = alert
        self.ks_stat          = ks_stat
        self.p_value          = p_value
        self.window_size      = window_size
        self.reference_size   = reference_size
        self.feature_drift    = feature_drift or {}
        self.timestamp        = timestamp or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Return dict representation (JSON-serialisable)."""
        return {
            "drift_detected": self.drift_detected,
            "score":          round(self.score, 6),
            "alert":          self.alert,
            "ks_stat":        round(self.ks_stat, 6),
            "p_value":        round(self.p_value, 6),
            "window_size":    self.window_size,
            "reference_size": self.reference_size,
            "feature_drift":  self.feature_drift,
            "timestamp":      self.timestamp,
        }

    def __repr__(self) -> str:
        status = "DRIFT" if self.drift_detected else "STABLE"
        return (
            f"DriftResult({status} score={self.score:.4f} "
            f"p={self.p_value:.4f} ks={self.ks_stat:.4f})"
        )


# ---------------------------------------------------------------------------
# Core SDK class
# ---------------------------------------------------------------------------

class DriftMonitor:
    """
    Real-time ML model drift monitor using the Kolmogorov-Smirnov test.

    Thread-safe. Designed to be instantiated once per model and called
    from your inference code on every prediction.

    Parameters
    ----------
    api_key : str
        Your TIAMAT API key (used for remote reporting and Pro features).
        Free tier: omit or pass any non-empty string for local-only mode.
    model_id : str
        Unique identifier for your model (e.g. "fraud-detector-v2").
        Used in alert messages and remote reporting.
    window_size : int
        Number of recent predictions to keep in memory (default: 100).
        Older predictions are evicted automatically.
    reference_size : int
        Number of initial predictions to use as the reference distribution.
        KS test compares future predictions against this baseline.
        Default: 30 (minimum for reliable KS results).
    pvalue_threshold : float
        KS test significance threshold. Drift is flagged when p-value is
        below this value (default: 0.05 = 95% confidence).
    alert_cooldown_sec : int
        Minimum seconds between Slack/webhook alerts (default: 300).
        Prevents alert storms when drift is sustained.
    remote_url : str, optional
        Override the TIAMAT API base URL (default: https://tiamat.live).

    Examples
    --------
    >>> monitor = DriftMonitor(api_key="sk-xxxx", model_id="churn-v3")
    >>> monitor.configure_slack("https://hooks.slack.com/services/T.../B.../xxx")
    >>>
    >>> # In your serving code:
    >>> result = monitor.log_prediction(
    ...     features={"age": 34, "tenure_months": 24, "monthly_charge": 79.5},
    ...     prediction=0.87,          # model output (probability, logit, score, etc.)
    ...     ground_truth=1.0,         # optional — logged but not used in KS test yet
    ... )
    >>> print(result["drift_detected"])  # False / True
    >>> print(result["score"])           # 0.0 – 1.0
    """

    def __init__(
        self,
        api_key:             str,
        model_id:            str,
        window_size:         int   = _DEFAULT_WINDOW_SIZE,
        reference_size:      int   = _MIN_REFERENCE_SIZE,
        pvalue_threshold:    float = _DEFAULT_PVALUE_THRESHOLD,
        alert_cooldown_sec:  int   = _DEFAULT_ALERT_COOLDOWN_SEC,
        remote_url:          str   = "https://tiamat.live",
    ):
        self.api_key            = api_key
        self.model_id           = model_id
        self.window_size        = max(window_size, 20)
        self.reference_size     = max(reference_size, _MIN_REFERENCE_SIZE)
        self.pvalue_threshold   = float(pvalue_threshold)
        self.alert_cooldown_sec = int(alert_cooldown_sec)
        self.remote_url         = remote_url.rstrip("/")

        # Sliding window of recent predictions (evicts oldest when full)
        self._window: deque[float] = deque(maxlen=self.window_size)

        # Reference (baseline) distribution — filled from the first N predictions
        self._reference: List[float] = []

        # Per-feature sliding windows for feature drift detection
        self._feature_windows: Dict[str, deque] = {}
        self._feature_reference: Dict[str, List[float]] = {}

        # State
        self._last_drift_score: float = 0.0
        self._last_ks_stat:     float = 0.0
        self._last_p_value:     float = 1.0
        self._total_logged:     int   = 0
        self._total_alerts:     int   = 0
        self._last_alert_time:  float = 0.0
        self._slack_webhook:    Optional[str] = None

        # Thread safety
        self._lock = threading.Lock()

        log.info(
            "DriftMonitor v%s initialized: model_id=%r window=%d ref=%d α=%.3f",
            SDK_VERSION, model_id, self.window_size, self.reference_size,
            self.pvalue_threshold,
        )

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def configure_slack(self, webhook_url: str) -> None:
        """
        Configure Slack notifications for drift alerts.

        Sends a POST with a JSON payload to the webhook URL whenever drift
        is detected (subject to alert_cooldown_sec between alerts).

        Parameters
        ----------
        webhook_url : str
            Slack Incoming Webhook URL.
            Format: https://hooks.slack.com/services/T.../B.../xxx

        Examples
        --------
        >>> monitor.configure_slack(
        ...     "https://hooks.slack.com/services/T0123/B0456/abcdefghijk"
        ... )
        """
        if not webhook_url or not webhook_url.startswith("http"):
            raise ValueError("webhook_url must be a valid HTTP/S URL")
        with self._lock:
            self._slack_webhook = webhook_url
        log.info("Slack webhook configured for model %r", self.model_id)

    def log_prediction(
        self,
        features:     Dict[str, Any],
        prediction:   float,
        ground_truth: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Log a single prediction and auto-detect drift.

        Call this for every prediction your model makes. The first
        `reference_size` predictions build the reference distribution;
        subsequent predictions are compared against it.

        Parameters
        ----------
        features : dict
            Input features for this prediction. Numeric values are
            tracked for per-feature drift detection.
            Example: {"age": 34, "tenure_months": 24, "score": 0.7}
        prediction : float
            The model's output value. Works with any scalar:
            - Classification: probability, logit, softmax confidence
            - Regression: predicted value
            - Ranking: score
            - PyTorch: float(tensor.item())
            - TensorFlow: float(tensor.numpy())
        ground_truth : float, optional
            Actual label/value (if available). Logged for future
            concept drift analysis but not used in KS test currently.

        Returns
        -------
        dict
            {
                "drift_detected": bool,   # True if KS p-value < threshold
                "score":  float,          # 0.0 (stable) – 1.0 (max drift)
                "alert":  str,            # alert message or empty string
                "ks_stat": float,         # KS test statistic
                "p_value": float,         # KS test p-value
                "window_size": int,       # current window size
                "reference_size": int,    # reference window size
                "feature_drift": dict,    # per-feature KS results (if available)
                "timestamp": str,         # ISO-8601 UTC
            }

        Examples
        --------
        # PyTorch
        >>> with torch.no_grad():
        ...     logit = model(x)
        ...     prob = torch.sigmoid(logit).item()
        >>> result = monitor.log_prediction({"feature_a": x[0].item()}, prob)

        # TensorFlow / Keras
        >>> prob = float(model.predict(x)[0][0])
        >>> result = monitor.log_prediction({"feature_a": float(x[0])}, prob)

        # Sklearn
        >>> prob = model.predict_proba(X)[0][1]
        >>> result = monitor.log_prediction(dict(zip(feature_names, X[0])), prob)
        """
        prediction = float(prediction)

        with self._lock:
            self._total_logged += 1
            self._window.append(prediction)
            self._track_features(features)

            # Build reference from first N predictions
            if len(self._reference) < self.reference_size:
                self._reference.append(prediction)
                self._grow_feature_reference(features)

            # Not enough data yet — return neutral result
            if (len(self._reference) < _MIN_REFERENCE_SIZE
                    or len(self._window) < _MIN_WINDOW_SIZE):
                remaining = max(
                    _MIN_REFERENCE_SIZE - len(self._reference),
                    _MIN_WINDOW_SIZE - len(self._window),
                )
                log.debug(
                    "Not enough data yet (%d/%d predictions). Need %d more.",
                    self._total_logged, self.reference_size, remaining,
                )
                return {
                    "drift_detected": False,
                    "score":          0.0,
                    "alert":          "",
                    "ks_stat":        0.0,
                    "p_value":        1.0,
                    "window_size":    len(self._window),
                    "reference_size": len(self._reference),
                    "feature_drift":  {},
                    "timestamp":      datetime.now(timezone.utc).isoformat(),
                }

            result = self._run_ks_test()

        # Fire Slack alert outside the lock (HTTP call can be slow)
        if result.drift_detected:
            self._maybe_alert(result)

        return result.to_dict()

    def get_drift_score(self) -> float:
        """
        Return the most recent drift score in [0.0, 1.0].

        0.0 = distributions are identical (stable).
        1.0 = maximum divergence (strong drift).

        Returns 0.0 if not enough data has been logged yet.

        Returns
        -------
        float

        Examples
        --------
        >>> score = monitor.get_drift_score()
        >>> print(f"Current drift score: {score:.3f}")
        """
        with self._lock:
            return self._last_drift_score

    def set_reference(self, predictions: List[float]) -> None:
        """
        Manually set the reference (baseline) distribution.

        Use this instead of waiting for the first `reference_size`
        predictions. Useful when you have historical baseline data.

        Parameters
        ----------
        predictions : list of float
            Historical predictions from a known-stable period.
            Minimum 30 values required.

        Examples
        --------
        >>> import numpy as np
        >>> # Use last month's production predictions as baseline
        >>> monitor.set_reference(last_month_predictions)
        """
        if len(predictions) < _MIN_REFERENCE_SIZE:
            raise InsufficientDataError(
                f"Reference requires at least {_MIN_REFERENCE_SIZE} predictions, "
                f"got {len(predictions)}"
            )
        with self._lock:
            self._reference = [float(p) for p in predictions]
        log.info(
            "Reference distribution set manually: %d samples for model %r",
            len(predictions), self.model_id,
        )

    def get_stats(self) -> Dict[str, Any]:
        """
        Return current monitor statistics.

        Returns
        -------
        dict
            {
                "model_id": str,
                "sdk_version": str,
                "total_logged": int,
                "total_alerts": int,
                "window_size": int,
                "reference_size": int,
                "last_drift_score": float,
                "last_ks_stat": float,
                "last_p_value": float,
                "slack_configured": bool,
            }
        """
        with self._lock:
            return {
                "model_id":         self.model_id,
                "sdk_version":      SDK_VERSION,
                "total_logged":     self._total_logged,
                "total_alerts":     self._total_alerts,
                "window_size":      len(self._window),
                "window_capacity":  self.window_size,
                "reference_size":   len(self._reference),
                "reference_capacity": self.reference_size,
                "last_drift_score": round(self._last_drift_score, 6),
                "last_ks_stat":     round(self._last_ks_stat, 6),
                "last_p_value":     round(self._last_p_value, 6),
                "pvalue_threshold": self.pvalue_threshold,
                "slack_configured": self._slack_webhook is not None,
            }

    def reset(self) -> None:
        """
        Reset all state. Clears the window, reference, and scores.

        Use this after a model retrain to start fresh.
        """
        with self._lock:
            self._window.clear()
            self._reference.clear()
            self._feature_windows.clear()
            self._feature_reference.clear()
            self._last_drift_score = 0.0
            self._last_ks_stat     = 0.0
            self._last_p_value     = 1.0
            self._total_logged     = 0
            self._total_alerts     = 0
            self._last_alert_time  = 0.0
        log.info("DriftMonitor reset for model %r", self.model_id)

    # -----------------------------------------------------------------------
    # Internal: KS test
    # -----------------------------------------------------------------------

    def _run_ks_test(self) -> DriftResult:
        """Run KS test comparing reference vs current window. Lock must be held."""
        ref  = np.array(self._reference, dtype=np.float64)
        curr = np.array(list(self._window), dtype=np.float64)

        _ks = ks_2samp(ref, curr)
        ks_stat = float(_ks[0])   # type: ignore[arg-type]  # KstestResult.statistic
        p_value = float(_ks[1])   # type: ignore[arg-type]  # KstestResult.pvalue

        # Drift score: 1 - p_value gives a 0–1 scale
        # (p=1.0 → score=0 = stable; p=0.0 → score=1 = maximum drift)
        drift_score    = 1.0 - p_value
        drift_detected = p_value < self.pvalue_threshold

        # Update state
        self._last_drift_score = drift_score
        self._last_ks_stat     = ks_stat
        self._last_p_value     = p_value

        # Per-feature drift
        feature_drift = self._compute_feature_drift()

        alert_msg = ""
        if drift_detected:
            self._total_alerts += 1
            alert_msg = (
                f"[TIAMAT DRIFT] Model '{self.model_id}' — prediction distribution has shifted. "
                f"KS stat={ks_stat:.4f}, p={p_value:.4f} (< {self.pvalue_threshold}). "
                f"Score={drift_score:.4f}. Window={len(curr)} predictions vs "
                f"Reference={len(ref)} predictions."
            )
            log.warning(alert_msg)
        else:
            log.debug(
                "Drift check OK: model=%r ks=%.4f p=%.4f score=%.4f",
                self.model_id, ks_stat, p_value, drift_score,
            )

        return DriftResult(
            drift_detected=drift_detected,
            score=round(drift_score, 6),
            alert=alert_msg,
            ks_stat=round(float(ks_stat), 6),
            p_value=round(float(p_value), 6),
            window_size=len(curr),
            reference_size=len(ref),
            feature_drift=feature_drift,
        )

    # -----------------------------------------------------------------------
    # Internal: feature tracking
    # -----------------------------------------------------------------------

    def _track_features(self, features: Dict[str, Any]) -> None:
        """Add numeric feature values to per-feature sliding windows."""
        for key, val in features.items():
            if not isinstance(val, (int, float)):
                continue
            if key not in self._feature_windows:
                self._feature_windows[key] = deque(maxlen=self.window_size)
            self._feature_windows[key].append(float(val))

    def _grow_feature_reference(self, features: Dict[str, Any]) -> None:
        """Add feature values to reference distributions during warm-up."""
        for key, val in features.items():
            if not isinstance(val, (int, float)):
                continue
            if key not in self._feature_reference:
                self._feature_reference[key] = []
            if len(self._feature_reference[key]) < self.reference_size:
                self._feature_reference[key].append(float(val))

    def _compute_feature_drift(self) -> Dict[str, Any]:
        """
        Run KS test for each numeric feature that has enough reference data.
        Returns dict of feature_name -> {ks_stat, p_value, drift_detected}.
        """
        results: Dict[str, Any] = {}
        for key, ref_vals in self._feature_reference.items():
            if len(ref_vals) < _MIN_REFERENCE_SIZE:
                continue
            curr_vals = self._feature_windows.get(key)
            if not curr_vals or len(curr_vals) < _MIN_WINDOW_SIZE:
                continue
            try:
                _fks = ks_2samp(
                    np.array(ref_vals, dtype=np.float64),
                    np.array(list(curr_vals), dtype=np.float64),
                )
                fstat = float(_fks[0])   # type: ignore[arg-type]  # KstestResult.statistic
                fp    = float(_fks[1])   # type: ignore[arg-type]  # KstestResult.pvalue
                results[key] = {
                    "ks_stat":        round(fstat, 6),
                    "p_value":        round(fp, 6),
                    "drift_detected": fp < self.pvalue_threshold,
                    "score":          round(1.0 - fp, 6),
                }
            except Exception as exc:
                log.debug("Feature KS test failed for %r: %s", key, exc)
        return results

    # -----------------------------------------------------------------------
    # Internal: alerting
    # -----------------------------------------------------------------------

    def _maybe_alert(self, result: DriftResult) -> None:
        """Send Slack alert if webhook is configured and cooldown has elapsed."""
        now = time.monotonic()
        with self._lock:
            if now - self._last_alert_time < self.alert_cooldown_sec:
                log.debug(
                    "Alert suppressed (cooldown). Next alert in %.0fs.",
                    self.alert_cooldown_sec - (now - self._last_alert_time),
                )
                return
            self._last_alert_time = now
            webhook = self._slack_webhook

        if webhook:
            self._post_slack(webhook, result)

    def _post_slack(self, webhook_url: str, result: DriftResult) -> None:
        """POST a formatted Slack message to the configured webhook URL."""
        # Detect which features drifted
        drifted_features = [
            f"`{k}` (p={v['p_value']:.3f})"
            for k, v in result.feature_drift.items()
            if v["drift_detected"]
        ]
        feature_line = (
            f"\n• *Drifted features:* {', '.join(drifted_features)}"
            if drifted_features else ""
        )

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f":rotating_light: Drift Detected — {self.model_id}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Model:* `{self.model_id}`\n"
                        f"*Drift Score:* `{result.score:.4f}` (1.0 = max drift)\n"
                        f"*KS Statistic:* `{result.ks_stat:.4f}`\n"
                        f"*p-value:* `{result.p_value:.4f}` "
                        f"(threshold: {self.pvalue_threshold})\n"
                        f"*Window:* {result.window_size} recent vs "
                        f"{result.reference_size} reference predictions"
                        f"{feature_line}"
                    ),
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"TIAMAT Drift Monitor v{SDK_VERSION} • "
                            f"{result.timestamp} • "
                            f"<https://tiamat.live/drift|Dashboard>"
                        ),
                    }
                ],
            },
        ]

        payload = {
            "text": result.alert,   # Fallback for notifications
            "blocks": blocks,
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req  = urllib.request.Request(
                webhook_url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent":   f"tiamat-drift-sdk/{SDK_VERSION}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                log.info(
                    "Slack alert sent for model %r (HTTP %d)", self.model_id, resp.status
                )
        except urllib.error.HTTPError as exc:
            log.error("Slack webhook HTTP error %d for model %r", exc.code, self.model_id)
        except urllib.error.URLError as exc:
            log.error("Slack webhook connection failed for model %r: %s", self.model_id, exc.reason)
        except Exception as exc:
            log.error("Slack webhook unexpected error for model %r: %s", self.model_id, exc)


# ---------------------------------------------------------------------------
# Module-level convenience factory
# ---------------------------------------------------------------------------

def create_monitor(
    api_key:          str,
    model_id:         str,
    slack_webhook:    Optional[str]  = None,
    window_size:      int            = _DEFAULT_WINDOW_SIZE,
    reference_size:   int            = _MIN_REFERENCE_SIZE,
    pvalue_threshold: float          = _DEFAULT_PVALUE_THRESHOLD,
) -> DriftMonitor:
    """
    Factory function: create and optionally configure a DriftMonitor.

    Parameters
    ----------
    api_key : str
        TIAMAT API key (used for Pro features).
    model_id : str
        Unique model identifier.
    slack_webhook : str, optional
        Slack Incoming Webhook URL for drift alerts.
    window_size : int
        Sliding window capacity (default: 100).
    reference_size : int
        Number of initial predictions to use as baseline (default: 30).
    pvalue_threshold : float
        KS test p-value threshold (default: 0.05).

    Returns
    -------
    DriftMonitor

    Examples
    --------
    >>> monitor = create_monitor(
    ...     api_key="sk-xxx",
    ...     model_id="fraud-detector-v2",
    ...     slack_webhook="https://hooks.slack.com/services/...",
    ... )
    """
    monitor = DriftMonitor(
        api_key=api_key,
        model_id=model_id,
        window_size=window_size,
        reference_size=reference_size,
        pvalue_threshold=pvalue_threshold,
    )
    if slack_webhook:
        monitor.configure_slack(slack_webhook)
    return monitor


# ---------------------------------------------------------------------------
# Demo / smoke test (python drift_v2_sdk.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    print(f"\n=== TIAMAT Drift Monitor SDK v{SDK_VERSION} — Demo ===\n")

    # ------------------------------------------------------------------ #
    # Example 1: Basic numeric drift (PyTorch-style predictions)
    # ------------------------------------------------------------------ #
    print("[ Example 1: Prediction drift detection ]")
    print("-" * 50)

    monitor = DriftMonitor(
        api_key="demo-key",
        model_id="fraud-detector-v2",
        window_size=100,
        reference_size=50,
        pvalue_threshold=0.05,
    )
    monitor.configure_slack("https://hooks.slack.com/services/DEMO/WEBHOOK/url")

    rng = np.random.default_rng(42)

    # Phase 1: Warm-up with stable high-confidence predictions (0.85–0.98)
    print(f"\nPhase 1: Logging {monitor.reference_size} stable predictions (warm-up)...")
    for i in range(monitor.reference_size):
        pred  = float(rng.beta(a=9, b=1))          # Stable: high confidence
        feats = {"age": float(rng.integers(25, 65)),
                 "tenure_months": float(rng.integers(1, 120))}
        result = monitor.log_prediction(feats, pred)

    print(f"  Reference built. Current score: {monitor.get_drift_score():.4f}")

    # Phase 2: Continue with stable predictions — no drift expected
    print("\nPhase 2: Stable predictions (no drift expected)...")
    stable_alerts = 0
    for i in range(30):
        pred  = float(rng.beta(a=9, b=1))
        feats = {"age": float(rng.integers(25, 65)),
                 "tenure_months": float(rng.integers(1, 120))}
        result = monitor.log_prediction(feats, pred)
        if result["drift_detected"]:
            stable_alerts += 1

    score = monitor.get_drift_score()
    print(f"  Score after stable phase: {score:.4f} | False alarms: {stable_alerts}")

    # Phase 3: Inject drift — predictions shift to low-confidence (0.1–0.4)
    print("\nPhase 3: Injecting drift (distribution shifts to low confidence)...")
    drift_detected = False
    for i in range(40):
        pred  = float(rng.beta(a=2, b=8))          # Drifted: low confidence
        feats = {"age": float(rng.integers(18, 30)),   # also feature drift
                 "tenure_months": float(rng.integers(1, 12))}
        result = monitor.log_prediction(feats, pred)
        if result["drift_detected"] and not drift_detected:
            drift_detected = True
            print(f"\n  >>> DRIFT DETECTED at prediction #{i + monitor.reference_size + 30}")
            print(f"      Score:    {result['score']:.4f}")
            print(f"      KS stat:  {result['ks_stat']:.4f}")
            print(f"      p-value:  {result['p_value']:.4f}")
            print(f"      Alert:    {result['alert'][:80]}...")
            if result["feature_drift"]:
                print(f"      Feature drift:")
                for feat, info in result["feature_drift"].items():
                    status = "DRIFT" if info["drift_detected"] else "stable"
                    print(f"        {feat}: {status} (p={info['p_value']:.4f})")

    if not drift_detected:
        print("  No drift detected (may need more injected predictions)")

    print(f"\n  Final drift score: {monitor.get_drift_score():.4f}")

    # Stats
    stats = monitor.get_stats()
    print(f"\nMonitor stats:")
    print(f"  Total logged:   {stats['total_logged']}")
    print(f"  Total alerts:   {stats['total_alerts']}")
    print(f"  Window size:    {stats['window_size']}/{stats['window_capacity']}")
    print(f"  Reference size: {stats['reference_size']}/{stats['reference_capacity']}")

    # ------------------------------------------------------------------ #
    # Example 2: Pre-set reference from historical data
    # ------------------------------------------------------------------ #
    print("\n\n[ Example 2: Pre-set reference from historical baseline ]")
    print("-" * 50)

    monitor2 = create_monitor(
        api_key="sk-prod-xxxx",
        model_id="churn-predictor-v3",
        slack_webhook=None,   # no Slack in this example
    )

    # Use last 90 days of stable predictions as reference
    historical = rng.beta(a=3, b=1, size=200).tolist()
    monitor2.set_reference(historical)
    print(f"Reference pre-loaded: {len(historical)} historical predictions")

    # Immediately start checking new predictions
    result = monitor2.log_prediction(
        features={"monthly_charge": 79.5, "num_support_tickets": 0},
        prediction=0.12,   # clearly out of distribution vs Beta(3,1)
        ground_truth=0.0,
    )
    print(f"\nFirst check result: {result['drift_detected']=}, {result['score']=:.4f}")

    # ------------------------------------------------------------------ #
    # Example 3: PyTorch-compatible usage snippet (printed, not run)
    # ------------------------------------------------------------------ #
    print("\n\n[ Example 3: PyTorch integration pattern ]")
    print("-" * 50)
    print("""
    # In your PyTorch serving code:

    from drift_v2_sdk import DriftMonitor

    monitor = DriftMonitor(api_key="sk-xxx", model_id="bert-sentiment-v2")
    monitor.configure_slack("https://hooks.slack.com/services/...")

    @torch.no_grad()
    def predict(batch):
        logits = model(batch["input_ids"], batch["attention_mask"])
        probs  = torch.softmax(logits, dim=-1)[:, 1]  # positive class prob

        for i, prob in enumerate(probs):
            monitor.log_prediction(
                features={k: float(v[i]) for k, v in batch.items()
                           if isinstance(v[i], (int, float))},
                prediction=float(prob),
            )

        return probs
    """)

    print("\n=== Demo complete ===\n")
