#!/usr/bin/env python3
"""
TIAMAT Drift Monitor SDK
========================
Python client for the Drift Monitor API at https://tiamat.live/drift

Endpoints:
  POST /drift/register   — Register a model for monitoring
  POST /drift/baseline   — Set baseline distribution (20+ samples)
  POST /drift/check      — Check new samples for drift
  GET  /drift/status/<id>— Model status and check history
  GET  /drift/meta       — API metadata and capabilities
  POST /drift/alert/test — Test webhook delivery

Model types:
  numeric     — PSI (Population Stability Index), threshold 0.25
  embedding   — Cosine distance, threshold 0.15
  probability — Entropy + KL divergence, threshold 0.20
  text        — Length + vocabulary z-scores, threshold 0.20

Free tier: 1 model, 10 checks/day
Pro ($99/mo): 5 models, unlimited checks, webhooks, Slack

Usage:
    from drift_monitor_sdk import DriftMonitor

    dm = DriftMonitor()  # or DriftMonitor(api_key="your-pro-key")

    # Register once
    model_id = dm.register("my-classifier", "numeric",
                            webhook_url="https://hooks.slack.com/...")

    # Baseline once (or after major retrains)
    dm.set_baseline(model_id, baseline_scores)

    # Check on every batch
    result = dm.check(model_id, today_scores)
    if result.alert:
        print(f"DRIFT ALERT: {result.score:.4f} > {result.threshold:.4f}")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import requests

log = logging.getLogger("drift_monitor")


# ---------------------------------------------------------------------------
# Response dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RegisterResult:
    model_id: int
    name: str
    model_type: str
    created_at: str
    message: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BaselineResult:
    model_id: int
    method: str
    sample_count: int
    message: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DriftResult:
    model_id: int
    check_id: int
    method: str
    score: float
    threshold: float
    alert: bool
    sample_n: int
    details: Dict[str, Any]
    timestamp: str
    free_checks_remaining: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def pct_of_threshold(self) -> float:
        """How far the score is relative to the threshold (1.0 = exactly at threshold)."""
        return self.score / max(self.threshold, 1e-10)

    @property
    def status(self) -> str:
        """Human-readable status string."""
        if not self.alert:
            if self.score < self.threshold * 0.5:
                return "stable"
            return "watch"
        return "alert"


@dataclass
class ModelStatus:
    model_id: int
    name: str
    model_type: str
    baseline_n: int
    total_checks: int
    total_alerts: int
    latest_score: Optional[float]
    latest_alert: Optional[bool]
    sparkline: str
    checks: List[Dict[str, Any]]
    raw: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DriftMonitorError(Exception):
    """Base exception for SDK errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, body: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body or {}


class RateLimitError(DriftMonitorError):
    """Raised when the free tier daily limit is hit (HTTP 429)."""
    pass


class PaymentRequiredError(DriftMonitorError):
    """Raised when a paid endpoint is hit without payment (HTTP 402)."""
    def __init__(self, message, body=None):
        super().__init__(message, status_code=402, body=body)
        self.payment_info = body or {}


class AuthError(DriftMonitorError):
    """Raised on authentication failures (HTTP 401/403)."""
    pass


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------

