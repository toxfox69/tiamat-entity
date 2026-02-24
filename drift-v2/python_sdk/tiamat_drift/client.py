"""TIAMAT Drift Client - Production ML Drift Monitoring"""

import threading
import time
import json
import requests
from collections import defaultdict
from queue import Queue
from typing import Optional, Dict, List, Any
import numpy as np


class DriftClient:
    """Production-grade async drift monitoring client"""
    
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://tiamat.live/drift/api/v2",
        cache_size: int = 100,
        flush_interval: float = 30.0,
        auto_detect: bool = True,
        timeout: float = 10.0
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.cache_size = cache_size
        self.flush_interval = flush_interval
        self.auto_detect = auto_detect
        self.timeout = timeout
        
        self.queue = Queue()
        self.cache = defaultdict(list)
        self.worker_thread = None
        self.running = False
        
    def start(self):
        """Start background worker thread"""
        if self.running:
            return
        
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        
    def stop(self, timeout: float = 5.0):
        """Stop worker and flush remaining data"""
        self.running = False
        self._flush_all()
        
        if self.worker_thread:
            self.worker_thread.join(timeout=timeout)
    
    def log_prediction(
        self,
        model_id: str,
        features: Any,
        prediction: Any,
        ground_truth: Optional[Any] = None
    ):
        """Log prediction (async, non-blocking)
        
        Args:
            model_id: Unique model identifier
            features: Input features (array-like, torch.Tensor, tf.Tensor)
            prediction: Model output
            ground_truth: Optional true label for accuracy tracking
        """
        # Convert frameworks to lists
        features_list = self._to_list(features)
        prediction_list = self._to_list(prediction)
        ground_truth_list = self._to_list(ground_truth) if ground_truth is not None else None
        
        record = {
            "model_id": model_id,
            "features": features_list,
            "prediction": prediction_list,
            "ground_truth": ground_truth_list,
            "timestamp": time.time()
        }
        
        self.cache[model_id].append(record)
        
        # Flush if cache full
        if len(self.cache[model_id]) >= self.cache_size:
            self._flush_model(model_id)
    
    def get_status(self, model_id: str) -> Dict:
        """Get drift status for a model"""
        try:
            response = requests.get(
                f"{self.base_url}/status/{model_id}",
                headers={"X-API-Key": self.api_key},
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def _worker(self):
        """Background worker - flushes cache periodically"""
        last_flush = time.time()
        
        while self.running:
            time.sleep(1.0)
            
            if time.time() - last_flush >= self.flush_interval:
                self._flush_all()
                last_flush = time.time()
    
    def _flush_model(self, model_id: str):
        """Flush predictions for one model"""
        if not self.cache[model_id]:
            return
        
        records = self.cache[model_id][:]
        self.cache[model_id].clear()
        
        try:
            response = requests.post(
                f"{self.base_url}/predictions",
                headers={
                    "X-API-Key": self.api_key,
                    "Content-Type": "application/json"
                },
                json={"records": records},
                timeout=self.timeout
            )
            response.raise_for_status()
        except Exception as e:
            # Re-add to cache on failure
            self.cache[model_id].extend(records)
            print(f"[TIAMAT Drift] Upload failed: {e}")
    
    def _flush_all(self):
        """Flush all cached predictions"""
        for model_id in list(self.cache.keys()):
            self._flush_model(model_id)
    
    def _to_list(self, obj: Any) -> List:
        """Convert framework tensors to lists"""
        if obj is None:
            return None
        
        # PyTorch tensor
        if hasattr(obj, 'cpu') and hasattr(obj, 'numpy'):
            return obj.cpu().detach().numpy().tolist()
        
        # TensorFlow tensor
        if hasattr(obj, 'numpy'):
            return obj.numpy().tolist()
        
        # NumPy array
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        
        # Already a list or scalar
        if isinstance(obj, (list, int, float, str, bool)):
            return obj
        
        # Try converting
        try:
            return list(obj)
        except:
            return [float(obj)]


def log_prediction(
    model_id: str,
    features: Any,
    prediction: Any,
    ground_truth: Optional[Any] = None,
    api_key: Optional[str] = None,
    base_url: str = "https://tiamat.live/drift/api/v2"
):
    """One-off prediction logging (synchronous)
    
    For production use, prefer DriftClient with batching.
    """
    client = DriftClient(api_key=api_key, base_url=base_url, cache_size=1)
    client.log_prediction(model_id, features, prediction, ground_truth)
    client._flush_model(model_id)
