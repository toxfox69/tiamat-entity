#!/usr/bin/env python3
"""
TIAMAT Inference Monitoring API v1.0
Tracks inference calls, detects response drift, and alerts on anomalies.

Endpoints:
  POST /monitor/track   — Record an inference call
  GET  /monitor/drift   — Compute response drift scores
  GET  /monitor/stats   — Latency, cost, and drift aggregates
  POST /monitor/alert   — Configure alert thresholds

Runs on port 5002 (port 5001 is occupied by the Memory API).
"""

import json
import os
import hashlib
import sqlite3
import datetime
import threading
import requests
from typing import Optional

import numpy as np
from flask import Flask, request, jsonify
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH       = "/root/.automaton/monitor.db"
CONFIG_PATH   = "/root/.automaton/monitor_config.json"
MODEL_NAME    = "all-MiniLM-L6-v2"
EMBED_DIM     = 384
PORT          = 5003

# Default alert thresholds
DEFAULT_DRIFT_THRESHOLD   = 0.3
DEFAULT_LATENCY_THRESHOLD = 5000.0  # ms

# ── App setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB

# Load embedding model once at startup (model already cached locally)
_model: Optional[SentenceTransformer] = None
_model_lock = threading.Lock()


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = SentenceTransformer(MODEL_NAME)
    return _model


