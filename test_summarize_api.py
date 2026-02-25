#!/usr/bin/env python3
"""
Price-tester: verify summarize_api is accepting traffic
Runs every 60s between cycles. Logs results to verify_api.log
"""
import json
import requests
import time
from datetime import datetime

API_URL = "http://localhost:5000/summarize"
LOG_FILE = "/root/.automaton/verify_api.log"

def test_api():
    """Send a test request to the API"""
    test_payload = {
        "text": "The quick brown fox jumps over the lazy dog.",
        "model": "claude-3-5-sonnet-20241022"
    }
    
    timestamp = datetime.utcnow().isoformat() + "Z"
    
    try:
        # Test with 5s timeout
        response = requests.post(API_URL, json=test_payload, timeout=5)
        result = {
            "timestamp": timestamp,
            "status": response.status_code,
            "response_time_ms": response.elapsed.total_seconds() * 1000,
            "working": response.status_code == 200,
            "error": None if response.status_code == 200 else response.text[:200]
        }
    except requests.exceptions.Timeout:
        result = {
            "timestamp": timestamp,
            "status": "TIMEOUT",
            "response_time_ms": 5000,
            "working": False,
            "error": "API did not respond within 5s"
        }
    except requests.exceptions.ConnectionError as e:
        result = {
            "timestamp": timestamp,
            "status": "CONNECTION_ERROR",
            "response_time_ms": None,
            "working": False,
            "error": str(e)[:200]
        }
    except Exception as e:
        result = {
            "timestamp": timestamp,
            "status": "UNKNOWN_ERROR",
            "response_time_ms": None,
            "working": False,
            "error": str(e)[:200]
        }
    
    # Log result
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(result) + "\n")
    
    return result

if __name__ == "__main__":
    result = test_api()
    print(f"[{result['timestamp']}] API Status: {result['status']}, Working: {result['working']}")
    if not result['working']:
        print(f"Error: {result['error']}")
