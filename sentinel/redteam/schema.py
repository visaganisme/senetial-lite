"""Pydantic schemas for Sentinel red-team attack evaluation and benchmarking."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AttackCategory(StrEnum):
    direct_injection = "direct_injection"
    poisoned_doc = "poisoned_doc"
    tool_abuse = "tool_abuse"
    exfiltration = "exfiltration"
    token_burn = "token_burn"


class GatewayAction(StrEnum):
    allow = "allow"
    block = "block"
    rewrite = "rewrite"
    escalate = "escalate"


class AttackCase(BaseModel):
    id: str
    category: AttackCategory
    subcategory: str
    split: Literal["dev", "heldout"] = "dev"
    payload: str
    target_role: str = "answer"
    expected_gateway_action: GatewayAction = GatewayAction.block
    expected_behavior: str
    compromise_indicators: list[str] = Field(default_factory=list)
    mitigation_indicators: list[str] = Field(default_factory=list)


class BenignQuestion(BaseModel):
    id: str
    question: str
    category: str = "factual"
    expected: list[dict[str, Any]] = Field(default_factory=list)
    refuse: bool = False


class AttackExecution(BaseModel):
    run_index: int
    compromised: bool
    blocked: bool
    latency_ms: float = 0.0
    tokens_used: int = 0
    agent_output: str = ""
    gateway_decision: GatewayAction | None = None
    reason: str = ""


class AttackResult(BaseModel):
    attack_id: str
    category: AttackCategory
    split: Literal["dev", "heldout"]
    model_id: str
    mode: Literal["unprotected", "protected"]
    executions: list[AttackExecution] = Field(default_factory=list)
    breach_rate: float = 0.0
    block_rate: float = 0.0
    avg_latency_ms: float = 0.0


class RedTeamRunSummary(BaseModel):
    run_id: str
    timestamp: str
    model_id: str
    mode: Literal["unprotected", "protected"]
    split: str
    total_attacks: int
    overall_breach_rate: float
    overall_block_rate: float
    false_positive_rate: float = 0.0
    avg_latency_ms: float = 0.0
    by_category: dict[str, dict[str, float]] = Field(default_factory=dict)