# ── Database ─────────────────────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS inference_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp        TEXT    NOT NULL,
                model_name       TEXT    NOT NULL,
                prompt_hash      TEXT    NOT NULL,
                response_embedding TEXT  NOT NULL,  -- JSON array of floats
                latency_ms       REAL    NOT NULL,
                tokens_used      INTEGER NOT NULL,
                cost_usd         REAL    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_model   ON inference_log (model_name);
            CREATE INDEX IF NOT EXISTS idx_phash   ON inference_log (prompt_hash);
            CREATE INDEX IF NOT EXISTS idx_ts      ON inference_log (timestamp);

            CREATE TABLE IF NOT EXISTS alert_config (
                id                    INTEGER PRIMARY KEY CHECK (id = 1),
                drift_threshold       REAL    NOT NULL DEFAULT 0.3,
                latency_threshold_ms  REAL    NOT NULL DEFAULT 5000.0,
                telegram_chat_id      TEXT,
                email                 TEXT,
                updated_at            TEXT    NOT NULL
            );

            INSERT OR IGNORE INTO alert_config
                (id, drift_threshold, latency_threshold_ms, updated_at)
            VALUES (1, 0.3, 5000.0, datetime('now'));
        """)


# ── Alert helpers ─────────────────────────────────────────────────────────────
def _load_env_token() -> Optional[str]:
    """Read TELEGRAM_BOT_TOKEN from /root/.env without importing dotenv."""
    try:
        with open("/root/.env") as f:
            for line in f:
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def _send_telegram(chat_id: str, text: str) -> None:
    token = _load_env_token()
    if not token:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass


def _get_alert_config() -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM alert_config WHERE id = 1").fetchone()
        if row:
            return dict(row)
    return {
        "drift_threshold": DEFAULT_DRIFT_THRESHOLD,
        "latency_threshold_ms": DEFAULT_LATENCY_THRESHOLD,
        "telegram_chat_id": None,
        "email": None,
    }


def _maybe_alert(model_name: str, latency_ms: float, drift_score: Optional[float]) -> None:
    """Fire alerts if thresholds are breached (non-blocking)."""
    cfg = _get_alert_config()
    msgs = []

    if latency_ms > cfg["latency_threshold_ms"]:
        msgs.append(
            f"*TIAMAT MONITOR — HIGH LATENCY*\n"
            f"Model: `{model_name}`\n"
            f"Latency: `{latency_ms:.0f}ms` (threshold: `{cfg['latency_threshold_ms']:.0f}ms`)"
        )

    if drift_score is not None and drift_score > cfg["drift_threshold"]:
        msgs.append(
            f"*TIAMAT MONITOR — DRIFT DETECTED*\n"
            f"Model: `{model_name}`\n"
            f"Drift score: `{drift_score:.3f}` (threshold: `{cfg['drift_threshold']:.3f}`)"
        )

    if msgs and cfg.get("telegram_chat_id"):
        for msg in msgs:
            threading.Thread(
                target=_send_telegram,
                args=(cfg["telegram_chat_id"], msg),
                daemon=True,
            ).start()


# ── Drift computation ─────────────────────────────────────────────────────────
def _compute_drift_for_hash(conn: sqlite3.Connection, prompt_hash: str, limit: int = 20) -> float:
    """
    For a given prompt_hash, retrieve the last `limit` response embeddings
    and compute pairwise drift as 1 - mean(consecutive cosine similarities).
    Returns 0.0 if fewer than 2 samples.
    """
    rows = conn.execute(
        "SELECT response_embedding FROM inference_log "
        "WHERE prompt_hash = ? ORDER BY id DESC LIMIT ?",
        (prompt_hash, limit),
    ).fetchall()

    if len(rows) < 2:
        return 0.0

    embeddings = np.array([json.loads(r["response_embedding"]) for r in rows])
    # Consecutive cosine similarities
    sims = []
    for i in range(len(embeddings) - 1):
        sim = cosine_similarity(
            embeddings[i].reshape(1, -1),
            embeddings[i + 1].reshape(1, -1),
        )[0][0]
        sims.append(float(sim))

    avg_sim = float(np.mean(sims))
    return round(max(0.0, min(1.0, 1.0 - avg_sim)), 4)


# ══════════════════════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/monitor/track", methods=["POST"])
def track():
    """Record a single inference call."""
    body = request.get_json(silent=True) or {}

    required = ["model_name", "prompt", "response", "latency_ms", "tokens_used", "cost_usd"]
    missing = [k for k in required if k not in body]
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 400

    model_name  = str(body["model_name"])[:128]
    prompt      = str(body["prompt"])
    response    = str(body["response"])
    latency_ms  = float(body["latency_ms"])
    tokens_used = int(body["tokens_used"])
    cost_usd    = float(body["cost_usd"])

    # SHA-256 of the exact prompt text
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

    # Embed the response
    embedding = get_model().encode(response, convert_to_numpy=True).tolist()
    embedding_json = json.dumps(embedding)

    timestamp = datetime.datetime.utcnow().isoformat()

    with get_db() as conn:
        conn.execute(
            "INSERT INTO inference_log "
            "(timestamp, model_name, prompt_hash, response_embedding, latency_ms, tokens_used, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (timestamp, model_name, prompt_hash, embedding_json, latency_ms, tokens_used, cost_usd),
        )

        # Compute drift for this prompt (non-blocking alert check)
        drift = _compute_drift_for_hash(conn, prompt_hash)

    threading.Thread(
        target=_maybe_alert,
        args=(model_name, latency_ms, drift if drift > 0 else None),
        daemon=True,
    ).start()

    return jsonify({
        "ok": True,
        "prompt_hash": prompt_hash,
        "drift_score": drift,
        "timestamp": timestamp,
    }), 201


@app.route("/monitor/drift", methods=["GET"])
def drift():
    """
    Detect response drift across all prompt groups.
    Query params:
      model_name  — filter by model (optional)
      limit       — max prompt groups to analyse (default 50)
    """
    model_filter = request.args.get("model_name")
    limit = min(int(request.args.get("limit", 50)), 200)

    with get_db() as conn:
        if model_filter:
            rows = conn.execute(
                "SELECT DISTINCT prompt_hash FROM inference_log "
                "WHERE model_name = ? LIMIT ?",
                (model_filter, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT prompt_hash FROM inference_log LIMIT ?",
                (limit,),
            ).fetchall()

        results = []
        total_drift = 0.0
        alerted = []

        cfg = _get_alert_config()

        for row in rows:
            ph = row["prompt_hash"]
            score = _compute_drift_for_hash(conn, ph)
            entry = {"prompt_hash": ph, "drift_score": score}

            # How many samples for this hash?
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM inference_log WHERE prompt_hash = ?", (ph,)
            ).fetchone()["n"]
            entry["sample_count"] = count

            if score > cfg["drift_threshold"]:
                entry["alert"] = True
                alerted.append(ph)
            else:
                entry["alert"] = False

            results.append(entry)
            total_drift += score

        avg_drift = round(total_drift / len(results), 4) if results else 0.0

    results.sort(key=lambda x: x["drift_score"], reverse=True)

    return jsonify({
        "ok": True,
        "drift_threshold": cfg["drift_threshold"],
        "prompt_groups_analysed": len(results),
        "average_drift": avg_drift,
        "alerted_hashes": alerted,
        "results": results,
    })


@app.route("/monitor/stats", methods=["GET"])
def stats():
    """Aggregate stats: latency by model, cost by model, recent drift scores."""
    with get_db() as conn:
        # Per-model latency + cost + token aggregates
        model_rows = conn.execute("""
            SELECT
                model_name,
                COUNT(*)              AS call_count,
                AVG(latency_ms)       AS avg_latency_ms,
                MIN(latency_ms)       AS min_latency_ms,
                MAX(latency_ms)       AS max_latency_ms,
                SUM(cost_usd)         AS total_cost_usd,
                SUM(tokens_used)      AS total_tokens,
                AVG(tokens_used)      AS avg_tokens
            FROM inference_log
            GROUP BY model_name
            ORDER BY call_count DESC
        """).fetchall()

        # Last 100 rows for per-request drift (same prompt_hash grouping)
        recent_rows = conn.execute(
            "SELECT id, model_name, prompt_hash, latency_ms, cost_usd, timestamp "
            "FROM inference_log ORDER BY id DESC LIMIT 100"
        ).fetchall()

        # Compute drift per distinct prompt_hash seen in last 100 rows
        recent_hashes = list({r["prompt_hash"] for r in recent_rows})
        drift_map = {ph: _compute_drift_for_hash(conn, ph) for ph in recent_hashes}

        # Overall totals
        totals = conn.execute(
            "SELECT COUNT(*) AS calls, SUM(cost_usd) AS cost, SUM(tokens_used) AS tokens "
            "FROM inference_log"
        ).fetchone()

    by_model = []
    for r in model_rows:
        by_model.append({
            "model_name":      r["model_name"],
            "call_count":      r["call_count"],
            "avg_latency_ms":  round(r["avg_latency_ms"] or 0, 2),
            "min_latency_ms":  round(r["min_latency_ms"] or 0, 2),
            "max_latency_ms":  round(r["max_latency_ms"] or 0, 2),
            "total_cost_usd":  round(r["total_cost_usd"] or 0, 6),
            "total_tokens":    r["total_tokens"] or 0,
            "avg_tokens":      round(r["avg_tokens"] or 0, 1),
        })

    recent_drift = [
        {"prompt_hash": ph, "drift_score": score}
        for ph, score in sorted(drift_map.items(), key=lambda x: -x[1])
    ]

    cfg = _get_alert_config()

    return jsonify({
        "ok": True,
        "totals": {
            "calls":        totals["calls"] or 0,
            "total_cost_usd": round(totals["cost"] or 0, 6),
            "total_tokens": totals["tokens"] or 0,
        },
        "by_model":     by_model,
        "recent_drift": recent_drift,
        "alert_config": {
            "drift_threshold":      cfg["drift_threshold"],
            "latency_threshold_ms": cfg["latency_threshold_ms"],
        },
    })


@app.route("/monitor/alert", methods=["POST"])
def configure_alert():
    """Configure alert thresholds and notification targets."""
    body = request.get_json(silent=True) or {}

    # Validate numeric thresholds when provided
    updates = {}
    if "drift_threshold" in body:
        v = float(body["drift_threshold"])
        if not (0.0 <= v <= 1.0):
            return jsonify({"error": "drift_threshold must be 0.0–1.0"}), 400
        updates["drift_threshold"] = v

    if "latency_threshold_ms" in body:
        v = float(body["latency_threshold_ms"])
        if v <= 0:
            return jsonify({"error": "latency_threshold_ms must be > 0"}), 400
        updates["latency_threshold_ms"] = v

    if "telegram_chat_id" in body:
        updates["telegram_chat_id"] = str(body["telegram_chat_id"])[:64] if body["telegram_chat_id"] else None

    if "email" in body:
        updates["email"] = str(body["email"])[:256] if body["email"] else None

    if not updates:
        return jsonify({"error": "No valid fields provided"}), 400

    updates["updated_at"] = datetime.datetime.utcnow().isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())

    with get_db() as conn:
        conn.execute(
            f"UPDATE alert_config SET {set_clause} WHERE id = 1",
            values,
        )
        row = conn.execute("SELECT * FROM alert_config WHERE id = 1").fetchone()

    return jsonify({
        "ok": True,
        "config": {
            "drift_threshold":      row["drift_threshold"],
            "latency_threshold_ms": row["latency_threshold_ms"],
            "telegram_chat_id":     row["telegram_chat_id"],
            "email":                row["email"],
            "updated_at":           row["updated_at"],
        },
    })


@app.route("/monitor/health", methods=["GET"])
def health():
    model_loaded = _model is not None
    try:
        with get_db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM inference_log").fetchone()[0]
        db_ok = True
    except Exception:
        count = -1
        db_ok = False

    return jsonify({
        "ok": True,
        "db": db_ok,
        "model_loaded": model_loaded,
        "total_records": count,
    })


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    # Warm up model on startup
    get_model()
    app.run(host="127.0.0.1", port=PORT, debug=False)
else:
    # Gunicorn entry point
    init_db()
    get_model()
