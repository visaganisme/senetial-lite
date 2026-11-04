"""Circuit breaker: 3 consecutive failures per provider:model -> open for 10 minutes."""

from __future__ import annotations

import threading
import time


class CircuitBreaker:
    def __init__(self, threshold: int = 3, cool_s: float = 600.0):
        self.threshold = threshold
        self.cool_s = cool_s
        self._fails: dict[str, int] = {}
        self._open_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_open(self, key: str) -> bool:
        with self._lock:
            return time.monotonic() < self._open_until.get(key, 0.0)

    def cooldown_left(self, key: str) -> float:
        with self._lock:
            return max(0.0, self._open_until.get(key, 0.0) - time.monotonic())

    def record_success(self, key: str) -> None:
        with self._lock:
            self._fails[key] = 0
            self._open_until.pop(key, None)

    def record_failure(self, key: str) -> None:
        with self._lock:
            fails = self._fails.get(key, 0) + 1
            self._fails[key] = fails
            if fails >= self.threshold:
                self._open_until[key] = time.monotonic() + self.cool_s
