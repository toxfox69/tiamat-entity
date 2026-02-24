"""
Drift v2 SDK — ML prediction drift detection.

Standalone module: no external deps beyond scipy (optional).

Quick start:
    from drift_v2_sdk import DriftClient
    client = DriftClient(api_key="sk_free_demo", server_url="http://localhost:9000")
    result = client.log_prediction(
        model_id="churn-v1",
        features={"age": 34, "spend": 120.5},
        prediction=0.82,
        ground_truth=1,
    )
    print(result)  # {"drift_detected": True, "ks_statistic": 0.24, ...}
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

try:
    from scipy.stats import ks_2samp as _ks_2samp
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


# ---------------------------------------------------------------------------
# Pure-Python KS statistic (fallback when scipy not available)
# ---------------------------------------------------------------------------

def _ks_statistic_pure(a: List[float], b: List[float]) -> float:
    """Two-sample KS statistic D (pure Python, O(n log n))."""
    if not a or not b:
        return 0.0
    n_a, n_b = len(a), len(b)
    sa, sb = sorted(a), sorted(b)
    all_vals = sorted(set(sa + sb))
    max_d, i, j = 0.0, 0, 0
    for x in all_vals:
        while i < n_a and sa[i] <= x:
            i += 1
        while j < n_b and sb[j] <= x:
            j += 1
        d = abs(i / n_a - j / n_b)
        if d > max_d:
            max_d = d
    return max_d


def ks_test(
    reference: List[float],
    current: List[float],
    threshold: float = 0.1,
) -> Tuple[float, bool]:
    """
    Two-sample KS test.
    Returns (ks_statistic, is_drifting).
    Uses scipy when available (p-value based); otherwise threshold-based.
    """
    if len(reference) < 2 or len(current) < 2:
        return 0.0, False

    if _HAS_SCIPY:
        stat, pvalue = _ks_2samp(reference, current)
        return float(stat), pvalue < 0.05

    stat = _ks_statistic_pure(reference, current)
    return stat, stat > threshold


# ---------------------------------------------------------------------------
# In-memory prediction cache (dict of model windows per api_key)
# ---------------------------------------------------------------------------

@dataclass
class _ModelWindow:
    """Sliding windows for reference and current prediction distributions."""
    reference: List[float] = field(default_factory=list)
    current: List[float] = field(default_factory=list)
    predictions: List[Dict[str, Any]] = field(default_factory=list)
    drift_events: List[Dict[str, Any]] = field(default_factory=list)
    window_size: int = 200

    def record(self, prediction: float, ground_truth: Optional[float],
               features: Dict[str, Any]) -> None:
        self.predictions.append({
            "prediction": prediction,
            "ground_truth": ground_truth,
            "features": features,
            "ts": time.time(),
        })
        self.current.append(prediction)
        if len(self.current) > self.window_size:
            self.current.pop(0)
        # Seed reference from first half-window
        if len(self.reference) < self.window_size // 2:
            self.reference.append(prediction)


# Global in-process cache: {api_key: {model_id: _ModelWindow}}
_CACHE: Dict[str, Dict[str, _ModelWindow]] = defaultdict(dict)


def _window(api_key: str, model_id: str) -> _ModelWindow:
    if model_id not in _CACHE[api_key]:
        _CACHE[api_key][model_id] = _ModelWindow()
    return _CACHE[api_key][model_id]


def models_for_key(api_key: str) -> List[str]:
    """Return list of model_ids seen under this api_key."""
    return list(_CACHE.get(api_key, {}).keys())


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def log_prediction(
    model_id: str,
    features: Dict[str, Any],
    prediction: float,
    ground_truth: Optional[float] = None,
    api_key: str = "local",
    ks_threshold: float = 0.1,
) -> Dict[str, Any]:
    """
    Log a single prediction and auto-detect drift.

    Parameters
    ----------
    model_id      : unique model identifier
    features      : dict of input feature values
    prediction    : model output (numeric scalar)
    ground_truth  : optional actual label / value
    api_key       : customer API key (namespaces the cache)
    ks_threshold  : KS statistic threshold when scipy unavailable

    Returns
    -------
    {
      "model_id":       str,
      "drift_detected": bool,
      "ks_statistic":   float,
      "n_reference":    int,
      "n_current":      int,
      "timestamp":      float,
    }
    """
    win = _window(api_key, model_id)
    win.record(float(prediction), ground_truth, features)

    result: Dict[str, Any] = {
        "model_id": model_id,
        "drift_detected": False,
        "ks_statistic": 0.0,
        "n_reference": len(win.reference),
        "n_current": len(win.current),
        "timestamp": time.time(),
    }

    if len(win.reference) >= 10 and len(win.current) >= 10:
        stat, drifting = ks_test(win.reference, win.current, ks_threshold)
        result["ks_statistic"] = round(stat, 6)
        result["drift_detected"] = bool(drifting)
        if drifting:
            win.drift_events.append({
                "ts": result["timestamp"],
                "ks_statistic": stat,
                "n_reference": len(win.reference),
                "n_current": len(win.current),
            })

    return result


def get_drift_status(api_key: str, model_id: Optional[str] = None) -> Dict[str, Any]:
    """Return cached drift status for an api_key (all models or one)."""
    models = _CACHE.get(api_key, {})
    if model_id:
        models = {model_id: models[model_id]} if model_id in models else {}

    out: Dict[str, Any] = {}
    for mid, win in models.items():
        stat, drifting = 0.0, False
        if len(win.reference) >= 10 and len(win.current) >= 10:
            stat, drifting = ks_test(win.reference, win.current)
        out[mid] = {
            "n_predictions": len(win.predictions),
            "n_drift_events": len(win.drift_events),
            "current_ks": round(stat, 6),
            "currently_drifting": bool(drifting),
            "recent_drift_events": win.drift_events[-5:],
        }
    return out


# ---------------------------------------------------------------------------
# Optional HTTP client (talks to drift_v2_server.py)
# ---------------------------------------------------------------------------

class DriftClient:
    """
    HTTP client for drift_v2_server.  Falls back to local-only mode when
    requests is not installed or the server is unreachable.
    """

    def __init__(
        self,
        api_key: str,
        server_url: str = "http://localhost:9000",
        timeout: int = 5,
        local_only: bool = False,
    ) -> None:
        self.api_key = api_key
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self.local_only = local_only or not _HAS_REQUESTS

    def log_prediction(
        self,
        model_id: str,
        features: Dict[str, Any],
        prediction: float,
        ground_truth: Optional[float] = None,
        ks_threshold: float = 0.1,
    ) -> Dict[str, Any]:
        # Always run local KS check for immediate feedback
        local = log_prediction(
            model_id=model_id,
            features=features,
            prediction=float(prediction),
            ground_truth=ground_truth,
            api_key=self.api_key,
            ks_threshold=ks_threshold,
        )
        if self.local_only:
            return local

        try:
            resp = _requests.post(
                f"{self.server_url}/drift/log",
                json={
                    "model_id": model_id,
                    "features": features,
                    "prediction": float(prediction),
                    "ground_truth": float(ground_truth) if ground_truth is not None else None,
                    "api_key": self.api_key,
                },
                timeout=self.timeout,
            )
            if resp.ok:
                return resp.json()
        except Exception:
            pass
        return local

    def get_status(self, model_id: Optional[str] = None) -> Dict[str, Any]:
        if self.local_only:
            return get_drift_status(self.api_key, model_id)
        url = f"{self.server_url}/drift/status/{self.api_key}"
        if model_id:
            url += f"?model_id={model_id}"
        try:
            resp = _requests.get(url, timeout=self.timeout)
            if resp.ok:
                return resp.json()
        except Exception:
            pass
        return get_drift_status(self.api_key, model_id)
