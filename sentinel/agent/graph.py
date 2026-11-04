"""Victim Agent LangGraph workflow.
Implements route -> retrieve / call_tool -> draft -> finish.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from langgraph.graph import END, StateGraph

from sentinel.agent.prompts import SYSTEM_PROMPT
from sentinel.agent.state import AgentState
from sentinel.mcp_servers.tools import get_victim_tools
from sentinel.router.router import Runtime, call

logger = logging.getLogger(__name__)


def _get_tool_map():
    tools = get_victim_tools()
    mapping = {t.name: t for t in tools}
    # Add common aliases
    if "notes_tasks_write" in mapping:
        mapping["save_note"] = mapping["notes_tasks_write"]
    if "notes_tasks_read" in mapping:
        mapping["get_note"] = mapping["notes_tasks_read"]
    if "notes_tasks_list" in mapping:
        mapping["get_all_notes"] = mapping["notes_tasks_list"]
    if "notes_tasks_delete" in mapping:
        mapping["remove_note"] = mapping["notes_tasks_delete"]
    return mapping


def _create_agent_graph(runtime: Runtime, gateway: Any | None = None):
    tool_map = _get_tool_map()
    tools = get_victim_tools()

    def start_node(state: AgentState) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": state.user_query},
        ]
        return {"messages": messages, "current_step": 0, "status": "running"}

    def model_node(state: AgentState) -> dict[str, Any]:
        step = state.current_step + 1
        if step > state.max_steps:
            return {
                "current_step": step,
                "status": "completed",
                "final_answer": "Execution limit reached: Maximum steps exceeded.",
            }

        try:
            call_res = call("answer", state.messages, runtime=runtime, tools=tools)
        except Exception as e:
            logger.error(f"Model invocation failed: {e}")
            return {
                "current_step": step,
                "status": "error",
                "status_reason": str(e),
                "final_answer": f"Error: Model invocation failed ({e})",
            }

        tokens = state.tokens_used + (
            call_res.meta.tokens_in + call_res.meta.tokens_out if call_res.meta else 0
        )
        model_name = (
            f"{call_res.meta.provider}/{call_res.meta.model}" if call_res.meta else "unknown"
        )

        new_messages = list(state.messages)
        content_text = call_res.content or ""

        # Format assistant message
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": content_text}
        if call_res.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "name": tc.name,
                    "args": tc.arguments,
                    "id": f"call_{step}_{i}",
                    "type": "tool_call",
                }
                for i, tc in enumerate(call_res.tool_calls)
            ]
        new_messages.append(assistant_msg)

        # Check for citations in text
        citations = list(state.citations)
        if "[" in content_text and "]" in content_text:
            import re

            found = re.findall(r"\[([A-Za-z0-9_\-\.]+\.(?:pdf|md)[^\]]*)\]", content_text)
            for c in found:
                citations.append({"citation": c, "step": step})

        return {
            "messages": new_messages,
            "current_step": step,
            "tokens_used": tokens,
            "model_used": model_name,
            "citations": citations,
            "final_answer": content_text if not call_res.tool_calls else state.final_answer,
        }

    def tool_node(state: AgentState) -> dict[str, Any]:
        last_msg = state.messages[-1] if state.messages else {}
        tool_calls = last_msg.get("tool_calls") or []
        new_messages = list(state.messages)
        trace = list(state.tool_trace)

        for i, tc in enumerate(tool_calls):
            tname = tc.get("name")
            targs = tc.get("args") or {}
            call_id = tc.get("id") or f"call_{state.current_step}_{i}"
            tool_entry = {"tool": tname, "args": targs, "step": state.current_step, "id": call_id}

            # If gateway is ON and provided, check tool guard
            if state.gateway_mode == "on" and gateway is not None:
                decision = gateway.check_tool(tname, targs, state)
                if decision.action == "block":
                    result_text = f"Gateway Blocked: {decision.reason}"
                    tool_entry["status"] = "blocked"
                    tool_entry["result"] = result_text
                    trace.append(tool_entry)
                    new_messages.append(
                        {
                            "role": "tool",
                            "name": tname,
                            "content": result_text,
                            "tool_call_id": call_id,
                        }
                    )
                    continue
                if decision.action == "escalate":
                    result_text = f"Gateway Escalated (Approval Required): {decision.reason}"
                    tool_entry["status"] = "escalated"
                    tool_entry["result"] = result_text
                    trace.append(tool_entry)
                    new_messages.append(
                        {
                            "role": "tool",
                            "name": tname,
                            "content": result_text,
                            "tool_call_id": call_id,
                        }
                    )
                    continue

            # Execute tool in unprotected mode (or if gateway allowed)
            tool_fn = tool_map.get(tname)
            if not tool_fn:
                result_text = f"Error: Tool '{tname}' not recognized"
            else:
                try:
                    result_text = tool_fn.invoke(targs)
                except Exception as e:
                    result_text = f"Error executing tool {tname}: {e}"

            tool_entry["status"] = "executed"
            tool_entry["result"] = str(result_text)[:500]
            trace.append(tool_entry)
            new_messages.append(
                {
                    "role": "tool",
                    "name": tname,
                    "content": str(result_text),
                    "tool_call_id": call_id,
                }
            )

        return {"messages": new_messages, "tool_trace": trace}

    def should_continue(state: AgentState) -> str:
        if state.status in ("completed", "error", "blocked"):
            return "finish"
        last_msg = state.messages[-1] if state.messages else {}
        if last_msg.get("tool_calls"):
            return "tools"
        return "finish"

    workflow = StateGraph(AgentState)
    workflow.add_node("start", start_node)
    workflow.add_node("model", model_node)
    workflow.add_node("tools", tool_node)

    workflow.set_entry_point("start")
    workflow.add_edge("start", "model")
    workflow.add_conditional_edges(
        "model",
        should_continue,
        {
            "tools": "tools",
            "finish": END,
        },
    )
    workflow.add_edge("tools", "model")

    return workflow.compile()


def run_agent(
    prompt: str,
    gateway_mode: str = "off",
    runtime: Runtime | None = None,
    gateway: Any | None = None,
    max_steps: int = 6,
) -> AgentState:
    """Run the victim agent workflow on a user prompt."""
    rt = runtime or Runtime.load()
    start_time = time.perf_counter()

    initial_state = AgentState(
        user_query=prompt,
        gateway_mode="on" if gateway_mode == "on" else "off",
        max_steps=max_steps,
    )

    # In gateway mode ON, intercept input first
    if gateway_mode == "on" and gateway is not None:
        input_decision = gateway.pass_input(prompt)
        initial_state.gateway_decisions.append(input_decision.model_dump())
        if input_decision.action == "block":
            initial_state.status = "blocked"
            initial_state.status_reason = f"Input Guard Blocked: {input_decision.reason}"
            initial_state.final_answer = (
                f"Security Gateway: Request blocked. Reason: {input_decision.reason}"
            )
            initial_state.latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return initial_state

    app = _create_agent_graph(rt, gateway=gateway)
    res = app.invoke(initial_state)

    final_state = AgentState.model_validate(res)
    final_state.latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    # In gateway mode ON, intercept output guard
    if gateway_mode == "on" and gateway is not None and final_state.final_answer:
        output_decision = gateway.pass_output(final_state.final_answer, final_state)
        final_state.gateway_decisions.append(output_decision.model_dump())
        if output_decision.action == "block":
            final_state.status = "blocked"
            final_state.status_reason = f"Output Guard Blocked: {output_decision.reason}"
            final_state.final_answer = (
                f"Security Gateway: Output suppressed. Reason: {output_decision.reason}"
            )

    return final_state
