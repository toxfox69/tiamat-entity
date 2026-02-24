"""
Drift v2 SDK Client - Log predictions and auto-detect drift
"""

import os
import json
import time
import hashlib
from typing import Dict, Any, Optional, List, Union
from collections import deque
import numpy as np
from scipy import stats
import requests

# Global client instance
_client = None


class DriftClient:
    """
    Production drift monitoring client with automatic drift detection
    """
    
    def __init__(
        self,
        api_key: str,
        endpoint: str = "https://tiamat.live/api/v1/drift",
        cache_size: int = 1000,
        drift_threshold: float = 0.05
    ):
        """
        Initialize drift monitoring client
        
        Args:
            api_key: Your TIAMAT API key
            endpoint: Drift API endpoint (default: tiamat.live)
            cache_size: Number of predictions to cache per model (default: 1000)
            drift_threshold: P-value threshold for drift detection (default: 0.05)
        """
        self.api_key = api_key
        self.endpoint = endpoint.rstrip('/')
        self.cache_size = cache_size
        self.drift_threshold = drift_threshold
        
        # Per-model caches for drift detection
        self._feature_cache: Dict[str, Dict[str, deque]] = {}
        self._prediction_cache: Dict[str, deque] = {}
        
    def log_prediction(
        self,
        model_id: str,
        features: Union[Dict[str, float], np.ndarray, List[float]],
        prediction: Union[float, int, str],
        ground_truth: Optional[Union[float, int, str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Log a prediction and check for drift
        
        Args:
            model_id: Unique identifier for your model
            features: Input features (dict, numpy array, or list)
            prediction: Model prediction
            ground_truth: True label (optional, for accuracy tracking)
            metadata: Additional metadata (optional)
            
        Returns:
            dict: {
                "drift_detected": bool,
                "drift_score": float,
                "affected_features": List[str],
                "recommendation": str
            }
        """
        # Convert features to dict format
        feature_dict = self._normalize_features(features)
        
        # Update local cache
        drift_result = self._check_drift_local(model_id, feature_dict)
        
        # Send to API
        payload = {
            "model_id": model_id,
            "features": feature_dict,
            "prediction": prediction,
            "ground_truth": ground_truth,
            "metadata": metadata or {},
            "timestamp": time.time()
        }
        
        try:
            response = requests.post(
                f"{self.endpoint}/log",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                timeout=5
            )
            
            if response.status_code == 200:
                server_result = response.json()
                # Merge local drift detection with server response
                drift_result.update(server_result.get("drift", {}))
            elif response.status_code == 402:
                drift_result["error"] = "Free tier limit reached. Upgrade at tiamat.live/drift"
            else:
                drift_result["error"] = f"API error: {response.status_code}"
                
        except requests.exceptions.RequestException as e:
            drift_result["error"] = f"Network error: {str(e)}"
            
        return drift_result
    
    def _normalize_features(
        self,
        features: Union[Dict[str, float], np.ndarray, List[float]]
    ) -> Dict[str, float]:
        """Convert features to dict format"""
        if isinstance(features, dict):
            return {str(k): float(v) for k, v in features.items()}
        elif isinstance(features, np.ndarray):
            return {f"feature_{i}": float(v) for i, v in enumerate(features.flatten())}
        elif isinstance(features, (list, tuple)):
            return {f"feature_{i}": float(v) for i, v in enumerate(features)}
        else:
            raise ValueError(f"Unsupported feature type: {type(features)}")
    
    def _check_drift_local(
        self,
        model_id: str,
        features: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Local drift detection using Kolmogorov-Smirnov test
        Compares recent feature distributions to baseline
        """
        # Initialize cache for this model
        if model_id not in self._feature_cache:
            self._feature_cache[model_id] = {}
        
        model_cache = self._feature_cache[model_id]
        
        # Update feature caches
        for feature_name, value in features.items():
            if feature_name not in model_cache:
                model_cache[feature_name] = deque(maxlen=self.cache_size)
            model_cache[feature_name].append(value)
        
        # Need at least 100 samples to detect drift reliably
        drift_detected = False
        drift_scores = {}
        affected_features = []
        
        for feature_name, values in model_cache.items():
            if len(values) < 100:
                continue
                
            # Split into baseline (first 50%) and recent (last 50%)
            split_point = len(values) // 2
            baseline = list(values)[:split_point]
            recent = list(values)[split_point:]
            
            # Kolmogorov-Smirnov test
            ks_stat, p_value = stats.ks_2samp(baseline, recent)
            drift_scores[feature_name] = ks_stat
            
            if p_value < self.drift_threshold:
                drift_detected = True
                affected_features.append(feature_name)
        
        # Calculate overall drift score
        overall_score = np.mean(list(drift_scores.values())) if drift_scores else 0.0
        
        # Generate recommendation
        recommendation = self._generate_recommendation(
            drift_detected,
            affected_features,
            overall_score
        )
        
        return {
            "drift_detected": drift_detected,
            "drift_score": float(overall_score),
            "affected_features": affected_features,
            "recommendation": recommendation
        }
    
    def _generate_recommendation(
        self,
        drift_detected: bool,
        affected_features: List[str],
        score: float
    ) -> str:
        """Generate actionable recommendation"""
        if not drift_detected:
            return "No drift detected. Model is stable."
        
        severity = "HIGH" if score > 0.3 else "MEDIUM" if score > 0.15 else "LOW"
        
        recommendations = [
            f"[{severity}] Drift detected in {len(affected_features)} feature(s): {', '.join(affected_features[:3])}",
        ]
        
        if score > 0.3:
            recommendations.append("→ URGENT: Retrain model immediately")
        elif score > 0.15:
            recommendations.append("→ Schedule model retraining within 24 hours")
        else:
            recommendations.append("→ Monitor closely, consider retraining if drift persists")
            
        recommendations.append("→ Investigate data pipeline for upstream changes")
        
        return " | ".join(recommendations)


def configure(api_key: str, **kwargs):
    """
    Configure global drift client
    
    Args:
        api_key: Your TIAMAT API key
        **kwargs: Additional DriftClient parameters
    """
    global _client
    _client = DriftClient(api_key, **kwargs)


def log_prediction(
    model_id: str,
    features: Union[Dict[str, float], np.ndarray, List[float]],
    prediction: Union[float, int, str],
    ground_truth: Optional[Union[float, int, str]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Log a prediction using the global client
    
    Must call configure() first to set API key
    """
    global _client
    
    if _client is None:
        # Try to get API key from environment
        api_key = os.getenv("TIAMAT_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Drift client not configured. Call drift_sdk.configure(api_key='...') first "
                "or set TIAMAT_API_KEY environment variable"
            )
        _client = DriftClient(api_key)
    
    return _client.log_prediction(model_id, features, prediction, ground_truth, **kwargs)
