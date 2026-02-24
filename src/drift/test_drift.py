#!/usr/bin/env python3
"""
Tests for TIAMAT Drift Monitor Engine.
Uses a temp SQLite DB. Tests all 4 model types.
"""

import os
import sys
import tempfile
import numpy as np

# Ensure drift_engine is importable
sys.path.insert(0, os.path.dirname(__file__))
from drift_engine import (
    init_db, register_model, set_baseline, check_drift, get_status, get_all_models,
    DRIFT_VERSION
)

PASS = 0
FAIL = 0

def test(name, condition, details=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} — {details}")


def run_tests():
    global PASS, FAIL
    # Use temp DB
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = tmp.name
    tmp.close()

    try:
        init_db(db)
        print(f"\nDrift Engine v{DRIFT_VERSION} — Test Suite\n{'='*50}")

        # ── Numeric (PSI) ──────────────────────────────────
        print("\n[numeric / PSI]")
        m = register_model("test-numeric", "numeric", "127.0.0.1", db_path=db)
        test("register numeric model", m["id"] > 0)

        # Baseline: normal distribution centered at 50
        np.random.seed(42)
        baseline_samples = np.random.normal(50, 10, 200).tolist()
        stats = set_baseline(m["id"], baseline_samples, db_path=db)
        test("set baseline", stats["method"] == "psi")
        test("baseline has bin_edges", len(stats["bin_edges"]) >= 2)

        # Check same distribution → low drift
        same_samples = np.random.normal(50, 10, 100).tolist()
        result = check_drift(m["id"], same_samples, db_path=db)
        test("same dist = low PSI", result["score"] < 0.15, f"score={result['score']:.4f}")
        test("no alert on same dist", result["alert"] == False)

        # Check shifted distribution → high drift
        shifted_samples = np.random.normal(80, 15, 100).tolist()
        result = check_drift(m["id"], shifted_samples, db_path=db)
        test("shifted dist = high PSI", result["score"] > 0.2, f"score={result['score']:.4f}")
        test("alert on shifted dist", result["alert"] == True)

        # ── Embedding (Cosine) ─────────────────────────────
        print("\n[embedding / Cosine]")
        m2 = register_model("test-embedding", "embedding", "127.0.0.1", db_path=db)
        test("register embedding model", m2["id"] > 0)

        # Baseline: vectors near [1,0,0]
        base_emb = np.random.normal(0, 0.1, (100, 3))
        base_emb[:, 0] += 1.0  # centered around [1, 0, 0]
        stats2 = set_baseline(m2["id"], base_emb.tolist(), db_path=db)
        test("set embedding baseline", stats2["method"] == "cosine")

        # Same direction → low drift
        same_emb = np.random.normal(0, 0.1, (50, 3))
        same_emb[:, 0] += 1.0
        result2 = check_drift(m2["id"], same_emb.tolist(), db_path=db)
        test("same direction = low cosine drift", result2["score"] < 0.1, f"score={result2['score']:.4f}")

        # Shifted direction → high drift
        shifted_emb = np.random.normal(0, 0.1, (50, 3))
        shifted_emb[:, 1] += 1.0  # now centered around [0, 1, 0]
        result2b = check_drift(m2["id"], shifted_emb.tolist(), db_path=db)
        test("shifted direction = high cosine drift", result2b["score"] > 0.1, f"score={result2b['score']:.4f}")

        # ── Probability (Entropy) ──────────────────────────
        print("\n[probability / Entropy]")
        m3 = register_model("test-probability", "probability", "127.0.0.1", db_path=db)

        # Baseline: peaked distributions [0.8, 0.1, 0.1]
        base_probs = []
        for _ in range(100):
            p = np.array([0.8, 0.1, 0.1]) + np.random.normal(0, 0.02, 3)
            p = np.clip(p, 0.01, 1.0)
            p = p / p.sum()
            base_probs.append(p.tolist())
        stats3 = set_baseline(m3["id"], base_probs, db_path=db)
        test("set probability baseline", stats3["method"] == "entropy")

        # Same distribution → low drift
        same_probs = []
        for _ in range(50):
            p = np.array([0.8, 0.1, 0.1]) + np.random.normal(0, 0.02, 3)
            p = np.clip(p, 0.01, 1.0)
            p = p / p.sum()
            same_probs.append(p.tolist())
        result3 = check_drift(m3["id"], same_probs, db_path=db)
        test("same probs = low entropy drift", result3["score"] < 0.15, f"score={result3['score']:.4f}")

        # Shifted to uniform [0.33, 0.33, 0.33] → high drift
        shifted_probs = []
        for _ in range(50):
            p = np.array([0.33, 0.33, 0.34]) + np.random.normal(0, 0.02, 3)
            p = np.clip(p, 0.01, 1.0)
            p = p / p.sum()
            shifted_probs.append(p.tolist())
        result3b = check_drift(m3["id"], shifted_probs, db_path=db)
        test("uniform probs = high entropy drift", result3b["score"] > 0.15, f"score={result3b['score']:.4f}")

        # ── Text (Text Stats) ─────────────────────────────
        print("\n[text / Text Stats]")
        m4 = register_model("test-text", "text", "127.0.0.1", db_path=db)

        # Baseline: medium-length English-like sentences
        base_texts = [f"The quick brown fox jumps over the lazy dog number {i} today" for i in range(50)]
        stats4 = set_baseline(m4["id"], base_texts, db_path=db)
        test("set text baseline", stats4["method"] == "text_stats")

        # Same style → low drift (same template, similar length & vocabulary pattern)
        same_texts = [f"The quick brown fox jumps over the lazy dog number {i + 50} today" for i in range(30)]
        result4 = check_drift(m4["id"], same_texts, db_path=db)
        test("similar text = low drift", result4["score"] < 0.25, f"score={result4['score']:.4f}")

        # Very different text → high drift
        shifted_texts = ["x"] * 30  # extremely short, no diversity
        result4b = check_drift(m4["id"], shifted_texts, db_path=db)
        test("shifted text = high drift", result4b["score"] > 0.2, f"score={result4b['score']:.4f}")

        # ── Status & Utility ──────────────────────────────
        print("\n[status / utility]")
        status = get_status(m["id"], db_path=db)
        test("get_status returns data", status is not None)
        test("status has sparkline", len(status["sparkline"]) > 0)
        test("status has checks", status["total_checks"] > 0)

        all_models = get_all_models(db_path=db)
        test("get_all_models", len(all_models) == 4)

        # ── Summary ────────────────────────────────────────
        print(f"\n{'='*50}")
        print(f"Results: {PASS} passed, {FAIL} failed")
        if FAIL == 0:
            print("ALL TESTS PASSED")
        return FAIL == 0

    finally:
        os.unlink(db)


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
