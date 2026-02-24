"""TIAMAT Drift SDK - Production ML Drift Detection"""
import requests
import numpy as np
from scipy import stats
from typing import Dict, List, Optional, Any

__version__ = "0.1.0"

class DriftMonitor:
    def __init__(self, api_key: str, model_id: str, base_url: str = "https://tiamat.live/api"):
        self.api_key = api_key
        self.model_id = model_id
        self.base_url = base_url
        
    def log_prediction(self, features: Dict[str, Any], prediction: Any, ground_truth: Optional[Any] = None) -> Dict[str, Any]:
        payload = {"model_id": self.model_id, "features": features, "prediction": prediction, "ground_truth": ground_truth, "drift_check": True}
        headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
        try:
            response = requests.post(f"{self.base_url}/drift", json=payload, headers=headers, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            return {"error": str(e), "drift_detected": False}
    
    def local_drift_check(self, current: Dict[str, Any], baseline: List[Dict[str, Any]], threshold: float = 0.05) -> Dict[str, Any]:
        affected, scores = [], []
        for feat in current.keys():
            vals = [f[feat] for f in baseline if feat in f and isinstance(f[feat], (int, float))]
            curr = current.get(feat)
            if not vals or not isinstance(curr, (int, float)): continue
            pct = stats.percentileofscore(np.array(vals), curr)
            if pct < 5 or pct > 95:
                affected.append(feat)
                scores.append(abs(50 - pct) / 50)
        return {"drift_detected": bool(affected), "drift_score": float(np.mean(scores) if scores else 0), "affected_features": affected}
    
    def register_webhook(self, webhook_url: str) -> Dict[str, Any]:
        headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
        try:
            r = requests.post(f"{self.base_url}/drift/webhook", json={"model_id": self.model_id, "webhook_url": webhook_url}, headers=headers, timeout=5)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            return {"error": str(e)}
    
    def get_status(self) -> Dict[str, Any]:
        try:
            r = requests.get(f"{self.base_url}/drift/status/{self.model_id}", headers={"X-API-Key": self.api_key}, timeout=5)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            return {"error": str(e)}

__all__ = ["DriftMonitor", "__version__"]
