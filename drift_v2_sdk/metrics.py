"""
Drift Monitor SDK v2 — Statistical drift metrics

Provides a unified interface for measuring distributional shift between a
reference dataset (baseline) and a current dataset (production window).

Supported metrics
-----------------
- Kolmogorov-Smirnov (KS) test          — distribution-free, continuous
- Kullback-Leibler (KL) divergence       — information-theoretic, binned
- Jensen-Shannon (JS) divergence         — symmetric KL variant
- Wasserstein distance (Earth Mover's)   — geometric, continuous
- Population Stability Index (PSI)       — industry-standard credit-risk metric
- Chi-Squared test                       — categorical / binned distributions

All metric functions return a normalised score in [0, 1] where 0 = no drift
and 1 = maximum drift, plus optional raw statistical values.
"""
from __future__ import annotations

import warnings
from typing import Dict, Optional, Tuple

import numpy as np
from scipy import stats
from scipy.spatial.distance import jensenshannon


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _safe_histogram(
    data: np.ndarray,
    n_bins: int,
    ref_range: Optional[Tuple[float, float]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (density, bin_edges) with a fixed range to keep histograms aligned."""
    if ref_range is None:
        ref_range = (float(np.min(data)), float(np.max(data)))
    lo: float = float(ref_range[0])
    hi: float = float(ref_range[1])
    if lo == hi:
        lo, hi = lo - 1e-6, hi + 1e-6
    counts, edges = np.histogram(data, bins=n_bins, range=(lo, hi))
    density = counts / (counts.sum() + 1e-12)
    return density, edges


def _smooth(p: np.ndarray, eps: float = 1e-10) -> np.ndarray:
    """Add tiny mass to every bin so log-based metrics are well-defined."""
    p = p + eps
    return p / p.sum()


# --------------------------------------------------------------------------- #
#  Individual metric functions                                                 #
# --------------------------------------------------------------------------- #

def kolmogorov_smirnov(
    ref: np.ndarray,
    cur: np.ndarray,
) -> Dict[str, float]:
    """
    Two-sample Kolmogorov-Smirnov test.

    Returns
    -------
    dict with keys:
        score    — KS statistic (0-1), higher = more drift
        p_value  — p-value of the test
        drifted  — True if p < 0.05
    """
    ref = np.asarray(ref, dtype=float).ravel()
    cur = np.asarray(cur, dtype=float).ravel()
    result = stats.ks_2samp(ref, cur)
    ks_stat = float(result.statistic)
    p_value = float(result.pvalue)
    return {
        "score": ks_stat,
        "p_value": p_value,
        "drifted": bool(p_value < 0.05),
    }


def kl_divergence(
    ref: np.ndarray,
    cur: np.ndarray,
    n_bins: int = 50,
) -> Dict[str, float]:
    """
    KL divergence KL(current || reference), binned estimation.

    The raw KL value is mapped to [0, 1] via: score = 1 - exp(-kl).

    Returns
    -------
    dict with keys:
        score    — normalised drift score in [0, 1]
        kl_raw   — raw KL divergence value (nats)
    """
    ref = np.asarray(ref, dtype=float).ravel()
    cur = np.asarray(cur, dtype=float).ravel()
    ref_range = (min(float(ref.min()), float(cur.min())),
                 max(float(ref.max()), float(cur.max())))

    p_ref, _ = _safe_histogram(ref, n_bins, ref_range)
    p_cur, _ = _safe_histogram(cur, n_bins, ref_range)

    p_ref = _smooth(p_ref)
    p_cur = _smooth(p_cur)

    kl_raw = float(np.sum(p_cur * np.log(p_cur / p_ref)))
    score = float(1.0 - np.exp(-kl_raw))
    return {"score": score, "kl_raw": kl_raw}


def jensen_shannon(
    ref: np.ndarray,
    cur: np.ndarray,
    n_bins: int = 50,
) -> Dict[str, float]:
    """
    Jensen-Shannon divergence — symmetric, bounded in [0, 1] (base-2 log).

    Returns
    -------
    dict with keys:
        score    — JS divergence in [0, 1]
        js_dist  — JS distance (sqrt of divergence)
    """
    ref = np.asarray(ref, dtype=float).ravel()
    cur = np.asarray(cur, dtype=float).ravel()
    ref_range = (min(float(ref.min()), float(cur.min())),
                 max(float(ref.max()), float(cur.max())))

    p_ref, _ = _safe_histogram(ref, n_bins, ref_range)
    p_cur, _ = _safe_histogram(cur, n_bins, ref_range)

    p_ref = _smooth(p_ref)
    p_cur = _smooth(p_cur)

    js_dist = float(jensenshannon(p_ref, p_cur, base=2.0))
    js_div = float(js_dist ** 2)
    return {"score": js_div, "js_dist": js_dist}


def wasserstein(
    ref: np.ndarray,
    cur: np.ndarray,
) -> Dict[str, float]:
    """
    Wasserstein-1 (Earth Mover's) distance.

    Raw distance is normalised by the reference standard deviation.
    Clipped to [0, 1].

    Returns
    -------
    dict with keys:
        score    — normalised drift score in [0, 1]
        w1_raw   — raw Wasserstein-1 distance (same units as input)
    """
    ref = np.asarray(ref, dtype=float).ravel()
    cur = np.asarray(cur, dtype=float).ravel()

    w1_raw = float(stats.wasserstein_distance(ref, cur))
    ref_std = float(np.std(ref)) or 1.0
    score = float(min(w1_raw / (ref_std * 3.0), 1.0))
    return {"score": score, "w1_raw": w1_raw}


def population_stability_index(
    ref: np.ndarray,
    cur: np.ndarray,
    n_bins: int = 10,
) -> dict:
    """
    Population Stability Index (PSI).

    Industry convention:
        PSI < 0.10   -> no drift
        0.10-0.25    -> minor drift, monitor
        PSI > 0.25   -> significant drift, action needed

    Returns
    -------
    dict with keys:
        score   — normalised drift score in [0, 1]
        psi_raw — raw PSI value
        band    — "stable" | "minor" | "significant"
    """
    ref = np.asarray(ref, dtype=float).ravel()
    cur = np.asarray(cur, dtype=float).ravel()
    ref_range = (min(float(ref.min()), float(cur.min())),
                 max(float(ref.max()), float(cur.max())))

    p_ref, _ = _safe_histogram(ref, n_bins, ref_range)
    p_cur, _ = _safe_histogram(cur, n_bins, ref_range)

    p_ref = _smooth(p_ref)
    p_cur = _smooth(p_cur)

    psi_raw = float(np.sum((p_cur - p_ref) * np.log(p_cur / p_ref)))
    score = float(min(psi_raw / 0.50, 1.0))

    if psi_raw < 0.10:
        band = "stable"
    elif psi_raw < 0.25:
        band = "minor"
    else:
        band = "significant"

    return {"score": score, "psi_raw": psi_raw, "band": band}


def chi_squared(
    ref: np.ndarray,
    cur: np.ndarray,
    n_bins: int = 20,
) -> Dict[str, float]:
    """
    Chi-squared test on binned distributions.

    Returns
    -------
    dict with keys:
        score       — normalised drift score in [0, 1]
        chi2_stat   — raw chi-squared statistic
        p_value     — p-value of the test
        drifted     — True if p < 0.05
    """
    ref = np.asarray(ref, dtype=float).ravel()
    cur = np.asarray(cur, dtype=float).ravel()
    ref_range = (min(float(ref.min()), float(cur.min())),
                 max(float(ref.max()), float(cur.max())))

    p_ref, _ = _safe_histogram(ref, n_bins, ref_range)
    p_cur, _ = _safe_histogram(cur, n_bins, ref_range)

    n = min(len(ref), len(cur))
    obs = (p_cur * n).astype(float)
    exp = (p_ref * n).astype(float)
    exp = np.where(exp < 1e-8, 1e-8, exp)

    result = stats.chisquare(obs, f_exp=exp)
    chi2_stat = float(result.statistic)
    p_value = float(result.pvalue)
    score = float(min(chi2_stat / 200.0, 1.0))

    return {
        "score": score,
        "chi2_stat": chi2_stat,
        "p_value": p_value,
        "drifted": bool(p_value < 0.05),
    }


# --------------------------------------------------------------------------- #
#  Categorical drift                                                           #
# --------------------------------------------------------------------------- #

def categorical_drift(
    ref_labels: np.ndarray,
    cur_labels: np.ndarray,
) -> dict:
    """
    Measure drift in a categorical distribution (e.g. class predictions).

    Uses Jensen-Shannon divergence on the empirical PMFs.

    Returns
    -------
    dict with keys:
        score        — JS divergence in [0, 1]
        js_dist      — JS distance
        ref_dist     — dict of label->fraction for reference
        cur_dist     — dict of label->fraction for current
    """
    ref_labels = np.asarray(ref_labels).ravel()
    cur_labels = np.asarray(cur_labels).ravel()

    all_labels = np.union1d(np.unique(ref_labels), np.unique(cur_labels))

    def _pmf(arr: np.ndarray) -> np.ndarray:
        counts = np.array([np.sum(arr == lbl) for lbl in all_labels], dtype=float)
        return _smooth(counts / (counts.sum() + 1e-12))

    p_ref = _pmf(ref_labels)
    p_cur = _pmf(cur_labels)

    js_dist = float(jensenshannon(p_ref, p_cur, base=2.0))
    score = float(js_dist ** 2)

    ref_dist = {str(lbl): float(p_ref[i]) for i, lbl in enumerate(all_labels)}
    cur_dist = {str(lbl): float(p_cur[i]) for i, lbl in enumerate(all_labels)}

    return {
        "score": score,
        "js_dist": js_dist,
        "ref_dist": ref_dist,
        "cur_dist": cur_dist,
    }


# --------------------------------------------------------------------------- #
#  Multi-feature dispatcher                                                    #
# --------------------------------------------------------------------------- #

METRIC_FN = {
    "kolmogorov_smirnov": kolmogorov_smirnov,
    "kl_divergence": kl_divergence,
    "jensen_shannon": jensen_shannon,
    "wasserstein": wasserstein,
    "psi": population_stability_index,
    "chi_squared": chi_squared,
}


def compute_feature_drift(
    ref: np.ndarray,
    cur: np.ndarray,
    metrics: list,
    n_bins: int = 50,
    feature_names: Optional[list] = None,
) -> Dict[str, Dict]:
    """
    Compute drift for every feature column using the requested metrics.

    Parameters
    ----------
    ref : ndarray, shape (n_ref, n_features) or (n_ref,)
    cur : ndarray, shape (n_cur, n_features) or (n_cur,)
    metrics : list of DriftMetric enum values
    n_bins : histogram bins for density-based metrics
    feature_names : optional list of column names

    Returns
    -------
    dict keyed by feature name (or "feature_0", "feature_1", ...)
    Each value is a dict: {metric_name: {score, ...extra_fields}}
    """
    ref = np.asarray(ref, dtype=float)
    cur = np.asarray(cur, dtype=float)

    if ref.ndim == 1:
        ref = ref.reshape(-1, 1)
    if cur.ndim == 1:
        cur = cur.reshape(-1, 1)

    n_features = ref.shape[1]
    if feature_names is None:
        feature_names = [f"feature_{i}" for i in range(n_features)]
    elif len(feature_names) != n_features:
        warnings.warn(
            f"feature_names length ({len(feature_names)}) != "
            f"n_features ({n_features}). Using auto-names."
        )
        feature_names = [f"feature_{i}" for i in range(n_features)]

    results: Dict[str, Dict] = {}
    for i, fname in enumerate(feature_names):
        col_ref = ref[:, i]
        col_cur = cur[:, i]
        results[fname] = {}
        for metric in metrics:
            metric_key = metric.value if hasattr(metric, "value") else str(metric)
            fn = METRIC_FN.get(metric_key)
            if fn is None:
                warnings.warn(f"Unknown metric: {metric_key!r} — skipping.")
                continue
            try:
                if metric_key in ("kl_divergence", "jensen_shannon",
                                  "psi", "chi_squared"):
                    results[fname][metric_key] = fn(col_ref, col_cur, n_bins=n_bins)
                else:
                    results[fname][metric_key] = fn(col_ref, col_cur)
            except Exception as exc:  # noqa: BLE001
                results[fname][metric_key] = {"score": 0.0, "error": str(exc)}

    return results
