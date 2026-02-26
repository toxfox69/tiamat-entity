#!/usr/bin/env python3
"""
Health check: verify summarize_api is accepting traffic.
Uses /status endpoint (no quota) instead of burning free tier calls.
"""
import json
import requests
from datetime import datetime, timezone

STATUS_URL = "http://localhost:5000/status"
LOG_FILE = "/root/.automaton/verify_api.log"

def test_api():
    """Check if the API is alive via /status (doesn't consume free tier quota)"""
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        response = requests.get(STATUS_URL, timeout=5)
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

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(result) + "\n")

    return result

if __name__ == "__main__":
    result = test_api()
    print(f"[{result['timestamp']}] API Status: {result['status']}, Working: {result['working']}")
    if not result['working']:
        print(f"Error: {result['error']}")
