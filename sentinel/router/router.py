"""Role router: call a role's chain in order with fallback on transient/invalid failure.
Every attempt is logged (cache/call_log.jsonl) with provider, model, latency, tokens."""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from typing import Any

import sentinel.config as cfg
from sentinel.router.breaker import CircuitBreaker
from sentinel.router.cache import OnDiskCache
from sentinel.router.factory import MissingKey, make_model
from sentinel.router.limiter import RateLimiter
from sentinel.router.schema import (
    CallMeta,
    CallResult,
    ChainEntry,
    ModelsConfig,
    ProviderLimit,
    RunBudget,
    ToolCall,
)

TRANSIENT_MARKERS = (
    "rate limit",
    "ratelimit",
    "quota",
    "429",
    "timeout",
    "timed out",
    "overloaded",
    "over capacity",
    "502",
    "503",
    "504",
    "unavailable",
    "capacity",
)
TRANSIENT_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


class NoModelAvailable(RuntimeError):
    pass


class Runtime:
    """Shared state for a run: config + limiter + breaker + cache."""

    def __init__(self, config: ModelsConfig, *, use_cache: bool = True):
        self.config = config
        self.limiter = RateLimiter({p: limit.rpm for p, limit in config.limits.items()})
        self.breaker = CircuitBreaker()
        self.cache = OnDiskCache(cfg.CACHE_DIR / "responses") if use_cache else None

    @classmethod
    def load(cls, *, use_cache: bool = True) -> Runtime:
        from sentinel.router.schema import load_models_config

        return cls(load_models_config(), use_cache=use_cache)

    def limit_for(self, provider: str) -> ProviderLimit:
        return self.config.limits.get(provider, ProviderLimit())


def expires(exc: BaseException) -> str | None:
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    if isinstance(status, int) and status in TRANSIENT_CODES:
        return "transient"
    msg = str(exc).lower()
    if any(m in msg for m in TRANSIENT_MARKERS):
        return "transient"
    if isinstance(exc, MissingKey):
        return "no_key"
    if isinstance(status, int):
        return f"http_{status}"
    return "provider_error"


def _log_event(runtime: Runtime, event: dict[str, Any]) -> None:
    event["ts"] = time.time()
    log = cfg.CACHE_DIR / "call_log.jsonl"
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")


def text_content(msg: Any) -> str | None:
    """LangChain message content may be str or a list of typed blocks; normalize to text."""
    c = getattr(msg, "content", None)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [
            b.get("text")
            for b in c
            if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
        ]
        return "".join(parts) or None
    return None


def _result_from_message(entry: ChainEntry, msg: Any, latency_ms: int, attempt: int) -> CallResult:
    usage = getattr(msg, "usage_metadata", None) or {}
    meta = CallMeta(
        provider=entry.provider,
        model=entry.model,
        latency_ms=latency_ms,
        attempt=attempt,
        tokens_in=int(usage.get("input_tokens") or 0),
        tokens_out=int(usage.get("output_tokens") or 0),
    )
    tool_calls = [
        ToolCall(name=tc["name"], arguments=tc.get("args") or {})
        for tc in (getattr(msg, "tool_calls", None) or [])
        if tc.get("name")
    ]
    structured = None
    content = text_content(msg)
    if not tool_calls and content:
        from sentinel.router.schema import extract_json

        try:
            structured = extract_json(content)
        except (ValueError, json.JSONDecodeError):
            structured = None
    return CallResult(
        content=content,
        tool_calls=tool_calls,
        structured=structured,
        meta=meta,
    )


def call(
    role: str,
    messages: list[dict[str, str]] | list[Any],
    *,
    runtime: Runtime,
    tools: list[dict[str, Any]] | None = None,
    check: Callable[[CallResult], str | None] | None = None,
    cache_ns: str = "chat",
    budget: RunBudget | None = None,
) -> CallResult:
    """Try the role chain in order. Returns the first success; validates via `check`.

    Fallback triggers: rate limit, timeout, server error, missing key, invalid model id,
    `check(result) -> reason str` failure (invalid structured output / failed tool call).
    """
    entries = list(runtime.config.roles.get(role, []))
    if not entries:
        raise NoModelAvailable(f"role {role!r} has no chain in models.yaml")
    last_err = ""
    for entry in entries:
        if runtime.breaker.is_open(entry.key):
            left = runtime.breaker.cooldown_left(entry.key)
            _log_event(
                runtime,
                {"event": "breaker_skip", "role": role, "model": entry.key, "cool_s": round(left)},
            )
            continue
        ok, result, err = _try_entry(
            entry,
            role=role,
            messages=messages,
            tools=tools,
            runtime=runtime,
            check=check,
            cache_ns=cache_ns,
            budget=budget,
        )
        if ok:
            return result
        last_err = err
    raise NoModelAvailable(f"all models failed for role {role!r}: {last_err}")


