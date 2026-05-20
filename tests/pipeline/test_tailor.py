"""Tests for compass.pipeline.nodes.tailor."""

from datetime import date

from compass.pipeline.state import CompassState, JobRequirements, JobScore, RawJob


def _state(approved: bool = True) -> CompassState:
    return {
        "raw_jobs": [],
        "current_job": RawJob(
            company="Sierra",
            title="Agent Engineer",
            url="https://example.com/x",
            source="ashby",
            description="Build agentic systems.",
            date_posted=date.today(),
        ),
        "extracted_requirements": JobRequirements(
            required_skills=["LangGraph", "MCP"],
            nice_to_have_skills=[],
            years_experience=2,
            seniority="mid",
            remote_policy="hybrid",
            summary="Build agents.",
        ),
        "score_result": JobScore(
            score=4.2,
            reasoning="Strong MCP",
            matched_skills=["MCP"],
            missing_skills=["LangGraph"],
            tailoring_notes="lead with MCP",
        ),
        "human_approved": approved,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


async def test_tailor_node_writes_tailored_paragraph(monkeypatch, temp_vault):
    """The polished paragraph lands on a separate state field — NOT on score.tailoring_notes."""
    from compass.pipeline.nodes import tailor

    async def fake_tailor(*a, **kw):
        return "Lead with your production MCP server work and the multi-server architecture."

    monkeypatch.setattr(tailor, "_tailor", fake_tailor)
    state = _state(approved=True)
    score_pitch_before = state["score_result"].tailoring_notes
    result = await tailor.tailor_node(state)
    # New polished paragraph on dedicated state field:
    assert "MCP" in result["tailored_paragraph"]
    # Score's original short pitch is NOT clobbered:
    assert "score_result" not in result  # tailor doesn't touch score
    # Sanity: original score pitch unchanged in the input state:
    assert state["score_result"].tailoring_notes == score_pitch_before


async def test_tailor_node_skips_when_not_approved(monkeypatch, temp_vault):
    from compass.pipeline.nodes import tailor

    called = {"count": 0}

    async def fake_tailor(*a, **kw):
        called["count"] += 1
        return "should not run"

    monkeypatch.setattr(tailor, "_tailor", fake_tailor)
    result = await tailor.tailor_node(_state(approved=False))
    assert called["count"] == 0
    assert result == {}  # no state mutation
