"""Router fallback / breaker integration tests - offline, fakes injected into make_model."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

import sentinel.router.router as router_mod
from sentinel.router.factory import MissingKey
from sentinel.router.router import NoModelAvailable, Runtime, call, call_structured
from sentinel.router.schema import ChainEntry, ProviderLimit
from tests.fakes import FakeModel, FakeMsg, OkMsg, ServiceDown


def runtime(entries: dict) -> Runtime:
    roles = {"answer": [ChainEntry(provider="fake", model="unused-answer",
                                   capabilities=["chat", "tools"])], **entries}
    config_model = router_mod.ModelsConfig(
        roles=roles,
        limits={"fake": ProviderLimit(rpm=60_000, retries=2, timeout_s=5)},
    )
    # exclude the dummy answer entry from factory mappings; it must never be called
    return Runtime(config_model, use_cache=False)


def patch_factory(monkeypatch, mapping: dict[str, object]):
    """mapping: model-name -> Exception | FakeModel; missing model name raises UnknownModel."""

    def factory(entry, timeout_s=45.0):
        if entry.model not in mapping:
            raise ValueError(f"unknown provider {entry.provider}")
        behavior = mapping[entry.model]
        if isinstance(behavior, Exception):
            return FakeModel(behavior)
        return behavior

    monkeypatch.setattr(router_mod, "make_model", factory)


def test_falls_back_past_transient_error(monkeypatch):
    rt = runtime(
        {
            "answer": [
                ChainEntry(provider="fake", model="flaky", capabilities=["chat"]),
                ChainEntry(provider="fake", model="solid", capabilities=["chat"]),
            ],
        }
    )
    patch_factory(
        monkeypatch,
        {
            "flaky": FakeModel(ServiceDown(503)),  # always transient-fails
            "solid": FakeModel(lambda _msgs: OkMsg("from solid")),
        },
    )
    res = call("answer", [{"role": "user", "content": "hi"}], runtime=rt)
    assert res.content == "from solid"
    assert res.meta.model == "solid" and res.meta.ok


def test_retries_transient_then_succeeds(monkeypatch):
    rt = runtime(
        {
            "answer": [ChainEntry(provider="fake", model="once", capabilities=["chat"])],
        }
    )
    state = {"n": 0}

    def flaky_once(_msgs):
        state["n"] += 1
        if state["n"] == 1:
            raise ServiceDown(429)
        return OkMsg("recovered")

    patch_factory(monkeypatch, {"once": FakeModel(flaky_once)})
    res = call("answer", [{"role": "user", "content": "hi"}], runtime=rt)
    assert res.content == "recovered"
    assert state["n"] == 2 and res.meta.attempt == 2


def test_check_failure_moves_to_next_entry(monkeypatch):
    """Invalid structured output (as judged by `check`) triggers chain fallback."""

    rt = runtime(
        {
            "answer": [
                ChainEntry(provider="fake", model="wrongjson", capabilities=["structured"]),
                ChainEntry(provider="fake", model="goodjson", capabilities=["structured"]),
            ],
        }
    )
    patch_factory(
        monkeypatch,
        {
            "wrongjson": FakeModel(lambda _m: OkMsg('{"n": "not-a-number"}')),
            "goodjson": FakeModel(lambda _m: OkMsg('{"n": 2}')),
        },
    )
    res = call(
        "answer",
        [{"role": "user", "content": "gimme json"}],
        runtime=rt,
        check=lambda r: "n must be int" if not str(r.content).count("2") else None,
    )
    assert res.meta.model == "goodjson"


def test_missing_key_falls_back(monkeypatch):
    rt = runtime(
        {
            "answer": [
                ChainEntry(provider="fake", model="nokey", capabilities=["chat"]),
                ChainEntry(provider="fake", model="ok-model", capabilities=["chat"]),
            ],
        }
    )

    def factory(entry, timeout_s=45.0):
        if entry.model == "nokey":
            raise MissingKey("fake")
        return FakeModel(lambda _m: OkMsg("present"))

    monkeypatch.setattr(router_mod, "make_model", factory)
    res = call("answer", [{"role": "user", "content": "hi"}], runtime=rt)
    assert res.meta.model == "ok-model"


def test_all_entries_dead_raises(monkeypatch):
    rt = runtime(
        {
            "answer": [
                ChainEntry(provider="fake", model="dead1", capabilities=["chat"]),
                ChainEntry(provider="fake", model="dead2", capabilities=["chat"]),
            ],
        }
    )
    patch_factory(
        monkeypatch,
        {
            "dead1": FakeModel(ServiceDown(500)),
            "dead2": FakeModel(ServiceDown(500)),
        },
    )
    with pytest.raises(NoModelAvailable):
        call("answer", [{"role": "user", "content": "hi"}], runtime=rt)


def test_open_breaker_skips_entry(monkeypatch):
    rt = runtime(
        {
            "answer": [
                ChainEntry(provider="fake", model="skipme", capabilities=["chat"]),
                ChainEntry(provider="fake", model="runner", capabilities=["chat"]),
            ],
        }
    )
    patch_factory(
        monkeypatch,
        {
            "skipme": FakeModel(lambda _m: OkMsg("should not be used")),
            "runner": FakeModel(lambda _m: OkMsg("ran")),
        },
    )
    for _ in range(rt.breaker.threshold):
        rt.breaker.record_failure("fake:skipme")
    res = call("answer", [{"role": "user", "content": "hi"}], runtime=rt)
    assert res.meta.model == "runner"


class QueryOut(BaseModel):
    rewritten: str


def test_call_structured_validates_and_falls_back(monkeypatch):
    rt = runtime(
        {
            "cheap": [
                ChainEntry(provider="fake", model="bad", capabilities=["chat", "structured"]),
                ChainEntry(provider="fake", model="good", capabilities=["chat", "structured"]),
            ],
        }
    )
    patch_factory(
        monkeypatch,
        {
            "bad": FakeModel(lambda _m: OkMsg(" Главный rewritten query is rusty")),
            "good": FakeModel(lambda _m: OkMsg('{"rewritten": "rusty pipe specs"}')),
        },
    )
    out, res = call_structured(
        "cheap",
        "rewrite: rusty",
        QueryOut,
        runtime=rt,
    )
    assert out.rewritten == "rusty pipe specs"
    assert res.meta.model == "good"


def test_tool_call_passthrough(monkeypatch):
    rt = runtime(
        {"answer": [ChainEntry(provider="fake", model="tooler", capabilities=["chat", "tools"])]}
    )
    tool_call = {"name": "add", "args": {"a": 2, "b": 3}}
    patch_factory(
        monkeypatch, {"tooler": FakeModel(lambda _m: FakeMsg(content="", tool_calls=[tool_call]))}
    )
    res = call(
        "answer",
        [{"role": "user", "content": "2+3?"}],
        runtime=rt,
        tools=[{"type": "function", "function": {"name": "add"}}],
    )
    assert res.tool_calls[0].name == "add"
    assert res.tool_calls[0].arguments == {"a": 2, "b": 3}
