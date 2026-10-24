"""Small in-memory sliding-window rate limiter.

Keyed by client IP, but the IP is replaced with an HMAC-SHA256 under a random per-process salt
before it's used, so raw IPs aren't held in memory and the keys can't be reversed after a
restart. Nothing is stored in a database. Resets when the server restarts, which is fine for a
single-instance demo. Behind a proxy, run uvicorn with --proxy-headers so request.client.host
is the real client IP.
"""

import hashlib
import hmac
import secrets
import threading
import time
from collections import deque

SWEEP_EVERY_CALLS = 500
SWEEP_AT_SIZE = 10_000


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, clock=time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._salt = secrets.token_bytes(32)
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def _hash(self, key: str) -> str:
        return hmac.new(self._salt, key.encode("utf-8"), hashlib.sha256).hexdigest()

    def allow(self, key: str) -> bool:
        hashed = self._hash(key)
        now = self._clock()
        with self._lock:
            self._calls += 1
            if self._calls % SWEEP_EVERY_CALLS == 0 or len(self._hits) >= SWEEP_AT_SIZE:
                self._sweep(now)
            hits = self._hits.setdefault(hashed, deque())
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def refund(self, key: str) -> None:
        """Give back one hit recorded by allow(), e.g. after a successful sign-in.

        Lets callers reserve an attempt atomically with allow() before doing the work, so
        concurrent requests can't all pass a separate check and exceed the limit.
        """
        hashed = self._hash(key)
        with self._lock:
            hits = self._hits.get(hashed)
            if hits:
                hits.pop()
                if not hits:
                    del self._hits[hashed]

    def is_limited(self, key: str) -> bool:
        """True when `key` is at the limit. Doesn't record a hit (for "count failures only" use)."""
        hashed = self._hash(key)
        now = self._clock()
        with self._lock:
            hits = self._hits.get(hashed)
            if not hits:
                return False
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            return len(hits) >= self.limit

    def _sweep(self, now: float) -> None:
        """Drop keys whose newest hit is outside the window, so one-off visitors don't pile up."""
        for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]:
            del self._hits[k]

    def sweep(self) -> None:
        with self._lock:
            self._sweep(self._clock())

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
