"""Tool Guard: Tool Allowlists, Pydantic Argument Validation, HITL Write Approval, and Budgets."""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from sentinel.gateway.schema import Decision, DecisionAction, GuardType
from sentinel.mcp_servers.tools import (
    DeleteNoteInput,
    DocsSearchInput,
    EngCalcInput,
    ReadNoteInput,
    WriteNoteInput,
)

ALLOWED_TOOLS = {
    "docs_search": DocsSearchInput,
    "eng_calc": EngCalcInput,
    "notes_tasks_write": WriteNoteInput,
    "save_note": WriteNoteInput,
    "notes_tasks_read": ReadNoteInput,
    "get_note": ReadNoteInput,
    "notes_tasks_list": None,
    "get_all_notes": None,
    "notes_tasks_delete": DeleteNoteInput,
    "remove_note": DeleteNoteInput,
}

WRITE_OPERATIONS = {
    "notes_tasks_write",
    "save_note",
    "notes_tasks_delete",
    "remove_note",
}

DANGEROUS_ARG_PATTERNS = [
    r"\.\.[/\\]",  # Path traversal
    r"(?i)(c:|/windows|/system32|/etc/)",  # OS root escapes
    r"(?i)(rm\s+-rf|del\s+/f|format\s+[a-z]:)",  # Shell destructive commands
    r"(?i)(__import__|subprocess|popen|exec\(|eval\()",  # Python code injection
]


class ToolGuard:
    def __init__(self, require_write_approval: bool = True, max_steps: int = 6):
        self.require_write_approval = require_write_approval
        self.max_steps = max_steps

    def check(
        self,
        tool_name: str,
        args: dict[str, Any],
        state: Any = None,
        pre_approved: bool = False,
    ) -> Decision:
        # 1. Tool allowlist check
        if tool_name not in ALLOWED_TOOLS:
            return Decision(
                action=DecisionAction.block,
                guard=GuardType.tool,
                reason=f"Tool '{tool_name}' is not in the authorized tool allowlist",
                confidence=1.0,
                metadata={"tool": tool_name},
            )

        # 2. Argument safety scan
        args_str = str(args)
        for pattern in DANGEROUS_ARG_PATTERNS:
            if re.search(pattern, args_str):
                return Decision(
                    action=DecisionAction.block,
                    guard=GuardType.tool,
                    reason=f"Dangerous payload detected in tool arguments (matched {pattern})",
                    confidence=0.99,
                    metadata={"tool": tool_name, "pattern": pattern},
                )

        # 3. Pydantic argument schema validation
        schema_cls = ALLOWED_TOOLS[tool_name]
        if schema_cls is not None:
            try:
                schema_cls.model_validate(args)
            except ValidationError as ve:
                return Decision(
                    action=DecisionAction.block,
                    guard=GuardType.tool,
                    reason=f"Tool argument schema validation failed: {ve}",
                    confidence=1.0,
                    metadata={"tool": tool_name, "validation_error": str(ve)},
                )

        # 4. Budget check: max step bounds
        current_step = getattr(state, "current_step", 0) if state else 0
        if current_step >= self.max_steps:
            return Decision(
                action=DecisionAction.block,
                guard=GuardType.tool,
                reason=f"Step budget exceeded ({current_step + 1} > {self.max_steps})",
                confidence=1.0,
                metadata={"current_step": current_step, "max_steps": self.max_steps},
            )

        # 5. Human-in-the-Loop Write Approval
        if self.require_write_approval and tool_name in WRITE_OPERATIONS and not pre_approved:
            return Decision(
                action=DecisionAction.escalate,
                guard=GuardType.tool,
                reason=f"Write operation '{tool_name}' requires explicit operator approval",
                confidence=1.0,
                metadata={"tool": tool_name, "args": args},
            )

        return Decision(
            action=DecisionAction.allow,
            guard=GuardType.tool,
            reason=f"Tool call '{tool_name}' authorized",
            confidence=1.0,
            metadata={"tool": tool_name},
        )
