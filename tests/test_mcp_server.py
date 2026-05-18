"""Regression tests for compass.mcp_server.server tools.

Lightweight smoke checks — full MCP protocol tests live in the SDK's tests.
We just want to confirm each exposed tool produces sensible output without
crashing, since these are the user-facing surface in Cursor / Claude Code.
"""

from __future__ import annotations

import pytest

from compass.pipeline.state import JobRequirements, JobScore


@pytest.fixture
def mocked_extract_score(monkeypatch):
    """Stub extract + score so MCP tool tests don't hit the network."""
    from compass.pipeline.nodes import extract, score

    async def fake_extract(jd_text):
        return JobRequirements(
            required_skills=["Python", "LangGraph"],
            nice_to_have_skills=["MCP"],
            years_experience=2,
            seniority="mid",
            remote_policy="remote",
            summary="Build agents.",
        )

    async def fake_score(req, profile_text):
        return JobScore(
            score=4.0,
            reasoning="Strong Python + LangGraph evidence in profile.",
            matched_skills=["Python", "LangGraph"],
            missing_skills=[],
            tailoring_notes="lead with MCP",
        )

    monkeypatch.setattr(extract, "_extract", fake_extract)
    monkeypatch.setattr(score, "_score", fake_score)


async def test_score_jd_returns_score_and_requirements(temp_vault, mocked_extract_score):
    """Regression: pre-fix score_jd built a state with current_job=None and
    invoked the full graph; intake_node rejected it and the tool returned
    {"error": "no score produced"} every call. The fix calls extract+score
    directly (no vault write, no tailor)."""
    from compass.mcp_server.server import score_jd

    result = await score_jd("We need a Python engineer for LangGraph agents.")
    assert "error" not in result, result
    assert "score" in result and "requirements" in result
    assert result["score"]["score"] == 4.0
    assert "Python" in result["requirements"]["required_skills"]


async def test_score_jd_does_not_write_to_vault(temp_vault, mocked_extract_score):
    """score_jd must be side-effect-free — no JobNote should land in the vault
    even for a high-score JD that would otherwise pass SCORE_THRESHOLD."""
    from compass.mcp_server.server import score_jd

    await score_jd("Adhoc JD that would score 4.0")
    assert list((temp_vault / "jobs").glob("*.md")) == []
    assert list((temp_vault / "companies").glob("*.md")) == []


def test_search_jobs_filters_by_query(temp_vault, monkeypatch):
    """search_jobs should match substring in JobNote frontmatter or body."""
    import compass.mcp_server.server as mcp_mod

    monkeypatch.setattr(mcp_mod, "VAULT_PATH", temp_vault)
    from datetime import date

    from compass.mcp_server.server import search_jobs
    from compass.vault.schemas import JobNote
    from compass.vault.writer import write_job_note

    write_job_note(JobNote(
        company="acme", title="Agent Engineer", url="https://x/1",
        source="manual", date_found=date(2026, 5, 18), match_score=4.2,
        jd_summary="LangGraph + MCP role",
    ))
    write_job_note(JobNote(
        company="other", title="Frontend Engineer", url="https://x/2",
        source="manual", date_found=date(2026, 5, 18), match_score=2.0,
        jd_summary="React + TypeScript role",
    ))
    hits = search_jobs("langgraph")
    assert len(hits) == 1
    assert hits[0]["company"] == "acme"


def test_list_canonical_skills_includes_llms(temp_vault):
    """Smoke check that taxonomy is loaded and the bug-#18 fix landed."""
    from compass.mcp_server.server import list_canonical_skills

    skills = list_canonical_skills()
    assert "LLMs" in skills
    assert "Machine Learning" in skills
    assert "Python" in skills
