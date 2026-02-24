"""
Kolmogorov-Smirnov drift detection.
Compares historical vs. recent feature distributions.
"""

import numpy as np
from scipy.stats import ks_2samp
from typing import List, Dict, Tuple


def detect_drift(
    historical_features: List[Dict[str, float]],
    recent_features: List[Dict[str, float]],
    threshold: float = 0.05
) -> Dict[str, any]:
    """
    Detect drift between historical and recent feature distributions.
    
    Args:
        historical_features: List of feature dicts (baseline)
        recent_features: List of feature dicts (recent window)
        threshold: p-value threshold (default 0.05)
    
    Returns:
        {
            "drift_detected": bool,
            "drift_score": float (0-1),
            "affected_features": List[str],
            "confidence": float (0-1),
            "details": Dict[str, any]
        }
    """
    
    if len(historical_features) < 30 or len(recent_features) < 30:
        return {
            "drift_detected": False,
            "drift_score": 0.0,
            "affected_features": [],
            "confidence": 0.0,
            "details": {"error": "Insufficient data (need 30+ samples each)"}
        }
    
    # Extract all feature names
    feature_names = set()
    for f in historical_features + recent_features:
        feature_names.update(f.keys())
    
    feature_names = sorted(feature_names)
    
    # Run KS test on each feature
    drift_scores = {}
    p_values = {}
    
    for feature in feature_names:
        try:
            hist_values = [f.get(feature, 0.0) for f in historical_features]
            recent_values = [f.get(feature, 0.0) for f in recent_features]
            
            # Remove None/NaN values
            hist_values = [v for v in hist_values if v is not None and not np.isnan(v)]
            recent_values = [v for v in recent_values if v is not None and not np.isnan(v)]
            
            if len(hist_values) < 10 or len(recent_values) < 10:
                continue
            
            # Run KS test
            statistic, p_value = ks_2samp(hist_values, recent_values)
            
            drift_scores[feature] = statistic
            p_values[feature] = p_value
            
        except Exception as e:
            print(f"Error testing feature {feature}: {e}")
            continue
    
    if not drift_scores:
        return {
            "drift_detected": False,
            "drift_score": 0.0,
            "affected_features": [],
            "confidence": 0.0,
            "details": {"error": "No valid features to test"}
        }
    
    # Find features with significant drift
    affected_features = [
        feature for feature, p_val in p_values.items()
        if p_val < threshold
    ]
    
    # Calculate aggregate drift score (max statistic)
    max_drift_score = max(drift_scores.values())
    
    # Calculate confidence (inverse of min p-value)
    min_p_value = min(p_values.values())
    confidence = 1.0 - min_p_value
    
    drift_detected = len(affected_features) > 0
    
    return {
        "drift_detected": drift_detected,
        "drift_score": round(max_drift_score, 3),
        "affected_features": affected_features,
        "confidence": round(confidence, 3),
        "details": {
            "feature_scores": {k: round(v, 3) for k, v in drift_scores.items()},
            "p_values": {k: round(v, 4) for k, v in p_values.items()},
            "threshold": threshold
        }
    }


def get_recommendation(drift_result: Dict[str, any]) -> str:
    """
    Generate recommendation based on drift detection result.
    """
    if not drift_result["drift_detected"]:
        return "No action needed. Model performance is stable."
    
    drift_score = drift_result["drift_score"]
    affected_features = drift_result["affected_features"]
    
    if drift_score > 0.7:
        severity = "CRITICAL"
        action = "Retrain model immediately on recent data"
    elif drift_score > 0.5:
        severity = "HIGH"
        action = "Schedule model retraining within 24 hours"
    elif drift_score > 0.3:
        severity = "MEDIUM"
        action = "Monitor closely and retrain within 1 week"
    else:
        severity = "LOW"
        action = "Consider retraining during next scheduled maintenance"
    
    feature_list = ", ".join(affected_features[:3])
    if len(affected_features) > 3:
        feature_list += f" (+{len(affected_features) - 3} more)"
    
    return f"[{severity}] {action}. Affected features: {feature_list}"
