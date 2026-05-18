"""Tests for compass.llm — the model resolver + Agent factory."""

import pytest


def test_get_model_id_reads_env_at_call_time(monkeypatch):
    """Changing the env between calls must change the resolved model id."""
    from compass.llm import get_model_id

    monkeypatch.setenv("EXTRACT_MODEL", "google/gemini-2.5-flash")
    assert get_model_id("extract") == "google/gemini-2.5-flash"

    monkeypatch.setenv("EXTRACT_MODEL", "anthropic/claude-haiku-4-5")
    assert get_model_id("extract") == "anthropic/claude-haiku-4-5"


def test_get_model_id_unknown_node_raises():
    from compass.llm import get_model_id

    with pytest.raises(ValueError, match="unknown node"):
        get_model_id("nonexistent_node")


def test_get_model_id_missing_env_raises(monkeypatch):
    from compass.llm import get_model_id

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
