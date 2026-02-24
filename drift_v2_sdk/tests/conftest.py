"""
pytest configuration — adds the SDK root to sys.path so that
test imports like `from config import DriftConfig` resolve correctly.
"""
import sys
import os

# Add the SDK root (drift_v2_sdk/) to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
