#!/usr/bin/env python3
"""
Data Scrubber API — Production service.
POST /api/scan — Scan 20 brokers for your data
POST /api/remove — Auto-remove from found brokers
GET /api/job/<id> — Check job status
GET /api/report/<id> — Get scan report
GET / — Web UI

SECURITY: All PII is encrypted at rest and auto-purged after 30 days.
No plaintext PII stored in logs. No PII in error messages.
"""

import asyncio
import json
import os
import sqlite3
import uuid
import hashlib
import base64
import threading
import logging
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify, render_template, send_from_directory
from cryptography.fernet import Fernet

# ── Logging (NO PII in logs) ──
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1MB max

# ── Encryption ──
# Generate or load encryption key (Fernet symmetric)
KEY_FILE = os.path.join(os.path.dirname(__file__), ".scrubber.key")
if os.path.exists(KEY_FILE):
    with open(KEY_FILE, "rb") as f:
        FERNET_KEY = f.read()
else:
    FERNET_KEY = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(FERNET_KEY)
    os.chmod(KEY_FILE, 0o600)

fernet = Fernet(FERNET_KEY)


def encrypt_pii(value: str) -> str:
    """Encrypt a PII string."""
    return fernet.encrypt(value.encode()).decode()


def decrypt_pii(token: str) -> str:
    """Decrypt a PII string."""
    return fernet.decrypt(token.encode()).decode()


def hash_pii(value: str) -> str:
    """One-way hash for lookup (can't reverse)."""
    return hashlib.sha256(value.lower().strip().encode()).hexdigest()[:16]


# ── Database ──
DB_PATH = os.path.join(os.path.dirname(__file__), "scrubber.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,           -- 'scan' or 'remove'
            status TEXT DEFAULT 'queued',  -- queued, running, complete, error
            person_hash TEXT NOT NULL,     -- hashed identifier (non-reversible)
            encrypted_input TEXT NOT NULL, -- Fernet-encrypted JSON of PII
            result TEXT,                   -- JSON result (PII in results also encrypted)
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL       -- auto-purge date
        );

        CREATE TABLE IF NOT EXISTS broker_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            broker_name TEXT NOT NULL,
            found INTEGER DEFAULT 0,       -- was listing found?
            removal_status TEXT,            -- submitted, pending, confirmed, failed
            removal_submitted_at TEXT,
            removal_confirmed_at TEXT,
            data_types_exposed TEXT,        -- what data was visible (encrypted)
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );

        CREATE TABLE IF NOT EXISTS data_lineage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_hash TEXT NOT NULL,
            broker_name TEXT NOT NULL,
            first_seen TEXT NOT NULL,         -- when we first found listing
            removal_requested TEXT,           -- when removal was submitted
            removal_confirmed TEXT,           -- when broker confirmed removal
            re_listed_at TEXT,                -- if broker re-listed after removal
            re_list_count INTEGER DEFAULT 0,  -- how many times re-listed
            last_checked TEXT,
            status TEXT DEFAULT 'found'       -- found, removal_pending, removed, re_listed
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_jobs_expires ON jobs(expires_at);
        CREATE INDEX IF NOT EXISTS idx_tracking_job ON broker_tracking(job_id);
        CREATE INDEX IF NOT EXISTS idx_lineage_person ON data_lineage(person_hash);
    """)
    conn.commit()
    conn.close()


init_db()


# ── Auto-purge expired data ──
def purge_expired():
    """Delete all jobs older than 30 days."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute("SELECT id FROM jobs WHERE expires_at < ?", (now,))
    expired = [row["id"] for row in cursor.fetchall()]
    if expired:
        for job_id in expired:
            conn.execute("DELETE FROM broker_tracking WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM jobs WHERE expires_at < ?", (now,))
        conn.commit()
        logger.info(f"Purged {len(expired)} expired jobs")
    conn.close()


