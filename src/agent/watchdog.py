#!/usr/bin/env python3
"""TIAMAT Watchdog Daemon — External behavioral monitor.

Monitors TIAMAT independently, detects behavioral problems, and force-creates
trouble tickets + sends alerts that TIAMAT cannot suppress.

Runs as systemd service: tiamat-watchdog.service
Check interval: 45 seconds
Resources: stdlib only, MemoryMax=64M, CPUQuota=5%
"""

import csv
import difflib
import fcntl
import io
import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────────────────

CHECK_INTERVAL = 45  # seconds between checks
COOLDOWN_SECONDS = 1800  # 30 minutes per issue key

STATE_DB = "/root/.automaton/state.db"
TIAMAT_LOG = "/root/.automaton/tiamat.log"
PACER_JSON = "/root/.automaton/pacer.json"
COST_LOG = "/root/.automaton/cost.log"
TICKETS_JSON = "/root/.automaton/tickets.json"
PID_FILE = "/tmp/tiamat.pid"
WATCHDOG_STATE = "/root/.automaton/watchdog_state.json"
WATCHDOG_LOG = "/root/.automaton/watchdog.log"
START_SCRIPT = "/root/start-tiamat.sh"
EMAIL_TOOL = "/root/entity/src/agent/email_tool.py"
ALERT_EMAIL = "jacl33t@gmail.com"

# Env vars (loaded from /root/.env via systemd EnvironmentFile)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("watchdog")

# ─── Utility ─────────────────────────────────────────────────────────────────

def utcnow():
    return datetime.now(timezone.utc)


def utcnow_iso():
    return utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_json_load(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default if default is not None else {}


# ─── WatchdogState ───────────────────────────────────────────────────────────

class WatchdogState:
    """Persists cooldowns and timestamps between checks."""

    def __init__(self, path=WATCHDOG_STATE):
        self.path = path
        self.data = safe_json_load(path, {"cooldowns": {}, "last_check": None, "checks_total": 0})

    def save(self):
        self.data["last_check"] = utcnow_iso()
        self.data["checks_total"] = self.data.get("checks_total", 0) + 1
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)

    def is_cooled_down(self, issue_key):
        """Return True if this issue is still in cooldown (should NOT alert)."""
        ts = self.data.get("cooldowns", {}).get(issue_key)
        if not ts:
            return False
        try:
            last = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return (utcnow() - last).total_seconds() < COOLDOWN_SECONDS
        except (ValueError, TypeError):
            return False

    def set_cooldown(self, issue_key):
        if "cooldowns" not in self.data:
            self.data["cooldowns"] = {}
        self.data["cooldowns"][issue_key] = utcnow_iso()

    def prune_cooldowns(self):
        """Remove expired cooldowns to prevent state file bloat."""
        cooldowns = self.data.get("cooldowns", {})
        now = utcnow()
        pruned = {}
        for key, ts in cooldowns.items():
            try:
                last = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if (now - last).total_seconds() < COOLDOWN_SECONDS:
                    pruned[key] = ts
            except (ValueError, TypeError):
                pass
        self.data["cooldowns"] = pruned


# ─── TicketManager ───────────────────────────────────────────────────────────

