"""
TIAMAT Drift v2 SDK - Production model drift monitoring
"""

from .client import DriftClient, log_prediction, configure

__version__ = "2.0.0"
__all__ = ["DriftClient", "log_prediction", "configure"]