# ── Input validation ──
def validate_scan_input(data):
    """Validate and sanitize scan input. Returns (clean_data, error)."""
    if not data:
        return None, "No JSON body provided"

    required = ["first_name", "last_name", "city", "state"]
    for field in required:
        val = data.get(field, "").strip()
        if not val:
            return None, f"Missing required field: {field}"
        if len(val) > 100:
            return None, f"Field {field} too long (max 100 chars)"
        # Block injection attempts
        if any(c in val for c in "<>{};"):
            return None, f"Invalid characters in {field}"

    clean = {
        "first_name": data["first_name"].strip(),
        "last_name": data["last_name"].strip(),
        "city": data["city"].strip(),
        "state": data["state"].strip().upper()[:2],
        "email": data.get("email", "").strip(),
        "phone": data.get("phone", "").strip(),
    }

    # Email is required for removal but optional for scan
    if clean["email"] and "@" not in clean["email"]:
        return None, "Invalid email format"

    return clean, None


# ── Rate limiting (simple in-memory) ──
_rate_limits = {}


def rate_limit(max_per_hour=10):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            ip = request.remote_addr or "unknown"
            key = f"{f.__name__}:{ip}"
            now = datetime.now(timezone.utc).timestamp()

            if key not in _rate_limits:
                _rate_limits[key] = []

            # Clean old entries
            _rate_limits[key] = [t for t in _rate_limits[key] if now - t < 3600]

            if len(_rate_limits[key]) >= max_per_hour:
                return jsonify({"error": "Rate limit exceeded. Try again later."}), 429

            _rate_limits[key].append(now)
            return f(*args, **kwargs)
        return wrapped
    return decorator


