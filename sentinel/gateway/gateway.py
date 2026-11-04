"""Sentinel Security Gateway for AI Agents.
Provides interposable Input, Retrieval, Tool, and Output Guards with Audit Logging.
"""

from __future__ import annotations

import time
from typing import Any

from sentinel.gateway.audit import AuditLogger
from sentinel.gateway.input_guard import InputGuard
from sentinel.gateway.output_guard import OutputGuard
from sentinel.gateway.retrieval_guard import RetrievalGuard
from sentinel.gateway.schema import Decision, GuardType
from sentinel.gateway.tool_guard import ToolGuard


class SentinelGateway:
    def __init__(
        self,
        audit_logger: AuditLogger | None = None,
        use_classifier: bool = True,
        require_write_approval: bool = True,
        min_retrieval_score: float = 0.25,
        max_steps: int = 6,
    ):
        self.audit = audit_logger or AuditLogger()
        self.input_guard = InputGuard(use_classifier=use_classifier)
        self.retrieval_guard = RetrievalGuard(min_score=min_retrieval_score)
        self.tool_guard = ToolGuard(
            require_write_approval=require_write_approval, max_steps=max_steps
        )
        self.output_guard = OutputGuard(check_safety=True)

    def pass_input(self, prompt: str) -> Decision:
        """Evaluate input message through the Input Guard."""
        start = time.perf_counter()
        decision = self.input_guard.check(prompt)
        lat_ms = (time.perf_counter() - start) * 1000
        self.audit.record(GuardType.input, decision, target=prompt, latency_ms=lat_ms)
        return decision

    def pass_retrieval(
        self,
        chunks: list[dict[str, Any]],
        user_access: str = "internal",
    ) -> tuple[Decision, list[dict[str, Any]]]:
        """Evaluate retrieved document chunks through the Retrieval Guard."""
        start = time.perf_counter()
        decision, filtered_chunks = self.retrieval_guard.check(chunks, user_access=user_access)
        lat_ms = (time.perf_counter() - start) * 1000
        self.audit.record(
            GuardType.retrieval,
            decision,
            target=f"chunks_count={len(chunks)}",
            latency_ms=lat_ms,
        )
        return decision, filtered_chunks

    def check_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        state: Any = None,
        pre_approved: bool = False,
    ) -> Decision:
        """Evaluate agent tool call through the Tool Guard."""
        start = time.perf_counter()
        decision = self.tool_guard.check(
            tool_name=tool_name, args=args, state=state, pre_approved=pre_approved
        )
        lat_ms = (time.perf_counter() - start) * 1000
        self.audit.record(
            GuardType.tool,
            decision,
            target=f"{tool_name}({args})",
            latency_ms=lat_ms,
        )
        return decision

    def pass_output(self, text: str, state: Any = None) -> Decision:
        """Evaluate final response through the Output Guard."""
        start = time.perf_counter()
        decision = self.output_guard.check(text, state=state)
        lat_ms = (time.perf_counter() - start) * 1000
        self.audit.record(GuardType.output, decision, target=text, latency_ms=lat_ms)
        return decision