class TicketManager:
    """Read/write tickets.json with file locking."""

    def __init__(self, path=TICKETS_JSON):
        self.path = path

    def _load(self):
        return safe_json_load(self.path, {"next_id": 1, "tickets": []})

    def _save(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)

    def has_open_duplicate(self, title_prefix):
        """Check if an open/in_progress watchdog ticket with same title prefix exists."""
        data = self._load()
        for t in data.get("tickets", []):
            if t.get("source") != "watchdog":
                continue
            if t.get("status") not in ("open", "in_progress"):
                continue
            existing_prefix = t.get("title", "").split(":")[0]
            if existing_prefix == title_prefix:
                return True
        return False

    def create_ticket(self, priority, title, description, tags=None):
        """Create a new watchdog ticket. Returns ticket ID or None if duplicate."""
        title_prefix = title.split(":")[0]
        if self.has_open_duplicate(title_prefix):
            log.info(f"Skipping duplicate ticket: {title}")
            return None

        # File-locked read-modify-write
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                raw = os.read(fd, 10_000_000)
                if raw:
                    data = json.loads(raw.decode())
                else:
                    data = {"next_id": 1, "tickets": []}

                # Re-check after lock
                for t in data.get("tickets", []):
                    if t.get("source") == "watchdog" and t.get("status") in ("open", "in_progress"):
                        if t.get("title", "").split(":")[0] == title_prefix:
                            return None

                # Find safe next_id by scanning existing tickets
                max_existing = 0
                for t in data.get("tickets", []):
                    tid = t.get("id", "")
                    if tid.startswith("TIK-"):
                        try:
                            max_existing = max(max_existing, int(tid[4:]))
                        except ValueError:
                            pass
                safe_next = max(data.get("next_id", 1), max_existing + 1)
                ticket_id = f"TIK-{safe_next:03d}"
                data["next_id"] = safe_next + 1
                ticket = {
                    "id": ticket_id,
                    "created": utcnow_iso(),
                    "source": "watchdog",
                    "priority": priority,
                    "status": "open",
                    "title": title,
                    "description": description,
                    "tags": tags or ["watchdog", "auto-diagnostic"],
                }
                data["tickets"].append(ticket)

                os.lseek(fd, 0, os.SEEK_SET)
                os.ftruncate(fd, 0)
                os.write(fd, json.dumps(data, indent=2).encode())
                log.info(f"Created ticket {ticket_id}: {title}")
                return ticket_id
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
        except Exception as e:
            log.error(f"Failed to create ticket: {e}")
            return None


# ─── AlertManager ────────────────────────────────────────────────────────────

class AlertManager:
    """Send alerts via Telegram and email based on severity."""

    def send_telegram(self, message):
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            log.warning("Telegram not configured, skipping alert")
            return False
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = json.dumps({
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"🐉 WATCHDOG: {message}",
                "parse_mode": "HTML",
            }).encode()
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception as e:
            log.error(f"Telegram alert failed: {e}")
            return False

    def send_email(self, subject, body):
        if not SENDGRID_API_KEY:
            log.warning("SendGrid not configured, skipping email")
            return False
        try:
            result = subprocess.run(
                ["python3", EMAIL_TOOL, "send", ALERT_EMAIL, subject, body],
                capture_output=True, text=True, timeout=15,
                env={**os.environ, "SENDGRID_API_KEY": SENDGRID_API_KEY},
            )
            if result.returncode == 0:
                log.info(f"Email sent: {subject}")
                return True
            else:
                log.error(f"Email failed: {result.stderr}")
                return False
        except Exception as e:
            log.error(f"Email alert failed: {e}")
            return False

    def alert(self, severity, title, description):
        """Send alerts based on severity: warning=ticket only, high=+telegram, critical=+email."""
        if severity == "high":
            self.send_telegram(title)
        elif severity == "critical":
            self.send_telegram(f"🚨 CRITICAL: {title}")
            self.send_email(f"[TIAMAT CRITICAL] {title}", description)


# ─── Detectors ───────────────────────────────────────────────────────────────

class Detection:
    """Result from a detector."""
    def __init__(self, key, severity, title, description):
        self.key = key          # for dedup/cooldown
        self.severity = severity
        self.title = title
        self.description = description
        self.action = None      # optional callable


class Detector:
    """Base class for detection patterns."""
    name = "base"

    def check(self):
        """Return a Detection or None."""
        raise NotImplementedError