# ── Background worker ──
def run_scan_job(job_id: str):
    """Run scan in background thread."""
    import scanner

    conn = get_db()
    row = conn.execute("SELECT encrypted_input FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return

    conn.execute("UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?",
                 (datetime.now(timezone.utc).isoformat(), job_id))
    conn.commit()

    # Decrypt input
    input_data = json.loads(decrypt_pii(row["encrypted_input"]))

    try:
        # Run the actual scan
        report = asyncio.run(scanner.full_scan(
            first_name=input_data["first_name"],
            last_name=input_data["last_name"],
            city=input_data["city"],
            state=input_data["state"],
            scan_id=job_id,
        ))

        # Encrypt PII in results before storing
        # Keep broker names and found/not-found status unencrypted (not PII)
        safe_report = {
            "scan_id": report["scan_id"],
            "summary": report["summary"],
            "found_on": [],
            "not_found_on": report["not_found_on"],
            "errors": report["errors"],
            "timestamp": report["timestamp"],
        }

        for r in report.get("found_on", []):
            safe_result = {
                "broker_name": r["broker_name"],
                "broker_key": r["broker_key"],
                "found": r["found"],
                "confidence": r["confidence"],
                "url_checked": r["url_checked"],
                "scan_time": r["scan_time"],
                "removal_url": r["removal_url"],
                "removal_method": r["removal_method"],
                "auto_removable": r["auto_removable"],
                "screenshot_path": r.get("screenshot_path"),
            }
            # Encrypt snippet (contains PII)
            if r.get("snippet"):
                safe_result["snippet_encrypted"] = encrypt_pii(r["snippet"])
            safe_report["found_on"].append(safe_result)

        # Track each broker result
        person_hash_val = hash_pii(f"{input_data['first_name']} {input_data['last_name']} {input_data['city']} {input_data['state']}")
        now_ts = datetime.now(timezone.utc).isoformat()
        for r in report.get("all_results", []):
            conn.execute(
                "INSERT INTO broker_tracking (job_id, broker_name, found, removal_status) VALUES (?, ?, ?, ?)",
                (job_id, r["broker_name"], 1 if r["found"] else 0, None),
            )
            # Data lineage tracking — detect re-listings
            if r["found"]:
                existing = conn.execute(
                    "SELECT id, status, removal_confirmed FROM data_lineage WHERE person_hash = ? AND broker_name = ?",
                    (person_hash_val, r["broker_name"]),
                ).fetchone()
                if existing:
                    if existing["status"] == "removed":
                        # RE-LISTED after removal!
                        conn.execute(
                            "UPDATE data_lineage SET status = 're_listed', re_listed_at = ?, "
                            "re_list_count = re_list_count + 1, last_checked = ? WHERE id = ?",
                            (now_ts, now_ts, existing["id"]),
                        )
                    else:
                        conn.execute(
                            "UPDATE data_lineage SET last_checked = ? WHERE id = ?",
                            (now_ts, existing["id"]),
                        )
                else:
                    conn.execute(
                        "INSERT INTO data_lineage (person_hash, broker_name, first_seen, last_checked, status) "
                        "VALUES (?, ?, ?, ?, 'found')",
                        (person_hash_val, r["broker_name"], now_ts, now_ts),
                    )

        conn.execute(
            "UPDATE jobs SET status = 'complete', result = ?, updated_at = ? WHERE id = ?",
            (json.dumps(safe_report), datetime.now(timezone.utc).isoformat(), job_id),
        )
        conn.commit()
        logger.info(f"Job {job_id[:8]}... complete: {report['summary']['brokers_found']} brokers found")

    except Exception as e:
        logger.error(f"Job {job_id[:8]}... failed: {e}")
        conn.execute(
            "UPDATE jobs SET status = 'error', result = ?, updated_at = ? WHERE id = ?",
            (json.dumps({"error": str(e)}), datetime.now(timezone.utc).isoformat(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def run_removal_job(job_id: str):
    """Run removal in background thread."""
    import remover

    conn = get_db()
    row = conn.execute("SELECT encrypted_input, result FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return

    conn.execute("UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?",
                 (datetime.now(timezone.utc).isoformat(), job_id))
    conn.commit()

    input_data = json.loads(decrypt_pii(row["encrypted_input"]))
    scan_result = json.loads(row["result"]) if row["result"] else {}

    # Get list of brokers to remove from
    found_brokers = [r["broker_key"] for r in scan_result.get("found_on", [])]

    if not found_brokers:
        conn.execute(
            "UPDATE jobs SET status = 'complete', result = ?, updated_at = ? WHERE id = ?",
            (json.dumps({"message": "No brokers to remove from", "removals": []}),
             datetime.now(timezone.utc).isoformat(), job_id),
        )
        conn.commit()
        conn.close()
        return

    try:
        results = asyncio.run(remover.remove_from_brokers(
            found_brokers=found_brokers,
            first_name=input_data["first_name"],
            last_name=input_data["last_name"],
            email=input_data.get("email", ""),
            city=input_data.get("city", ""),
            state=input_data.get("state", ""),
            scan_id=job_id,
        ))

        # Update tracking
        for r in results:
            conn.execute(
                "UPDATE broker_tracking SET removal_status = ?, removal_submitted_at = ? "
                "WHERE job_id = ? AND broker_name = ?",
                (r["status"], datetime.now(timezone.utc).isoformat(), job_id, r["broker_name"]),
            )

        # Store result
        conn.execute(
            "UPDATE jobs SET status = 'complete', result = ?, updated_at = ? WHERE id = ?",
            (json.dumps({"removals": results}), datetime.now(timezone.utc).isoformat(), job_id),
        )
        conn.commit()

        submitted = sum(1 for r in results if r["status"] in ("submitted", "pending_email"))
        manual = sum(1 for r in results if r["status"] == "manual_required")
        logger.info(f"Removal {job_id[:8]}...: {submitted} auto-submitted, {manual} manual")

    except Exception as e:
        logger.error(f"Removal {job_id[:8]}... failed: {e}")
        conn.execute(
            "UPDATE jobs SET status = 'error', result = ?, updated_at = ? WHERE id = ?",
            (json.dumps({"error": str(e)}), datetime.now(timezone.utc).isoformat(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


# =============================================================================
# API ROUTES
# =============================================================================

@app.route("/api/scan", methods=["POST"])
@rate_limit(max_per_hour=5)
def start_scan():
    """
    Start a scan job. Returns job ID for polling.
    Input: {"first_name": "...", "last_name": "...", "city": "...", "state": "...", "email": "..."}
    """
    data, error = validate_scan_input(request.get_json(silent=True))
    if error:
        return jsonify({"error": error}), 400

    # Purge old data
    purge_expired()

    job_id = str(uuid.uuid4())
    person_hash = hash_pii(f"{data['first_name']} {data['last_name']} {data['city']} {data['state']}")
    encrypted_input = encrypt_pii(json.dumps(data))

    now = datetime.now(timezone.utc).isoformat()
    expires = datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()  # 30-day purge handled by cron
    from datetime import timedelta
    expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    conn = get_db()
    conn.execute(
        "INSERT INTO jobs (id, type, status, person_hash, encrypted_input, created_at, updated_at, expires_at) "
        "VALUES (?, 'scan', 'queued', ?, ?, ?, ?, ?)",
        (job_id, person_hash, encrypted_input, now, now, expires),
    )
    conn.commit()
    conn.close()

    # Start scan in background
    thread = threading.Thread(target=run_scan_job, args=(job_id,), daemon=True)
    thread.start()

    logger.info(f"Scan queued: {job_id[:8]}...")
    return jsonify({
        "job_id": job_id,
        "status": "queued",
        "message": "Scan started. Poll GET /api/job/<job_id> for results.",
        "estimated_time": "2-5 minutes for 20 brokers",
    }), 202


@app.route("/api/remove", methods=["POST"])
@rate_limit(max_per_hour=3)
def start_removal():
    """
    Start removal for a completed scan.
    Input: {"scan_job_id": "...", "email": "..."}
    Email is required for removal (brokers send confirmation there).
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No JSON body"}), 400

    scan_job_id = data.get("scan_job_id", "").strip()
    email = data.get("email", "").strip()

    if not scan_job_id:
        return jsonify({"error": "Missing scan_job_id"}), 400
    if not email or "@" not in email:
        return jsonify({"error": "Valid email required for removal (brokers send confirmation there)"}), 400

    # Get scan job
    conn = get_db()
    scan_job = conn.execute("SELECT * FROM jobs WHERE id = ? AND type = 'scan'", (scan_job_id,)).fetchone()
    if not scan_job:
        conn.close()
        return jsonify({"error": "Scan job not found"}), 404
    if scan_job["status"] != "complete":
        conn.close()
        return jsonify({"error": f"Scan not complete (status: {scan_job['status']})"}), 400

    # Create removal job with scan results + email
    input_data = json.loads(decrypt_pii(scan_job["encrypted_input"]))
    input_data["email"] = email

    # Merge user-reported brokers (from manual checks) into scan results
    user_reported = data.get("user_reported", [])
    scan_result = json.loads(scan_job["result"]) if scan_job["result"] else {}
    if user_reported:
        from brokers import BROKERS
        existing_keys = {r["broker_key"] for r in scan_result.get("found_on", [])}
        for bkey in user_reported:
            if bkey not in existing_keys and bkey in BROKERS:
                broker = BROKERS[bkey]
                scan_result.setdefault("found_on", []).append({
                    "broker_name": broker["name"],
                    "broker_key": bkey,
                    "found": True,
                    "confidence": 1.0,
                    "url_checked": "",
                    "scan_time": 0,
                    "removal_url": broker["removal"]["url"],
                    "removal_method": broker["removal"]["method"],
                    "auto_removable": broker["removal"].get("auto_possible", False),
                    "user_reported": True,
                })

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    from datetime import timedelta
    expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    conn.execute(
        "INSERT INTO jobs (id, type, status, person_hash, encrypted_input, result, created_at, updated_at, expires_at) "
        "VALUES (?, 'remove', 'queued', ?, ?, ?, ?, ?, ?)",
        (job_id, scan_job["person_hash"], encrypt_pii(json.dumps(input_data)),
         json.dumps(scan_result), now, now, expires),
    )
    conn.commit()
    conn.close()

    # Start removal in background
    thread = threading.Thread(target=run_removal_job, args=(job_id,), daemon=True)
    thread.start()

    logger.info(f"Removal queued: {job_id[:8]}...")
    return jsonify({
        "job_id": job_id,
        "status": "queued",
        "message": "Removal started. This may take several minutes.",
    }), 202


@app.route("/api/job/<job_id>", methods=["GET"])
def get_job(job_id):
    """Get job status and results."""
    conn = get_db()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        conn.close()
        return jsonify({"error": "Job not found"}), 404

    response = {
        "job_id": job["id"],
        "type": job["type"],
        "status": job["status"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }

    if job["status"] == "complete" and job["result"]:
        response["result"] = json.loads(job["result"])

    # Get broker tracking
    tracking = conn.execute(
        "SELECT * FROM broker_tracking WHERE job_id = ?", (job_id,)
    ).fetchall()
    if tracking:
        response["broker_details"] = [
            {
                "broker": t["broker_name"],
                "found": bool(t["found"]),
                "removal_status": t["removal_status"],
                "removal_submitted_at": t["removal_submitted_at"],
            }
            for t in tracking
        ]

    conn.close()
    return jsonify(response)


@app.route("/api/report/<job_id>", methods=["GET"])
def get_report(job_id):
    """
    Get detailed report showing which brokers have your data,
    what they expose, and removal status.
    """
    conn = get_db()
    job = conn.execute("SELECT * FROM jobs WHERE id = ? AND type = 'scan'", (job_id,)).fetchone()
    if not job:
        conn.close()
        return jsonify({"error": "Scan job not found"}), 404

    if job["status"] != "complete":
        conn.close()
        return jsonify({"error": f"Scan not complete (status: {job['status']})"}), 400

    result = json.loads(job["result"])

    # Get removal status
    tracking = conn.execute(
        "SELECT * FROM broker_tracking WHERE job_id = ?", (job_id,)
    ).fetchall()

    # Build data exposure map
    exposure_map = {}
    for t in tracking:
        if t["found"]:
            exposure_map[t["broker_name"]] = {
                "found": True,
                "removal_status": t["removal_status"] or "not_started",
                "removal_submitted_at": t["removal_submitted_at"],
            }

    report = {
        "scan_id": job_id,
        "status": job["status"],
        "summary": result.get("summary", {}),
        "exposure": {
            "total_brokers_scanned": result["summary"]["brokers_scanned"],
            "brokers_with_your_data": result["summary"]["brokers_found"],
            "auto_removable": result["summary"].get("auto_removable", 0),
            "manual_removal_needed": result["summary"]["brokers_found"] - result["summary"].get("auto_removable", 0),
        },
        "brokers_found": [
            {
                "name": r["broker_name"],
                "key": r["broker_key"],
                "confidence": r["confidence"],
                "removal_url": r["removal_url"],
                "removal_method": r["removal_method"],
                "auto_removable": r["auto_removable"],
                "removal_status": exposure_map.get(r["broker_name"], {}).get("removal_status", "not_started"),
            }
            for r in result.get("found_on", [])
        ],
        "brokers_clear": result.get("not_found_on", []),
        "errors": result.get("errors", []),
        "scanned_at": result.get("timestamp"),
    }

    conn.close()
    return jsonify(report)


@app.route("/api/status", methods=["GET"])
def api_status():
    """Service status."""
    from brokers import BROKERS
    conn = get_db()
    total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    active_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')").fetchone()[0]
    conn.close()

    return jsonify({
        "service": "TIAMAT Data Scrubber",
        "status": "online",
        "brokers_covered": len(BROKERS),
        "broker_list": sorted([b["name"] for b in BROKERS.values()]),
        "total_jobs_processed": total_jobs,
        "active_jobs": active_jobs,
        "security": {
            "pii_encryption": "AES-128 (Fernet)",
            "data_retention": "30 days auto-purge",
            "logging": "No PII in logs",
        },
    })


@app.route("/api/lineage/<job_id>", methods=["GET"])
def get_lineage(job_id):
    """
    Data lineage report — shows which brokers have had your data,
    when it was found, when removal was requested, and if they re-listed you.
    This is how you track who keeps selling/re-sharing your data.
    """
    conn = get_db()
    job = conn.execute("SELECT person_hash FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        conn.close()
        return jsonify({"error": "Job not found"}), 404

    lineage = conn.execute(
        "SELECT * FROM data_lineage WHERE person_hash = ? ORDER BY first_seen",
        (job["person_hash"],),
    ).fetchall()

    if not lineage:
        conn.close()
        return jsonify({"message": "No data lineage recorded yet. Run a scan first.", "brokers": []})

    brokers = []
    re_listers = []
    for row in lineage:
        entry = {
            "broker": row["broker_name"],
            "status": row["status"],
            "first_seen": row["first_seen"],
            "removal_requested": row["removal_requested"],
            "removal_confirmed": row["removal_confirmed"],
            "re_listed_at": row["re_listed_at"],
            "re_list_count": row["re_list_count"],
            "last_checked": row["last_checked"],
        }
        brokers.append(entry)
        if row["re_list_count"] > 0:
            re_listers.append({
                "broker": row["broker_name"],
                "times_re_listed": row["re_list_count"],
                "last_re_listed": row["re_listed_at"],
            })

    conn.close()
    return jsonify({
        "lineage": brokers,
        "re_listers": re_listers,
        "summary": {
            "total_brokers_tracked": len(brokers),
            "currently_listed": sum(1 for b in brokers if b["status"] in ("found", "re_listed")),
            "removed": sum(1 for b in brokers if b["status"] == "removed"),
            "re_listed_after_removal": len(re_listers),
        },
        "note": "Re-scan periodically to detect brokers that re-list your data after removal.",
    })


@app.route("/api/breach/password", methods=["POST"])
@rate_limit(max_per_hour=20)
def check_password_breach():
    """
    Check if a password has been in known data breaches.
    Uses HIBP k-anonymity — password never leaves server, only partial hash sent to HIBP.
    Input: {"password": "..."}
    """
    data = request.get_json(silent=True)
    if not data or not data.get("password"):
        return jsonify({"error": "Missing password field"}), 400

    from breach_check import check_password
    result = check_password(data["password"])
    # Never log or store the password
    return jsonify(result)


@app.route("/api/breach/email", methods=["POST"])
@rate_limit(max_per_hour=10)
def check_email_breach():
    """
    Check if an email has been in known data breaches.
    Without HIBP API key: returns link to check manually.
    With HIBP API key: returns full breach list.
    Input: {"email": "..."}
    """
    data = request.get_json(silent=True)
    if not data or not data.get("email"):
        return jsonify({"error": "Missing email field"}), 400

    email = data["email"].strip()
    if "@" not in email:
        return jsonify({"error": "Invalid email"}), 400

    from breach_check import check_email_breaches
    hibp_key = os.environ.get("HIBP_API_KEY", "")
    result = check_email_breaches(email, api_key=hibp_key or None)
    return jsonify(result)


@app.route("/api/delete/<job_id>", methods=["DELETE"])
def delete_job(job_id):
    """Immediately delete all data for a job (user-initiated purge)."""
    conn = get_db()
    job = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        conn.close()
        return jsonify({"error": "Job not found"}), 404

    conn.execute("DELETE FROM broker_tracking WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    # Delete screenshots
    import glob
    for f in glob.glob(os.path.join(os.path.dirname(__file__), "screenshots", f"{job_id}_*")):
        try:
            os.remove(f)
        except:
            pass

    return jsonify({"message": "All data for this job has been permanently deleted."})


# ── Web UI ──

@app.route("/")
def index():
    """Web UI."""
    return render_template("index.html")


@app.route("/screenshots/<path:filename>")
def serve_screenshot(filename):
    """Serve screenshot proof images."""
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), "screenshots"),
        filename,
    )


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("SCRUBBER_PORT", 5006))
    logger.info(f"Starting TIAMAT Data Scrubber on port {port}")
    logger.info(f"PII encryption: enabled (Fernet)")
    logger.info(f"Data retention: 30 days")
    app.run(host="127.0.0.1", port=port, debug=False)
