"""
Drift Monitor SDK v2 — Test Suite
==================================
Run with pytest from the drift_v2_sdk directory:
    pytest tests/ -v

Requirements: numpy, scipy, pytest
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from config import AlertConfig, DriftConfig, DriftMetric, ModelType, TaskType
from metrics import (
    categorical_drift,
    chi_squared,
    compute_feature_drift,
    jensen_shannon,
    kl_divergence,
    kolmogorov_smirnov,
    population_stability_index,
    wasserstein,
)
from drift_monitor import DriftMonitor, DriftReport


# --------------------------------------------------------------------------- #
#  Fixtures                                                                    #
# --------------------------------------------------------------------------- #

@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(0)


@pytest.fixture
def ref_data(rng: np.random.Generator):
    """200-sample reference dataset, 4 features."""
    X = rng.normal(0.0, 1.0, size=(200, 4)).astype(np.float32)
    y = (rng.random(200) > 0.7).astype(int)
    return X, y


@pytest.fixture
def cur_data_clean(rng: np.random.Generator):
    """100-sample current dataset from the same distribution."""
    X = rng.normal(0.0, 1.0, size=(100, 4)).astype(np.float32)
    y = (rng.random(100) > 0.7).astype(int)
    return X, y


@pytest.fixture
def cur_data_drifted(rng: np.random.Generator):
    """100-sample current dataset with heavy drift (mean +3)."""
    X = rng.normal(3.0, 1.5, size=(100, 4)).astype(np.float32)
    y = (rng.random(100) > 0.1).astype(int)  # 90% class-1
    return X, y


@pytest.fixture
def basic_config() -> DriftConfig:
    return DriftConfig(
        model_name="test_model",
        drift_threshold=0.75,
        feature_metrics=[DriftMetric.KOLMOGOROV_SMIRNOV, DriftMetric.JENSEN_SHANNON],
        output_metric=DriftMetric.JENSEN_SHANNON,
        enable_dashboard=False,  # No network calls in tests
        min_reference_samples=50,
    )


# --------------------------------------------------------------------------- #
#  Config tests                                                                #
# --------------------------------------------------------------------------- #

class TestDriftConfig:
    def test_default_construction(self):
        cfg = DriftConfig()
        assert cfg.model_name == "unnamed_model"
        assert 0.0 < cfg.drift_threshold <= 1.0

    def test_invalid_threshold_raises(self):
        with pytest.raises(ValueError, match="drift_threshold"):
            DriftConfig(drift_threshold=0.0)

        with pytest.raises(ValueError, match="drift_threshold"):
            DriftConfig(drift_threshold=1.5)

    def test_slack_without_url_raises(self, monkeypatch):
        monkeypatch.delenv("DRIFT_SLACK_WEBHOOK", raising=False)
        with pytest.raises(ValueError, match="slack_webhook"):
            DriftConfig(enable_slack=True)

    def test_webhook_without_url_raises(self, monkeypatch):
        monkeypatch.delenv("DRIFT_WEBHOOK_URL", raising=False)
        with pytest.raises(ValueError, match="webhook_url"):
            DriftConfig(enable_webhook=True)

    def test_severity_mapping(self):
        cfg = DriftConfig()
        assert cfg.severity(0.10) == "NONE"
        assert cfg.severity(0.55) == "LOW"
        assert cfg.severity(0.75) == "MEDIUM"
        assert cfg.severity(0.88) == "HIGH"
        assert cfg.severity(0.97) == "CRITICAL"

    def test_custom_alert_config(self):
        cfg = DriftConfig(alert=AlertConfig(
            low_threshold=0.2,
            medium_threshold=0.4,
            high_threshold=0.6,
            critical_threshold=0.8,
        ))
        assert cfg.severity(0.15) == "NONE"
        assert cfg.severity(0.30) == "LOW"
        assert cfg.severity(0.50) == "MEDIUM"
        assert cfg.severity(0.70) == "HIGH"
        assert cfg.severity(0.90) == "CRITICAL"


# --------------------------------------------------------------------------- #
#  Metrics tests                                                               #
# --------------------------------------------------------------------------- #

class TestKolmogorovSmirnov:
    def test_identical_distributions(self, rng):
        data = rng.normal(0, 1, 500)
        result = kolmogorov_smirnov(data, data)
        assert result["score"] == 0.0
        assert result["p_value"] == 1.0
        assert not result["drifted"]

    def test_well_separated_distributions(self, rng):
        ref = rng.normal(0.0, 1.0, 500)
        cur = rng.normal(5.0, 1.0, 500)
        result = kolmogorov_smirnov(ref, cur)
        assert result["score"] > 0.8, "KS stat should be high for clearly separated distributions"
        assert result["drifted"]

    def test_score_bounded(self, rng):
        ref = rng.normal(0, 1, 200)
        cur = rng.normal(2, 1, 200)
        result = kolmogorov_smirnov(ref, cur)
        assert 0.0 <= result["score"] <= 1.0

    def test_accepts_2d_input(self, rng):
        ref = rng.normal(0, 1, (200, 1))
        cur = rng.normal(1, 1, (200, 1))
        result = kolmogorov_smirnov(ref, cur)
        assert 0.0 <= result["score"] <= 1.0


class TestKLDivergence:
    def test_same_distribution_near_zero(self, rng):
        data = rng.normal(0, 1, 1000)
        result = kl_divergence(data, data)
        assert result["score"] < 0.05

    def test_different_distribution_high_score(self, rng):
        ref = rng.normal(0, 1, 1000)
        cur = rng.normal(4, 0.5, 1000)
        result = kl_divergence(ref, cur)
        assert result["score"] > 0.5

    def test_score_in_unit_interval(self, rng):
        ref = rng.normal(0, 1, 500)
        cur = rng.exponential(1.0, 500)
        result = kl_divergence(ref, cur)
        assert 0.0 <= result["score"] <= 1.0

    def test_kl_raw_is_nonnegative(self, rng):
        ref = rng.normal(0, 1, 500)
        cur = rng.normal(1, 1, 500)
        result = kl_divergence(ref, cur)
        assert result["kl_raw"] >= 0.0


class TestJensenShannon:
    def test_same_distribution_zero(self, rng):
        data = rng.normal(0, 1, 500)
        result = jensen_shannon(data, data)
        assert result["score"] < 0.01

    def test_symmetry(self, rng):
        ref = rng.normal(0, 1, 500)
        cur = rng.normal(3, 1, 500)
        r1 = jensen_shannon(ref, cur)
        r2 = jensen_shannon(cur, ref)
        assert abs(r1["score"] - r2["score"]) < 0.05

    def test_bounded(self, rng):
        ref = rng.normal(0, 1, 500)
        cur = rng.normal(10, 1, 500)
        result = jensen_shannon(ref, cur)
        assert 0.0 <= result["score"] <= 1.0


class TestWasserstein:
    def test_same_distribution(self, rng):
        data = rng.normal(0, 1, 500)
        result = wasserstein(data, data)
        assert result["score"] < 0.05
        assert result["w1_raw"] < 0.1

    def test_large_shift(self, rng):
        ref = rng.normal(0, 1, 500)
        cur = rng.normal(10, 1, 500)
        result = wasserstein(ref, cur)
        assert result["score"] > 0.5

    def test_raw_units(self, rng):
        ref = rng.normal(0, 1, 500)
        cur = rng.normal(1, 1, 500)
        result = wasserstein(ref, cur)
        assert result["w1_raw"] > 0.0


class TestPSI:
    def test_stable(self, rng):
        data = rng.normal(0, 1, 1000)
        result = population_stability_index(data, data)
        assert result["band"] == "stable"
        assert result["psi_raw"] < 0.10

    def test_significant_drift(self, rng):
        ref = rng.normal(0, 1, 1000)
        cur = rng.normal(4, 1, 1000)
        result = population_stability_index(ref, cur)
        assert result["band"] == "significant"
        assert result["psi_raw"] > 0.25


class TestChiSquared:
    def test_same_distribution(self, rng):
        data = rng.normal(0, 1, 500)
        result = chi_squared(data, data)
        assert result["p_value"] > 0.05
        assert not result["drifted"]

    def test_very_different_distributions(self, rng):
        ref = rng.normal(0, 1, 1000)
        cur = rng.normal(5, 0.5, 1000)
        result = chi_squared(ref, cur)
        assert result["chi2_stat"] > 10.0


class TestCategoricalDrift:
    def test_same_distribution(self):
        labels = np.array([0, 1, 2, 0, 1, 2, 0, 1, 2] * 50)
        result = categorical_drift(labels, labels)
        assert result["score"] < 0.05

    def test_class_imbalance_detected(self):
        ref = np.array([0, 1] * 200)           # 50/50
        cur = np.array([0] * 10 + [1] * 190)   # heavily imbalanced
        result = categorical_drift(ref, cur)
        assert result["score"] > 0.1

    def test_ref_and_cur_dist_sum_to_one(self):
        ref = np.array([0, 1, 2] * 100)
        cur = np.array([0, 1, 2, 0, 1] * 60)
        result = categorical_drift(ref, cur)
        ref_sum = sum(result["ref_dist"].values())
        cur_sum = sum(result["cur_dist"].values())
        assert abs(ref_sum - 1.0) < 0.01
        assert abs(cur_sum - 1.0) < 0.01


class TestComputeFeatureDrift:
    def test_basic(self, rng):
        ref = rng.normal(0, 1, (200, 3))
        cur = rng.normal(0, 1, (100, 3))
        results = compute_feature_drift(
            ref, cur,
            metrics=[DriftMetric.KOLMOGOROV_SMIRNOV],
            feature_names=["a", "b", "c"],
        )
        assert set(results.keys()) == {"a", "b", "c"}
        for fname, metric_res in results.items():
            assert "kolmogorov_smirnov" in metric_res
            assert 0.0 <= metric_res["kolmogorov_smirnov"]["score"] <= 1.0

    def test_1d_input(self, rng):
        ref = rng.normal(0, 1, 200)
        cur = rng.normal(2, 1, 100)
        results = compute_feature_drift(ref, cur, metrics=[DriftMetric.KL_DIVERGENCE])
        assert "feature_0" in results

    def test_auto_names_when_none(self, rng):
        ref = rng.normal(0, 1, (200, 5))
        cur = rng.normal(0, 1, (100, 5))
        results = compute_feature_drift(ref, cur, metrics=[DriftMetric.KOLMOGOROV_SMIRNOV])
        for i in range(5):
            assert f"feature_{i}" in results

    def test_multiple_metrics(self, rng):
        ref = rng.normal(0, 1, (200, 2))
        cur = rng.normal(1, 1, (100, 2))
        results = compute_feature_drift(
            ref, cur,
            metrics=[DriftMetric.KOLMOGOROV_SMIRNOV, DriftMetric.JENSEN_SHANNON],
        )
        for fname in results:
            assert "kolmogorov_smirnov" in results[fname]
            assert "jensen_shannon" in results[fname]


# --------------------------------------------------------------------------- #
#  DriftMonitor integration tests                                             #
# --------------------------------------------------------------------------- #

class TestDriftMonitor:
    def test_requires_reference_before_check(self, basic_config):
        monitor = DriftMonitor(config=basic_config)
        X = np.random.randn(50, 4)
        with pytest.raises(RuntimeError, match="No reference data"):
            monitor.check_drift(X)

    def test_minimum_reference_samples_enforced(self, basic_config):
        monitor = DriftMonitor(config=basic_config)
        X_small = np.random.randn(10, 4)  # < min_reference_samples=50
        with pytest.raises(ValueError, match="50"):
            monitor.track_reference(X_small)

    def test_no_drift_scenario(self, basic_config, ref_data, cur_data_clean):
        X_ref, y_ref = ref_data
        X_cur, y_cur = cur_data_clean
        monitor = DriftMonitor(config=basic_config)
        monitor.track_reference(X_ref, y_ref)
        report = monitor.check_drift(X_cur, y_cur, send_notifications=False)

        assert isinstance(report, DriftReport)
        assert 0.0 <= report.drift_score <= 1.0
        assert report.severity in ("NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert report.drift_score < basic_config.drift_threshold  # should be low
        assert not report.alert

    def test_drift_detected_scenario(self, ref_data, cur_data_drifted, cur_data_clean):
        """Drifted data must score significantly higher than clean data."""
        # Use a low threshold so composite drift (feature + output averaged) fires
        cfg = DriftConfig(
            model_name="test_model",
            drift_threshold=0.40,
            feature_metrics=[DriftMetric.KOLMOGOROV_SMIRNOV, DriftMetric.JENSEN_SHANNON],
            enable_dashboard=False,
            min_reference_samples=50,
        )
        X_ref, y_ref = ref_data
        X_cur_drifted, y_cur_drifted = cur_data_drifted
        X_cur_clean, y_cur_clean = cur_data_clean

        monitor = DriftMonitor(config=cfg)
        monitor.track_reference(X_ref, y_ref)

        report_drift = monitor.check_drift(X_cur_drifted, y_cur_drifted, send_notifications=False)
        report_clean = monitor.check_drift(X_cur_clean, y_cur_clean, send_notifications=False)

        # Drifted data must score higher than clean data
        assert report_drift.drift_score > report_clean.drift_score
        # Drift should be statistically meaningful (>0.35 for a 3-sigma mean shift)
        assert report_drift.drift_score > 0.35
        # Alert should fire at 0.40 threshold for a 3-sigma shift
        assert report_drift.alert
        assert report_drift.severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    def test_report_has_feature_scores(self, basic_config, ref_data, cur_data_drifted):
        X_ref, y_ref = ref_data
        X_cur, y_cur = cur_data_drifted
        monitor = DriftMonitor(config=basic_config)
        monitor.track_reference(X_ref, y_ref)
        report = monitor.check_drift(X_cur, y_cur, send_notifications=False)

        assert len(report.feature_scores) == 4  # 4 features
        for score in report.feature_scores.values():
            assert 0.0 <= score <= 1.0

    def test_report_has_recommendations(self, basic_config, ref_data, cur_data_drifted):
        X_ref, y_ref = ref_data
        X_cur, y_cur = cur_data_drifted
        monitor = DriftMonitor(config=basic_config)
        monitor.track_reference(X_ref, y_ref)
        report = monitor.check_drift(X_cur, y_cur, send_notifications=False)

        assert len(report.recommendations) > 0
        assert all(isinstance(r, str) for r in report.recommendations)

    def test_history_accumulates(self, basic_config, ref_data, cur_data_clean):
        X_ref, y_ref = ref_data
        X_cur, y_cur = cur_data_clean
        monitor = DriftMonitor(config=basic_config)
        monitor.track_reference(X_ref, y_ref)

        for _ in range(3):
            monitor.check_drift(X_cur, y_cur, send_notifications=False)

        assert len(monitor.history) == 3

    def test_summary(self, basic_config, ref_data, cur_data_clean, cur_data_drifted):
        X_ref, y_ref = ref_data
        monitor = DriftMonitor(config=basic_config)
        monitor.track_reference(X_ref, y_ref)
        monitor.check_drift(cur_data_clean[0], cur_data_clean[1], send_notifications=False)
        monitor.check_drift(cur_data_drifted[0], cur_data_drifted[1], send_notifications=False)

        summary = monitor.summary()
        assert summary["checks"] == 2
        assert "mean_drift_score" in summary
        assert "max_drift_score" in summary

    def test_reset_reference(self, basic_config, ref_data):
        X_ref, y_ref = ref_data
        monitor = DriftMonitor(config=basic_config)
        monitor.track_reference(X_ref, y_ref)
        monitor.reset_reference()

        with pytest.raises(RuntimeError, match="No reference data"):
            monitor.check_drift(X_ref)

    def test_overwrite_reference_guard(self, basic_config, ref_data):
        X_ref, y_ref = ref_data
        monitor = DriftMonitor(config=basic_config)
        monitor.track_reference(X_ref, y_ref)

        with pytest.raises(RuntimeError, match="overwrite=True"):
            monitor.track_reference(X_ref, y_ref)

        # With overwrite=True it should succeed
        monitor.track_reference(X_ref, y_ref, overwrite=True)

    def test_custom_feature_names(self, ref_data, cur_data_drifted):
        X_ref, y_ref = ref_data
        X_cur, y_cur = cur_data_drifted
        cfg = DriftConfig(
            model_name="named_model",
            drift_threshold=0.75,
            feature_names=["f1", "f2", "f3", "f4"],
            enable_dashboard=False,
            min_reference_samples=50,
        )
        monitor = DriftMonitor(config=cfg)
        monitor.track_reference(X_ref, y_ref)
        report = monitor.check_drift(X_cur, y_cur, send_notifications=False)

        assert set(report.feature_scores.keys()) == {"f1", "f2", "f3", "f4"}

    def test_regression_task(self, rng):
        cfg = DriftConfig(
            model_name="regression_model",
            task_type=TaskType.REGRESSION,
            output_metric=DriftMetric.KOLMOGOROV_SMIRNOV,
            drift_threshold=0.75,
            enable_dashboard=False,
            min_reference_samples=50,
        )
        monitor = DriftMonitor(config=cfg)
        X_ref = rng.normal(0, 1, (200, 3))
        y_ref = rng.normal(0, 1, 200)  # Continuous targets
        monitor.track_reference(X_ref, y_ref)

        X_cur = rng.normal(3, 1, (100, 3))
        y_cur = rng.normal(5, 1, 100)
        report = monitor.check_drift(X_cur, y_cur, send_notifications=False)

        assert isinstance(report, DriftReport)
        assert "score" in report.output_drift

    def test_to_dict_serialisable(self, basic_config, ref_data, cur_data_clean):
        X_ref, y_ref = ref_data
        X_cur, y_cur = cur_data_clean
        monitor = DriftMonitor(config=basic_config)
        monitor.track_reference(X_ref, y_ref)
        report = monitor.check_drift(X_cur, y_cur, send_notifications=False)

        d = report.to_dict()
        import json
        # Should be JSON-serialisable
        json.dumps(d, default=str)
        assert d["model_name"] == "test_model"
        assert "drift_score" in d
        assert "recommendations" in d

    def test_no_y_reference(self, basic_config):
        """check_drift without labels should still work (only feature drift)."""
        X_ref = np.random.randn(200, 4)
        monitor = DriftMonitor(config=basic_config)
        monitor.track_reference(X_ref)  # No y

        X_cur = np.random.randn(100, 4)
        report = monitor.check_drift(X_cur, send_notifications=False)

        assert isinstance(report, DriftReport)
        assert report.output_drift == {}

    def test_rolling_window(self, basic_config, ref_data):
        """With window_size set, drift is computed over recent data only."""
        X_ref, y_ref = ref_data
        cfg = DriftConfig(
            model_name="windowed",
            drift_threshold=0.75,
            window_size=3,
            enable_dashboard=False,
            min_reference_samples=50,
        )
        monitor = DriftMonitor(config=cfg)
        monitor.track_reference(X_ref, y_ref)

        for _ in range(5):
            X_batch = np.random.randn(20, 4)
            monitor.check_drift(X_batch, send_notifications=False)

        assert len(monitor._window_X) <= 3


# --------------------------------------------------------------------------- #
#  Edge cases                                                                  #
# --------------------------------------------------------------------------- #

class TestEdgeCases:
    def test_constant_feature_column(self):
        """A constant column should not cause NaN/inf in metrics."""
        ref = np.ones((200, 1))
        cur = np.ones((100, 1))
        result = kolmogorov_smirnov(ref, cur)
        assert np.isfinite(result["score"])

    def test_single_class_labels(self, basic_config):
        """All labels being the same class should not crash."""
        X_ref = np.random.randn(200, 4)
        y_ref = np.zeros(200, dtype=int)
        monitor = DriftMonitor(config=basic_config)
        monitor.track_reference(X_ref, y_ref)

        X_cur = np.random.randn(100, 4)
        y_cur = np.ones(100, dtype=int)
        report = monitor.check_drift(X_cur, y_cur, send_notifications=False)
        assert isinstance(report, DriftReport)

    def test_very_small_current_batch(self, basic_config):
        """Even tiny current batches should complete without error."""
        X_ref = np.random.randn(200, 4)
        monitor = DriftMonitor(config=basic_config)
        monitor.track_reference(X_ref)

        X_cur = np.random.randn(5, 4)
        report = monitor.check_drift(X_cur, send_notifications=False)
        assert 0.0 <= report.drift_score <= 1.0
