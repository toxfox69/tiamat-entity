"""
Sliding-window rate limiter with lockout.

Adapted from OpenClaw's auth-rate-limit.ts pattern for TIAMAT's Python APIs.
Pure in-memory — no external dependencies. Suitable for a single-process or
small worker pool (gunicorn with 2 workers shares via import-time singleton).

Design:
- Tracks request timestamps per {scope}:{ip} in a sliding window.
- When max_attempts is exceeded within window_sec, the IP is locked out
  for lockout_sec.
- Loopback (127.0.0.1, ::1) is exempt by default.
- A background-thread prune runs every 60s to prevent unbounded growth.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

__all__ = ["RateLimiter", "RateLimitResult", "create_rate_limiter"]

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@dataclass
class _Entry:
    attempts: list = field(default_factory=list)  # list of float timestamps
    locked_until: float = 0.0


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_sec: float  # 0 if not locked


class RateLimiter:
    """Sliding-window rate limiter with lockout, adapted from OpenClaw."""

    def __init__(
        self,
        max_attempts: int = 10,
        window_sec: float = 60.0,
        lockout_sec: float = 300.0,
        exempt_loopback: bool = True,
    ):
        self.max_attempts = max_attempts
        self.window_sec = window_sec
        self.lockout_sec = lockout_sec
        self.exempt_loopback = exempt_loopback
        self._entries: Dict[str, _Entry] = {}
        self._lock = threading.Lock()

        # Periodic prune thread (daemon — won't block process exit)
        self._prune_timer = threading.Thread(target=self._prune_loop, daemon=True)
        self._prune_timer.start()

    def _key(self, ip: str, scope: str) -> str:
        return f"{scope}:{ip.strip() or 'unknown'}"

    def _is_exempt(self, ip: str) -> bool:
        return self.exempt_loopback and ip.strip() in LOOPBACK

    def _slide_window(self, entry: _Entry, now: float) -> None:
        cutoff = now - self.window_sec
        entry.attempts = [t for t in entry.attempts if t > cutoff]

    def check(self, ip: str, scope: str = "default") -> RateLimitResult:
        """Check whether ip is allowed to proceed."""
        if self._is_exempt(ip):
            return RateLimitResult(allowed=True, remaining=self.max_attempts, retry_after_sec=0)

        key = self._key(ip, scope)
        now = time.monotonic()

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return RateLimitResult(allowed=True, remaining=self.max_attempts, retry_after_sec=0)

            # Still locked out?
            if entry.locked_until and now < entry.locked_until:
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    retry_after_sec=entry.locked_until - now,
                )

            # Lockout expired — clear it
            if entry.locked_until and now >= entry.locked_until:
                entry.locked_until = 0.0
                entry.attempts = []

            self._slide_window(entry, now)
            remaining = max(0, self.max_attempts - len(entry.attempts))
            return RateLimitResult(allowed=remaining > 0, remaining=remaining, retry_after_sec=0)

    def record(self, ip: str, scope: str = "default") -> None:
        """Record a request (or failed attempt) for ip."""
        if self._is_exempt(ip):
            return

        key = self._key(ip, scope)
        now = time.monotonic()

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _Entry()
                self._entries[key] = entry

            if entry.locked_until and now < entry.locked_until:
                return  # already blocked

            self._slide_window(entry, now)
            entry.attempts.append(now)

            if len(entry.attempts) >= self.max_attempts:
                entry.locked_until = now + self.lockout_sec

    def reset(self, ip: str, scope: str = "default") -> None:
        """Reset rate-limit state for ip (e.g. after successful paid request)."""
        key = self._key(ip, scope)
        with self._lock:
            self._entries.pop(key, None)

    def size(self) -> int:
        """Number of tracked IPs."""
        with self._lock:
            return len(self._entries)

    def prune(self) -> int:
        """Remove expired entries. Returns number removed."""
        now = time.monotonic()
        removed = 0
        with self._lock:
            keys_to_remove = []
            for key, entry in self._entries.items():
                if entry.locked_until and now < entry.locked_until:
                    continue
                self._slide_window(entry, now)
                if not entry.attempts:
                    keys_to_remove.append(key)
            for key in keys_to_remove:
                del self._entries[key]
                removed += 1
        return removed

    def _prune_loop(self) -> None:
        while True:
            time.sleep(60)
            self.prune()


def create_rate_limiter(
    max_attempts: int = 10,
    window_sec: float = 60.0,
    lockout_sec: float = 300.0,
) -> RateLimiter:
    """Factory matching OpenClaw's createAuthRateLimiter pattern."""
    return RateLimiter(
        max_attempts=max_attempts,
        window_sec=window_sec,
        lockout_sec=lockout_sec,
    )
