"""Central per-provider spacing rate limiter (requests/minute cap). Thread-safe."""

from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, rpm: dict[str, int]):
        self._interval: dict[str, float] = {p: 60.0 / max(1, r) for p, r in rpm.items()}
        self._next_slot: dict[str, float] = {}
        self._lock = threading.Lock()

    def acquire(self, provider: str) -> float:
        """Reserve a slot for `provider`; sleeps until it, returns seconds waited."""
        interval = self._interval.get(provider, 6.0)
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot.get(provider, 0.0))
            self._next_slot[provider] = slot + interval
        wait = max(0.0, slot - now)
        if wait > 0:
            time.sleep(wait)
        return wait
