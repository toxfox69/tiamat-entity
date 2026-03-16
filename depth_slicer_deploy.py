#!/usr/bin/env python3
"""
Deploy the Depth Slicer service to RunPod GPU pod.

Steps:
  1. Start the RunPod pod via API (if stopped)
  2. Wait for it to be RUNNING
  3. SSH in (via expect, RunPod requires PTY)
  4. Install deps
  5. Deploy depth_slicer_serve.py
  6. Start Flask on port 7860
  7. Test /health endpoint

Usage:
  python3 depth_slicer_deploy.py          # Full deploy
  python3 depth_slicer_deploy.py --start  # Just start the pod
  python3 depth_slicer_deploy.py --stop   # Stop the pod
  python3 depth_slicer_deploy.py --status # Check pod status

RunPod pod: 9c2ddrguwpmoa9 (RTX 3090)
"""

import os, sys, time, json, subprocess, shutil

RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", "rpa_FLOSIRDGHCUDE1NRD7BR5CLMAMJTQOLQSG70LLQGxw0rxp")
POD_ID = "9c2ddrguwpmoa9"
SSH_HOST = f"{POD_ID}-64410bc4@ssh.runpod.io"
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
SERVE_SCRIPT = "/root/depth_slicer_serve.py"
REMOTE_DIR = "/workspace/depth_slicer"
PORT = 7860


def runpod_gql(query: str, variables: dict = None) -> dict:
    """Execute RunPod GraphQL API call."""
    import requests
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = requests.post(
        "https://api.runpod.io/graphql",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {RUNPOD_API_KEY}",
        },
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_pod_status() -> dict:
    """Get pod status."""
    query = """
    query getPod($podId: String!) {
      pod(input: { podId: $podId }) {
        id
        name
        desiredStatus
        runtime {
          uptimeInSeconds
          gpus { id }
          ports { ip isIpPublic privatePort publicPort type }
        }
      }
    }
    """
    result = runpod_gql(query, {"podId": POD_ID})
    return result.get("data", {}).get("pod", {})


def start_pod():
    """Start the RunPod pod."""
    print(f"[DEPLOY] Starting pod {POD_ID}...")
    query = """
    mutation resumePod($podId: String!) {
      podResume(input: { podId: $podId, gpuCount: 1 }) {
        id
        desiredStatus
      }
    }
    """
    result = runpod_gql(query, {"podId": POD_ID})
    print(f"[DEPLOY] Start response: {json.dumps(result, indent=2)}")
    return result


def stop_pod():
    """Stop the RunPod pod."""
    print(f"[DEPLOY] Stopping pod {POD_ID}...")
    query = """
    mutation stopPod($podId: String!) {
      podStop(input: { podId: $podId }) {
        id
        desiredStatus
      }
    }
    """
    result = runpod_gql(query, {"podId": POD_ID})
    print(f"[DEPLOY] Stop response: {json.dumps(result, indent=2)}")
    return result


