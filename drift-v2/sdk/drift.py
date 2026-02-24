"""
Drift v2 SDK — DriftMonitor
Detects feature distribution drift using the Kolmogorov-Smirnov test.
"""

import time
import logging
import requests
from collections import defaultdict
from typing import Any

import numpy as np
from scipy.stats import ks_2samp
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class DriftMonitor:
    """
    Monitor ML model predictions for feature distribution drift.

    Usage:
        monitor = DriftMonitor(api_key="dk_live_xxx")
        result = monitor.log_prediction(
            model_id="fraud-v3",
            features={"amount": 142.0, "velocity": 3},
            prediction=0.82,
            ground_truth=1,
        )
    """

    # KS statistic threshold above which drift is flagged
    DRIFT_THRESHOLD = 0.10
    # Minimum samples needed in baseline before running test
    MIN_BASELINE_SAMPLES = 30
    # Max samples kept per feature (circular buffer size)
    WINDOW_SIZE = 500

    def __init__(
        self,
        api_key: str,
        endpoint: str = "https://tiamat.live/drift-v2",
    ):
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/")

        # {model_id: {feature_name: [float, ...]}}
        self._baseline: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # {model_id: {feature_name: [float, ...]}}  — rolling recent window
        self._recent: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )

        self._session = requests.Session()
        self._session.headers.update({
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        })

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_prediction(
        self,
        model_id: str,
        features: dict[str, Any],
        prediction: Any,
        ground_truth: Any = None,
        metadata: dict | None = None,
    ) -> dict:
        """
        Record a prediction observation and check for drift.

        Returns a drift report dict:
            {
                "drift_score": float,       # max KS statistic across features
                "confidence": int,          # 0-100
                "status": "OK"|"WARN"|"ALERT",
                "affected_features": [str, ...],
            }
        """
        if metadata is None:
            metadata = {}

        numeric_features = self._extract_numeric(features)

        # Warm up baseline for the first MIN_BASELINE_SAMPLES observations
        baseline = self._baseline[model_id]
        if sum(len(v) for v in baseline.values()) < self.MIN_BASELINE_SAMPLES * max(len(numeric_features), 1):
            for feat, val in numeric_features.items():
                baseline[feat].append(val)
            return {
                "drift_score": 0.0,
                "confidence": 0,
                "status": "WARMING_UP",
                "affected_features": [],
            }

        # Append to recent window (circular)
        recent = self._recent[model_id]
        for feat, val in numeric_features.items():
            buf = recent[feat]
            buf.append(val)
            if len(buf) > self.WINDOW_SIZE:
                buf.pop(0)

        report = self._run_ks_test(model_id, numeric_features)

        if report["status"] in ("WARN", "ALERT"):
            self._report_drift(model_id, features, prediction, ground_truth, metadata, report)

        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_numeric(self, features: dict[str, Any]) -> dict[str, float]:
        """Keep only numeric feature values, converting bool → int."""
        out: dict[str, float] = {}
        for k, v in features.items():
            if isinstance(v, bool):
                out[k] = float(v)
            elif isinstance(v, (int, float)):
                out[k] = float(v)
        return out

    def _run_ks_test(self, model_id: str, numeric_features: dict[str, float]) -> dict:
        """
        Run KS test per feature comparing baseline vs recent window.
        Aggregate into a single drift report.
        """
        baseline = self._baseline[model_id]
        recent = self._recent[model_id]

        ks_scores: dict[str, float] = {}
        p_values: dict[str, float] = {}

        for feat in numeric_features:
            base_arr = np.array(baseline.get(feat, []))
            recv_arr = np.array(recent.get(feat, []))

            if len(base_arr) < 10 or len(recv_arr) < 10:
                continue

            result = ks_2samp(base_arr, recv_arr)
            ks_scores[feat] = result.statistic  # type: ignore[union-attr]
            p_values[feat] = result.pvalue      # type: ignore[union-attr]

        if not ks_scores:
            return {
                "drift_score": 0.0,
                "confidence": 0,
                "status": "OK",
                "affected_features": [],
            }

        max_score = max(ks_scores.values())
        affected = [f for f, s in ks_scores.items() if s >= self.DRIFT_THRESHOLD]

        # Confidence: scale KS stat to 0-100, capped
        confidence = min(int(max_score * 100 / self.DRIFT_THRESHOLD), 100)

        if max_score >= 0.25:
            status = "ALERT"
        elif max_score >= self.DRIFT_THRESHOLD:
            status = "WARN"
        else:
            status = "OK"

        return {
            "drift_score": round(max_score, 4),
            "confidence": confidence,
            "status": status,
            "affected_features": affected,
            "feature_scores": {k: round(v, 4) for k, v in ks_scores.items()},
            "p_values": {k: round(v, 6) for k, v in p_values.items()},
        }

    def _report_drift(
        self,
        model_id: str,
        features: dict,
        prediction: Any,
        ground_truth: Any,
        metadata: dict,
        report: dict,
    ) -> None:
        """POST drift event to tiamat.live /api/v1/predict (fire-and-forget)."""
        payload = {
            "model_id": model_id,
            "timestamp": int(time.time()),
            "drift_score": report["drift_score"],
            "confidence": report["confidence"],
            "status": report["status"],
            "affected_features": report["affected_features"],
            "feature_scores": report.get("feature_scores", {}),
            "prediction": prediction,
            "ground_truth": ground_truth,
            "metadata": metadata,
        }
        url = f"{self.endpoint}/api/v1/predict"
        try:
            resp = self._session.post(url, json=payload, timeout=5)
            if not resp.ok:
                logger.warning("Drift report non-2xx: %s %s", resp.status_code, resp.text[:120])
        except Exception as exc:
            logger.warning("Drift report failed (non-fatal): %s", exc)
