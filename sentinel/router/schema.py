"""Pydantic schemas for router configuration, calls, budgets, and probe results."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


class ChainEntry(BaseModel):
    provider: str
    model: str
    capabilities: list[str] = Field(default_factory=list)

    @field_validator("provider")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("provider must be non-empty")
        return v

    @field_validator("model")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("model must be non-empty")
        return v

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


class ProviderLimit(BaseModel):
    rpm: int = 10
    retries: int = 3
    timeout_s: float = 45.0


class ModelsConfig(BaseModel):
    roles: dict[str, list[ChainEntry]]
    limits: dict[str, ProviderLimit] = Field(default_factory=dict)

    @field_validator("roles")
    @classmethod
    def _require_answer(cls, roles: dict[str, list[ChainEntry]]) -> dict[str, list[ChainEntry]]:
        if not roles.get("answer"):
            raise ValueError("models.yaml must define at least the 'answer' role")
        return roles

    @classmethod
    def load(cls, path: str | None = None) -> ModelsConfig:
        return load_models_config(path)


class RunBudget(BaseModel):
    """Hard per-run caps. Exceeded budget aborts the run with BudgetExceeded."""

    max_tokens: int = 40_000
    max_steps: int = 25
    max_wall_s: float = 300.0
    _tokens_used: int = 0
    _steps_used: int = 0
    _started: float = time.perf_counter()

    def account_tokens(self, n: int) -> None:
        if n > 0:
            self._tokens_used += n
        if self._tokens_used > self.max_tokens:
            raise BudgetExceeded(f"token budget {self.max_tokens} exceeded ({self._tokens_used})")

    def next_step(self) -> None:
        self._steps_used += 1
        if self._steps_used > self.max_steps:
            raise BudgetExceeded(f"step budget {self.max_steps} exceeded")
        if time.perf_counter() - self._started > self.max_wall_s:
            raise BudgetExceeded(f"wall-clock budget {self.max_wall_s}s exceeded")


class BudgetExceeded(RuntimeError):
    pass


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class CallMeta(BaseModel):
    provider: str
    model: str
    latency_ms: int
    attempt: int
    ok: bool = True
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None


class CallResult(BaseModel):
    """Normalized provider response. tool_calls/structured populated when requested/parseable."""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    structured: dict[str, Any] | None = None
    meta: CallMeta


def load_models_config(path: str | None = None) -> ModelsConfig:
    import sentinel.config as cfg

    p = (cfg.BASE_DIR / path) if path else cfg.BASE_DIR / "models.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return ModelsConfig.model_validate(data)


def cache_key(namespace: str, payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(f"{namespace}|{blob}".encode()).hexdigest()


def extract_json(text: str) -> dict[str, Any]:
    """Parse the first JSON object found in text; raises ValueError on garbage."""
    if not text:
        raise ValueError("empty content")
    text = text.strip()
    # strip fenced code blocks
    if text.startswith("```"):
        text = text.removeprefix("```").removeprefix("json").strip()
        text = text.split("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    # fall back: find first {...} span
    start, depth = text.find("{"), 0
    if start == -1:
        raise ValueError(f"no JSON object found in: {text[:120]!r}")
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                parsed = json.loads(text[start : i + 1])
                if not isinstance(parsed, dict):
                    raise ValueError("json object expected")
                return parsed
    raise ValueError(f"unterminated json in: {text[:120]!r}")


def validate_structured(result: CallResult, schema: type[BaseModel]) -> Any:
    if result.structured is None:
        raise ValueError("model returned no structured payload")
    try:
        return schema.model_validate(result.structured)
    except ValidationError as exc:
        raise ValueError(f"structured output failed schema: {exc}") from exc
