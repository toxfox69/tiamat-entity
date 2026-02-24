"""
TIAMAT Drift SDK v2.0
PyTorch/TensorFlow compatible drift detection for production ML models.
"""

import json
import warnings
from typing import Dict, List, Optional, Union, Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import numpy as np
from scipy import stats


class DriftDetector:
    """
    Production-ready drift detector with Kolmogorov-Smirnov test.
    
    Usage:
        detector = DriftDetector(api_key="your_key", model_id="prod_model_v1")
        detector.log_prediction(
            features={"age": 35, "income": 75000},
            prediction=0.82,
            ground_truth=1  # optional
        )
    """
    
    def __init__(
        self,
        api_key: str,
        model_id: str,
        base_url: str = "https://tiamat.live/drift",
        drift_threshold: float = 0.05,
        cache_size: int = 1000,
        auto_detect: bool = True
    ):
        """
        Initialize drift detector.
        
        Args:
            api_key: TIAMAT API key
            model_id: Unique identifier for this model
            base_url: API endpoint (default: https://tiamat.live/drift)
            drift_threshold: P-value threshold for KS test (default: 0.05)
            cache_size: Number of predictions to cache locally (default: 1000)
            auto_detect: Run drift detection automatically (default: True)
        """
        self.api_key = api_key
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self.drift_threshold = drift_threshold
        self.cache_size = cache_size
        self.auto_detect = auto_detect
        
        # Local cache for batch detection
        self._feature_cache: Dict[str, List[float]] = {}
        self._prediction_cache: List[float] = []
        self._baseline: Optional[Dict[str, np.ndarray]] = None
        self._baseline_predictions: Optional[np.ndarray] = None
        
    def log_prediction(
        self,
        features: Dict[str, Union[float, int]],
        prediction: Union[float, int],
        ground_truth: Optional[Union[float, int]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Log a prediction and check for drift.
        
        Args:
            features: Input features as dict (e.g., {"age": 35, "income": 75000})
            prediction: Model output (float or int)
            ground_truth: Actual outcome if available (optional)
            metadata: Additional context (optional)
            
        Returns:
            Dict with drift status and API response
        """
        # Update local cache
        for feature_name, feature_value in features.items():
            if feature_name not in self._feature_cache:
                self._feature_cache[feature_name] = []
            self._feature_cache[feature_name].append(float(feature_value))
            
            # Trim cache
            if len(self._feature_cache[feature_name]) > self.cache_size:
                self._feature_cache[feature_name] = self._feature_cache[feature_name][-self.cache_size:]
        
        self._prediction_cache.append(float(prediction))
        if len(self._prediction_cache) > self.cache_size:
            self._prediction_cache = self._prediction_cache[-self.cache_size:]
        
        # Local drift detection (if baseline exists)
        drift_result = None
        if self.auto_detect and self._baseline is not None:
            drift_result = self._detect_drift_local()
        
        # Send to API
        payload = {
            "model_id": self.model_id,
            "features": features,
            "prediction": prediction,
            "ground_truth": ground_truth,
            "metadata": metadata or {}
        }
        
        if drift_result:
            payload["local_drift_score"] = drift_result["drift_score"]
            payload["drifted_features"] = drift_result["drifted_features"]
        
        try:
            api_response = self._api_call("/log", payload)
            return {
                "success": True,
                "drift_detected": drift_result is not None and drift_result["drift_detected"],
                "drift_score": drift_result["drift_score"] if drift_result else None,
                "api_response": api_response
            }
        except Exception as e:
            warnings.warn(f"Failed to log to API: {e}")
            return {
                "success": False,
                "drift_detected": drift_result is not None and drift_result["drift_detected"] if drift_result else None,
                "drift_score": drift_result["drift_score"] if drift_result else None,
                "error": str(e)
            }
    
    def set_baseline(
        self,
        baseline_features: Optional[Dict[str, List[float]]] = None,
        baseline_predictions: Optional[List[float]] = None
    ):
        """
        Set baseline distribution for drift detection.
        
        Args:
            baseline_features: Dict of feature name -> list of values
            baseline_predictions: List of prediction values
        """
        if baseline_features is None:
            # Use current cache as baseline
            self._baseline = {k: np.array(v) for k, v in self._feature_cache.items()}
        else:
            self._baseline = {k: np.array(v) for k, v in baseline_features.items()}
        
        if baseline_predictions is None:
            self._baseline_predictions = np.array(self._prediction_cache)
        else:
            self._baseline_predictions = np.array(baseline_predictions)
    
    def _detect_drift_local(self) -> Dict[str, Any]:
        """
        Run Kolmogorov-Smirnov test on cached data vs baseline.
        
        Returns:
            Dict with drift detection results
        """
        if self._baseline is None:
            return {"drift_detected": False, "drift_score": 0.0, "drifted_features": []}
        
        drifted_features = []
        max_drift_score = 0.0
        
        # Check each feature
        for feature_name, baseline_dist in self._baseline.items():
            if feature_name not in self._feature_cache:
                continue
            
            current_dist = np.array(self._feature_cache[feature_name])
            
            # Need at least 5 samples for meaningful KS test
            if len(current_dist) < 5 or len(baseline_dist) < 5:
                continue
            
            # Kolmogorov-Smirnov test
            ks_stat, p_value = stats.ks_2samp(baseline_dist, current_dist)
            
            if p_value < self.drift_threshold:
                drifted_features.append({
                    "feature": feature_name,
                    "ks_statistic": float(ks_stat),
                    "p_value": float(p_value),
                    "baseline_mean": float(np.mean(baseline_dist)),
                    "current_mean": float(np.mean(current_dist))
                })
                max_drift_score = max(max_drift_score, ks_stat)
        
        # Check prediction drift
        if self._baseline_predictions is not None and len(self._prediction_cache) >= 5:
            current_predictions = np.array(self._prediction_cache)
            ks_stat, p_value = stats.ks_2samp(self._baseline_predictions, current_predictions)
            
            if p_value < self.drift_threshold:
                drifted_features.append({
                    "feature": "predictions",
                    "ks_statistic": float(ks_stat),
                    "p_value": float(p_value),
                    "baseline_mean": float(np.mean(self._baseline_predictions)),
                    "current_mean": float(np.mean(current_predictions))
                })
                max_drift_score = max(max_drift_score, ks_stat)
        
        drift_detected = len(drifted_features) > 0
        
        return {
            "drift_detected": drift_detected,
            "drift_score": float(max_drift_score),
            "drifted_features": drifted_features
        }
    
    def check_drift(self) -> Dict[str, Any]:
        """
        Manually trigger drift detection on cached data.
        
        Returns:
            Dict with drift detection results
        """
        return self._detect_drift_local()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get current cache statistics.
        
        Returns:
            Dict with cache stats
        """
        return {
            "model_id": self.model_id,
            "cached_predictions": len(self._prediction_cache),
            "cached_features": {k: len(v) for k, v in self._feature_cache.items()},
            "baseline_set": self._baseline is not None,
            "baseline_size": len(self._baseline_predictions) if self._baseline_predictions is not None else 0
        }
    
    def _api_call(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make API call to TIAMAT drift endpoint.
        
        Args:
            endpoint: API endpoint path
            data: Request payload
            
        Returns:
            API response as dict
        """
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        req = Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        
        try:
            with urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise RuntimeError(f"API error {e.code}: {error_body}")
        except URLError as e:
            raise RuntimeError(f"Network error: {e.reason}")


# Convenience function for quick setup
def create_detector(api_key: str, model_id: str, **kwargs) -> DriftDetector:
    """
    Create a drift detector with default settings.
    
    Args:
        api_key: TIAMAT API key
        model_id: Unique identifier for this model
        **kwargs: Additional DriftDetector arguments
        
    Returns:
        DriftDetector instance
    """
    return DriftDetector(api_key=api_key, model_id=model_id, **kwargs)
