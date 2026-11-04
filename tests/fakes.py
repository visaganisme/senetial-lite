"""Shared offline fakes for router tests. No network calls anywhere in tests/."""

from __future__ import annotations


class ServiceDown(RuntimeError):
    """Looks transient to the router (status_code attribute)."""

    def __init__(self, status_code: int = 503):
        super().__init__(f"provider returned {status_code}")
        self.status_code = status_code


class FakeMsg:
    def __init__(self, content=None, tool_calls=None, usage=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage_metadata = usage or {"input_tokens": 1, "output_tokens": 2}


class FakeModel:
    """behavior: an Exception to always raise, or a callable(messages, call_no) -> FakeMsg."""

    def __init__(self, behavior):
        self.behavior = behavior

    def bind_tools(self, tools):  # noqa: ARG002 - probe signature parity
        return self

    def invoke(self, messages):
        if isinstance(self.behavior, Exception):
            raise self.behavior
        return self.behavior(messages)


class OkMsg(FakeMsg):
    def __init__(self, content="OK"):
        super().__init__(content=content)
