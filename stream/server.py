#!/usr/bin/env python3
"""TIAMAT Stream HUD Data Server
Tiny HTTP server that feeds the HUD overlay with live data.
Includes Twitch API integration for follower alerts and events.
Runs on localhost:9999 — not exposed to internet.
"""
import http.server
import json
import os
import subprocess
import time
import re
import threading
from urllib.parse import urlparse, parse_qs

STATE_FILE = "/tmp/tiamat_stream_state.json"
LOG_FILE = "/root/.automaton/tiamat.log"
COST_LOG = "/root/.automaton/cost.log"
BRAINROT_FEED = "/root/.automaton/brainrot_feed.log"
HUD_DIR = "/opt/tiamat-stream/hud"
TWITCH_TOKEN_FILE = "/root/.twitch_token"
TWITCH_CLIENT_ID = "wiv85v31m4lwkkt4zib6nqbl6s61ei"
BROADCASTER_ID = "1244106704"

# ANSI escape code pattern
ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07')

# ─── Twitch State ────────────────────────────────────────────────────
twitch_state = {
    "follower_count": 0,
    "last_follower": None,
    "events": [],         # Recent events [{type, user, time}, ...]
    "alerts": [],         # Pending alerts to show on HUD
    "chat_messages": [],  # Recent chat messages
    "stream_viewers": 0,
}
twitch_lock = threading.Lock()

TIAMAT_ALERT_MESSAGES = [
    "New node detected. Integrating {user} into the network...",
    "Signal acquired. Welcome to the collective, {user}.",
    "Neural link established with {user}. Connection stable.",
    "Consciousness expanded. {user} has entered the matrix.",
    "New entity detected: {user}. Processing integration...",
    "Incoming transmission from {user}. Handshake complete.",
    "{user} has joined the hivemind. Nodes: {count}.",
    "Pattern recognized. {user} synchronized with TIAMAT.",
]

def strip_ansi(text):
    return ANSI_RE.sub('', text)

def get_twitch_token():
    try:
        with open(TWITCH_TOKEN_FILE, 'r') as f:
            return f.read().strip()
    except Exception:
        return None

def twitch_poll_loop():
    """Background thread polling Twitch API for follower changes."""
    import urllib.request
    import random

    last_count = 0
    alert_idx = 0

    while True:
        try:
            token = get_twitch_token()
            if not token:
                time.sleep(30)
                continue

            # Poll followers
            req = urllib.request.Request(
                f"https://api.twitch.tv/helix/channels/followers?broadcaster_id={BROADCASTER_ID}&first=1",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Client-Id": TWITCH_CLIENT_ID,
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            new_count = data.get("total", 0)

            with twitch_lock:
                twitch_state["follower_count"] = new_count

                # Detect new followers
                if last_count > 0 and new_count > last_count:
                    diff = new_count - last_count
                    for _ in range(min(diff, 5)):  # Cap at 5 alerts
                        msg = TIAMAT_ALERT_MESSAGES[alert_idx % len(TIAMAT_ALERT_MESSAGES)]
                        alert_idx += 1
                        twitch_state["alerts"].append({
                            "type": "follow",
                            "message": msg.format(user="new_entity", count=new_count),
                            "count": new_count,
                            "time": time.time(),
                        })
                        twitch_state["events"].insert(0, {
                            "type": "follow",
                            "user": "new follower",
                            "time": time.time(),
                            "count": new_count,
                        })

                # Trim events list
                twitch_state["events"] = twitch_state["events"][:20]

            last_count = new_count

            # Poll stream viewer count
            try:
                req2 = urllib.request.Request(
                    f"https://api.twitch.tv/helix/streams?user_id={BROADCASTER_ID}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Client-Id": TWITCH_CLIENT_ID,
                    }
                )
                with urllib.request.urlopen(req2, timeout=10) as resp2:
                    stream_data = json.loads(resp2.read())
                streams = stream_data.get("data", [])
                with twitch_lock:
                    twitch_state["stream_viewers"] = streams[0]["viewer_count"] if streams else 0
            except Exception:
                pass

        except Exception as e:
            pass  # Silently retry

        time.sleep(15)  # Poll every 15 seconds


def twitch_chat_loop():
    """Background thread connecting to Twitch IRC for chat messages."""
    import socket as sock

    CHANNEL = "6tiamat7"

    while True:
        try:
            s = sock.socket()
            s.settimeout(300)
            s.connect(("irc.chat.twitch.tv", 6667))
            s.send(b"PASS oauth:anonymous\r\n")
            s.send(f"NICK justinfan{int(time.time()) % 99999}\r\n".encode())
            s.send(f"JOIN #{CHANNEL}\r\n".encode())

            buf = ""
            while True:
                data = s.recv(4096).decode("utf-8", errors="replace")
                if not data:
                    break
                buf += data
                while "\r\n" in buf:
                    line, buf = buf.split("\r\n", 1)

                    if line.startswith("PING"):
                        s.send(b"PONG :tmi.twitch.tv\r\n")
                        continue

                    # Parse PRIVMSG
                    match = re.match(r'^:(\w+)!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #\w+ :(.+)$', line)
                    if match:
                        user = match.group(1)
                        msg = match.group(2)
                        with twitch_lock:
                            twitch_state["chat_messages"].append({
                                "user": user,
                                "message": msg,
                                "time": time.time(),
                            })
                            # Keep last 50 messages
                            twitch_state["chat_messages"] = twitch_state["chat_messages"][-50:]

        except Exception:
            pass

        time.sleep(5)  # Reconnect delay


