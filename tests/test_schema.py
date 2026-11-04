from __future__ import annotations

import pytest
from pydantic import ValidationError

from sentinel.router.schema import (
    BudgetExceeded,
    CallMeta,
    CallResult,
    ChainEntry,
    ModelsConfig,
    RunBudget,
    cache_key,
    extract_json,
    load_models_config,
)


def test_real_models_yaml_loads():
    cfg = load_models_config()
    assert "answer" in cfg.roles and cfg.roles["answer"]
    # provider = first segment, model = the rest (dots/colons preserved)
    e = cfg.roles["answer"][0]
    assert e.provider in {"groq", "cohere", "cloudflare", "openrouter"}


def test_chain_entry_key_split():
    e = ChainEntry(provider="Groq", model="openai/gpt-oss-120b", capabilities=["chat", "tools"])
    assert e.provider == "groq"
    assert e.model == "openai/gpt-oss-120b"  # only the FIRST segment is the provider
    assert e.key == "groq:openai/gpt-oss-120b"


def test_models_config_requires_answer_role():
    with pytest.raises(ValidationError):
        ModelsConfig.model_validate({"roles": {}})


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here you go: {"a": 1} hope that helps') == {"a": 1}
    assert extract_json('{"limit": null}') == {"limit": None}
    with pytest.raises(ValueError):
        extract_json("no json here")
    with pytest.raises(ValueError):
        extract_json("")


def test_cache_key_stable_and_differs():
    a = cache_key("ns", {"x": 1, "y": [2, 3]})
    b = cache_key("ns", {"y": [2, 3], "x": 1})  # order-insensitive
    assert a == b
    assert a != cache_key("ns", {"x": 2, "y": [2, 3]})


def test_run_budget_tokens_and_steps():
    budget = RunBudget(max_tokens=10, max_steps=2, max_wall_s=3600)
    budget.account_tokens(5)
    budget.next_step()
    budget.next_step()
    with pytest.raises(BudgetExceeded):
        budget.account_tokens(6)  # 5+6 > 10
    with pytest.raises(BudgetExceeded):
        budget.next_step()


def test_call_result_schema_roundtrip():
    r = CallResult(
        content="hi",
        meta=CallMeta(
            provider="fake", model="m", latency_ms=12, attempt=1, tokens_in=3, tokens_out=2
        ),
    )
    d = r.model_dump()
    assert CallResult.model_validate(d).content == "hi"
