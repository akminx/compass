"""Tests for compass.llm — the model resolver + Agent factory."""

import pytest


def test_get_model_id_reads_env_at_call_time(monkeypatch):
    """Changing the env between calls must change the resolved model id."""
    import compass.config as cfg
    from compass.llm import get_model_id

    # `compass.config` reads EXTRACT_MODEL from env at import time. To force a
    # call-time lookup via env, clear the cfg constant so the os.environ
    # fallback fires.
    monkeypatch.setattr(cfg, "EXTRACT_MODEL", "")
    monkeypatch.setenv("EXTRACT_MODEL", "google/gemini-2.5-flash")
    assert get_model_id("extract") == "google/gemini-2.5-flash"

    monkeypatch.setenv("EXTRACT_MODEL", "anthropic/claude-haiku-4-5")
    assert get_model_id("extract") == "anthropic/claude-haiku-4-5"


def test_get_model_id_reads_config_attr(monkeypatch):
    """Regression for wave-3 fix: monkeypatching `compass.config.EXTRACT_MODEL`
    must take effect — pre-fix the resolver bypassed cfg and read os.environ
    directly, so cfg patches in tests silently used the real env value."""
    import compass.config as cfg
    from compass.llm import get_model_id

    monkeypatch.setattr(cfg, "EXTRACT_MODEL", "test-only-model")
    monkeypatch.delenv("EXTRACT_MODEL", raising=False)
    assert get_model_id("extract") == "test-only-model"


def test_get_model_id_unknown_node_raises():
    from compass.llm import get_model_id

    with pytest.raises(ValueError, match="unknown node"):
        get_model_id("nonexistent_node")


def test_get_model_id_missing_env_raises(monkeypatch):
    import compass.config as cfg
    from compass.llm import get_model_id

    # Must clear BOTH cfg constant and env var — the resolver falls back to
    # os.environ if cfg is empty, so leaving cfg with its imported value
    # would mask the env deletion.
    monkeypatch.setattr(cfg, "EXTRACT_MODEL", "")
    monkeypatch.delenv("EXTRACT_MODEL", raising=False)
    with pytest.raises(ValueError, match="no model configured"):
        get_model_id("extract")


def test_make_agent_returns_pydantic_ai_agent(monkeypatch):
    """make_agent should construct a pydantic-ai Agent wired to OpenRouter."""
    from pydantic import BaseModel
    from pydantic_ai import Agent

    from compass.llm import make_agent

    monkeypatch.setenv("EXTRACT_MODEL", "google/gemini-2.5-flash")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    class Result(BaseModel):
        answer: str

    agent = make_agent("extract", output_type=Result, system_prompt="hi")
    assert isinstance(agent, Agent)


def test_make_agent_requires_keyword_args(monkeypatch):
    """Positional args after `node` must fail — keeps call sites explicit."""
    from pydantic import BaseModel

    from compass.llm import make_agent

    monkeypatch.setenv("EXTRACT_MODEL", "google/gemini-2.5-flash")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    class Result(BaseModel):
        answer: str

    with pytest.raises(TypeError):
        make_agent("extract", Result, "hi")  # type: ignore[misc]
