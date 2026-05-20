"""score_node uses RAG retrieval to build profile context, not full inventory."""

from __future__ import annotations

import pytest

from compass.pipeline.state import JobRequirements

pytestmark = pytest.mark.usefixtures("embedding_model_cached")


def _stub_req(**overrides) -> JobRequirements:
    base = dict(
        required_skills=["Python", "LangGraph"],
        nice_to_have_skills=["MCP"],
        seniority="senior",
        remote_policy="remote",
        summary="Build agentic systems.",
    )
    base.update(overrides)
    return JobRequirements(**base)


async def test_profile_text_includes_resume_and_retrieved_chunks(monkeypatch):
    from compass.pipeline.nodes import score as score_mod
    from compass.rag.retriever import RetrievedChunk

    async def fake_retrieve(query, k=8):
        return [RetrievedChunk(skill="Python", document="## Python\nLevel 4.", score=0.9)]

    monkeypatch.setattr("compass.pipeline.nodes.score.rag_retrieve", fake_retrieve)
    monkeypatch.setattr("compass.pipeline.nodes.score.read_resume", lambda: "RESUME TEXT")

    text = await score_mod._profile_text(_stub_req())
    assert "RESUME TEXT" in text
    assert "## Python\nLevel 4." in text


async def test_retrieval_query_carries_jd_skills_and_summary(monkeypatch):
    from compass.pipeline.nodes import score as score_mod
    from compass.rag.retriever import RetrievedChunk

    captured: dict[str, object] = {}

    async def fake_retrieve(query, k=8):
        captured["query"] = query
        return [RetrievedChunk(skill="Python", document="## Python", score=0.9)]

    monkeypatch.setattr("compass.pipeline.nodes.score.rag_retrieve", fake_retrieve)
    monkeypatch.setattr("compass.pipeline.nodes.score.read_resume", lambda: "")

    await score_mod._profile_text(_stub_req())
    q = captured["query"]
    assert "Python" in q and "LangGraph" in q and "MCP" in q
    assert "Build agentic systems" in q


async def test_score_node_handles_empty_jd_skills(monkeypatch):
    """JD with no required/nice-to-have skills falls back to summary-only query."""
    from compass.pipeline.nodes import score as score_mod
    from compass.rag.retriever import RetrievedChunk

    async def fake_retrieve(query, k=8):
        return [RetrievedChunk(skill="Python", document="## Python\nLevel 4.", score=0.9)]

    monkeypatch.setattr("compass.pipeline.nodes.score.rag_retrieve", fake_retrieve)
    monkeypatch.setattr("compass.pipeline.nodes.score.read_resume", lambda: "RESUME")

    text = await score_mod._profile_text(
        _stub_req(required_skills=[], nice_to_have_skills=[], summary="Just a summary.")
    )
    assert "RESUME" in text
    assert "## Python\nLevel 4." in text


async def test_score_node_handles_empty_retrieval(monkeypatch):
    """If retriever returns [], profile context still includes the resume."""
    from compass.pipeline.nodes import score as score_mod

    async def fake_retrieve(query, k=8):
        return []

    monkeypatch.setattr("compass.pipeline.nodes.score.rag_retrieve", fake_retrieve)
    monkeypatch.setattr("compass.pipeline.nodes.score.read_resume", lambda: "RESUME ONLY")

    text = await score_mod._profile_text(_stub_req())
    assert "RESUME ONLY" in text
