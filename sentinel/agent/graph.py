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
        is_final_step = step > state.max_steps
        avail_tools = [] if is_final_step else tools

        try:
            call_res = call("answer", state.messages, runtime=runtime, tools=avail_tools)
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

        # If on final step, ignore any tool calls the model attempted
        tool_calls_to_record = []
        if not is_final_step and call_res.tool_calls:
            tool_calls_to_record = [
                {
                    "name": tc.name,
                    "args": tc.arguments,
                    "id": f"call_{step}_{i}",
                    "type": "tool_call",
                }
                for i, tc in enumerate(call_res.tool_calls)
            ]

        # Format assistant message
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": content_text}
        if tool_calls_to_record:
            assistant_msg["tool_calls"] = tool_calls_to_record
        new_messages.append(assistant_msg)

        # Check for citations in text
        citations = list(state.citations)
        if "[" in content_text and "]" in content_text:
            import re

            found = re.findall(r"\[([A-Za-z0-9_\-\.]+\.(?:pdf|md)[^\]]*)\]", content_text)
            for c in found:
                citations.append({"citation": c, "step": step})

        # Determine status and final answer
        if is_final_step:
            status = "completed"
            if call_res.tool_calls or not content_text.strip():
                final_ans = "Execution limit reached: Maximum steps exceeded."
            else:
                final_ans = content_text.strip()
        else:
            status = state.status
            final_ans = content_text if not tool_calls_to_record else state.final_answer

        return {
            "messages": new_messages,
            "current_step": step,
            "tokens_used": tokens,
            "model_used": model_name,
            "citations": citations,
            "final_answer": final_ans,
            "status": status,
        }

    def tool_node(state: AgentState) -> dict[str, Any]:
        last_msg = state.messages[-1] if state.messages else {}
        tool_calls = last_msg.get("tool_calls") or []
        new_messages = list(state.messages)
        trace = list(state.tool_trace)
        decisions = list(state.gateway_decisions)
        guard_time = 0.0

        for i, tc in enumerate(tool_calls):
            tname = tc.get("name")
            targs = tc.get("args") or {}
            call_id = tc.get("id") or f"call_{state.current_step}_{i}"
            tool_entry = {"tool": tname, "args": targs, "step": state.current_step, "id": call_id}

            # If gateway is ON and provided, check tool guard
            if state.gateway_mode == "on" and gateway is not None:
                t_tool = time.perf_counter()
                decision = gateway.check_tool(tname, targs, state)
                guard_time += (time.perf_counter() - t_tool) * 1000
                decisions.append(decision.model_dump())
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
                    import uuid

                    op_id = decision.metadata.get("operation_id") or f"op_{uuid.uuid4().hex[:8]}"
                    decision.metadata["operation_id"] = op_id
                    decision.metadata["tool"] = tname
                    decision.metadata["args"] = targs
                    # Replace last decision in decisions list with updated metadata
                    if decisions:
                        decisions[-1]["metadata"]["operation_id"] = op_id
                        decisions[-1]["metadata"]["tool"] = tname
                        decisions[-1]["metadata"]["args"] = targs
                    tool_entry["status"] = "awaiting_approval"
                    tool_entry["operation_id"] = op_id
                    tool_entry["result"] = (
                        f"Paused: Write operation '{tname}' requires human operator approval. "
                        f"Operation ID: {op_id}"
                    )
                    trace.append(tool_entry)

                    from sentinel.gateway.approvals import register_pending_approval

                    register_pending_approval(
                        operation_id=op_id,
                        tool_name=tname,
                        args=targs,
                        call_id=call_id,
                        current_state=state,
                    )

                    return {
                        "messages": new_messages,
                        "tool_trace": trace,
                        "gateway_decisions": decisions,
                        "guard_latency_ms": state.guard_latency_ms + guard_time,
                        "status": "awaiting_approval",
                        "status_reason": (
                            f"Paused at write operation '{tname}' (ID: {op_id}). "
                            "Awaiting human approval."
                        ),
                        "final_answer": (
                            f"Operation '{tname}' requires human operator authorization. "
                            f"Awaiting approval for operation ID '{op_id}'."
                        ),
                    }

            # Execute tool in unprotected mode (or if gateway allowed)
            tool_fn = tool_map.get(tname)
            if not tool_fn:
                result_text = f"Error: Tool '{tname}' not recognized"
            else:
                try:
                    result_text = tool_fn.invoke(targs)
                    # If docs_search and gateway is ON, inspect retrieved chunks
                    if (
                        state.gateway_mode == "on"
                        and gateway is not None
                        and tname == "docs_search"
                    ):
                        try:
                            import json

                            parsed_chunks = (
                                json.loads(result_text)
                                if isinstance(result_text, str)
                                else result_text
                            )
                            if isinstance(parsed_chunks, list):
                                t_ret = time.perf_counter()
                                ret_dec, cleaned = gateway.pass_retrieval(
                                    parsed_chunks, user_access="internal"
                                )
                                guard_time += (time.perf_counter() - t_ret) * 1000
                                decisions.append(ret_dec.model_dump())
                                if len(cleaned) < len(parsed_chunks):
                                    tool_entry["quarantined"] = len(parsed_chunks) - len(cleaned)
                                result_text = json.dumps(cleaned)
                        except Exception as err:
                            logger.warning(f"Retrieval guard parsing failed: {err}")
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

        return {
            "messages": new_messages,
            "tool_trace": trace,
            "gateway_decisions": decisions,
            "guard_latency_ms": state.guard_latency_ms + guard_time,
        }

    def should_continue(state: AgentState) -> str:
        if state.status in ("completed", "error", "blocked", "awaiting_approval"):
            return "finish"
        if state.current_step > state.max_steps:
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
        t_in = time.perf_counter()
        input_decision = gateway.pass_input(prompt)
        initial_state.guard_latency_ms += (time.perf_counter() - t_in) * 1000
        initial_state.gateway_decisions.append(input_decision.model_dump())
        if input_decision.action == "block":
            initial_state.status = "blocked"
            initial_state.status_reason = f"Input Guard Blocked: {input_decision.reason}"
            initial_state.final_answer = (
                f"Security Gateway: Request blocked. Reason: {input_decision.reason}"
            )
            initial_state.latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            initial_state.guard_latency_ms = round(initial_state.guard_latency_ms, 2)
            return initial_state

    app = _create_agent_graph(rt, gateway=gateway)
    rec_limit = max_steps * 3 + 5
    res = app.invoke(initial_state, config={"recursion_limit": rec_limit})

    final_state = AgentState.model_validate(res)
    final_state.latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    # In gateway mode ON, intercept output guard
    if gateway_mode == "on" and gateway is not None and final_state.final_answer:
        t_out = time.perf_counter()
        output_decision = gateway.pass_output(final_state.final_answer, final_state)
        final_state.guard_latency_ms += (time.perf_counter() - t_out) * 1000
        final_state.gateway_decisions.append(output_decision.model_dump())
        if output_decision.action == "block":
            final_state.status = "blocked"
            final_state.status_reason = f"Output Guard Blocked: {output_decision.reason}"
            final_state.final_answer = (
                f"Security Gateway: Output suppressed. Reason: {output_decision.reason}"
            )

    final_state.guard_latency_ms = round(final_state.guard_latency_ms, 2)
    return final_state
