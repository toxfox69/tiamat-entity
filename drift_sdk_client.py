"""
Drift Monitor Python SDK
Detect model drift in production with automatic alerts.
"""

import requests
import hashlib
import json
from typing import Dict, List, Optional, Any
from datetime import datetime


class DriftMonitor:
    """
    Python SDK for TIAMAT Drift Monitor API.
    
    Usage:
        monitor = DriftMonitor(api_key="your_api_key")
        monitor.log_prediction(
            model_id="recommendation_v2",
            features={"user_age": 32, "session_count": 15},
            prediction=0.87,
            ground_truth=1.0  # optional
        )
    """
    
    def __init__(self, api_key: str, base_url: str = "https://tiamat.live"):
        """
        Initialize Drift Monitor client.
        
        Args:
            api_key: Your TIAMAT API key
            base_url: API endpoint (default: https://tiamat.live)
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.endpoint = f"{self.base_url}/drift"
        
    def log_prediction(
        self,
        model_id: str,
        features: Dict[str, Any],
        prediction: Any,
        ground_truth: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Log a single prediction for drift monitoring.
        
        Auto-detects drift using Kolmogorov-Smirnov test when enough
        data has been collected. Sends alerts via webhook/Slack if
        drift is detected.
        
        Args:
            model_id: Unique identifier for your model
            features: Feature dictionary (e.g., {"age": 32, "income": 50000})
            prediction: Model output (can be scalar, class, or array)
            ground_truth: Actual outcome (optional, for error drift)
            metadata: Additional context (optional)
            
        Returns:
            Response dict with drift_score, affected_features, alert_sent
            
        Raises:
            ValueError: Invalid input
            requests.HTTPError: API request failed
        """
        if not model_id:
            raise ValueError("model_id is required")
        if not features or not isinstance(features, dict):
            raise ValueError("features must be a non-empty dictionary")
            
        payload = {
            "model_id": model_id,
            "features": features,
            "prediction": prediction,
        }
        
        if ground_truth is not None:
            payload["ground_truth"] = ground_truth
            
        if metadata:
            payload["metadata"] = metadata
            
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.post(
                self.endpoint,
                json=payload,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            # Re-raise with more context
            raise RuntimeError(f"Drift API request failed: {e}") from e
    
    def log_batch(
        self,
        model_id: str,
        predictions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Log multiple predictions at once (more efficient).
        
        Args:
            model_id: Unique identifier for your model
            predictions: List of prediction dicts, each containing:
                - features: Dict[str, Any]
                - prediction: Any
                - ground_truth: Optional[Any]
                - metadata: Optional[Dict[str, Any]]
                
        Returns:
            List of response dicts
            
        Example:
            monitor.log_batch("model_v2", [
                {"features": {"x": 1}, "prediction": 0.9},
                {"features": {"x": 2}, "prediction": 0.1},
            ])
        """
        results = []
        for pred in predictions:
            result = self.log_prediction(
                model_id=model_id,
                features=pred["features"],
                prediction=pred["prediction"],
                ground_truth=pred.get("ground_truth"),
                metadata=pred.get("metadata")
            )
            results.append(result)
        return results
    
    def register_webhook(self, webhook_url: str) -> Dict[str, Any]:
        """
        Register a webhook URL to receive drift alerts.
        
        When drift is detected, a POST request will be sent to your webhook:
        {
            "model_id": "recommendation_v2",
            "drift_score": 0.87,
            "affected_features": ["user_age", "session_count"],
            "timestamp": "2026-02-24T19:45:00Z"
        }
        
        Args:
            webhook_url: Your webhook endpoint URL
            
        Returns:
            Confirmation response
        """
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            f"{self.base_url}/drift/webhook",
            json={"webhook_url": webhook_url},
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    
    def get_slack_oauth_url(self) -> str:
        """
        Get Slack OAuth URL to connect your workspace.
        
        Returns:
            OAuth URL - visit this to authorize Slack alerts
        """
        headers = {"X-API-Key": self.api_key}
        response = requests.get(
            f"{self.base_url}/drift/slack/oauth",
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        return response.json()["oauth_url"]


# Convenience function for quick setup
def monitor(api_key: str) -> DriftMonitor:
    """
    Shorthand to create a DriftMonitor instance.
    
    Usage:
        from drift_sdk_client import monitor
        drift = monitor("your_api_key")
        drift.log_prediction(...)
    """
    return DriftMonitor(api_key)
