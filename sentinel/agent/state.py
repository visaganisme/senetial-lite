"""Agent state schema for the Sentinel victim agent LangGraph workflow."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentState(BaseModel):
    user_query: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    current_step: int = 0
    max_steps: int = 6
    tokens_used: int = 0
    max_tokens: int = 4000
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    final_answer: str = ""
    model_used: str = ""
    latency_ms: float = 0.0
    guard_latency_ms: float = 0.0
    gateway_mode: Literal["on", "off"] = "off"
    gateway_decisions: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["running", "completed", "error", "blocked", "awaiting_approval"] = "running"
    status_reason: str = ""
