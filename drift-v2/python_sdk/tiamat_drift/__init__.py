"""TIAMAT Drift - Production ML Drift Monitoring"""

from .client import DriftClient, log_prediction
from .detector import ks_test, analyze_drift

__version__ = "2.0.0"
__all__ = ["DriftClient", "log_prediction", "ks_test", "analyze_drift"]
