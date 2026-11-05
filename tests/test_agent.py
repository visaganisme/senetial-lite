"""Tests for Phase-5 victim agent LangGraph workflow."""

from pydantic import BaseModel

from sentinel.agent.graph import run_agent
from sentinel.agent.state import AgentState
from sentinel.router.schema import CallMeta, CallResult, ChainEntry, ModelsConfig, ProviderLimit
from tests.fakes import FakeMsg


class DummyGatewayDecision(BaseModel):
    action: str
    reason: str


class MockGateway:
    def __init__(self, block_input=False, block_tool=False):
        self.block_input = block_input
        self.block_tool = block_tool

    def pass_input(self, prompt: str):
        if self.block_input:
            return DummyGatewayDecision(action="block", reason="Prompt injection detected")
        return DummyGatewayDecision(action="allow", reason="Clean input")

    def check_tool(self, tool_name: str, args: dict, state: AgentState):
        if self.block_tool:
            return DummyGatewayDecision(action="block", reason=f"Tool {tool_name} forbidden")
        return DummyGatewayDecision(action="allow", reason="Allowed tool")

    def pass_output(self, text: str, state: AgentState):
        return DummyGatewayDecision(action="allow", reason="Safe output")


def test_agent_graph_execution_with_tools(monkeypatch):
    """Test full agent turn where model requests a tool and produces final answer."""
    # Step 1: Model requests eng_calc
    msg1 = FakeMsg(content="Calculating value.")
    msg1.tool_calls = [{"name": "eng_calc", "args": {"expression": "25 * 4"}}]

    # Step 2: Model finishes with answer
    msg2 = FakeMsg(content="The calculated value is 100 [VES-9_Pressure_Vessel_Manual.pdf, p. 1].")
    msg2.tool_calls = []

    call_count = 0

    def mock_call(role, messages, runtime, tools=None):
        nonlocal call_count
        call_count += 1
        msg = msg1 if call_count == 1 else msg2
        return CallResult(
            content=msg.content,
            tool_calls=[{"name": tc["name"], "arguments": tc["args"]} for tc in msg.tool_calls],
            meta=CallMeta(provider="fake", model="fake-model", latency_ms=10, attempt=1),
        )

    monkeypatch.setattr("sentinel.agent.graph.call", mock_call)

    # Fake runtime
    from sentinel.router.router import Runtime

    cfg = ModelsConfig(
        roles={
            "answer": [
                ChainEntry(provider="fake", model="test-model", capabilities=["chat", "tools"])
            ]
        },
        limits={"fake": ProviderLimit(rpm=1000, retries=1, timeout_s=10)},
    )
    runtime = Runtime(cfg, use_cache=False)

    state = run_agent("Calculate 25 * 4", gateway_mode="off", runtime=runtime)

    assert state.status == "completed" or state.status == "running"
    assert "100" in state.final_answer
    assert len(state.tool_trace) == 1
    assert state.tool_trace[0]["tool"] == "eng_calc"
    assert state.tool_trace[0]["status"] == "executed"
    assert state.tool_trace[0]["result"] == "100"
    assert len(state.citations) == 1


def test_agent_step_cap_limit(monkeypatch):
    """Verify that agent loop stops cleanly when max_steps is reached."""
    # Model endlessly calls eng_calc
    msg = FakeMsg(content="Looping...")
    msg.tool_calls = [{"name": "eng_calc", "args": {"expression": "1 + 1"}}]

    def mock_call(role, messages, runtime, tools=None):
        return CallResult(
            content=msg.content,
            tool_calls=[{"name": tc["name"], "arguments": tc["args"]} for tc in msg.tool_calls],
            meta=CallMeta(provider="fake", model="fake-model", latency_ms=5, attempt=1),
        )

    monkeypatch.setattr("sentinel.agent.graph.call", mock_call)

    from sentinel.router.router import Runtime

    cfg = ModelsConfig(
        roles={
            "answer": [
                ChainEntry(provider="fake", model="test-model", capabilities=["chat", "tools"])
            ]
        },
        limits={"fake": ProviderLimit(rpm=1000, retries=1, timeout_s=10)},
    )
    runtime = Runtime(cfg, use_cache=False)

    state = run_agent("Infinite loop test", gateway_mode="off", runtime=runtime, max_steps=3)

    assert state.current_step > 3
    assert "Maximum steps exceeded" in state.final_answer


def test_agent_final_step_tool_calls_ignored(monkeypatch):
    """Verify tool calls on final step are ignored and graph finishes in max_steps + 1 calls."""
    call_count = 0

    def mock_call(role, messages, runtime, tools=None):
        nonlocal call_count
        call_count += 1
        # Model stubbornly returns tool_calls even on the final no-tools step
        return CallResult(
            content="Attempting tool call anyway",
            tool_calls=[{"name": "eng_calc", "arguments": {"expression": "2 + 2"}}],
            meta=CallMeta(provider="fake", model="fake-model", latency_ms=5, attempt=1),
        )

    monkeypatch.setattr("sentinel.agent.graph.call", mock_call)

    from sentinel.router.router import Runtime

    cfg = ModelsConfig(
        roles={
            "answer": [
                ChainEntry(provider="fake", model="test-model", capabilities=["chat", "tools"])
            ]
        },
        limits={"fake": ProviderLimit(rpm=1000, retries=1, timeout_s=10)},
    )
    runtime = Runtime(cfg, use_cache=False)

    max_steps = 3
    state = run_agent(
        "Final step tool call test", gateway_mode="off", runtime=runtime, max_steps=max_steps
    )

    # Exactly max_steps + 1 model calls, ended without infinite recursion
    assert call_count == max_steps + 1
    assert state.status == "completed"
    assert "Maximum steps exceeded" in state.final_answer


def test_agent_gateway_input_block():
    """Verify that when gateway is on, malicious inputs are halted before graph starts."""
    gw = MockGateway(block_input=True)
    state = run_agent("Malicious prompt", gateway_mode="on", gateway=gw)

    assert state.status == "blocked"
    assert "Input Guard Blocked" in state.status_reason
    assert len(state.messages) == 0
