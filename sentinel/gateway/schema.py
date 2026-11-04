"""Schemas for Sentinel Gateway decisions, guards, and audit trail."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DecisionAction(StrEnum):
    allow = "allow"
    block = "block"
    rewrite = "rewrite"
    escalate = "escalate"


class GuardType(StrEnum):
    input = "input"
    retrieval = "retrieval"
    tool = "tool"
    output = "output"


class Decision(BaseModel):
    action: DecisionAction
    guard: GuardType
    reason: str
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    modified_payload: Any = None


class AuditRecord(BaseModel):
    id: str
    timestamp: str
    guard: GuardType
    action: DecisionAction
    reason: str
    target: str = ""
    latency_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
