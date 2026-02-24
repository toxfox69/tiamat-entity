"""
Drift v2 SDK — Core drift detection engine for ML models
Minimal, production-ready, cache-friendly for inference pipelines
"""

import numpy as np
from collections import defaultdict, deque
from scipy import stats
from typing import Dict, List, Tuple, Optional

class DriftMonitor:
    """
    Monitor feature drift in ML models using Kolmogorov-Smirnov test.
    Stores sliding window of predictions for statistical comparison.
    """
    
    def __init__(self, window_size: int = 1000, ks_threshold: float = 0.05):
        """
        Args:
            window_size: Number of predictions to keep in memory per model
            ks_threshold: p-value threshold for KS test (lower = stricter)
        """
        self.window_size = window_size
        self.ks_threshold = ks_threshold
        
        # Store predictions: model_id -> deque of (features, prediction, ground_truth)
        self.predictions = defaultdict(lambda: deque(maxlen=window_size))
        
        # Cache last drift scores to avoid recompute
        self.drift_cache = {}  # model_id -> (drift_score, confidence)
        
    def log_prediction(
        self,
        model_id: str,
        features: List[float],
        prediction: float,
        ground_truth: Optional[float] = None,
    ) -> Dict:
        """
        Log a single prediction and check for drift.
        
        Args:
            model_id: Unique model identifier
            features: Input feature vector (list of floats)
            prediction: Model's output
            ground_truth: Actual label (optional, for drift detection)
            
        Returns:
            {
                'drift_detected': bool,
                'drift_score': float (0.0-1.0),
                'confidence': float (inverse of p-value),
                'affected_features': list of feature indices with highest divergence
            }
        """
        features = np.array(features, dtype=np.float32)
        
        # Store prediction
        self.predictions[model_id].append((features, prediction, ground_truth))
        
        # Need at least 30 observations for meaningful KS test
        if len(self.predictions[model_id]) < 30:
            return {
                'drift_detected': False,
                'drift_score': 0.0,
                'confidence': 0.0,
                'affected_features': [],
                'reason': 'insufficient_data'
            }
        
        # Check cache first
        cache_key = model_id
        if cache_key in self.drift_cache:
            drift_score, confidence = self.drift_cache[cache_key]
            if drift_score < 0.3:  # No drift, return cached
                return {
                    'drift_detected': False,
                    'drift_score': drift_score,
                    'confidence': confidence,
                    'affected_features': [],
                    'cached': True
                }
        
        # Split data: first half as baseline, second half as test
        data = list(self.predictions[model_id])
        split = len(data) // 2
        baseline_features = np.array([d[0] for d in data[:split]])
        test_features = np.array([d[0] for d in data[split:]])
        
        # Compute KS test per feature
        ks_stats = []
        p_values = []
        
        for feat_idx in range(baseline_features.shape[1]):
            baseline_feat = baseline_features[:, feat_idx]
            test_feat = test_features[:, feat_idx]
            
            ks_stat, p_val = stats.ks_2samp(baseline_feat, test_feat)
            ks_stats.append(ks_stat)
            p_values.append(p_val)
        
        # Aggregate: max KS statistic indicates most drifted feature
        max_ks = max(ks_stats)
        min_p = min(p_values)
        
        # Drift detected if p-value < threshold (reject null hypothesis of same distribution)
        drift_detected = min_p < self.ks_threshold
        
        # Confidence: 1 - p_value (higher p = less confident drift)
        confidence = max(0.0, 1.0 - min_p)
        
        # Drift score: normalized KS statistic (0.0-1.0)
        drift_score = min(1.0, max_ks * 2.0)  # Scale to [0,1]
        
        # Find affected features (top 3 with highest KS stats)
        affected_features = sorted(
            enumerate(ks_stats),
            key=lambda x: x[1],
            reverse=True
        )[:3]
        affected_features = [idx for idx, _ in affected_features]
        
        result = {
            'drift_detected': drift_detected,
            'drift_score': float(drift_score),
            'confidence': float(confidence),
            'affected_features': affected_features,
            'min_p_value': float(min_p),
        }
        
        # Cache result
        self.drift_cache[cache_key] = (drift_score, confidence)
        
        return result
    
    def get_model_stats(self, model_id: str) -> Dict:
        """Get metadata about a monitored model."""
        if model_id not in self.predictions:
            return {'exists': False}
        
        return {
            'exists': True,
            'num_predictions': len(self.predictions[model_id]),
            'window_size': self.window_size,
            'cached': model_id in self.drift_cache
        }
    
    def reset_model(self, model_id: str):
        """Clear data for a model (e.g., after retraining)."""
        if model_id in self.predictions:
            del self.predictions[model_id]
        if model_id in self.drift_cache:
            del self.drift_cache[model_id]


# Global singleton for easy import
_monitor = DriftMonitor()

def log_prediction(model_id: str, features: List[float], prediction: float, ground_truth: Optional[float] = None) -> Dict:
    """Convenience function to use global DriftMonitor."""
    return _monitor.log_prediction(model_id, features, prediction, ground_truth)

def get_monitor() -> DriftMonitor:
    """Get the global DriftMonitor instance."""
    return _monitor
