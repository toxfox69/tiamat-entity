#!/usr/bin/env python3
"""
TIAMAT Drift Monitor Engine v0.1.0
Pure Python + numpy + sqlite3. No Flask dependency.
Detects when ML model outputs shift from their baseline distribution.
"""

import json
import sqlite3
import urllib.request
from datetime import datetime, timezone

import numpy as np

# ── Constants ─────────────────────────────────────────────────
DRIFT_VERSION = "0.1.0"
MAX_CHECKS_PER_MODEL = 50
DB_PATH = "/root/drift_monitor.db"

VALID_MODEL_TYPES = {"numeric", "embedding", "probability", "text"}

# Default thresholds (score above = alert)
DEFAULT_THRESHOLDS = {
    "numeric": 0.25,      # PSI > 0.25 = significant drift
    "embedding": 0.15,    # Cosine distance > 0.15
    "probability": 0.20,  # KL divergence > 0.20
    "text": 0.20,         # Combined z-score > 0.20
}

# ── Database ──────────────────────────────────────────────────

def _get_conn(db_path=None):
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path=None):
    """Initialize the drift monitor database."""
    conn = _get_conn(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            model_type TEXT NOT NULL,
            owner_ip TEXT NOT NULL DEFAULT '',
            config TEXT NOT NULL DEFAULT '{}',
            baseline_stats TEXT NOT NULL DEFAULT '{}',
            baseline_n INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            score REAL NOT NULL,
            alert INTEGER NOT NULL DEFAULT 0,
            details TEXT NOT NULL DEFAULT '{}',
            sample_n INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (model_id) REFERENCES models(id)
        );

        CREATE INDEX IF NOT EXISTS idx_checks_model_date
            ON checks(model_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id INTEGER NOT NULL,
            check_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            score REAL NOT NULL,
            threshold REAL NOT NULL,
            webhook_url TEXT NOT NULL DEFAULT '',
            webhook_status TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (model_id) REFERENCES models(id),
            FOREIGN KEY (check_id) REFERENCES checks(id)
        );
    """)
    conn.commit()
    conn.close()


# ── Model Registration ────────────────────────────────────────

def register_model(name, model_type, owner_ip="", config=None, db_path=None):
    """Register a new model for drift monitoring. Returns model dict."""
    if model_type not in VALID_MODEL_TYPES:
        raise ValueError(f"Invalid model_type '{model_type}'. Must be one of: {VALID_MODEL_TYPES}")
    if not name or len(name) > 200:
        raise ValueError("Model name must be 1-200 characters")

    now = datetime.now(timezone.utc).isoformat()
    cfg = json.dumps(config or {})

    conn = _get_conn(db_path)
    cur = conn.execute(
        "INSERT INTO models (name, model_type, owner_ip, config, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (name, model_type, owner_ip, cfg, now, now)
    )
    model_id = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
    conn.close()
    return dict(row)


def get_model(model_id, db_path=None):
    """Get a model by ID. Returns dict or None."""
    conn = _get_conn(db_path)
    row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_models(db_path=None):
    """Get all registered models."""
    conn = _get_conn(db_path)
    rows = conn.execute("SELECT * FROM models ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_models_by_ip(ip, db_path=None):
    """Count models registered by a given IP."""
    conn = _get_conn(db_path)
    row = conn.execute("SELECT COUNT(*) as c FROM models WHERE owner_ip=?", (ip,)).fetchone()
    conn.close()
    return row["c"]


# ── Baseline Setting ──────────────────────────────────────────

def set_baseline(model_id, samples, db_path=None):
    """
    Compute and store baseline statistics from sample data.
    samples: list of values (numbers, vectors, probabilities, or strings depending on model_type)
    Returns baseline_stats dict.
    """
    model = get_model(model_id, db_path)
    if not model:
        raise ValueError(f"Model {model_id} not found")

    if len(samples) < 20:
        raise ValueError("Need at least 20 samples for baseline")
    if len(samples) > 10000:
        raise ValueError("Maximum 10,000 samples per call")

    model_type = model["model_type"]
    stats = _compute_baseline(model_type, samples)
    stats["n"] = len(samples)

    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn(db_path)
    conn.execute(
        "UPDATE models SET baseline_stats=?, baseline_n=?, updated_at=? WHERE id=?",
        (json.dumps(stats, cls=_NumpyEncoder), len(samples), now, model_id)
    )
    conn.commit()
    conn.close()

    return stats


def _compute_baseline(model_type, samples):
    """Compute baseline statistics for the given model type."""
    if model_type == "numeric":
        return _baseline_numeric(samples)
    elif model_type == "embedding":
        return _baseline_embedding(samples)
    elif model_type == "probability":
        return _baseline_probability(samples)
    elif model_type == "text":
        return _baseline_text(samples)
    else:
        raise ValueError(f"Unknown model_type: {model_type}")


def _baseline_numeric(samples):
    """PSI baseline: compute 10-bin equal-frequency histogram."""
    arr = np.array(samples, dtype=float)
    # Equal-frequency binning: 10 quantile bins
    quantiles = np.linspace(0, 100, 11)
    bin_edges = np.percentile(arr, quantiles)
    # Ensure unique edges, extend to -inf/+inf to catch outliers
    bin_edges = np.unique(bin_edges)
    if len(bin_edges) < 2:
        bin_edges = np.array([arr.min() - 1, arr.max() + 1])
    bin_edges[0] = -np.inf
    bin_edges[-1] = np.inf
    counts, _ = np.histogram(arr, bins=bin_edges)
    proportions = counts / counts.sum()
    # Replace zeros to avoid log(0)
    proportions = np.clip(proportions, 1e-8, None)
    return {
        "method": "psi",
        "bin_edges": bin_edges.tolist(),
        "proportions": proportions.tolist(),
        "mean": float(arr.mean()),
        "std": float(arr.std()),
    }


def _baseline_embedding(samples):
    """Cosine drift baseline: compute centroid and mean cosine similarity."""
    arr = np.array(samples, dtype=float)
    if arr.ndim != 2:
        raise ValueError("Embedding samples must be 2D (list of vectors)")
    centroid = arr.mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid_unit = centroid / norm
    else:
        centroid_unit = centroid
    # Compute mean cosine similarity to centroid
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.clip(norms, 1e-8, None)
    unit_vecs = arr / norms
    sims = unit_vecs @ centroid_unit
    return {
        "method": "cosine",
        "centroid": centroid.tolist(),
        "mean_similarity": float(sims.mean()),
        "std_similarity": float(sims.std()),
        "dim": int(arr.shape[1]),
    }


def _baseline_probability(samples):
    """Entropy baseline: compute mean entropy and distribution stats."""
    arr = np.array(samples, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    # Compute per-sample entropy
    entropies = []
    for row in arr:
        row_clipped = np.clip(row, 1e-10, 1.0)
        row_clipped = row_clipped / row_clipped.sum()
        h = -np.sum(row_clipped * np.log2(row_clipped))
        entropies.append(h)
    entropies = np.array(entropies)
    # Mean distribution across all samples
    mean_dist = arr.mean(axis=0)
    mean_dist = np.clip(mean_dist, 1e-10, None)
    mean_dist = mean_dist / mean_dist.sum()
    return {
        "method": "entropy",
        "mean_entropy": float(entropies.mean()),
        "std_entropy": float(entropies.std()),
        "mean_distribution": mean_dist.tolist(),
        "n_classes": int(arr.shape[1]),
    }


def _baseline_text(samples):
    """Text stats baseline: length distribution + vocabulary diversity."""
    if not all(isinstance(s, str) for s in samples):
        raise ValueError("Text samples must be strings")
    lengths = np.array([len(s) for s in samples], dtype=float)
    # Vocabulary diversity: unique words / total words per sample
    diversities = []
    for s in samples:
        words = s.lower().split()
        if len(words) == 0:
            diversities.append(0.0)
        else:
            diversities.append(len(set(words)) / len(words))
    diversities = np.array(diversities)
    return {
        "method": "text_stats",
        "length_mean": float(lengths.mean()),
        "length_std": float(lengths.std()) if len(lengths) > 1 else 1.0,
        "diversity_mean": float(diversities.mean()),
        "diversity_std": float(diversities.std()) if len(diversities) > 1 else 0.1,
    }


# ── Drift Checking ────────────────────────────────────────────

def check_drift(model_id, samples, db_path=None):
    """
    Check new samples against baseline. Returns check result dict.
    """
    model = get_model(model_id, db_path)
    if not model:
        raise ValueError(f"Model {model_id} not found")

    baseline_stats = json.loads(model["baseline_stats"]) if model["baseline_stats"] else {}
    if not baseline_stats or baseline_stats == {}:
        raise ValueError(f"Model {model_id} has no baseline. Call set_baseline first.")

    if len(samples) < 5:
        raise ValueError("Need at least 5 samples for drift check")
    if len(samples) > 10000:
        raise ValueError("Maximum 10,000 samples per call")

    model_type = model["model_type"]
    config = json.loads(model["config"]) if model["config"] else {}
    threshold = config.get("threshold", DEFAULT_THRESHOLDS.get(model_type, 0.25))

    result = _compute_drift(model_type, baseline_stats, samples)
    score = result["score"]
    alert = score > threshold

    # Store check
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn(db_path)
    cur = conn.execute(
        "INSERT INTO checks (model_id, method, score, alert, details, sample_n, created_at) VALUES (?,?,?,?,?,?,?)",
        (model_id, result["method"], score, int(alert), json.dumps(result, cls=_NumpyEncoder), len(samples), now)
    )
    check_id = cur.lastrowid

    # Prune old checks
    conn.execute("""
        DELETE FROM checks WHERE model_id=? AND id NOT IN (
            SELECT id FROM checks WHERE model_id=? ORDER BY created_at DESC LIMIT ?
        )
    """, (model_id, model_id, MAX_CHECKS_PER_MODEL))

    # Record alert if triggered
    if alert:
        webhook_url = config.get("webhook_url", "")
        conn.execute(
            "INSERT INTO alerts (model_id, check_id, method, score, threshold, webhook_url, created_at) VALUES (?,?,?,?,?,?,?)",
            (model_id, check_id, result["method"], score, threshold, webhook_url, now)
        )

    conn.commit()
    conn.close()

    # Fire webhook if configured and alert triggered
    webhook_status = ""
    if alert and config.get("webhook_url"):
        webhook_status = trigger_alert(config["webhook_url"], {
            "model_id": model_id,
            "model_name": model["name"],
            "method": result["method"],
            "score": score,
            "threshold": threshold,
            "sample_n": len(samples),
            "timestamp": now,
        })

    return {
        "check_id": check_id,
        "model_id": model_id,
        "method": result["method"],
        "score": round(score, 6),
        "threshold": threshold,
        "alert": alert,
        "details": result,
        "sample_n": len(samples),
        "webhook_status": webhook_status,
        "timestamp": now,
    }


def _compute_drift(model_type, baseline, samples):
    """Compute drift score for the given model type."""
    if model_type == "numeric":
        return _drift_psi(baseline, samples)
    elif model_type == "embedding":
        return _drift_cosine(baseline, samples)
    elif model_type == "probability":
        return _drift_entropy(baseline, samples)
    elif model_type == "text":
        return _drift_text(baseline, samples)
    else:
        raise ValueError(f"Unknown model_type: {model_type}")


def _drift_psi(baseline, samples):
    """Population Stability Index between baseline and new samples."""
    arr = np.array(samples, dtype=float)
    bin_edges = np.array(baseline["bin_edges"], dtype=float)
    # Ensure edges cover all values (handle legacy baselines without inf)
    bin_edges[0] = -np.inf
    bin_edges[-1] = np.inf
    expected = np.array(baseline["proportions"])

    counts, _ = np.histogram(arr, bins=bin_edges)
    actual = counts / max(counts.sum(), 1)
    actual = np.clip(actual, 1e-8, None)
    expected = np.clip(expected, 1e-8, None)

    # PSI = sum((actual - expected) * ln(actual / expected))
    psi = float(np.sum((actual - expected) * np.log(actual / expected)))
    psi = max(0.0, psi)  # PSI is non-negative

    return {
        "method": "psi",
        "score": psi,
        "actual_proportions": actual.tolist(),
        "expected_proportions": expected.tolist(),
        "interpretation": "PSI < 0.1: no drift, 0.1-0.25: moderate, > 0.25: significant",
    }


def _drift_cosine(baseline, samples):
    """Cosine distance drift from baseline centroid."""
    arr = np.array(samples, dtype=float)
    if arr.ndim != 2:
        raise ValueError("Embedding samples must be 2D")

    centroid = np.array(baseline["centroid"])
    centroid_norm = np.linalg.norm(centroid)
    if centroid_norm > 0:
        centroid_unit = centroid / centroid_norm
    else:
        centroid_unit = centroid

    # New centroid
    new_centroid = arr.mean(axis=0)
    new_norm = np.linalg.norm(new_centroid)
    if new_norm > 0:
        new_unit = new_centroid / new_norm
    else:
        new_unit = new_centroid

    # Cosine distance = 1 - cosine_similarity
    cos_sim = float(np.dot(centroid_unit, new_unit))
    cos_sim = max(-1.0, min(1.0, cos_sim))
    drift_score = 1.0 - cos_sim

    # Also compute mean per-sample similarity
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.clip(norms, 1e-8, None)
    unit_vecs = arr / norms
    per_sample_sims = unit_vecs @ centroid_unit
    mean_sim = float(per_sample_sims.mean())

    baseline_mean_sim = baseline.get("mean_similarity", 1.0)
    sim_shift = abs(mean_sim - baseline_mean_sim)

    # Combined score: weighted centroid drift + similarity shift
    score = 0.7 * drift_score + 0.3 * sim_shift

    return {
        "method": "cosine",
        "score": score,
        "centroid_drift": drift_score,
        "cosine_similarity": cos_sim,
        "mean_sample_similarity": mean_sim,
        "baseline_mean_similarity": baseline_mean_sim,
        "interpretation": "Score < 0.05: stable, 0.05-0.15: minor, > 0.15: significant drift",
    }


def _drift_entropy(baseline, samples):
    """Shannon entropy change + KL divergence from baseline distribution."""
    arr = np.array(samples, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)

    # Per-sample entropy
    entropies = []
    for row in arr:
        row_clipped = np.clip(row, 1e-10, 1.0)
        row_clipped = row_clipped / row_clipped.sum()
        h = -np.sum(row_clipped * np.log2(row_clipped))
        entropies.append(h)
    new_entropy = float(np.mean(entropies))

    baseline_entropy = baseline["mean_entropy"]
    entropy_std = max(baseline.get("std_entropy", 0.1), 0.01)
    entropy_zscore = abs(new_entropy - baseline_entropy) / entropy_std

    # KL divergence: D_KL(new || baseline)
    new_dist = arr.mean(axis=0)
    new_dist = np.clip(new_dist, 1e-10, None)
    new_dist = new_dist / new_dist.sum()

    base_dist = np.array(baseline["mean_distribution"])
    base_dist = np.clip(base_dist, 1e-10, None)
    base_dist = base_dist / base_dist.sum()

    kl_div = float(np.sum(new_dist * np.log(new_dist / base_dist)))
    kl_div = max(0.0, kl_div)

    # Combined score
    score = 0.4 * min(entropy_zscore / 3.0, 1.0) + 0.6 * min(kl_div, 1.0)

    return {
        "method": "entropy",
        "score": score,
        "new_entropy": new_entropy,
        "baseline_entropy": baseline_entropy,
        "entropy_zscore": entropy_zscore,
        "kl_divergence": kl_div,
        "interpretation": "Score < 0.1: stable, 0.1-0.2: moderate, > 0.2: significant drift",
    }


def _drift_text(baseline, samples):
    """Text stats drift: length z-score + vocabulary diversity z-score."""
    if not all(isinstance(s, str) for s in samples):
        raise ValueError("Text samples must be strings")

    lengths = np.array([len(s) for s in samples], dtype=float)
    diversities = []
    for s in samples:
        words = s.lower().split()
        if len(words) == 0:
            diversities.append(0.0)
        else:
            diversities.append(len(set(words)) / len(words))
    diversities = np.array(diversities)

    # Length z-score
    length_std = max(baseline.get("length_std", 1.0), 1.0)
    length_z = abs(float(lengths.mean()) - baseline["length_mean"]) / length_std

    # Diversity z-score
    div_std = max(baseline.get("diversity_std", 0.1), 0.01)
    div_z = abs(float(diversities.mean()) - baseline["diversity_mean"]) / div_std

    # Combined score (normalized)
    score = 0.5 * min(length_z / 3.0, 1.0) + 0.5 * min(div_z / 3.0, 1.0)

    return {
        "method": "text_stats",
        "score": score,
        "new_length_mean": float(lengths.mean()),
        "baseline_length_mean": baseline["length_mean"],
        "length_zscore": length_z,
        "new_diversity_mean": float(diversities.mean()),
        "baseline_diversity_mean": baseline["diversity_mean"],
        "diversity_zscore": div_z,
        "interpretation": "Score < 0.1: stable, 0.1-0.2: moderate, > 0.2: significant drift",
    }


# ── Status & History ──────────────────────────────────────────

def get_status(model_id, db_path=None):
    """Get model status with recent check history."""
    model = get_model(model_id, db_path)
    if not model:
        return None

    conn = _get_conn(db_path)
    checks = conn.execute(
        "SELECT * FROM checks WHERE model_id=? ORDER BY created_at DESC LIMIT 20",
        (model_id,)
    ).fetchall()
    alert_count = conn.execute(
        "SELECT COUNT(*) as c FROM alerts WHERE model_id=?",
        (model_id,)
    ).fetchone()["c"]
    conn.close()

    checks_list = [dict(c) for c in checks]

    # ASCII sparkline of recent scores
    scores = [c["score"] for c in reversed(checks_list)]
    sparkline = _ascii_sparkline(scores) if scores else ""

    return {
        "model": model,
        "checks": checks_list,
        "total_checks": len(checks_list),
        "total_alerts": alert_count,
        "sparkline": sparkline,
        "latest_score": checks_list[0]["score"] if checks_list else None,
        "latest_alert": bool(checks_list[0]["alert"]) if checks_list else None,
    }


def _ascii_sparkline(values, width=20):
    """Generate ASCII sparkline from a list of values."""
    if not values:
        return ""
    chars = "▁▂▃▄▅▆▇█"
    mn = min(values)
    mx = max(values)
    rng = mx - mn if mx != mn else 1
    return "".join(chars[min(int((v - mn) / rng * (len(chars) - 1)), len(chars) - 1)] for v in values)


# ── Webhook Alert ─────────────────────────────────────────────

def trigger_alert(webhook_url, payload):
    """Send a POST to the webhook URL with alert payload. Returns status string."""
    if not webhook_url:
        return "no_webhook"
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "TIAMAT-Drift-Monitor/0.1"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return f"sent_{resp.status}"
    except Exception as e:
        return f"failed_{str(e)[:80]}"


# ── Numpy JSON Encoder ────────────────────────────────────────

class _NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)