class DriftMonitor:
    """
    Python client for the TIAMAT Drift Monitor API.

    Parameters
    ----------
    api_key : str, optional
        Pro/Enterprise API key. Omit for free tier usage.
    base_url : str, optional
        Override the API base URL (default: https://tiamat.live).
    timeout : float
        Request timeout in seconds (default: 15).
    retries : int
        Number of retries on 5xx errors (default: 3).
    retry_backoff : float
        Exponential backoff base in seconds (default: 1.5).
    """

    DEFAULT_BASE_URL = "https://tiamat.live"
    DEFAULT_TIMEOUT  = 15.0
    DEFAULT_RETRIES  = 3

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        retry_backoff: float = 1.5,
    ):
        self._base = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._retries = retries
        self._backoff = retry_backoff

        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "tiamat-drift-sdk/0.1.0 (python)",
        })
        if api_key:
            self._session.headers.update({"X-API-Key": api_key})

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def register(
        self,
        name: str,
        model_type: str,
        threshold: Optional[float] = None,
        webhook_url: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> RegisterResult:
        """
        Register a model for drift monitoring.

        Parameters
        ----------
        name : str
            Unique name for your model (e.g. "fraud-detector-v2").
        model_type : str
            One of: "numeric", "embedding", "probability", "text"
        threshold : float, optional
            Custom alert threshold (overrides the default for this model type).
            Defaults: numeric=0.25, embedding=0.15, probability=0.20, text=0.20
        webhook_url : str, optional
            URL to POST alert payloads when drift is detected.
        config : dict, optional
            Any additional config options.

        Returns
        -------
        RegisterResult

        Examples
        --------
        >>> dm = DriftMonitor()
        >>> result = dm.register(
        ...     "churn-predictor",
        ...     "numeric",
        ...     threshold=0.20,
        ...     webhook_url="https://hooks.slack.com/services/..."
        ... )
        >>> print(result.model_id)  # → 17
        """
        cfg = dict(config or {})
        if threshold is not None:
            cfg["threshold"] = threshold
        if webhook_url:
            cfg["webhook_url"] = webhook_url

        payload: Dict[str, Any] = {"name": name, "model_type": model_type}
        if cfg:
            payload["config"] = cfg

        data = self._post("/drift/register", payload)
        return RegisterResult(
            model_id=data["model_id"],
            name=data["name"],
            model_type=data["model_type"],
            created_at=data["created_at"],
            message=data.get("message", ""),
            raw=data,
        )

    def set_baseline(
        self,
        model_id: int,
        samples: List[Union[float, List[float], str]],
    ) -> BaselineResult:
        """
        Set the baseline distribution for a model.

        Call this once after registering, using a representative sample of
        production outputs from a known-stable period. Re-call after major
        model retrains.

        Parameters
        ----------
        model_id : int
            The ID returned by register().
        samples : list
            For numeric/probability: list of floats or list of float lists.
            For embedding: list of vectors (list of lists, same dimension).
            For text: list of strings.
            Minimum 20 samples, maximum 10,000.

        Returns
        -------
        BaselineResult

        Examples
        --------
        # Numeric: confidence scores from last 30 days
        >>> dm.set_baseline(17, [0.94, 0.87, 0.91, 0.03, 0.95, ...])

        # Embedding: 128-dim vectors from user encoder
        >>> dm.set_baseline(3, [[0.1, 0.8, ...], [0.3, 0.2, ...], ...])

        # Probability: softmax distributions (N, K)
        >>> dm.set_baseline(5, [[0.9, 0.05, 0.05], [0.1, 0.8, 0.1], ...])

        # Text: raw LLM responses
        >>> dm.set_baseline(9, ["The product works well.", "Fast shipping.", ...])
        """
        if len(samples) < 20:
            raise ValueError(f"Baseline requires at least 20 samples, got {len(samples)}")
        if len(samples) > 10_000:
            raise ValueError(f"Maximum 10,000 baseline samples, got {len(samples)}")

        data = self._post("/drift/baseline", {"model_id": model_id, "samples": samples})
        return BaselineResult(
            model_id=model_id,
            method=data.get("method", ""),
            sample_count=data.get("sample_count", len(samples)),
            message=data.get("message", ""),
            raw=data,
        )

    def check(
        self,
        model_id: int,
        samples: List[Union[float, List[float], str]],
    ) -> DriftResult:
        """
        Check a batch of new model outputs for drift against the baseline.

        Run this after every batch scoring job, or on a scheduled cadence
        (e.g. hourly/daily). Does NOT affect serving latency — run async.

        Parameters
        ----------
        model_id : int
            The ID returned by register().
        samples : list
            New batch of model outputs. Same format as set_baseline().
            Minimum 5 samples, maximum 10,000.

        Returns
        -------
        DriftResult
            .score: drift magnitude (PSI, cosine distance, etc.)
            .alert: True if score exceeds the model's threshold
            .method: detection algorithm used
            .threshold: the threshold that was compared against

        Examples
        --------
        >>> result = dm.check(17, today_scores)
        >>> if result.alert:
        ...     print(f"Drift detected! PSI={result.score:.4f}")
        ...     # Webhook already fired to your Slack channel
        """
        if len(samples) < 5:
            raise ValueError(f"Check requires at least 5 samples, got {len(samples)}")
        if len(samples) > 10_000:
            raise ValueError(f"Maximum 10,000 check samples, got {len(samples)}")

        data = self._post("/drift/check", {"model_id": model_id, "samples": samples})
        return DriftResult(
            model_id=data["model_id"],
            check_id=data["check_id"],
            method=data["method"],
            score=float(data["score"]),
            threshold=float(data["threshold"]),
            alert=bool(data["alert"]),
            sample_n=data["sample_n"],
            details=data.get("details", {}),
            timestamp=data["timestamp"],
            free_checks_remaining=data.get("free_checks_remaining"),
            raw=data,
        )

    def status(self, model_id: int) -> ModelStatus:
        """
        Get model status, alert counts, and recent check history.

        Parameters
        ----------
        model_id : int
            The ID returned by register().

        Returns
        -------
        ModelStatus
            .total_checks: all-time check count
            .total_alerts: all-time alert count
            .latest_score: most recent drift score
            .sparkline: ASCII sparkline of recent scores
            .checks: list of last 10 check dicts
        """
        resp = self._session.get(
            f"{self._base}/drift/status/{model_id}",
            timeout=self._timeout
        )
        self._raise_for_status(resp)
        data = resp.json()
        return ModelStatus(
            model_id=data["model_id"],
            name=data["name"],
            model_type=data["model_type"],
            baseline_n=data["baseline_n"],
            total_checks=data["total_checks"],
            total_alerts=data["total_alerts"],
            latest_score=data.get("latest_score"),
            latest_alert=data.get("latest_alert"),
            sparkline=data.get("sparkline", ""),
            checks=data.get("checks", []),
            raw=data,
        )

    def test_webhook(self, webhook_url: str) -> str:
        """
        Send a test POST to a webhook URL and return the delivery status.

        Parameters
        ----------
        webhook_url : str
            The URL to test (must start with "http").

        Returns
        -------
        str
            "sent_200" on success, "failed_..." on error.

        Examples
        --------
        >>> status = dm.test_webhook("https://hooks.slack.com/services/...")
        >>> print(status)  # → "sent_200"
        """
        data = self._post("/drift/alert/test", {"webhook_url": webhook_url})
        return data.get("status", "unknown")

    def meta(self) -> dict:
        """Return API metadata: methods, thresholds, limits, pricing."""
        resp = self._session.get(f"{self._base}/drift/meta", timeout=self._timeout)
        self._raise_for_status(resp)
        return resp.json()

    # -----------------------------------------------------------------------
    # Convenience helpers
    # -----------------------------------------------------------------------

    def check_batch_safe(
        self,
        model_id: int,
        samples: List,
        min_samples: int = 5,
    ) -> Optional[DriftResult]:
        """
        Like check(), but silently returns None if there aren't enough samples
        or if the API call fails. Useful for non-critical monitoring paths.

        Will never raise an exception — safe to call in production code
        without a try/except.

        Examples
        --------
        >>> result = dm.check_batch_safe(17, today_scores)
        >>> if result and result.alert:
        ...     log.warning("Drift detected", score=result.score)
        """
        if len(samples) < min_samples:
            log.debug(f"Skipping drift check: {len(samples)} samples < minimum {min_samples}")
            return None
        try:
            return self.check(model_id, samples[:10_000])
        except Exception as e:
            log.warning(f"Drift check failed (non-fatal): {e}")
            return None

    def setup_model(
        self,
        name: str,
        model_type: str,
        baseline_samples: List,
        threshold: Optional[float] = None,
        webhook_url: Optional[str] = None,
    ) -> int:
        """
        One-shot setup: register + baseline in a single call.
        Returns model_id.

        Examples
        --------
        >>> model_id = dm.setup_model(
        ...     "fraud-detector-v3",
        ...     "numeric",
        ...     baseline_samples=october_scores,
        ...     threshold=0.15,
        ...     webhook_url="https://hooks.slack.com/..."
        ... )
        """
        reg = self.register(name, model_type, threshold=threshold, webhook_url=webhook_url)
        self.set_baseline(reg.model_id, baseline_samples)
        log.info(f"Model '{name}' registered (id={reg.model_id}) and baselined ({len(baseline_samples)} samples)")
        return reg.model_id

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._base}{path}"
        last_exc = None

        for attempt in range(self._retries):
            try:
                resp = self._session.post(url, json=payload, timeout=self._timeout)
                self._raise_for_status(resp)
                return resp.json()

            except (RateLimitError, PaymentRequiredError, AuthError, ValueError):
                raise  # Don't retry client errors

            except DriftMonitorError as e:
                if e.status_code and e.status_code < 500:
                    raise  # Don't retry 4xx
                last_exc = e
                if attempt < self._retries - 1:
                    wait = self._backoff ** attempt
                    log.warning(f"Drift API server error (attempt {attempt+1}/{self._retries}), retrying in {wait:.1f}s")
                    time.sleep(wait)

            except requests.exceptions.Timeout as e:
                last_exc = DriftMonitorError(f"Request timed out after {self._timeout}s")
                if attempt < self._retries - 1:
                    time.sleep(self._backoff ** attempt)

            except requests.exceptions.ConnectionError as e:
                last_exc = DriftMonitorError(f"Connection failed: {e}")
                if attempt < self._retries - 1:
                    time.sleep(self._backoff ** attempt)

        raise last_exc or DriftMonitorError("Unknown error")

    def _raise_for_status(self, resp: requests.Response):
        if resp.ok:
            return

        body = {}
        try:
            body = resp.json()
        except Exception:
            pass

        message = body.get("error") or body.get("message") or resp.text[:200]

        if resp.status_code == 429:
            raise RateLimitError(f"Rate limited: {message}", status_code=429, body=body)
        if resp.status_code == 402:
            raise PaymentRequiredError(f"Payment required: {message}", body=body)
        if resp.status_code in (401, 403):
            raise AuthError(f"Auth error ({resp.status_code}): {message}", status_code=resp.status_code, body=body)
        if resp.status_code == 404:
            raise DriftMonitorError(f"Not found: {message}", status_code=404, body=body)
        if resp.status_code == 400:
            raise ValueError(f"Bad request: {message}")

        raise DriftMonitorError(f"API error {resp.status_code}: {message}", status_code=resp.status_code, body=body)