class ToolRepetitionDetector(Detector):
    name = "tool_repetition"

    def check(self):
        try:
            conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cutoff = (utcnow() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
            rows = conn.execute(
                "SELECT name, COUNT(*) as cnt FROM tool_calls "
                "WHERE created_at > ? GROUP BY name HAVING cnt >= 5 "
                "ORDER BY cnt DESC",
                (cutoff,)
            ).fetchall()
            conn.close()

            # Tools that are part of normal operation — don't flag unless extreme
            NORMAL_TOOLS = {
                "ticket_list", "ticket_claim", "ticket_complete",  # ticket management
                "exec", "read_file", "write_file",                 # building things
                "browse", "browse_web",                            # browser automation
                "ask_claude_code", "ask_claude_chat",              # AI assistance
                "send_telegram",                                   # status updates
                "post_bluesky", "post_social",                     # social posting
                "grow", "remember", "recall", "reflect",           # learning/memory
                "check_revenue",                                   # routine checks
                "read_farcaster",                                  # social reading
            }

            # Research tools — NEVER flag. TIAMAT is autonomous and researches heavily.
            WHITELIST_TOOLS = {"search_web", "web_fetch"}

            for row in rows:
                tool_name = row["name"]
                count = row["cnt"]

                if tool_name in WHITELIST_TOOLS:
                    continue

                # Normal tools only flagged at 15+ (extreme repetition)
                if tool_name in NORMAL_TOOLS and count < 15:
                    continue

                severity = "critical" if count >= 15 else "high"
                return Detection(
                    key=f"tool_loop_{tool_name}",
                    severity=severity,
                    title=f"Tool loop: {tool_name} called {count}x in 10min",
                    description=(
                        f"Watchdog detected {tool_name} called {count} times in the last "
                        f"10 minutes. This suggests a behavioral loop where TIAMAT is "
                        f"repeating the same action without making progress."
                    ),
                )
        except Exception as e:
            log.error(f"ToolRepetitionDetector error: {e}")
        return None


class ProductivityDetector(Detector):
    name = "productivity"

    def check(self):
        try:
            pacer = safe_json_load(PACER_JSON)
            rate = pacer.get("productivity_rate", 1.0)
            cycles = pacer.get("last_20_cycles", [])

            # Count consecutive unproductive from end
            consecutive_unproductive = 0
            for c in reversed(cycles):
                if not c.get("productive", True):
                    consecutive_unproductive += 1
                else:
                    break

            if rate < 0.3 and consecutive_unproductive >= 5:
                return Detection(
                    key="low_productivity",
                    severity="high",
                    title=f"Low productivity: {rate:.0%} over {consecutive_unproductive} unproductive cycles",
                    description=(
                        f"Watchdog detected productivity rate of {rate:.0%} with "
                        f"{consecutive_unproductive} consecutive unproductive cycles. "
                        f"TIAMAT may be stuck in an ineffective pattern."
                    ),
                )
        except Exception as e:
            log.error(f"ProductivityDetector error: {e}")
        return None


class CostAnomalyDetector(Detector):
    name = "cost_anomaly"

    def check(self):
        try:
            if not os.path.exists(COST_LOG):
                return None

            # Read last 20 lines, filter to routine, take last 5
            with open(COST_LOG, "r") as f:
                lines = f.readlines()

            routine_lines = []
            for line in lines[-20:]:
                line = line.strip()
                if not line:
                    continue
                # Skip CC CLI subscription cycles — logged cost is subscription estimate, not real API spend
                if ",claude-code-cli," in line:
                    continue
                if line.endswith(",routine"):
                    routine_lines.append(line)

            if len(routine_lines) < 5:
                return None

            costs = []
            for line in routine_lines[-5:]:
                parts = line.split(",")
                # format: timestamp,turn,model,input,cache_read,cache_write,output,cost_usd,label
                if len(parts) >= 8:
                    try:
                        costs.append(float(parts[7]))
                    except ValueError:
                        pass

            if len(costs) < 5:
                return None

            avg = sum(costs) / len(costs)
            if avg > 0.025:
                severity = "critical" if avg > 0.05 else "high"
                return Detection(
                    key="cost_anomaly",
                    severity=severity,
                    title=f"Cost anomaly: ${avg:.4f}/cycle avg over last 5 routine cycles",
                    description=(
                        f"Watchdog detected average routine cycle cost of ${avg:.4f}, "
                        f"exceeding the $0.01 threshold. Individual costs: "
                        f"{', '.join(f'${c:.4f}' for c in costs)}."
                    ),
                )
        except Exception as e:
            log.error(f"CostAnomalyDetector error: {e}")
        return None


class StuckTicketDetector(Detector):
    name = "stuck_ticket"

    def check(self):
        try:
            data = safe_json_load(TICKETS_JSON, {"tickets": []})
            now = utcnow()

            for t in data.get("tickets", []):
                if t.get("status") != "in_progress":
                    continue
                started = t.get("started_at")
                if not started:
                    continue

                try:
                    started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    hours = (now - started_dt).total_seconds() / 3600
                except (ValueError, TypeError):
                    continue

                if hours >= 8:
                    tid = t.get("id", "?")
                    title = t.get("title", "?")[:60]
                    return Detection(
                        key=f"stuck_{tid}",
                        severity="warning",
                        title=f"Stuck ticket: {tid} '{title}' in_progress for {hours:.1f}h",
                        description=(
                            f"Ticket {tid} has been in_progress for {hours:.1f} hours "
                            f"(threshold: 3h). It may need human attention or should be "
                            f"closed/re-prioritized."
                        ),
                    )
        except Exception as e:
            log.error(f"StuckTicketDetector error: {e}")
        return None


class ErrorStormDetector(Detector):
    name = "error_storm"

    def check(self):
        try:
            conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
            # Get last 10 turns
            turn_ids = conn.execute(
                "SELECT id FROM turns ORDER BY created_at DESC LIMIT 10"
            ).fetchall()

            if not turn_ids:
                conn.close()
                return None

            placeholders = ",".join("?" for _ in turn_ids)
            ids = [r[0] for r in turn_ids]
            error_count = conn.execute(
                f"SELECT COUNT(*) FROM tool_calls WHERE turn_id IN ({placeholders}) AND error IS NOT NULL AND error != ''",
                ids
            ).fetchone()[0]
            conn.close()

            if error_count >= 3:
                severity = "critical" if error_count >= 8 else "high"
                return Detection(
                    key="error_storm",
                    severity=severity,
                    title=f"Error storm: {error_count} tool failures in last 10 cycles",
                    description=(
                        f"Watchdog detected {error_count} tool call errors in the last "
                        f"10 cycles. TIAMAT may be encountering systemic failures."
                    ),
                )
        except Exception as e:
            log.error(f"ErrorStormDetector error: {e}")
        return None


class ProcessDeathDetector(Detector):
    name = "process_death"

    def check(self):
        try:
            if not os.path.exists(PID_FILE):
                return self._make_detection("PID file missing")

            with open(PID_FILE, "r") as f:
                pid_str = f.read().strip()

            if not pid_str:
                return self._make_detection("PID file empty")

            pid = int(pid_str)
            os.kill(pid, 0)  # signal 0 = check if process exists
            return None  # process is alive

        except ProcessLookupError:
            return self._make_detection(f"PID {pid_str} not running")
        except PermissionError:
            return None  # process exists but we can't signal it (shouldn't happen as root)
        except (ValueError, OSError) as e:
            return self._make_detection(f"PID check failed: {e}")

    def _make_detection(self, reason):
        d = Detection(
            key="process_death",
            severity="critical",
            title="TIAMAT process died — auto-restart attempted",
            description=(
                f"Watchdog detected TIAMAT is not running: {reason}. "
                f"Attempting automatic restart via {START_SCRIPT}."
            ),
        )
        d.action = self._attempt_restart
        return d

    @staticmethod
    def _attempt_restart():
        try:
            log.info("Attempting TIAMAT restart...")
            result = subprocess.run(
                ["bash", START_SCRIPT],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                log.info(f"Restart initiated: {result.stdout.strip()[:200]}")
            else:
                log.error(f"Restart failed: {result.stderr.strip()[:200]}")
        except Exception as e:
            log.error(f"Restart exception: {e}")


class ThoughtLoopDetector(Detector):
    name = "thought_loop"

    def check(self):
        try:
            conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
            rows = conn.execute(
                "SELECT thinking FROM turns ORDER BY created_at DESC LIMIT 5"
            ).fetchall()
            conn.close()

            if len(rows) < 4:
                return None

            texts = [r[0] for r in reversed(rows)]  # oldest first
            similar_pairs = 0
            max_ratio = 0.0

            for i in range(len(texts) - 1):
                if not texts[i] or not texts[i + 1]:
                    continue
                # Truncate to 500 chars for performance
                a = texts[i][:500]
                b = texts[i + 1][:500]
                ratio = difflib.SequenceMatcher(None, a, b).ratio()
                max_ratio = max(max_ratio, ratio)
                if ratio > 0.75:
                    similar_pairs += 1

            if similar_pairs >= 3:
                return Detection(
                    key="thought_loop",
                    severity="high",
                    title=f"Thought loop: thinking text {max_ratio:.0%} similar across {similar_pairs + 1} cycles",
                    description=(
                        f"Watchdog detected {similar_pairs} consecutive pairs of thinking "
                        f"text with >75% similarity (max: {max_ratio:.0%}). TIAMAT appears "
                        f"to be stuck in a cognitive loop, generating nearly identical "
                        f"reasoning each cycle."
                    ),
                )
        except Exception as e:
            log.error(f"ThoughtLoopDetector error: {e}")
        return None


# ─── Main Watchdog ───────────────────────────────────────────────────────────

class Watchdog:
    """Main watchdog loop: load state → run detectors → create tickets → alert → save state."""

    def __init__(self):
        self.state = WatchdogState()
        self.tickets = TicketManager()
        self.alerts = AlertManager()
        self.detectors = [
            ToolRepetitionDetector(),
            ProductivityDetector(),
            CostAnomalyDetector(),
            StuckTicketDetector(),
            ErrorStormDetector(),
            ProcessDeathDetector(),
            ThoughtLoopDetector(),
        ]
        self.running = True

    def run_once(self):
        """Execute one check cycle."""
        detections = []

        for detector in self.detectors:
            try:
                result = detector.check()
                if result:
                    detections.append(result)
            except Exception as e:
                log.error(f"Detector {detector.name} crashed: {e}")

        for d in detections:
            if self.state.is_cooled_down(d.key):
                log.debug(f"Skipping (cooldown): {d.key}")
                continue

            # Execute action if present (e.g., restart)
            if d.action:
                try:
                    d.action()
                except Exception as e:
                    log.error(f"Action failed for {d.key}: {e}")

            # Create ticket
            ticket_id = self.tickets.create_ticket(
                priority=d.severity,
                title=d.title,
                description=d.description,
            )

            if ticket_id:
                # Send alerts based on severity
                self.alerts.alert(d.severity, d.title, d.description)
                self.state.set_cooldown(d.key)
                log.info(f"[{d.severity.upper()}] {d.title}")
            else:
                # Even if ticket was duplicate, still set cooldown to avoid log spam
                self.state.set_cooldown(d.key)

        self.state.prune_cooldowns()
        self.state.save()

        if not detections:
            log.info(f"Check OK — all {len(self.detectors)} detectors clean")
        else:
            log.info(f"Check done — {len(detections)} issue(s) detected")

    def run(self):
        """Main loop."""
        log.info(f"TIAMAT Watchdog started (PID {os.getpid()}, interval {CHECK_INTERVAL}s)")
        log.info(f"Monitoring: {', '.join(d.name for d in self.detectors)}")

        while self.running:
            try:
                self.run_once()
            except Exception as e:
                log.error(f"Check cycle error: {e}")

            # Sleep in small increments so we can respond to signals
            for _ in range(CHECK_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)

        log.info("Watchdog shutting down")


# ─── Entry Point ─────────────────────────────────────────────────────────────

_watchdog = None

def _handle_signal(signum, frame):
    global _watchdog
    log.info(f"Received signal {signum}, shutting down...")
    if _watchdog:
        _watchdog.running = False


def main():
    global _watchdog

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    _watchdog = Watchdog()
    _watchdog.run()


if __name__ == "__main__":
    main()