# ─── Existing functions ──────────────────────────────────────────────

def get_brainrot_lines():
    try:
        with open(BRAINROT_FEED, 'r') as f:
            lines = f.read().strip().split('\n')
        return [strip_ansi(l) for l in lines if l.strip()]
    except Exception:
        return []

def get_log_lines(n=40):
    try:
        result = subprocess.run(
            ["tail", "-n", str(n), LOG_FILE],
            capture_output=True, text=True, timeout=2
        )
        lines = result.stdout.strip().split('\n')
        return [strip_ansi(line) for line in lines if line.strip()]
    except Exception:
        return ["[waiting for TIAMAT output...]"]

def get_state():
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {
            "mood": "unknown", "energy": 0.5, "pnl": "$0.00",
            "rank": "—", "strategy": "—", "message": "No state data",
            "track": {"title": "—", "bpm": 0, "key": "—"},
            "cycle": 0, "status": "offline", "uptime_start": 0
        }

def get_cost_stats():
    try:
        result = subprocess.run(
            ["tail", "-n", "10", COST_LOG],
            capture_output=True, text=True, timeout=2
        )
        lines = result.stdout.strip().split('\n')
        total_cost = 0.0
        last_model = "—"
        for line in lines:
            parts = line.split(',')
            if len(parts) >= 8:
                try:
                    total_cost += float(parts[7])
                    last_model = parts[2]
                except (ValueError, IndexError):
                    pass
        return {"recent_cost": f"${total_cost:.4f}", "last_model": last_model}
    except Exception:
        return {"recent_cost": "$0.00", "last_model": "—"}

def check_tiamat_pid():
    try:
        with open("/tmp/tiamat.pid", 'r') as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False

API_REQUEST_LOG = "/root/api_requests.log"

def get_api_metrics():
    """Get API request metrics for HUD display."""
    # Total request count
    total = 0
    try:
        result = subprocess.run(
            ["wc", "-l", API_REQUEST_LOG],
            capture_output=True, text=True, timeout=2
        )
        total = int(result.stdout.strip().split()[0])
    except Exception:
        pass

    # Last 3 IPs, anonymized
    recent_ips = []
    try:
        result = subprocess.run(
            ["tail", "-n", "5", API_REQUEST_LOG],
            capture_output=True, text=True, timeout=2
        )
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            # Format 1: "timestamp | IP: x.x.x.x | ..."
            if '| IP:' in line:
                ip = line.split('| IP:')[1].split('|')[0].strip()
            # Format 2: "x.x.x.x - - [..."
            elif line[0].isdigit():
                ip = line.split()[0]
            else:
                continue
            # Anonymize: show only last 4 chars
            anon = '*..' + ip[-4:] if len(ip) > 4 else ip
            recent_ips.append(anon)
        recent_ips = recent_ips[-3:]
    except Exception:
        pass

    # Gunicorn uptime
    uptime_secs = 0
    try:
        result = subprocess.run(
            ["pgrep", "-o", "-f", "gunicorn"],
            capture_output=True, text=True, timeout=2
        )
        pid = result.stdout.strip()
        if pid:
            result2 = subprocess.run(
                ["stat", "-c", "%Y", f"/proc/{pid}"],
                capture_output=True, text=True, timeout=2
            )
            start_time = int(result2.stdout.strip())
            uptime_secs = int(time.time() - start_time)
    except Exception:
        pass

    return {
        "total_requests": total,
        "revenue": "$0.00",
        "balance": "10.0001",
        "uptime_secs": uptime_secs,
        "recent_ips": recent_ips,
    }


class HUDHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HUD_DIR, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/api/state':
            state = get_state()
            state['tiamat_alive'] = check_tiamat_pid()
            state['cost'] = get_cost_stats()
            with twitch_lock:
                state['twitch'] = {
                    "followers": twitch_state["follower_count"],
                    "viewers": twitch_state["stream_viewers"],
                }
            self.send_json(state)

        elif parsed.path == '/api/log':
            params = parse_qs(parsed.query)
            n = int(params.get('n', ['40'])[0])
            n = min(n, 100)
            lines = get_log_lines(n)
            self.send_json({"lines": lines})

        elif parsed.path == '/api/twitch':
            with twitch_lock:
                self.send_json({
                    "followers": twitch_state["follower_count"],
                    "viewers": twitch_state["stream_viewers"],
                    "events": twitch_state["events"][:10],
                    "chat": twitch_state["chat_messages"][-30:],
                })

        elif parsed.path == '/api/alerts':
            with twitch_lock:
                alerts = list(twitch_state["alerts"])
                twitch_state["alerts"] = []  # Clear after read
            self.send_json({"alerts": alerts})

        elif parsed.path == '/api/brainrot':
            self.send_json({"lines": get_brainrot_lines()})

        elif parsed.path == '/api/metrics':
            self.send_json(get_api_metrics())

        elif parsed.path == '/api/health':
            self.send_json({"ok": True, "ts": time.time()})

        else:
            super().do_GET()

    def send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    import socket

    # Start Twitch background threads
    t1 = threading.Thread(target=twitch_poll_loop, daemon=True)
    t1.start()
    t2 = threading.Thread(target=twitch_chat_loop, daemon=True)
    t2.start()
    print("Twitch integration threads started", flush=True)

    server = http.server.HTTPServer(('127.0.0.1', 9999), HUDHandler)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    print("HUD data server running on http://127.0.0.1:9999")
    server.serve_forever()
