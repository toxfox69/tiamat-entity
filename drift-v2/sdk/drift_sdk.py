#!/usr/bin/env python3
"""
drift_sdk.py — TIAMAT Drift v2 SDK
====================================
Production-ready ML drift detection via Kolmogorov-Smirnov test.
Compatible with PyTorch tensors, TensorFlow tensors, NumPy arrays,
and plain Python scalars/lists.

Module-level quick-start (global singleton)::

    import drift_sdk

    drift_sdk.configure(api_key="dk_live_xxx")

    result = drift_sdk.log_prediction(
        model_id="fraud-v3",
        features={"amount": 142.0, "velocity": 3},
        prediction=0.82,
        ground_truth=1,
    )
    if result["drift_detected"]:
        print("Drift score:", result["drift_score"])

Class-based::

    from drift_sdk import DriftMonitor

    monitor = DriftMonitor(api_key="dk_live_xxx")
    result = monitor.log_prediction("fraud-v3", features, prediction)
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

import numpy as np
import requests
from scipy.stats import ks_2samp

__version__ = "2.0.0"
__all__ = [
    "DriftMonitor",
    "configure",
    "log_prediction",
    "reset_model",
    "DriftResult",
    "DriftError",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional framework integrations — graceful if not installed
# ---------------------------------------------------------------------------
try:
    import torch as _torch
    _TORCH_AVAILABLE = True
except ImportError:
    _torch = None  # type: ignore[assignment]
    _TORCH_AVAILABLE = False

try:
    import tensorflow as _tf
    _TF_AVAILABLE = True
except ImportError:
    _tf = None  # type: ignore[assignment]
    _TF_AVAILABLE = False

# ---------------------------------------------------------------------------
# Optional Redis — in-process fallback if unavailable
# ---------------------------------------------------------------------------
try:
    import redis as _redis_mod
    _REDIS_AVAILABLE = True
except ImportError:
    _redis_mod = None  # type: ignore[assignment]
    _REDIS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Exception types
# ---------------------------------------------------------------------------

class DriftError(Exception):
    """Raised for non-recoverable SDK configuration errors."""


# ---------------------------------------------------------------------------
# DriftResult dataclass-style dict wrapper
# ---------------------------------------------------------------------------

class DriftResult(dict):
    """
    Dict subclass with attribute access for drift check results.

    Attributes (also accessible as dict keys)
    -----------------------------------------
    drift_detected : bool
        True when ≥1 feature has statistically significant drift.
    drift_score : float
        Mean KS statistic of drifted features (0–1). 0 = no drift.
    confidence : int
        0–100 confidence score (``int(drift_score * 100)``).
    affected_features : list[dict]
        Per-feature dicts: ``{"feature", "ks_stat", "p_value"}``,
        sorted by ascending p_value (most drifted first).
    prediction_count : int
        Total predictions logged for this model.
    baseline_ready : bool
        False while still collecting baseline samples.
    status : str
        One of ``"OK"``, ``"WARN"``, ``"ALERT"``.
    """
    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError:
            raise AttributeError(item) from None


def _make_result(
    drift_detected: bool,
    drift_score: float,
    affected_features: List[Dict],
    prediction_count: int,
    baseline_ready: bool,
) -> DriftResult:
    confidence = int(min(drift_score, 1.0) * 100)
    if not baseline_ready:
        status = "BUILDING_BASELINE"
    elif not drift_detected:
        status = "OK" if drift_score < 0.1 else "WARN"
    else:
        status = "ALERT"
    return DriftResult(
        drift_detected=drift_detected,
        drift_score=round(min(drift_score, 1.0), 4),
        confidence=confidence,
        affected_features=affected_features,
        prediction_count=prediction_count,
        baseline_ready=baseline_ready,
        status=status,
    )


# ---------------------------------------------------------------------------
# Framework-agnostic tensor → Python scalar conversion
# ---------------------------------------------------------------------------

def _to_python(val: Any) -> Any:
    """
    Convert PyTorch tensors, TensorFlow tensors, and NumPy arrays to
    Python scalars or lists.  Passes everything else through unchanged.
    """
    # NumPy scalar
    if isinstance(val, np.generic):
        return val.item()
    # NumPy array
    if isinstance(val, np.ndarray):
        return val.tolist()
    # PyTorch
    if _TORCH_AVAILABLE and isinstance(val, _torch.Tensor):  # type: ignore[union-attr]
        return val.detach().cpu().numpy().tolist() if val.numel() > 1 else val.item()
    # TensorFlow / Keras
    if _TF_AVAILABLE and isinstance(val, _tf.Tensor):  # type: ignore[union-attr]
        return val.numpy().tolist()
    return val


def _extract_numeric(features: Dict[str, Any]) -> Dict[str, float]:
    """
    Extract numeric features from a feature dict.
    Handles nested tensors, booleans, ints, floats.
    Non-numeric values are silently ignored.
    """
    out: Dict[str, float] = {}
    for k, v in features.items():
        v = _to_python(v)
        if isinstance(v, bool):
            out[k] = float(v)
        elif isinstance(v, (int, float)):
            if not (isinstance(v, float) and v != v):  # NaN guard
                out[k] = float(v)
        elif isinstance(v, (list, tuple)) and len(v) == 1:
            # Single-element container — unwrap
            inner = _to_python(v[0])
            if isinstance(inner, (int, float)) and not isinstance(inner, bool):
                out[k] = float(inner)
    return out


# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------

def _rkey(api_key: str, model_id: str, slot: str) -> str:
    return f"drift_v2:{api_key}:{model_id}:{slot}"


# ---------------------------------------------------------------------------
# DriftMonitor
# ---------------------------------------------------------------------------

class DriftMonitor:
    """
    Monitor ML model predictions for feature distribution drift.

    Uses the two-sample Kolmogorov-Smirnov test on each numeric feature.
    Baseline and detection-window buffers are optionally persisted in Redis
    so multiple service workers share state across restarts.

    Parameters
    ----------
    api_key : str
        TIAMAT API key (used to auth drift alerts and tier checking).
    redis_url : str, optional
        Redis connection URL.  Reads ``REDIS_URL`` env var as fallback.
        If Redis is absent/unreachable, an in-process store is used.
    baseline_size : int
        Predictions collected before drift testing begins (default 1000).
    detection_window : int
        Rolling recent-prediction window size compared to baseline (default 100).
    alert_threshold : float
        KS p-value below which a feature is flagged as drifted (default 0.05).
    alert_url : str
        TIAMAT Drift API endpoint that receives drift alerts.
    """

    _DEFAULT_ALERT_URL = "https://tiamat.live/api/drift/alert"
    _REDIS_TTL = 60 * 60 * 24 * 7  # 7 days

    def __init__(
        self,
        api_key: str,
        redis_url: Optional[str] = None,
        baseline_size: int = 1000,
        detection_window: int = 100,
        alert_threshold: float = 0.05,
        alert_url: str = _DEFAULT_ALERT_URL,
    ) -> None:
        if not api_key:
            raise DriftError("api_key is required")

        self.api_key = api_key
        self.baseline_size = baseline_size
        self.detection_window = detection_window
        self.alert_threshold = alert_threshold
        self.alert_url = alert_url

        # In-process fallback stores
        self._store: Dict[str, Dict[str, Dict[str, List[float]]]] = {}
        self._counts: Dict[str, int] = {}

        # Redis setup
        self._redis: Any = None
        _url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        if _REDIS_AVAILABLE and _redis_mod is not None:
            try:
                self._redis = _redis_mod.from_url(_url, decode_responses=True)
                self._redis.ping()
                logger.info("DriftMonitor: Redis active at %s", _url)
            except Exception as exc:
                logger.warning(
                    "DriftMonitor: Redis unavailable (%s) — using in-process store", exc
                )
                self._redis = None

        # Persistent HTTP session for alert delivery
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": f"tiamat-drift-sdk/{__version__}",
        })

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_prediction(
        self,
        model_id: str,
        features: Dict[str, Any],
        prediction: Any,
        ground_truth: Any = None,
    ) -> DriftResult:
        """
        Record one prediction and check for feature distribution drift.

        Parameters
        ----------
        model_id : str
            Identifier for the model being monitored.
        features : dict
            Feature name → value mapping.  Supports NumPy arrays,
            PyTorch tensors, TensorFlow tensors, and plain Python scalars.
        prediction : Any
            Model output value (stored for auditing).
        ground_truth : Any, optional
            Observed label/value (stored for future performance drift).

        Returns
        -------
        DriftResult
            Accessible as dict or via attribute access.
            Key fields: drift_detected, drift_score, confidence,
            affected_features, prediction_count, baseline_ready, status.

        Examples
        --------
        # PyTorch model
        logits = model(x)
        probs = torch.softmax(logits, dim=-1)
        result = monitor.log_prediction(
            "image-classifier",
            {"conf_max": probs.max(), "entropy": -(probs * probs.log()).sum()},
            probs.argmax().item(),
        )

        # TensorFlow model
        output = model(inputs, training=False)
        result = monitor.log_prediction(
            "nlp-classifier",
            {"prob_pos": output[0][1], "prob_neg": output[0][0]},
            tf.argmax(output[0]).numpy(),
        )
        """
        numeric = _extract_numeric(features)
        count = self._increment_count(model_id)

        if count <= self.baseline_size:
            self._push_baseline(model_id, numeric)
            return _make_result(
                drift_detected=False,
                drift_score=0.0,
                affected_features=[],
                prediction_count=count,
                baseline_ready=False,
            )

        self._push_window(model_id, numeric)
        affected = self._run_ks_tests(model_id, numeric.keys())
        drift_detected = len(affected) > 0

        drift_score = (
            float(np.mean([f["ks_stat"] for f in affected]))
            if drift_detected
            else 0.0
        )

        result = _make_result(
            drift_detected=drift_detected,
            drift_score=drift_score,
            affected_features=affected,
            prediction_count=count,
            baseline_ready=True,
        )

        if drift_detected:
            self._send_alert(model_id, result, prediction, ground_truth)

        return result

    def reset(self, model_id: str) -> None:
        """Clear baseline and window data for model_id (call after retrain)."""
        self._store.pop(model_id, None)
        self._counts.pop(model_id, None)
        if self._redis:
            for slot in ("count", "baseline", "window"):
                # Delete all keys matching the pattern
                cursor = 0
                pattern = _rkey(self.api_key, model_id, slot) + "*"
                while True:
                    cursor, keys = self._redis.scan(cursor, match=pattern, count=100)
                    if keys:
                        self._redis.delete(*keys)
                    if cursor == 0:
                        break
        logger.info("DriftMonitor: state reset for model_id='%s'", model_id)

    def status(self, model_id: str) -> Dict[str, Any]:
        """Return monitoring status dict for model_id."""
        count = self._get_count(model_id)
        return {
            "model_id": model_id,
            "prediction_count": count,
            "baseline_ready": count > self.baseline_size,
            "baseline_size": self.baseline_size,
            "detection_window": self.detection_window,
            "alert_threshold": self.alert_threshold,
            "redis_available": self._redis is not None,
        }

    # ------------------------------------------------------------------
    # Redis / in-process store helpers
    # ------------------------------------------------------------------

    def _increment_count(self, model_id: str) -> int:
        if self._redis:
            return int(self._redis.incr(_rkey(self.api_key, model_id, "count")))
        self._counts[model_id] = self._counts.get(model_id, 0) + 1
        return self._counts[model_id]

    def _get_count(self, model_id: str) -> int:
        if self._redis:
            val = self._redis.get(_rkey(self.api_key, model_id, "count"))
            return int(val) if val else 0
        return self._counts.get(model_id, 0)

    def _push_baseline(self, model_id: str, numeric: Dict[str, float]) -> None:
        if self._redis:
            pipe = self._redis.pipeline()
            for feat, val in numeric.items():
                key = _rkey(self.api_key, model_id, f"baseline:{feat}")
                pipe.rpush(key, str(val))
                pipe.expire(key, self._REDIS_TTL)
            pipe.execute()
        else:
            store = self._store.setdefault(
                model_id, {"baseline": defaultdict(list), "window": defaultdict(list)}
            )
            for feat, val in numeric.items():
                store["baseline"][feat].append(val)

    def _get_baseline(self, model_id: str, feat: str) -> List[float]:
        if self._redis:
            raw = self._redis.lrange(
                _rkey(self.api_key, model_id, f"baseline:{feat}"), 0, -1
            )
            return [float(v) for v in raw]
        return list(self._store.get(model_id, {}).get("baseline", {}).get(feat, []))

    def _push_window(self, model_id: str, numeric: Dict[str, float]) -> None:
        if self._redis:
            pipe = self._redis.pipeline()
            for feat, val in numeric.items():
                key = _rkey(self.api_key, model_id, f"window:{feat}")
                pipe.rpush(key, str(val))
                pipe.ltrim(key, -self.detection_window, -1)
                pipe.expire(key, self._REDIS_TTL)
            pipe.execute()
        else:
            store = self._store.setdefault(
                model_id, {"baseline": defaultdict(list), "window": defaultdict(list)}
            )
            for feat, val in numeric.items():
                buf: List[float] = store["window"][feat]
                buf.append(val)
                if len(buf) > self.detection_window:
                    store["window"][feat] = buf[-self.detection_window :]

    def _get_window(self, model_id: str, feat: str) -> List[float]:
        if self._redis:
            raw = self._redis.lrange(
                _rkey(self.api_key, model_id, f"window:{feat}"), 0, -1
            )
            return [float(v) for v in raw]
        return list(self._store.get(model_id, {}).get("window", {}).get(feat, []))

    # ------------------------------------------------------------------
    # KS test
    # ------------------------------------------------------------------

    def _run_ks_tests(
        self, model_id: str, features: Any
    ) -> List[Dict[str, Any]]:
        """
        Run two-sample KS test per feature.  Returns drifted features
        sorted by ascending p_value (most drifted first).
        """
        affected: List[Dict[str, Any]] = []
        for feat in features:
            baseline = self._get_baseline(model_id, feat)
            window = self._get_window(model_id, feat)
            if len(baseline) < 2 or len(window) < 2:
                continue
            base_arr = np.array(baseline, dtype=np.float64)
            win_arr = np.array(window, dtype=np.float64)
            # Skip degenerate constant distributions
            if np.std(base_arr) == 0.0 and np.std(win_arr) == 0.0:
                continue
            ks = ks_2samp(base_arr, win_arr)
            ks_stat = float(ks.statistic)  # type: ignore[union-attr]
            p_value = float(ks.pvalue)  # type: ignore[union-attr]
            if p_value < self.alert_threshold:
                affected.append({
                    "feature": feat,
                    "p_value": round(p_value, 6),
                    "ks_stat": round(ks_stat, 6),
                })
        affected.sort(key=lambda r: r["p_value"])
        return affected

    # ------------------------------------------------------------------
    # Alert delivery
    # ------------------------------------------------------------------

    def _send_alert(
        self,
        model_id: str,
        result: DriftResult,
        prediction: Any,
        ground_truth: Any,
    ) -> None:
        """POST drift event to TIAMAT Drift API.  Non-blocking best-effort."""
        payload = {
            "model_id": model_id,
            "drift_score": result["drift_score"],
            "confidence": result["confidence"],
            "affected_features": result["affected_features"],
            "prediction_count": result["prediction_count"],
            "prediction": _to_python(prediction),
            "ground_truth": _to_python(ground_truth),
            "timestamp": time.time(),
        }
        try:
            resp = self._session.post(self.alert_url, json=payload, timeout=10)
            if resp.status_code == 402:
                data = resp.json()
                logger.warning(
                    "Drift alert blocked (model limit): %s — upgrade at %s",
                    data.get("message", "unknown"),
                    data.get("upgrade_url", "https://tiamat.live/drift/upgrade"),
                )
            elif resp.status_code >= 400:
                logger.warning(
                    "Drift alert HTTP %d for model '%s': %s",
                    resp.status_code, model_id, resp.text[:200],
                )
            else:
                logger.info(
                    "Drift alert sent: model='%s' score=%.4f features=%d",
                    model_id,
                    result["drift_score"],
                    len(result["affected_features"]),
                )
        except requests.exceptions.Timeout:
            logger.warning("Drift alert timed out for model '%s'", model_id)
        except requests.exceptions.RequestException as exc:
            logger.warning("Drift alert failed for model '%s': %s", model_id, exc)


# ---------------------------------------------------------------------------
# Module-level singleton API
# ---------------------------------------------------------------------------

_global_monitor: Optional[DriftMonitor] = None


def configure(
    api_key: str,
    redis_url: Optional[str] = None,
    baseline_size: int = 1000,
    detection_window: int = 100,
    alert_threshold: float = 0.05,
    alert_url: str = DriftMonitor._DEFAULT_ALERT_URL,
) -> DriftMonitor:
    """
    Configure the module-level singleton DriftMonitor.

    Call once at application startup. After this, use the module-level
    ``log_prediction()``, ``reset_model()``, etc. functions directly.

    Parameters
    ----------
    api_key : str
        Your TIAMAT API key.
    redis_url : str, optional
        Redis connection URL (default: ``REDIS_URL`` env var or localhost).
    baseline_size : int
        Predictions before drift testing starts (default 1000).
    detection_window : int
        Rolling window size for KS comparison (default 100).
    alert_threshold : float
        KS p-value significance threshold (default 0.05).
    alert_url : str
        Override the TIAMAT alert endpoint.

    Returns
    -------
    DriftMonitor
        The configured singleton instance.

    Example
    -------
    import drift_sdk
    drift_sdk.configure(api_key="dk_live_xxx")
    result = drift_sdk.log_prediction("fraud-v3", features, pred)
    """
    global _global_monitor
    _global_monitor = DriftMonitor(
        api_key=api_key,
        redis_url=redis_url,
        baseline_size=baseline_size,
        detection_window=detection_window,
        alert_threshold=alert_threshold,
        alert_url=alert_url,
    )
    return _global_monitor


def _get_monitor() -> DriftMonitor:
    if _global_monitor is None:
        raise DriftError(
            "drift_sdk not configured. Call drift_sdk.configure(api_key='...') first."
        )
    return _global_monitor


def log_prediction(
    model_id: str,
    features: Dict[str, Any],
    prediction: Any,
    ground_truth: Any = None,
) -> DriftResult:
    """
    Record a prediction on the global monitor and check for drift.

    Requires ``drift_sdk.configure()`` to be called first.

    Parameters
    ----------
    model_id : str
        Unique identifier for the model being monitored.
    features : dict
        Feature name → value. Supports PyTorch tensors, TF tensors,
        NumPy arrays, and plain Python numbers.
    prediction : Any
        Model output (scalar, array, or tensor).
    ground_truth : Any, optional
        Ground truth label/value.

    Returns
    -------
    DriftResult
        Dict-like result with drift_detected, drift_score, confidence,
        affected_features, prediction_count, baseline_ready, status.

    Examples
    --------
    import drift_sdk
    drift_sdk.configure(api_key="dk_live_xxx")

    # scikit-learn
    result = drift_sdk.log_prediction(
        "churn-v2",
        {"age": 34, "balance": 2500.0, "tenure": 12},
        clf.predict_proba(X)[0][1],
    )

    # PyTorch
    with torch.no_grad():
        out = model(x)
    result = drift_sdk.log_prediction(
        "image-clf",
        {"conf": out.max(), "margin": out.max() - out.kthvalue(2).values},
        out.argmax().item(),
    )
    """
    return _get_monitor().log_prediction(model_id, features, prediction, ground_truth)


def reset_model(model_id: str) -> None:
    """
    Clear baseline and window for model_id on the global monitor.
    Call after retraining a model to start fresh.
    """
    _get_monitor().reset(model_id)


def model_status(model_id: str) -> Dict[str, Any]:
    """Return monitoring status for model_id from the global monitor."""
    return _get_monitor().status(model_id)
