#!/usr/bin/env python3
"""
Drift Monitor v2 — Python SDK
==============================
Two modes of operation:

  Standalone (local KS detection, no server):
  --------------------------------------------
      from drift_sdk import DriftMonitor
      monitor = DriftMonitor(model_name="my_model", ks_threshold=0.05)
      monitor.track_reference(X_baseline)
      result = monitor.log_prediction(features, prediction=0.87)
      if result.drift_detected:
          print(f"Drift! score={result.ks_score:.3f}")

  Client mode (server integration):
  -----------------------------------
      from drift_sdk import DriftClient
      client = DriftClient(api_key="sk_drift_xxx", server_url="https://tiamat.live")
      result = client.log_prediction("my_model", features, prediction=0.87)
      client.setup_webhook("my_model", url="https://myapp.com/hooks/drift",
                           events=["drift.detected", "drift.resolved"])

Dependencies: numpy, scipy, requests
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from scipy import stats

try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

__version__ = "2.0.0"
__all__ = [
    "DriftMonitor",
    "DriftClient",
    "DriftResult",
    "ks_test",
    "psi_score",
]


# ---------------------------------------------------------------------------
#  Statistical helpers
# ---------------------------------------------------------------------------

def ks_test(ref: np.ndarray, cur: np.ndarray) -> Dict[str, float]:
    """
    Two-sample Kolmogorov-Smirnov test between reference and current data.

    Returns
    -------
    dict with:
      ks_stat   — KS statistic in [0, 1], higher = more drift
      p_value   — statistical significance
      drifted   — True if p_value < 0.05
      score     — alias for ks_stat (0-1 normalised)
    """
    ref = np.asarray(ref, dtype=float).ravel()
    cur = np.asarray(cur, dtype=float).ravel()
    if len(ref) < 2 or len(cur) < 2:
        return {"ks_stat": 0.0, "p_value": 1.0, "drifted": False, "score": 0.0}
    result = stats.ks_2samp(ref, cur)
    return {
        "ks_stat": float(result.statistic),
        "p_value": float(result.pvalue),
        "drifted": bool(result.pvalue < 0.05),
        "score": float(result.statistic),
    }


def psi_score(ref: np.ndarray, cur: np.ndarray, n_bins: int = 10) -> float:
    """
    Population Stability Index — industry standard for scorecard monitoring.
    PSI < 0.1 = stable, 0.1-0.2 = minor shift, > 0.2 = significant drift.
    Returns normalised score in [0, 1].
    """
    ref = np.asarray(ref, dtype=float).ravel()
    cur = np.asarray(cur, dtype=float).ravel()
    min_val = min(ref.min(), cur.min())
    max_val = max(ref.max(), cur.max())
    if min_val == max_val:
        return 0.0
    bins = np.linspace(min_val, max_val, n_bins + 1)
    ref_counts, _ = np.histogram(ref, bins=bins)
    cur_counts, _ = np.histogram(cur, bins=bins)
    ref_pct = (ref_counts + 1e-8) / (len(ref) + 1e-8 * n_bins)
    cur_pct = (cur_counts + 1e-8) / (len(cur) + 1e-8 * n_bins)
    psi_raw = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
    # normalise: PSI > 0.5 treated as max drift
    return min(psi_raw / 0.5, 1.0)


def _severity(score: float, threshold: float = 0.05) -> str:
    """Map KS p-value or drift score to severity label."""
    if score >= 0.7:
        return "CRITICAL"
    if score >= 0.5:
        return "HIGH"
    if score >= 0.3:
        return "MEDIUM"
    if score >= 0.15:
        return "LOW"
    return "NONE"


# ---------------------------------------------------------------------------
#  DriftResult — return value from both standalone and client modes
# ---------------------------------------------------------------------------

@dataclass
class DriftResult:
    """Result of a drift check."""
    model_name: str
    drift_detected: bool
    ks_stat: float                       # KS statistic (0-1)
    p_value: float                       # KS p-value
    psi: float                           # Population Stability Index (0-1)
    severity: str                        # NONE / LOW / MEDIUM / HIGH / CRITICAL
    samples_ref: int                     # reference window size
    samples_cur: int                     # current window size
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    feature_scores: Dict[str, float] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # convenience
    @property
    def score(self) -> float:
        """Combined drift score (0-1). Average of KS stat and PSI."""
        return (self.ks_stat + self.psi) / 2.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "drift_detected": self.drift_detected,
            "ks_stat": round(self.ks_stat, 4),
            "p_value": round(self.p_value, 6),
            "psi": round(self.psi, 4),
            "score": round(self.score, 4),
            "severity": self.severity,
            "samples_ref": self.samples_ref,
            "samples_cur": self.samples_cur,
            "timestamp": self.timestamp,
            "feature_scores": self.feature_scores,
            "recommendations": self.recommendations,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        return (
            f"DriftResult(model={self.model_name!r}, drift={self.drift_detected}, "
            f"ks_stat={self.ks_stat:.3f}, p={self.p_value:.4f}, severity={self.severity!r})"
        )


def _make_recommendations(result: "DriftResult") -> List[str]:
    recs: List[str] = []
    if result.severity in ("HIGH", "CRITICAL"):
        recs.append("Consider retraining your model on recent data.")
        recs.append("Investigate upstream data pipeline for schema/distribution changes.")
    if result.severity == "MEDIUM":
        recs.append("Monitor closely — drift may be early-stage concept drift.")
        recs.append("Check if feature engineering or preprocessing has changed.")
    if result.psi > 0.2:
        recs.append(f"PSI={result.psi:.3f} exceeds 0.2 threshold — significant population shift.")
    if result.ks_stat > 0.3:
        top_features = sorted(result.feature_scores.items(), key=lambda x: x[1], reverse=True)[:3]
        if top_features:
            names = ", ".join(f"{k}({v:.2f})" for k, v in top_features)
            recs.append(f"Highest drift features: {names}")
    return recs


# ---------------------------------------------------------------------------
#  DriftMonitor — standalone local drift detection
# ---------------------------------------------------------------------------

class DriftMonitor:
    """
    Standalone in-process drift monitor.

    Maintains a sliding window of reference and recent predictions.
    Runs KS test + PSI on each log_prediction() call (or check_drift).

    Parameters
    ----------
    model_name : str
        Identifier for this model (used in reports).
    window_size : int
        Max number of reference samples to retain (circular buffer).
    recent_size : int
        Number of most-recent predictions compared against reference.
    ks_threshold : float
        p-value below which drift is flagged (default 0.05).
    min_samples : int
        Minimum samples in both windows before KS is computed.
    feature_names : list[str] | None
        Optional feature labels for richer reports.
    on_drift : callable | None
        Optional callback: on_drift(result: DriftResult) called when drift detected.
    """

    def __init__(
        self,
        model_name: str = "model",
        window_size: int = 1000,
        recent_size: int = 100,
        ks_threshold: float = 0.05,
        min_samples: int = 30,
        feature_names: Optional[List[str]] = None,
        on_drift: Optional[Any] = None,
    ) -> None:
        self.model_name = model_name
        self.window_size = window_size
        self.recent_size = recent_size
        self.ks_threshold = ks_threshold
        self.min_samples = min_samples
        self.feature_names = feature_names
        self.on_drift = on_drift

        # Reference data (set via track_reference or accumulated from initial preds)
        self._reference: Optional[np.ndarray] = None
        # Sliding window of recent features
        self._recent: deque = deque(maxlen=recent_size)
        # Full prediction log (for building reference)
        self._all: deque = deque(maxlen=window_size)

        self._n_logged = 0
        self._last_result: Optional[DriftResult] = None

    def track_reference(
        self,
        data: Union[np.ndarray, List],
        feature_names: Optional[List[str]] = None,
    ) -> None:
        """
        Set the reference (baseline) dataset.

        Parameters
        ----------
        data : array-like, shape (n_samples,) or (n_samples, n_features)
        feature_names : optional feature labels
        """
        arr = np.asarray(data, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        self._reference = arr
        if feature_names:
            self.feature_names = feature_names
        logger.debug(f"[{self.model_name}] reference set: {arr.shape}")

    def log_prediction(
        self,
        features: Union[np.ndarray, List, float],
        prediction: Optional[float] = None,
        ground_truth: Optional[float] = None,
    ) -> DriftResult:
        """
        Log a single prediction and check for drift.

        Parameters
        ----------
        features : feature vector (1-D) or scalar
        prediction : model output (optional)
        ground_truth : actual label (optional, unused for KS but logged)

        Returns
        -------
        DriftResult — use .drift_detected, .ks_stat, .severity
        """
        feat = np.asarray(features, dtype=float).ravel()
        self._recent.append(feat)
        self._all.append(feat)
        self._n_logged += 1

        # Auto-build reference from first window_size preds if not set explicitly
        if self._reference is None and len(self._all) >= self.window_size:
            self._reference = np.array(list(self._all))
            logger.debug(f"[{self.model_name}] auto-set reference from {len(self._reference)} samples")

        result = self._compute_drift()
        self._last_result = result

        if result.drift_detected and self.on_drift:
            try:
                self.on_drift(result)
            except Exception as exc:
                logger.warning(f"on_drift callback raised: {exc}")

        return result

    def check_drift(
        self,
        current_data: Union[np.ndarray, List],
    ) -> DriftResult:
        """
        Run drift check on a batch of current data against reference.

        Parameters
        ----------
        current_data : array-like, shape (n_samples,) or (n_samples, n_features)
        """
        arr = np.asarray(current_data, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        # Temporarily store as recent data
        old_recent = self._recent
        self._recent = deque(arr.tolist(), maxlen=len(arr))
        result = self._compute_drift()
        self._recent = old_recent
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_drift(self) -> DriftResult:
        ref = self._reference
        recent = list(self._recent)

        no_drift = DriftResult(
            model_name=self.model_name,
            drift_detected=False,
            ks_stat=0.0,
            p_value=1.0,
            psi=0.0,
            severity="NONE",
            samples_ref=len(ref) if ref is not None else 0,
            samples_cur=len(recent),
        )

        if ref is None or len(recent) < self.min_samples:
            no_drift.metadata["reason"] = (
                "insufficient_data" if ref is None else
                f"need {self.min_samples} recent samples, have {len(recent)}"
            )
            return no_drift

        ref_arr = np.array(ref, dtype=float)
        cur_arr = np.array(recent, dtype=float)
        if ref_arr.ndim == 1:
            ref_arr = ref_arr.reshape(-1, 1)
        if cur_arr.ndim == 1:
            cur_arr = cur_arr.reshape(-1, 1)

        n_features = ref_arr.shape[1]
        feature_ks: Dict[str, float] = {}

        # Per-feature KS test
        all_ks_stats: List[float] = []
        all_p_values: List[float] = []
        for i in range(n_features):
            name = (self.feature_names[i] if self.feature_names and i < len(self.feature_names)
                    else f"feature_{i}")
            r = ks_test(ref_arr[:, i], cur_arr[:, i])
            feature_ks[name] = round(r["ks_stat"], 4)
            all_ks_stats.append(r["ks_stat"])
            all_p_values.append(r["p_value"])

        # Composite: use max KS stat across features (most conservative)
        max_ks = float(np.max(all_ks_stats)) if all_ks_stats else 0.0
        min_p = float(np.min(all_p_values)) if all_p_values else 1.0

        # PSI on flattened data
        psi = psi_score(ref_arr.ravel(), cur_arr.ravel())

        detected = min_p < self.ks_threshold
        sev = _severity(max_ks)

        result = DriftResult(
            model_name=self.model_name,
            drift_detected=detected,
            ks_stat=max_ks,
            p_value=min_p,
            psi=psi,
            severity=sev,
            samples_ref=len(ref_arr),
            samples_cur=len(cur_arr),
            feature_scores=feature_ks,
        )
        result.recommendations = _make_recommendations(result)
        return result

    @property
    def n_logged(self) -> int:
        return self._n_logged

    @property
    def last_result(self) -> Optional[DriftResult]:
        return self._last_result


# ---------------------------------------------------------------------------
#  DriftClient — HTTP client for the Drift v2 server
# ---------------------------------------------------------------------------

class DriftClient:
    """
    HTTP client for the Drift Monitor v2 server.

    Parameters
    ----------
    api_key : str
        API key (sk_drift_...) obtained from /api/keys/register.
    server_url : str
        Base URL of the Drift server.
    timeout : int
        HTTP request timeout in seconds.
    local_monitor : bool
        If True, also run KS test locally before sending to server.
        Useful for low-latency drift feedback without waiting for server.
    """

    def __init__(
        self,
        api_key: str,
        server_url: str = "https://tiamat.live",
        timeout: int = 10,
        local_monitor: bool = False,
    ) -> None:
        if not _REQUESTS_AVAILABLE:
            raise ImportError("requests is required: pip install requests")
        self.api_key = api_key
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self._local_monitors: Dict[str, DriftMonitor] = {}
        self._local_enabled = local_monitor
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": f"drift-sdk/{__version__}",
        })

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def log_prediction(
        self,
        model_id: str,
        features: Union[np.ndarray, List, float],
        prediction: Optional[float] = None,
        ground_truth: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DriftResult:
        """
        Log a prediction to the server. Server runs KS test and fires webhooks.

        Parameters
        ----------
        model_id : str
            Unique model identifier.
        features : feature vector or scalar
        prediction : model output (optional)
        ground_truth : actual label (optional)
        metadata : arbitrary key-value pairs attached to this prediction

        Returns
        -------
        DriftResult — reflects server-side drift state
        """
        feat_list = np.asarray(features, dtype=float).ravel().tolist()
        payload: Dict[str, Any] = {
            "model_id": model_id,
            "features": feat_list,
        }
        if prediction is not None:
            payload["prediction"] = float(prediction)
        if ground_truth is not None:
            payload["ground_truth"] = float(ground_truth)
        if metadata:
            payload["metadata"] = metadata

        try:
            resp = self._session.post(
                f"{self.server_url}/log_prediction",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(f"[DriftClient] log_prediction failed: {exc}")
            # Fallback to local detection
            if self._local_enabled:
                return self._local_check(model_id, feat_list)
            return DriftResult(
                model_name=model_id, drift_detected=False, ks_stat=0.0,
                p_value=1.0, psi=0.0, severity="NONE",
                samples_ref=0, samples_cur=0,
                metadata={"error": str(exc)},
            )

        return self._parse_server_result(model_id, data)

    def setup_webhook(
        self,
        model_id: str,
        url: str,
        events: Optional[List[str]] = None,
        secret: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Register a webhook URL for a model.

        Parameters
        ----------
        model_id : str
        url : str
            HTTPS URL to receive drift event POSTs.
        events : list[str]
            Event types to subscribe to. Defaults to ['drift.detected'].
            Available: drift.detected, drift.resolved, drift.report
        secret : str | None
            Shared secret for HMAC-SHA256 signature verification.
            Sent as X-Drift-Signature header on each webhook POST.
        description : str | None
            Human-readable label for this webhook.

        Returns
        -------
        dict with webhook_id, model_id, url, events, created_at
        """
        payload: Dict[str, Any] = {
            "model_id": model_id,
            "url": url,
            "events": events or ["drift.detected"],
        }
        if secret:
            payload["secret"] = secret
        if description:
            payload["description"] = description

        resp = self._session.post(
            f"{self.server_url}/webhook/setup",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def list_webhooks(self, model_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List webhooks for this API key, optionally filtered by model."""
        params = {}
        if model_id:
            params["model_id"] = model_id
        resp = self._session.get(
            f"{self.server_url}/webhook/setup",
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("webhooks", [])

    def get_report(self, model_id: str) -> Dict[str, Any]:
        """Fetch the latest drift report for a model."""
        resp = self._session.get(
            f"{self.server_url}/reports/{model_id}",
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def track_reference(
        self,
        model_id: str,
        data: Union[np.ndarray, List],
        feature_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Upload reference (baseline) data for a model.
        This seeds the server's reference window.
        """
        arr = np.asarray(data, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        payload: Dict[str, Any] = {
            "model_id": model_id,
            "reference_data": arr.tolist(),
        }
        if feature_names:
            payload["feature_names"] = feature_names
        resp = self._session.post(
            f"{self.server_url}/models/{model_id}/reference",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Webhook signature verification (server-side helper)
    # ------------------------------------------------------------------

    @staticmethod
    def verify_webhook_signature(
        payload_bytes: bytes,
        signature_header: str,
        secret: str,
    ) -> bool:
        """
        Verify HMAC-SHA256 signature on incoming webhook events.

        Usage in your webhook endpoint:
            ok = DriftClient.verify_webhook_signature(
                request.get_data(),
                request.headers.get("X-Drift-Signature", ""),
                secret="your-shared-secret",
            )
        """
        expected = hmac.new(
            secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature_header)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _local_check(self, model_id: str, features: List[float]) -> DriftResult:
        if model_id not in self._local_monitors:
            self._local_monitors[model_id] = DriftMonitor(model_name=model_id)
        return self._local_monitors[model_id].log_prediction(features)

    @staticmethod
    def _parse_server_result(model_id: str, data: Dict[str, Any]) -> DriftResult:
        dr = data.get("drift", {})
        return DriftResult(
            model_name=model_id,
            drift_detected=dr.get("drift_detected", False),
            ks_stat=dr.get("ks_stat", 0.0),
            p_value=dr.get("p_value", 1.0),
            psi=dr.get("psi", 0.0),
            severity=dr.get("severity", "NONE"),
            samples_ref=dr.get("samples_ref", 0),
            samples_cur=dr.get("samples_cur", 0),
            feature_scores=dr.get("feature_scores", {}),
            recommendations=dr.get("recommendations", []),
            metadata=dr.get("metadata", {}),
        )
