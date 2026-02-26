"""
AnomalyDetector — per-API-key statistical usage monitor for TIAMAT.

Designed to complement rate_limiter.py (IP hard-caps) with key-level
behavioral analysis. Uses rolling 24-hour hourly buckets and flags
requests that exceed mean + N*sigma of the key's own baseline.

Usage:
    detector = AnomalyDetector()

    # On every request (before handler):
    result = detector.check(api_key, endpoint="/summarize")
    if not result.allowed:
        return 429, {"error": result.reason, "retry_after": result.blocked_until}

    # After handler completes (record success):
    detector.record(api_key, endpoint="/summarize")

    # Trust a known-good internal key:
    detector.whitelist_key("sk-internal-monitor")

    # Trust a key only on specific endpoints:
    detector.whitelist_key("sk-partner-abc", endpoints={"/summarize", "/chat"})

Integration point (FastAPI middleware sketch):
    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        key = request.headers.get("X-Api-Key", "")
        result = detector.check(key, request.url.path)
        if not result.allowed:
            return JSONResponse({"error": result.reason}, status_code=429)
        response = await call_next(request)
        detector.record(key, request.url.path)
        return response
"""

import json
import logging
import math
import os
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

__all__ = ["AnomalyDetector", "AnomalyResult", "DetectionEvent"]

# ── Constants ──────────────────────────────────────────────────────────────────
SECURITY_LOG = "/root/.automaton/security.log"
HISTORY_HOURS = 24           # rolling baseline window (completed hourly buckets)
MIN_BUCKETS = 3              # min completed buckets before detection is active
SIGMA_THRESHOLD = 3.0        # σ above mean to trigger block
ROTATION_SIGMA = 6.0         # σ threshold to also flag key for rotation
DEFAULT_BLOCK_SEC = 3600.0   # 1-hour block on detection
MIN_MEAN_FOR_DETECTION = 2.0 # don't flag if baseline mean < 2 req/hr (too sparse)
MIN_STD_FOR_DETECTION = 0.5  # don't flag if std < 0.5 (zero-variance / dormant key)
MAINTENANCE_INTERVAL = 600   # flush + bucket-advance every 10 minutes

# ── Security logger (structured JSONL) ────────────────────────────────────────
os.makedirs(os.path.dirname(SECURITY_LOG), exist_ok=True)

_sec_logger = logging.getLogger("tiamat.security")
_sec_logger.setLevel(logging.INFO)
_sec_logger.propagate = False
if not _sec_logger.handlers:
    _fh = logging.FileHandler(SECURITY_LOG)
    _fh.setFormatter(logging.Formatter(
        '{"ts": "%(asctime)s", "lvl": "%(levelname)s", %(message)s}',
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    ))
    _fh.setLevel(logging.INFO)
    _sec_logger.addHandler(_fh)


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class AnomalyResult:
    """Returned by AnomalyDetector.check()."""
    allowed: bool
    anomaly_detected: bool
    reason: str = ""
    sigma: float = 0.0            # deviation from baseline (0 if normal)
    blocked_until: float = 0.0    # unix epoch; 0 = not blocked
    flagged_for_rotation: bool = False


@dataclass
class DetectionEvent:
    """Emitted on each anomaly detection (for logging/alerting)."""
    key_prefix: str               # first 8 chars only — never log full keys
    endpoint: str
    sigma: float
    requests_this_hour: int
    baseline_mean: float
    baseline_std: float
    rotation_flagged: bool
    timestamp: float = field(default_factory=time.time)


@dataclass
class _KeyStats:
    """Per-key mutable state. Always accessed under AnomalyDetector._lock."""
    # Rolling completed hourly bucket counts (oldest → newest)
    hourly_buckets: deque = field(default_factory=lambda: deque(maxlen=HISTORY_HOURS))
    # Unix timestamp of current (incomplete) bucket's hour boundary
    current_bucket_ts: float = 0.0
    # Request count in the current (incomplete) hour
    current_count: int = 0

    # Block state
    blocked_until: float = 0.0
    block_reason: str = ""
    flagged_for_rotation: bool = False

    # Whitelist
    is_whitelisted: bool = False
    endpoint_whitelist: Set[str] = field(default_factory=set)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hour_boundary(t: Optional[float] = None) -> float:
    """Floor a unix timestamp to its hour boundary (e.g. 14:37 → 14:00)."""
    return math.floor((t or time.time()) / 3600) * 3600


def _compute_stats(buckets: deque) -> Tuple[float, float]:
    """Return (mean, population_std) for completed hourly bucket counts."""
    if not buckets:
        return 0.0, 0.0
    vals = list(buckets)
    mean = sum(vals) / len(vals)
    if len(vals) < 2:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in vals) / len(vals)
    return mean, math.sqrt(variance)


