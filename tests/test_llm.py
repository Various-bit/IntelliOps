"""Офлайн-тесты обёртки LLM (#12): без сети и ключей, транспорт подменён."""
from __future__ import annotations

import pytest

from agent.config import load_settings
from agent.llm import (
    DEFAULT_BUDGET_USD,
    BudgetExceeded,
    LLMWrapper,
    estimate_tokens,
    get_llm,
    reset_clients,
)


def fake_response(text: str = "{}", *, prompt_tokens: int | None = 100, completion_tokens: int | None = 50):
    usage = {}
    if prompt_tokens is not None:
        usage = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
    return {
        "choices": [{"message": {"content": text}}],
        "usage": usage,
    }


def make_wrapper(**kwargs) -> LLMWrapper:
    kwargs.setdefault("transport", lambda payload: fake_response())
    return LLMWrapper("test-role", **kwargs)


def test_usage_and_cost_recorded():
    wrapper = make_wrapper(model="gpt-4o-mini")
    text = wrapper([{"role": "user", "content": "привет"}])
    assert text == "{}"
    assert len(wrapper.usage) == 1
    record = wrapper.usage[0]
    assert record.agent == "test-role"
    assert record.model == "gpt-4o-mini"
    assert record.input_tokens == 100
    assert record.output_tokens == 50
    # 100 * 0.15/1e6 + 50 * 0.60/1e6 = 0.000045
    assert record.cost_usd == pytest.approx(0.000045)
    assert wrapper.spent_usd == pytest.approx(0.000045)


def test_missing_usage_estimates_tokens():
    wrapper = make_wrapper(model="gpt-4o-mini")
    wrapper([{"role": "user", "content": "x" * 400}])
    record = wrapper.usage[0]
    assert record.input_tokens == estimate_tokens("x" * 400) == 100
    assert record.output_tokens >= 1


def test_unknown_model_uses_conservative_fallback():
    wrapper = make_wrapper(model="some-future-model")
    wrapper([{"role": "user", "content": "hi"}])
    assert wrapper.usage[0].cost_usd > 0


def test_budget_blocks_calls():
    wrapper = make_wrapper(budget_usd=0.00004)  # меньше стоимости одного вызова
    wrapper([{"role": "user", "content": "привет"}])
    with pytest.raises(BudgetExceeded):
        wrapper([{"role": "user", "content": "еще"}])


def test_missing_key_raises_without_transport():
    wrapper = LLMWrapper("test-role", api_key="")
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        wrapper([{"role": "user", "content": "hi"}])


def test_transport_receives_payload():
    seen = {}

    def transport(payload):
        seen.update(payload)
        return fake_response()

    wrapper = LLMWrapper("test-role", transport=transport, model="m1")
    wrapper([{"role": "user", "content": "hi"}])
    assert seen["model"] == "m1"
    assert seen["messages"][0]["content"] == "hi"


def test_get_llm_uses_settings_and_caches(monkeypatch):
    reset_clients()
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("LLM_BUDGET_USD", "0.5")
    first = get_llm("supervisor")
    second = get_llm("supervisor")
    assert first is second
    assert first.api_key == "test-key"
    assert first.model == "deepseek-chat"
    assert first.budget_usd == 0.5
    assert first._transport is None
    reset_clients()


def test_get_llm_custom_transport_not_cached():
    reset_clients()
    wrapper = get_llm("verifier", transport=lambda payload: fake_response())
    assert get_llm("verifier") is not wrapper
    reset_clients()


def test_settings_defaults_without_env(tmp_path):
    settings = load_settings(tmp_path / ".env")
    assert settings.llm_model == "gpt-4o-mini"
    assert settings.llm_budget_usd == DEFAULT_BUDGET_USD
    assert settings.langsmith_tracing is False
    assert settings.langsmith_project == "intelliops"


def test_settings_from_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "LLM_MODEL=gpt-4o\nLLM_BUDGET_USD=2.5\nLANGSMITH_TRACING=true\nLANGSMITH_PROJECT=custom\n",
        encoding="utf-8",
    )
    settings = load_settings(env)
    assert settings.llm_model == "gpt-4o"
    assert settings.llm_budget_usd == 2.5
    assert settings.langsmith_tracing is True
    assert settings.langsmith_project == "custom"
