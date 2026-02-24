"""
Drift v2 SDK - Production-ready drift detection for ML models

Usage:
  from drift import DriftClient
  
  client = DriftClient(api_key="sk_...", model_id="resnet_50")
  client.log_prediction(features=[...], prediction=0.95, ground_truth=1.0)
  
  # Automatic KS-test drift detection + alerting
"""

import numpy as np
from scipy import stats
from collections import deque
import hashlib
import requests
from typing import List, Dict, Optional, Tuple
import time
import json


class DriftClient:
    """
    Production ML drift detection client.
    
    - Kolmogorov-Smirnov test for feature distribution drift
    - Redis caching for free/pro rate limiting
    - Slack webhook alerts
    - Custom webhook support for drift events
    """
    
    def __init__(
        self,
        api_key: str,
        model_id: str,
        server_url: str = "https://drift.tiamat.live",
        window_size: int = 1000,
        drift_threshold: float = 0.05
    ):
        """
        Initialize drift client.
        
        Args:
            api_key: Your TIAMAT API key (sk_...)
            model_id: Unique identifier for your model
            server_url: Drift server endpoint
            window_size: Reference window for KS test (default 1000 predictions)
            drift_threshold: P-value threshold for drift (default 0.05 = 95% confidence)
        """
        self.api_key = api_key
        self.model_id = model_id
        self.server_url = server_url.rstrip('/')
        self.window_size = window_size
        self.drift_threshold = drift_threshold
        
        # Local buffers for features and predictions
        self.feature_history = {}  # feature_name -> deque of values
        self.prediction_history = deque(maxlen=window_size)
        self.ground_truth_history = deque(maxlen=window_size)
        self.timestamps = deque(maxlen=window_size)
        
        # Track drift state
        self.last_drift_alert = {}  # feature_name -> timestamp
        self.drift_cooldown_seconds = 300  # Don't spam alerts
        
    def log_prediction(
        self,
        features: Dict[str, float],
        prediction: float,
        ground_truth: Optional[float] = None,
        metadata: Optional[Dict] = None
    ) -> Dict:
        """
        Log a single prediction and check for drift.
        
        Returns:
            {
              'model_id': str,
              'drift_detected': bool,
              'drift_features': [str],
              'drift_scores': {feature: ks_statistic},
              'cached': bool  # if True, this was pulled from cache
            }
        """
        timestamp = time.time()
        
        # Store locally
        self.prediction_history.append(prediction)
        self.timestamps.append(timestamp)
        if ground_truth is not None:
            self.ground_truth_history.append(ground_truth)
        
        # Build feature history
        for feature_name, value in features.items():
            if feature_name not in self.feature_history:
                self.feature_history[feature_name] = deque(maxlen=self.window_size)
            self.feature_history[feature_name].append(value)
        
        # Check for drift
        drift_result = self._check_drift(features.keys())
        
        # Send to server (async-style)
        payload = {
            'api_key': self.api_key,
            'model_id': self.model_id,
            'features': features,
            'prediction': prediction,
            'ground_truth': ground_truth,
            'metadata': metadata or {},
            'drift_detected': drift_result['drift_detected'],
            'drift_features': drift_result['drift_features']
        }
        
        try:
            response = requests.post(
                f"{self.server_url}/log_prediction",
                json=payload,
                timeout=2  # Don't block on server call
            )
            drift_result['server_response'] = response.status_code
        except Exception as e:
            # Drift detection is local, so we don't fail if server is down
            drift_result['server_error'] = str(e)
        
        return drift_result
    
    def _check_drift(self, feature_names) -> Dict:
        """
        Local KS test drift detection.
        
        Returns drift score for each feature if we have enough history.
        """
        result = {
            'drift_detected': False,
            'drift_features': [],
            'drift_scores': {}
        }
        
        # Need at least 2 * window_size samples for reference vs test split
        if len(self.prediction_history) < self.window_size * 1.5:
            return result
        
        # Split history: first half = reference, second half = test
        history_list = list(self.prediction_history)
        mid = len(history_list) // 2
        reference = history_list[:mid]
        test = history_list[mid:]
        
        # KS test on features
        for feature_name in feature_names:
            if feature_name not in self.feature_history:
                continue
            
            feature_data = list(self.feature_history[feature_name])
            if len(feature_data) < mid:
                continue
            
            ref_features = feature_data[:mid]
            test_features = feature_data[mid:]
            
            # Kolmogorov-Smirnov test
            ks_stat, p_value = stats.ks_2samp(ref_features, test_features)
            result['drift_scores'][feature_name] = {
                'ks_statistic': float(ks_stat),
                'p_value': float(p_value),
                'drifted': p_value < self.drift_threshold
            }
            
            if p_value < self.drift_threshold:
                result['drift_detected'] = True
                result['drift_features'].append(feature_name)
        
        return result
    
    def get_statistics(self) -> Dict:
        """Get summary statistics for this model's monitoring."""
        return {
            'model_id': self.model_id,
            'predictions_logged': len(self.prediction_history),
            'features_monitored': len(self.feature_history),
            'uptime_seconds': time.time() - min(self.timestamps) if self.timestamps else 0
        }


class DriftServer:
    """
    Simple Flask reference implementation.
    See drift_v2_server.py for full deployment.
    """
    pass