def _try_entry(
    entry: ChainEntry,
    *,
    role: str,
    messages: Any,
    tools: list[dict[str, Any]] | None,
    runtime: Runtime,
    check: Callable[[CallResult], str | None] | None,
    cache_ns: str,
    budget: RunBudget | None,
) -> tuple[bool, CallResult, str]:
    limit = runtime.limit_for(entry.provider)
    cache_payload = {"m": [str(m) for m in messages]} if tools is None else None
    if runtime.cache and cache_payload:
        cached = runtime.cache.get(cache_ns, cache_payload)
        if cached:
            return True, CallResult.model_validate(cached), ""

    runtime.limiter.acquire(entry.provider)
    try:
        model = make_model(entry, timeout_s=limit.timeout_s)  # MissingKey -> fallback
    except Exception as exc:  # noqa: BLE001 - constructor failures feed the chain
        runtime.breaker.record_failure(entry.key)
        _log_event(
            runtime,
            {
                "event": "fail",
                "role": role,
                "provider": entry.provider,
                "model": entry.model,
                "attempt": 0,
                "error": str(exc)[:300],
            },
        )
        return False, _failed_meta(entry, 0, str(exc)), f"{type(exc).__name__}: {exc}"
    last_err = ""
    for attempt in range(max(1, limit.retries)):
        try:
            start = time.perf_counter()
            msg = model.bind_tools(tools).invoke(messages) if tools else model.invoke(messages)
            latency_ms = int((time.perf_counter() - start) * 1000)
            result = _result_from_message(entry, msg, latency_ms, attempt + 1)
            if budget is not None:
                budget.account_tokens(result.meta.tokens_in + result.meta.tokens_out)
            if check is not None:
                reason = check(result)  # returns None when ok
                if reason:
                    raise ValueError(f"invalid output: {reason}")
            runtime.breaker.record_success(entry.key)
            if runtime.cache and cache_payload:
                runtime.cache.set(cache_ns, cache_payload, result.model_dump())
            _log_result(runtime, result, role)
            return True, result, ""
        except Exception as exc:  # noqa: BLE001 - provider failures are data, not bugs
            last_err = f"{type(exc).__name__}: {exc}"
            runtime.breaker.record_failure(entry.key)
            _log_event(
                runtime,
                {
                    "event": "fail",
                    "role": role,
                    "provider": entry.provider,
                    "model": entry.model,
                    "attempt": attempt + 1,
                    "error": str(exc)[:300],
                },
            )
            kind = expires(exc)
            if kind == "no_key":
                return False, _failed_meta(entry, attempt + 1, str(exc)), last_err
            if kind != "transient" or attempt >= limit.retries - 1:
                return False, _failed_meta(entry, attempt + 1, str(exc)), last_err
            backoff = min(30.0, 1.5 * (2**attempt)) + random.uniform(0.25, 1.1)
            time.sleep(backoff)
    return False, _failed_meta(entry, limit.retries, last_err), last_err


def _failed_meta(entry: ChainEntry, attempt: int, err: str) -> CallResult:
    return CallResult(
        meta=CallMeta(
            provider=entry.provider,
            model=entry.model,
            latency_ms=0,
            attempt=attempt,
            ok=False,
            error=err[:400],
        ),
    )


def _log_result(runtime: Runtime, result: CallResult, role: str) -> None:
    _log_event(
        runtime,
        {
            "event": "ok",
            "role": role,
            "provider": result.meta.provider,
            "model": result.meta.model,
            "latency_ms": result.meta.latency_ms,
            "tokens_in": result.meta.tokens_in,
            "tokens_out": result.meta.tokens_out,
        },
    )


def call_structured(
    role: str,
    prompt: str,
    schema: type[Any],
    *,
    runtime: Runtime,
    budget: RunBudget | None = None,
):
    """Prompt-in-JSON-out structured call with pydantic validation as the `check`.

    Invalid structured output fails the check and moves the router to the next model
    in the chain automatically.
    """
    from sentinel.router.schema import validate_structured

    def _check(res: CallResult):
        try:
            validate_structured(res, schema)
        except ValueError as exc:
            return str(exc)
        return None

    result = call(
        role,
        [
            {"role": "system", "content": "Return ONLY a JSON object. No prose, no code fences."},
            {"role": "user", "content": prompt},
        ],
        runtime=runtime,
        check=_check,
        budget=budget,
    )
    return validate_structured(result, schema), result


__all__ = [
    "NoModelAvailable",
    "Runtime",
    "call",
    "call_structured",
    "expires",
]
