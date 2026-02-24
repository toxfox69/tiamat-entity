"""
Drift Monitor SDK v2 — Webhook notifier

POSTs drift event payloads to a user-configured endpoint and optionally
syncs to the tiamat.live dashboard.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if TYPE_CHECKING:
    from drift_monitor import DriftReport

logger = logging.getLogger(__name__)


def _build_session(retries: int = 3, backoff: float = 0.5) -> requests.Session:
    """Return a requests.Session with automatic retry logic."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class WebhookNotifier:
    """
    POSTs JSON drift event payloads to a configurable endpoint.

    Parameters
    ----------
    url : str
        Destination webhook URL.
    headers : dict
        Extra HTTP headers (e.g. ``{"Authorization": "Bearer token"}``).
    timeout : int
        HTTP request timeout in seconds.
    retries : int
        Number of automatic retries on transient failures.
    """

    def __init__(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 15,
        retries: int = 3,
    ) -> None:
        if not url or not url.startswith(("http://", "https://")):
            raise ValueError("url must be a valid http(s):// URL.")
        self._url = url
        self._headers = {"Content-Type": "application/json"}
        if headers:
            self._headers.update(headers)
        self._timeout = timeout
        self._session = _build_session(retries=retries)

    # ------------------------------------------------------------------ #
    def notify(self, report: "DriftReport") -> bool:
        """
        POST a drift event payload to the configured endpoint.

        Returns
        -------
        bool — True if the server returned 2xx.
        """
        payload = self._report_to_payload(report)
        return self._post(payload)

    # ------------------------------------------------------------------ #
    def _post(self, payload: dict) -> bool:
        try:
            resp = self._session.post(
                self._url,
                data=json.dumps(payload, default=str),
                headers=self._headers,
                timeout=self._timeout,
            )
            if not resp.ok:
                logger.error(
                    "Webhook POST to %s returned %d: %s",
                    self._url,
                    resp.status_code,
                    resp.text[:300],
                )
                return False
            logger.debug("Webhook POST to %s succeeded (%d).", self._url, resp.status_code)
            return True
        except requests.RequestException as exc:
            logger.error("Webhook POST to %s failed: %s", self._url, exc)
            return False

    # ------------------------------------------------------------------ #
    @staticmethod
    def _report_to_payload(report: "DriftReport") -> dict:
        return {
            "event": "drift_detected" if report.alert else "drift_checked",
            "model_name": report.model_name,
            "drift_score": round(report.drift_score, 6),
            "severity": report.severity,
            "alert": report.alert,
            "timestamp": report.timestamp,
            "ref_samples": report.ref_samples,
            "cur_samples": report.cur_samples,
            "feature_scores": {
                k: round(v, 6) for k, v in report.feature_scores.items()
            },
            "output_drift": report.output_drift,
            "components": report.components,
            "recommendations": report.recommendations,
            "metadata": report.metadata,
        }


# --------------------------------------------------------------------------- #
#  Dashboard sync                                                              #
# --------------------------------------------------------------------------- #

class DashboardSync:
    """
    Syncs drift events to the tiamat.live dashboard endpoint.

    Parameters
    ----------
    api_key : str
        Drift Monitor API key (``sk_drift_xxx``).
    dashboard_url : str
        Ingest endpoint.
    timeout : int
        HTTP timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        dashboard_url: str = "https://tiamat.live/api/drift/events",
        timeout: int = 15,
    ) -> None:
        self._api_key = api_key
        self._url = dashboard_url
        self._timeout = timeout
        self._session = _build_session()

    # ------------------------------------------------------------------ #
    def sync(self, report: "DriftReport") -> bool:
        """
        POST a drift report to the dashboard. Non-blocking on error.

        Returns True if the server accepted the event.
        """
        payload = WebhookNotifier._report_to_payload(report)
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self._api_key,
            "X-SDK-Version": "2.0.0",
        }
        try:
            resp = self._session.post(
                self._url,
                data=json.dumps(payload, default=str),
                headers=headers,
                timeout=self._timeout,
            )
            if resp.ok:
                logger.debug("Dashboard sync succeeded.")
                return True
            logger.warning(
                "Dashboard sync to %s returned %d: %s",
                self._url,
                resp.status_code,
                resp.text[:200],
            )
            return False
        except requests.RequestException as exc:
            logger.warning("Dashboard sync failed (non-fatal): %s", exc)
            return False
