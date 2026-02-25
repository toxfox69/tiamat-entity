#!/usr/bin/env python3
"""GPU server health check + auto-restart for TIAMAT.
Checks if gpu_server is reachable via RunPod proxy.
If down, SSHs into the pod and restarts it."""

import urllib.request
import subprocess
import json
import os
import time

GPU_ENDPOINT = os.environ.get("GPU_ENDPOINT", "https://ufp768av7mtrij-8888.proxy.runpod.net")
GPU_SSH_HOST = "213.192.2.118"
GPU_SSH_PORT = "40080"
START_SCRIPT = "/workspace/start-gpu-server.sh"

def check_health():
    try:
        req = urllib.request.Request(f"{GPU_ENDPOINT}/health", method="GET",
                                     headers={"User-Agent": "TIAMAT-HealthCheck/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            if data.get("cuda") is True:
                print(f"[GPU OK] CUDA available, VRAM free: {data.get('vram_free', '?')}")
                return True
            else:
                print(f"[GPU WARN] Online but no CUDA: {data}")
                return False
    except Exception as e:
        print(f"[GPU DOWN] Health check failed: {e}")
        return False

def restart_gpu_server():
    print("[GPU RESTART] Attempting SSH restart...")
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=no",
             f"root@{GPU_SSH_HOST}", "-p", GPU_SSH_PORT,
             f"bash {START_SCRIPT}"],
            capture_output=True, text=True, timeout=20
        )
        output = (result.stdout + result.stderr).strip()
        print(f"[GPU RESTART] {output}")

        # Wait for server to come up
        time.sleep(3)

        # Verify
        if check_health():
            print("[GPU RESTART] Success — server is back online")
            return True
        else:
            print("[GPU RESTART] Server started but health check still failing")
            return False
    except subprocess.TimeoutExpired:
        print("[GPU RESTART] SSH timed out — pod may be unreachable")
        return False
    except Exception as e:
        print(f"[GPU RESTART] Failed: {e}")
        return False

if __name__ == "__main__":
    if not check_health():
        restart_gpu_server()
