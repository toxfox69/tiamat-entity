"""Drift detection algorithms"""

import numpy as np
from scipy import stats
from typing import Dict, List, Any


def ks_test(reference: List[float], current: List[float]) -> float:
    """Kolmogorov-Smirnov test for distribution drift
    
    Returns:
        p-value (0-1): lower = more drift. <0.05 = significant drift
    """
    if len(reference) < 2 or len(current) < 2:
        return 1.0  # Not enough data
    
    statistic, pvalue = stats.ks_2samp(reference, current)
    return pvalue


def analyze_drift(
    reference_predictions: List[Dict],
    current_predictions: List[Dict]
) -> Dict[str, Any]:
    """Comprehensive drift analysis
    
    Args:
        reference_predictions: Baseline predictions (list of {features, prediction})
        current_predictions: Recent predictions to compare
        
    Returns:
        {
            "drift_score": float (0-1, higher = more drift),
            "drift_detected": bool,
            "affected_features": List[int],
            "suggestions": List[str]
        }
    """
    if not reference_predictions or not current_predictions:
        return {
            "drift_score": 0.0,
            "drift_detected": False,
            "affected_features": [],
            "suggestions": ["Not enough data for drift detection"]
        }
    
    # Extract feature dimensions
    ref_features = [r["features"] for r in reference_predictions]
    cur_features = [r["features"] for r in current_predictions]
    
    # Handle different shapes
    ref_array = np.array(ref_features)
    cur_array = np.array(cur_features)
    
    if ref_array.ndim == 1:
        ref_array = ref_array.reshape(-1, 1)
    if cur_array.ndim == 1:
        cur_array = cur_array.reshape(-1, 1)
    
    num_features = ref_array.shape[1]
    
    # Test each feature dimension
    feature_pvalues = []
    affected_features = []
    
    for i in range(num_features):
        ref_col = ref_array[:, i]
        cur_col = cur_array[:, i]
        
        pvalue = ks_test(ref_col.tolist(), cur_col.tolist())
        feature_pvalues.append(pvalue)
        
        if pvalue < 0.05:  # Significant drift
            affected_features.append(i)
    
    # Aggregate drift score
    avg_pvalue = np.mean(feature_pvalues) if feature_pvalues else 1.0
    drift_score = 1.0 - avg_pvalue  # Convert: higher = more drift
    drift_detected = drift_score > 0.8  # 80% confidence threshold
    
    # Generate suggestions
    suggestions = []
    if drift_detected:
        suggestions.append(f"Significant drift detected in {len(affected_features)} features")
        suggestions.append("Consider retraining model with recent data")
        
        if len(affected_features) < num_features * 0.3:
            suggestions.append("Drift is localized - feature engineering may help")
        else:
            suggestions.append("Drift is widespread - data distribution has changed")
    else:
        suggestions.append("No significant drift detected")
    
    return {
        "drift_score": round(drift_score, 3),
        "drift_detected": drift_detected,
        "affected_features": affected_features,
        "suggestions": suggestions,
        "num_features": num_features,
        "pvalues": [round(p, 3) for p in feature_pvalues]
    }
