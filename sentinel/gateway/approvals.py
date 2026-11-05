"""Pending approval storage for Human-in-the-Loop (HITL) tool execution."""

from __future__ import annotations

from typing import Any

PENDING_APPROVALS: dict[str, dict[str, Any]] = {}


def register_pending_approval(
    operation_id: str,
    tool_name: str,
    args: dict[str, Any],
    call_id: str,
    current_state: Any = None,
) -> None:
    """Register an operation awaiting operator approval."""
    if not operation_id:
        raise ValueError("operation_id cannot be empty")
    PENDING_APPROVALS[operation_id] = {
        "operation_id": operation_id,
        "tool_name": tool_name,
        "args": args,
        "call_id": call_id,
        "state": current_state,
    }


def get_pending_approval(operation_id: str) -> dict[str, Any] | None:
    """Retrieve details for a pending approval."""
    return PENDING_APPROVALS.get(operation_id)


def remove_pending_approval(operation_id: str) -> dict[str, Any] | None:
    """Remove and return a resolved pending approval."""
    return PENDING_APPROVALS.pop(operation_id, None)


def clear_pending_approvals() -> None:
    """Clear all pending approvals (used primarily in tests)."""
    PENDING_APPROVALS.clear()

