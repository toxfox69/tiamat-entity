"""
TIAMAT Drift v2 SDK - Production ML Drift Detection
Minimal, cache-friendly, PyTorch/TensorFlow compatible
"""

import json
import time
from collections import deque
from scipy.stats import ks_2samp
import requests

class DriftSDK:
    def __init__(self, api_key, endpoint="http://localhost:9000"):
        self.api_key = api_key
        self.endpoint = endpoint
        # Local cache: model_id -> deque of predictions
        self.local_cache = {}
        self.max_history = 100  # Keep last 100 predictions per model
        
    def log_prediction(self, model_id, features, prediction, ground_truth=None):
        """
        Log a prediction and check for drift.
        
        Args:
            model_id (str): Unique model identifier
            features (dict): Input features used
            prediction (float): Model output
            ground_truth (float, optional): Actual value for validation
            
        Returns:
            dict: {drift_detected: bool, drift_score: float, message: str}
        """
        if model_id not in self.local_cache:
            self.local_cache[model_id] = deque(maxlen=self.max_history)
            
        # Store locally
        entry = {
            "features": features,
            "prediction": prediction,
            "ground_truth": ground_truth,
            "timestamp": time.time()
        }
        self.local_cache[model_id].append(entry)
        
        # Send to server
        try:
            response = requests.post(
                f"{self.endpoint}/drift/log",
                json={
                    "model_id": model_id,
                    "features": features,
                    "prediction": prediction,
                    "ground_truth": ground_truth,
                    "api_key": self.api_key
                },
                timeout=5
            )
            return response.json()
        except Exception as e:
            return {
                "drift_detected": False,
                "drift_score": 0,
                "message": f"Local cache only: {str(e)}"
            }
    
    def get_status(self):
        """Get drift status for all models under this API key."""
        try:
            response = requests.get(
                f"{self.endpoint}/drift/status/{self.api_key}",
                timeout=5
            )
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def local_drift_detection(self, model_id, window_size=50):
        """
        Detect drift using local cache with Kolmogorov-Smirnov test.
        Splits history into two windows and compares distributions.
        """
        if model_id not in self.local_cache:
            return {"drift_detected": False, "drift_score": 0}
            
        history = list(self.local_cache[model_id])
        if len(history) < window_size * 2:
            return {"drift_detected": False, "drift_score": 0, "message": "Insufficient data"}
        
        # Split into two windows
        window1 = [h["prediction"] for h in history[-window_size*2:-window_size]]
        window2 = [h["prediction"] for h in history[-window_size:]]
        
        # KS test: null hypothesis is same distribution
        statistic, p_value = ks_2samp(window1, window2)
        
        # drift_score = 1 - p_value (higher = more drift)
        drift_score = max(0, min(1, 1 - p_value))
        drift_detected = drift_score > 0.5
        
        return {
            "drift_detected": drift_detected,
            "drift_score": round(drift_score, 3),
            "ks_statistic": round(statistic, 3),
            "p_value": round(p_value, 3)
        }
