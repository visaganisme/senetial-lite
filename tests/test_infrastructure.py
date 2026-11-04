from __future__ import annotations

import time

import sentinel.router.limiter as limiter_mod
from sentinel.router.breaker import CircuitBreaker
from sentinel.router.cache import OnDiskCache
from sentinel.router.limiter import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


def test_rate_limiter_spaces_requests_per_provider(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(limiter_mod.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(limiter_mod.time, "sleep", clock.sleep)
    rl = RateLimiter({"prov": 60})  # one request per second

    assert rl.acquire("prov") == 0.0  # first request immediate
    assert rl.acquire("prov") == 1.0  # then spaced 1/s
    assert rl.acquire("prov") == 1.0
    assert clock.now == 2.0  # slept proportional to spacing


def test_rate_limiter_providers_independent(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(limiter_mod.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(limiter_mod.time, "sleep", clock.sleep)
    rl = RateLimiter({"a": 60})  # b unknown -> conservative 6s spacing

    assert rl.acquire("a") == 0.0
    assert rl.acquire("b") == 0.0
    assert rl.acquire("a") == 1.0


def test_breaker_opens_after_three_consecutive_failures():
    br = CircuitBreaker(threshold=3, cool_s=600.0)
    assert not br.is_open("m")
    br.record_failure("m")
    br.record_failure("m")
    assert not br.is_open("m")  # threshold not reached
    br.record_failure("m")
    assert br.is_open("m")  # 3 consecutive failures -> open
    assert 599 < br.cooldown_left("m") <= 600


def test_breaker_success_resets():
    br = CircuitBreaker()
    br.record_failure("m")
    br.record_failure("m")
    br.record_success("m")
    br.record_failure("m")
    br.record_failure("m")
    assert not br.is_open("m")  # consecutive count, not cumulative
    br.record_failure("m")
    assert br.is_open("m")


def test_on_disk_cache_roundtrip(tmp_path):
    cache = OnDiskCache(tmp_path, ttl_s=3600)
    payload = {"m": ["user: hi"]}
    assert cache.get("chat", payload) is None
    cache.set("chat", payload, {"content": "cached-answer"})
    assert cache.get("chat", payload) == {"content": "cached-answer"}
    assert cache.get("chat", {"m": ["different"]}) is None


def test_on_disk_cache_ttl_expiry(tmp_path, monkeypatch):
    import sentinel.router.cache as cache_mod

    cache = OnDiskCache(tmp_path, ttl_s=10.0)
    cache.set("ns", {"k": 1}, {"v": 1})
    assert cache.get("ns", {"k": 1}) == {"v": 1}
    real_time = time.time  # noqa: F841 - kept for clarity of the freeze below
    monkeypatch.setattr(cache_mod.time, "time", lambda: real_time() + 3600)
    assert cache.get("ns", {"k": 1}) is None  # expired