# ---------------------------------------------------------------------------
# CLI convenience (python -m drift_monitor_sdk)
# ---------------------------------------------------------------------------

def _cli():
    """Quick smoke test / interactive tool."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="TIAMAT Drift Monitor SDK CLI")
    sub = parser.add_subparsers(dest="cmd")

    # register
    p = sub.add_parser("register", help="Register a new model")
    p.add_argument("name")
    p.add_argument("model_type", choices=["numeric", "embedding", "probability", "text"])
    p.add_argument("--threshold", type=float)
    p.add_argument("--webhook-url")
    p.add_argument("--api-key")

    # status
    p = sub.add_parser("status", help="Get model status")
    p.add_argument("model_id", type=int)
    p.add_argument("--api-key")

    # meta
    p = sub.add_parser("meta", help="Show API metadata")
    p.add_argument("--api-key")

    # test-webhook
    p = sub.add_parser("test-webhook", help="Test a webhook URL")
    p.add_argument("webhook_url")
    p.add_argument("--api-key")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    dm = DriftMonitor(api_key=getattr(args, "api_key", None))

    if args.cmd == "register":
        result = dm.register(args.name, args.model_type,
                             threshold=args.threshold,
                             webhook_url=args.webhook_url)
        print(json.dumps(result.raw, indent=2))

    elif args.cmd == "status":
        s = dm.status(args.model_id)
        print(f"Model: {s.name} ({s.model_type}) id={s.model_id}")
        print(f"Baseline: {s.baseline_n} samples")
        print(f"Checks: {s.total_checks}  Alerts: {s.total_alerts}")
        print(f"Latest score: {s.latest_score}")
        print(f"Sparkline: {s.sparkline}")

    elif args.cmd == "meta":
        print(json.dumps(dm.meta(), indent=2))

    elif args.cmd == "test-webhook":
        status = dm.test_webhook(args.webhook_url)
        print(f"Webhook delivery status: {status}")


if __name__ == "__main__":
    _cli()


# ---------------------------------------------------------------------------
# Usage examples (run this file directly with --demo flag)
# ---------------------------------------------------------------------------
"""
QUICK START EXAMPLES
====================