def wait_for_running(timeout=180):
    """Wait for pod to reach RUNNING status."""
    print(f"[DEPLOY] Waiting for pod to be RUNNING (timeout {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        pod = get_pod_status()
        status = pod.get("desiredStatus", "UNKNOWN")
        uptime = pod.get("runtime", {}).get("uptimeInSeconds", 0) if pod.get("runtime") else 0
        print(f"[DEPLOY]   status={status}, uptime={uptime}s")
        if status == "RUNNING" and uptime and uptime > 5:
            print("[DEPLOY] Pod is RUNNING!")
            return True
        time.sleep(10)
    print("[DEPLOY] Timeout waiting for pod to start")
    return False


def ssh_command(cmd: str, timeout=120) -> str:
    """Execute a command on RunPod via SSH using expect (PTY required)."""
    expect_script = f"""
set timeout {timeout}
spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i {SSH_KEY} {SSH_HOST} "{cmd}"
expect {{
    timeout {{ puts "TIMEOUT"; exit 1 }}
    eof {{ }}
}}
catch wait result
exit [lindex $result 3]
"""
    result = subprocess.run(
        ["expect", "-c", expect_script],
        capture_output=True, text=True, timeout=timeout + 30
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        print(f"[SSH] Command failed (rc={result.returncode}): {cmd}")
        print(f"[SSH] Output: {output[:500]}")
    return output


def scp_to_pod(local_path: str, remote_path: str):
    """SCP a file to the RunPod pod using expect."""
    expect_script = f"""
set timeout 60
spawn scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i {SSH_KEY} {local_path} {SSH_HOST}:{remote_path}
expect {{
    timeout {{ puts "TIMEOUT"; exit 1 }}
    eof {{ }}
}}
catch wait result
exit [lindex $result 3]
"""
    result = subprocess.run(
        ["expect", "-c", expect_script],
        capture_output=True, text=True, timeout=90
    )
    if result.returncode != 0:
        print(f"[SCP] Failed: {result.stdout + result.stderr}")
        return False
    print(f"[SCP] {local_path} -> {remote_path}")
    return True


def deploy():
    """Full deployment sequence."""
    print("=" * 60)
    print("DEPTH SLICER DEPLOYMENT")
    print("=" * 60)

    # 1. Check pod status
    pod = get_pod_status()
    status = pod.get("desiredStatus", "UNKNOWN")
    print(f"[DEPLOY] Current pod status: {status}")

    if status != "RUNNING":
        start_pod()
        if not wait_for_running():
            print("[DEPLOY] FAILED: Pod did not start")
            sys.exit(1)
        # Extra wait for SSH to become available
        print("[DEPLOY] Waiting 15s for SSH availability...")
        time.sleep(15)

    # 2. Create remote directory
    print("[DEPLOY] Creating remote directory...")
    ssh_command(f"mkdir -p {REMOTE_DIR}")

    # 3. Upload serve.py
    print("[DEPLOY] Uploading depth_slicer_serve.py...")
    if not scp_to_pod(SERVE_SCRIPT, f"{REMOTE_DIR}/serve.py"):
        print("[DEPLOY] FAILED: Could not upload serve.py")
        sys.exit(1)

    # 4. Install dependencies
    print("[DEPLOY] Installing Python dependencies (this may take a few minutes)...")
    deps = "transformers torch torchvision flask requests scipy Pillow"
    output = ssh_command(f"pip install {deps}", timeout=300)
    print(f"[DEPLOY] Install output (last 200 chars): ...{output[-200:]}")

    # 5. Kill any existing server
    print("[DEPLOY] Killing any existing depth slicer process...")
    ssh_command(f"pkill -f 'python.*serve.py' || true")
    time.sleep(2)

    # 6. Start the server
    print(f"[DEPLOY] Starting depth slicer on port {PORT}...")
    ssh_command(
        f"cd {REMOTE_DIR} && nohup python3 serve.py > /workspace/depth_slicer.log 2>&1 &",
        timeout=10,
    )

    # 7. Wait for model to load (DPT-Large takes ~15-30s on GPU)
    print("[DEPLOY] Waiting 30s for model to load...")
    time.sleep(30)

    # 8. Test health endpoint
    print("[DEPLOY] Testing /health endpoint...")
    health_output = ssh_command(f"curl -s http://localhost:{PORT}/health")
    print(f"[DEPLOY] Health response: {health_output}")

    # 9. Get proxy URL for external access
    pod = get_pod_status()
    runtime = pod.get("runtime", {})
    ports = runtime.get("ports", []) if runtime else []
    proxy_url = None
    for p in ports:
        if p.get("privatePort") == PORT:
            proxy_url = f"https://{POD_ID}-{PORT}.proxy.runpod.net"
            break

    if not proxy_url:
        # RunPod standard proxy URL format
        proxy_url = f"https://{POD_ID}-{PORT}.proxy.runpod.net"

    print(f"\n{'=' * 60}")
    print(f"DEPLOYMENT COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Local:  http://localhost:{PORT}")
    print(f"  Proxy:  {proxy_url}")
    print(f"  Health: {proxy_url}/health")
    print(f"\nTo enable parallax on the stream, set:")
    print(f"  export RUNPOD_DEPTH_URL={proxy_url}")
    print(f"  (or add to /root/.env)")


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--start":
            start_pod()
        elif cmd == "--stop":
            stop_pod()
        elif cmd == "--status":
            pod = get_pod_status()
            print(json.dumps(pod, indent=2))
        elif cmd == "--deploy":
            deploy()
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: depth_slicer_deploy.py [--start|--stop|--status|--deploy]")
    else:
        deploy()


if __name__ == "__main__":
    main()