# ── Core class ─────────────────────────────────────────────────────────────────

class AnomalyDetector:
    """
    Per-API-key statistical anomaly detector.

    Tracks each key's request volume in 1-hour buckets over a rolling
    HISTORY_HOURS window. When the current hour's count exceeds
    (mean + sigma_threshold * std) of the baseline, the key is blocked
    for block_sec seconds and a structured event is written to security.log.

    Keys with fewer than min_buckets completed hours are never flagged
    (cold-start safety). Zero-variance / dormant baselines are also
    exempt (MIN_MEAN and MIN_STD guards).

    Persistence (optional): pass db_path to reload baselines across
    gunicorn restarts. Baselines are flushed every MAINTENANCE_INTERVAL
    seconds by a background daemon thread.
    """

    def __init__(
        self,
        sigma_threshold: float = SIGMA_THRESHOLD,
        rotation_sigma: float = ROTATION_SIGMA,
        block_sec: float = DEFAULT_BLOCK_SEC,
        history_hours: int = HISTORY_HOURS,
        min_buckets: int = MIN_BUCKETS,
        db_path: Optional[str] = None,
    ):
        self.sigma_threshold = sigma_threshold
        self.rotation_sigma = rotation_sigma
        self.block_sec = block_sec
        self.history_hours = history_hours
        self.min_buckets = min_buckets
        self.db_path = db_path

        self._stats: Dict[str, _KeyStats] = {}
        self._lock = threading.Lock()

        if db_path:
            self._init_db()
            self._load_baselines()

        # Background maintenance: advance idle buckets + flush to DB
        self._bg = threading.Thread(target=self._maintenance_loop, daemon=True)
        self._bg.start()

    # ── Public API ─────────────────────────────────────────────────────────────

    def check(self, api_key: str, endpoint: str = "") -> AnomalyResult:
        """
        Check whether a request should be allowed for this key.

        Call BEFORE the route handler. Does not record the request —
        call record() after your handler completes successfully.

        Returns AnomalyResult.allowed = True if the request should proceed.
        """
        if not api_key:
            # Keyless requests are governed by rate_limiter.py, not here
            return AnomalyResult(allowed=True, anomaly_detected=False)

        with self._lock:
            stats = self._stats.get(api_key)
            if stats is None:
                # First time we've seen this key — allow it and start tracking
                self._stats[api_key] = _KeyStats(current_bucket_ts=_hour_boundary())
                self._log_request(api_key, endpoint, "new_key")
                return AnomalyResult(allowed=True, anomaly_detected=False)

            now = time.time()

            # ── Still blocked from a previous detection? ─────────────────────
            if stats.blocked_until and now < stats.blocked_until:
                return AnomalyResult(
                    allowed=False,
                    anomaly_detected=True,
                    reason=stats.block_reason,
                    blocked_until=stats.blocked_until,
                    flagged_for_rotation=stats.flagged_for_rotation,
                )

            # Clear expired block
            if stats.blocked_until and now >= stats.blocked_until:
                stats.blocked_until = 0.0
                stats.block_reason = ""

            # ── Whitelist bypass ──────────────────────────────────────────────
            if stats.is_whitelisted:
                return AnomalyResult(allowed=True, anomaly_detected=False)

            if endpoint and endpoint in stats.endpoint_whitelist:
                return AnomalyResult(allowed=True, anomaly_detected=False)

            # ── Advance bucket (may flush completed hour to history) ──────────
            self._advance_bucket(stats)

            # ── Not enough history yet ────────────────────────────────────────
            if len(stats.hourly_buckets) < self.min_buckets:
                return AnomalyResult(allowed=True, anomaly_detected=False)

            # ── 3-sigma evaluation ────────────────────────────────────────────
            return self._evaluate(api_key, stats, endpoint, now)

    def record(self, api_key: str, endpoint: str = "") -> None:
        """
        Record one completed request for api_key.
        Call this AFTER the route handler succeeds.
        """
        if not api_key:
            return
        with self._lock:
            if api_key not in self._stats:
                self._stats[api_key] = _KeyStats(current_bucket_ts=_hour_boundary())
            stats = self._stats[api_key]
            self._advance_bucket(stats)
            stats.current_count += 1

    def whitelist_key(self, api_key: str, endpoints: Optional[Set[str]] = None) -> None:
        """
        Mark a key as trusted.

        - No endpoints provided → global whitelist (all endpoints exempt)
        - endpoints provided   → only those specific endpoints are exempt
        """
        with self._lock:
            if api_key not in self._stats:
                self._stats[api_key] = _KeyStats(current_bucket_ts=_hour_boundary())
            stats = self._stats[api_key]
            if endpoints:
                stats.endpoint_whitelist.update(endpoints)
                _sec_logger.info(
                    f'"event": "whitelist_endpoint", "key_prefix": "{api_key[:8]}", '
                    f'"endpoints": {json.dumps(list(endpoints))}'
                )
            else:
                stats.is_whitelisted = True
                _sec_logger.info(
                    f'"event": "whitelist_global", "key_prefix": "{api_key[:8]}"'
                )

    def unblock_key(self, api_key: str) -> None:
        """
        Manually unblock a flagged key (e.g. after human review or rotation).
        """
        with self._lock:
            stats = self._stats.get(api_key)
            if stats:
                stats.blocked_until = 0.0
                stats.block_reason = ""
                stats.flagged_for_rotation = False
                _sec_logger.info(
                    f'"event": "manual_unblock", "key_prefix": "{api_key[:8]}"'
                )

    def key_summary(self, api_key: str) -> dict:
        """
        Return current diagnostic stats for a key.
        Safe to expose on internal monitoring endpoints.
        Never includes the full key.
        """
        with self._lock:
            stats = self._stats.get(api_key)
            if not stats:
                return {"known": False}
            mean, std = _compute_stats(stats.hourly_buckets)
            now = time.time()
            return {
                "known": True,
                "key_prefix": api_key[:8] + "...",
                "current_hour_count": stats.current_count,
                "baseline_mean": round(mean, 2),
                "baseline_std": round(std, 2),
                "completed_buckets": len(stats.hourly_buckets),
                "detection_active": len(stats.hourly_buckets) >= self.min_buckets,
                "is_whitelisted": stats.is_whitelisted,
                "endpoint_whitelist": list(stats.endpoint_whitelist),
                "blocked": bool(stats.blocked_until and now < stats.blocked_until),
                "blocked_until": stats.blocked_until or None,
                "blocked_reason": stats.block_reason or None,
                "flagged_for_rotation": stats.flagged_for_rotation,
            }

    def blocked_keys(self) -> List[str]:
        """Return prefixes of all currently blocked keys (for dashboards)."""
        now = time.time()
        with self._lock:
            return [
                k[:8] + "..."
                for k, s in self._stats.items()
                if s.blocked_until and now < s.blocked_until
            ]

    def rotation_candidates(self) -> List[str]:
        """Return prefixes of keys flagged for rotation."""
        with self._lock:
            return [
                k[:8] + "..."
                for k, s in self._stats.items()
                if s.flagged_for_rotation
            ]

    # ── Internal evaluation ────────────────────────────────────────────────────

    def _evaluate(
        self, api_key: str, stats: _KeyStats, endpoint: str, now: float
    ) -> AnomalyResult:
        """
        Run 3-sigma check against the current (incomplete) bucket count
        versus the completed-bucket baseline. Called under self._lock.
        """
        mean, std = _compute_stats(stats.hourly_buckets)
        current = stats.current_count

        # Baseline too sparse / zero-variance — skip detection
        if mean < MIN_MEAN_FOR_DETECTION or std < MIN_STD_FOR_DETECTION:
            return AnomalyResult(allowed=True, anomaly_detected=False)

        threshold = mean + self.sigma_threshold * std
        if current <= threshold:
            return AnomalyResult(allowed=True, anomaly_detected=False)

        # Anomaly confirmed
        sigma = (current - mean) / std
        rotation_flagged = sigma >= self.rotation_sigma

        block_reason = (
            f"Anomalous usage pattern: {current} req/hr vs "
            f"baseline {mean:.1f}±{std:.1f} ({sigma:.1f}σ). "
            f"Key blocked for {int(self.block_sec // 60)} minutes."
        )
        stats.blocked_until = now + self.block_sec
        stats.block_reason = block_reason
        stats.flagged_for_rotation = rotation_flagged

        event = DetectionEvent(
            key_prefix=api_key[:8],
            endpoint=endpoint,
            sigma=sigma,
            requests_this_hour=current,
            baseline_mean=mean,
            baseline_std=std,
            rotation_flagged=rotation_flagged,
        )
        self._emit_detection(event)

        return AnomalyResult(
            allowed=False,
            anomaly_detected=True,
            reason=block_reason,
            sigma=sigma,
            blocked_until=stats.blocked_until,
            flagged_for_rotation=rotation_flagged,
        )

    def _advance_bucket(self, stats: _KeyStats) -> None:
        """
        If the current hour has rolled over, commit the completed bucket
        count to hourly_buckets and reset the counter.
        Fills gap hours with 0 if the key was idle for multiple hours.
        Called under self._lock.
        """
        now_bucket = _hour_boundary()

        if stats.current_bucket_ts == 0.0:
            stats.current_bucket_ts = now_bucket
            return

        if now_bucket <= stats.current_bucket_ts:
            return  # still in the same hour

        # One or more hours have passed — commit completed buckets
        hours_elapsed = int((now_bucket - stats.current_bucket_ts) / 3600)

        # Commit the just-completed hour with its actual count
        stats.hourly_buckets.append(stats.current_count)

        # Fill gap hours with 0 (key was idle)
        for _ in range(min(hours_elapsed - 1, self.history_hours)):
            stats.hourly_buckets.append(0)

        stats.current_count = 0
        stats.current_bucket_ts = now_bucket

    def _emit_detection(self, event: DetectionEvent) -> None:
        """Write structured detection event to security.log. Called under lock."""
        _sec_logger.warning(
            f'"event": "anomaly_detected", '
            f'"key_prefix": "{event.key_prefix}", '
            f'"endpoint": "{event.endpoint}", '
            f'"sigma": {event.sigma:.2f}, '
            f'"req_this_hour": {event.requests_this_hour}, '
            f'"baseline_mean": {event.baseline_mean:.2f}, '
            f'"baseline_std": {event.baseline_std:.2f}, '
            f'"rotation_flagged": {str(event.rotation_flagged).lower()}'
        )

    def _log_request(self, api_key: str, endpoint: str, tag: str) -> None:
        """Write a lightweight request event (info level). Called under lock."""
        _sec_logger.info(
            f'"event": "{tag}", '
            f'"key_prefix": "{api_key[:8]}", '
            f'"endpoint": "{endpoint}"'
        )

    # ── SQLite persistence ─────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create baseline persistence table if it doesn't exist."""
        assert self.db_path is not None
        db_path: str = self.db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS key_baselines (
                api_key_hash  TEXT    PRIMARY KEY,
                buckets_json  TEXT    NOT NULL,
                bucket_ts     REAL    NOT NULL,
                current_count INTEGER NOT NULL DEFAULT 0,
                whitelisted   INTEGER NOT NULL DEFAULT 0,
                endpoint_wl   TEXT    NOT NULL DEFAULT '[]',
                updated_at    REAL    NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def _load_baselines(self) -> None:
        """Reload persisted baselines from SQLite on startup."""
        assert self.db_path is not None
        db_path: str = self.db_path
        try:
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT api_key_hash, buckets_json, bucket_ts, current_count, "
                "whitelisted, endpoint_wl FROM key_baselines"
            ).fetchall()
            conn.close()
        except Exception:
            return

        for key_hash, buckets_json, bucket_ts, count, whitelisted, endpoint_wl in rows:
            try:
                buckets = json.loads(buckets_json)
                ep_whitelist = set(json.loads(endpoint_wl))
                stats = _KeyStats(
                    hourly_buckets=deque(buckets, maxlen=self.history_hours),
                    current_bucket_ts=bucket_ts,
                    current_count=count,
                    is_whitelisted=bool(whitelisted),
                    endpoint_whitelist=ep_whitelist,
                )
                self._stats[key_hash] = stats
            except Exception:
                continue

    def _flush_baselines(self) -> None:
        """Persist current in-memory baselines to SQLite."""
        if not self.db_path:
            return
        db_path: str = self.db_path
        now = time.time()
        rows = []
        with self._lock:
            for key, stats in self._stats.items():
                rows.append((
                    key,
                    json.dumps(list(stats.hourly_buckets)),
                    stats.current_bucket_ts,
                    stats.current_count,
                    int(stats.is_whitelisted),
                    json.dumps(list(stats.endpoint_whitelist)),
                    now,
                ))
        if not rows:
            return
        try:
            conn = sqlite3.connect(db_path)
            conn.executemany("""
                INSERT OR REPLACE INTO key_baselines
                (api_key_hash, buckets_json, bucket_ts, current_count,
                 whitelisted, endpoint_wl, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()
            conn.close()
        except Exception:
            pass

    # ── Maintenance loop ───────────────────────────────────────────────────────

    def _maintenance_loop(self) -> None:
        """
        Background daemon: advance idle buckets and flush baselines every
        MAINTENANCE_INTERVAL seconds. Ensures keys that go quiet between
        requests still accumulate correct 0-count gap hours.
        """
        while True:
            time.sleep(MAINTENANCE_INTERVAL)
            with self._lock:
                for stats in self._stats.values():
                    self._advance_bucket(stats)
            self._flush_baselines()
