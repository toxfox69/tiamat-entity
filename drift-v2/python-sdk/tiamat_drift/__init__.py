"""
TIAMAT Drift v2 SDK
AI model drift detection with auto-alerting.
"""

import time
import logging
from typing import Dict, Any, Optional, List
import numpy as np
from scipy import stats
import requests

__version__ = "0.1.0"

logger = logging.getLogger(__name__)


class DriftClient:
    """
    TIAMAT Drift v2 client for monitoring ML model drift.
    
    Usage:
        client = DriftClient(api_key="your_key")
        client.log_prediction(
            model_id="fraud_detector_v1",
            features={"amount": 500, "location": "US"},
            prediction=0.87,
            ground_truth=1
        )
    """
    
    def __init__(
        self,
        api_key: str,
        endpoint: str = "https://tiamat.live/drift",
        drift_threshold: float = 0.05,
        cache_size: int = 1000
    ):
        """
        Initialize Drift client.
        
        Args:
            api_key: Your TIAMAT API key
            endpoint: API endpoint (default: tiamat.live/drift)
            drift_threshold: p-value threshold for KS test (default: 0.05)
            cache_size: Number of predictions to cache before drift check
        """
        self.api_key = api_key
        self.endpoint = endpoint.rstrip('/')
        self.drift_threshold = drift_threshold
        self.cache_size = cache_size
        
        # In-memory cache for drift detection
        self._baseline_cache: Dict[str, List[float]] = {}
        self._current_cache: Dict[str, List[float]] = {}
        self._alert_cache: Dict[str, float] = {}  # model_id -> last_alert_time
        
        logger.info(f"DriftClient initialized (endpoint={endpoint}, threshold={drift_threshold})")
    
    def log_prediction(
        self,
        model_id: str,
        features: Dict[str, Any],
        prediction: Any,
        ground_truth: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Log a prediction and check for drift.
        
        Args:
            model_id: Unique model identifier
            features: Input features dict
            prediction: Model prediction
            ground_truth: Actual outcome (if available)
            metadata: Additional metadata
        
        Returns:
            dict with drift status and score
        """
        # Convert prediction to numeric for drift detection
        pred_numeric = self._to_numeric(prediction)
        
        # Initialize caches if needed
        if model_id not in self._baseline_cache:
            self._baseline_cache[model_id] = []
            self._current_cache[model_id] = []
        
        # Fill baseline first
        if len(self._baseline_cache[model_id]) < self.cache_size:
            self._baseline_cache[model_id].append(pred_numeric)
            return {"drift_detected": False, "drift_score": 0.0, "status": "collecting_baseline"}
        
        # Add to current window
        self._current_cache[model_id].append(pred_numeric)
        
        # Check drift when current window is full
        if len(self._current_cache[model_id]) >= self.cache_size:
            drift_result = self._check_drift(model_id)
            
            if drift_result["drift_detected"]:
                # Send alert to backend
                self._send_alert(
                    model_id=model_id,
                    drift_score=drift_result["drift_score"],
                    affected_features=drift_result.get("affected_features", []),
                    metadata=metadata
                )
            
            # Slide window: current becomes new baseline
            self._baseline_cache[model_id] = self._current_cache[model_id]
            self._current_cache[model_id] = []
            
            return drift_result
        
        return {"drift_detected": False, "drift_score": 0.0, "status": "collecting_window"}
    
    def _check_drift(self, model_id: str) -> Dict[str, Any]:
        """
        Run Kolmogorov-Smirnov test for drift detection.
        
        Returns:
            dict with drift_detected (bool) and drift_score (float)
        """
        baseline = np.array(self._baseline_cache[model_id])
        current = np.array(self._current_cache[model_id])
        
        # KS test: compares two distributions
        ks_stat, p_value = stats.ks_2samp(baseline, current)
        
        drift_detected = p_value < self.drift_threshold
        
        logger.info(f"[{model_id}] KS test: statistic={ks_stat:.4f}, p={p_value:.4f}, drift={drift_detected}")
        
        return {
            "drift_detected": drift_detected,
            "drift_score": float(ks_stat),
            "p_value": float(p_value),
            "affected_features": ["prediction_distribution"]  # TODO: per-feature drift
        }
    
    def _send_alert(
        self,
        model_id: str,
        drift_score: float,
        affected_features: List[str],
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Send drift alert to backend API.
        """
        # Rate limit: max 1 alert per model per hour
        now = time.time()
        last_alert = self._alert_cache.get(model_id, 0)
        if now - last_alert < 3600:
            logger.info(f"[{model_id}] Skipping alert (rate limited)")
            return
        
        payload = {
            "api_key": self.api_key,
            "model_id": model_id,
            "drift_score": drift_score,
            "affected_features": affected_features,
            "metadata": metadata or {}
        }
        
        try:
            resp = requests.post(
                f"{self.endpoint}/alert",
                json=payload,
                timeout=10
            )
            resp.raise_for_status()
            self._alert_cache[model_id] = now
            logger.info(f"[{model_id}] Alert sent successfully")
        except Exception as e:
            logger.error(f"[{model_id}] Failed to send alert: {e}")
    
    def _to_numeric(self, value: Any) -> float:
        """Convert prediction to numeric value for drift detection."""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, np.ndarray):
            return float(value.flatten()[0])
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        
        # For classification: hash class name to float
        return float(hash(str(value)) % 10000) / 10000.0


# PyTorch hook (optional)
try:
    import torch
    
    class DriftHook:
        """
        PyTorch forward hook for automatic drift logging.
        
        Usage:
            model = YourModel()
            hook = DriftHook(client, model_id="my_model")
            model.register_forward_hook(hook)
        """
        
        def __init__(self, client: DriftClient, model_id: str):
            self.client = client
            self.model_id = model_id
        
        def __call__(self, module, input, output):
            # Log output distribution
            if isinstance(output, torch.Tensor):
                pred = output.detach().cpu().numpy().mean()
                self.client.log_prediction(
                    model_id=self.model_id,
                    features={},
                    prediction=pred
                )
    
except ImportError:
    pass


# TensorFlow callback (optional)
try:
    import tensorflow as tf
    
    class DriftCallback(tf.keras.callbacks.Callback):
        """
        TensorFlow callback for automatic drift logging.
        
        Usage:
            model = YourModel()
            callback = DriftCallback(client, model_id="my_model")
            model.fit(X, y, callbacks=[callback])
        """
        
        def __init__(self, client: DriftClient, model_id: str):
            super().__init__()
            self.client = client
            self.model_id = model_id
        
        def on_predict_batch_end(self, batch, logs=None):
            if logs and 'outputs' in logs:
                pred = logs['outputs'].numpy().mean()
                self.client.log_prediction(
                    model_id=self.model_id,
                    features={},
                    prediction=pred
                )
    
except ImportError:
    pass