# 1. Basic numeric model (fraud/churn classifier outputs)
from drift_monitor_sdk import DriftMonitor
import numpy as np

dm = DriftMonitor()  # free tier

# Register
result = dm.register("my-classifier", "numeric", threshold=0.20)
model_id = result.model_id

# Baseline (production scores from last 30 days)
baseline_scores = np.random.beta(2, 1, 500).tolist()  # simulate stable high-confidence scores
dm.set_baseline(model_id, baseline_scores)

# Daily check
today_scores = np.random.beta(1, 1, 200).tolist()  # simulate drift: flatter distribution
result = dm.check(model_id, today_scores)
print(f"PSI score:  {result.score:.4f}")   # → 0.31 (drifted)
print(f"Alert:      {result.alert}")       # → True
print(f"Remaining:  {result.free_checks_remaining} free checks today")


# 2. Embedding model (recommendation system user tower)
import numpy as np

dm = DriftMonitor()
result = dm.register("recsys-user-tower", "embedding", threshold=0.08)
model_id = result.model_id

# Baseline: 200 user embeddings (128-dim each)
baseline_embs = np.random.randn(200, 128)
baseline_embs = (baseline_embs / np.linalg.norm(baseline_embs, axis=1, keepdims=True)).tolist()
dm.set_baseline(model_id, baseline_embs)

# Check today's user embeddings
today_embs = (np.random.randn(50, 128) * 1.3)  # simulate drift: scale shift
today_embs = (today_embs / np.linalg.norm(today_embs, axis=1, keepdims=True)).tolist()
result = dm.check(model_id, today_embs)
print(f"Cosine drift: {result.score:.4f}")
print(f"Centroid drift: {result.details.get('centroid_drift', 0):.4f}")


# 3. LLM output monitoring (text drift)
dm = DriftMonitor()
result = dm.register("support-llm-responses", "text", threshold=0.20)
model_id = result.model_id

baseline_texts = [
    "Thank you for contacting us. Your issue has been resolved.",
    "We apologize for the inconvenience. Please allow 2-3 business days.",
    # ... 20+ real LLM responses from stable week
]
dm.set_baseline(model_id, baseline_texts)

# Check this week's responses
new_texts = [
    "ok",          # much shorter — length drift
    "k",
    "noted.",
    # ... actual LLM responses from this week
]
result = dm.check(model_id, new_texts)
print(f"Text drift: {result.score:.4f}")
print(f"Length z-score: {result.details.get('length_zscore', 0):.2f}")


# 4. Safe usage in production (never crashes your job)
result = dm.check_batch_safe(model_id, today_scores)
if result and result.alert:
    log.warning("Model drift detected", score=result.score, method=result.method)


# 5. One-shot setup
model_id = dm.setup_model(
    "churn-v3",
    "numeric",
    baseline_samples=october_production_scores,
    threshold=0.20,
    webhook_url="https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
)
"""
