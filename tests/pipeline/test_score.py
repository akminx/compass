"""Tests for compass.pipeline.nodes.score."""

from datetime import date

from compass.pipeline.state import JobRequirements, JobScore, RawJob


def _state(req):
    return {
        "raw_jobs": [],
        "current_job": RawJob(
            company="sample",
            title="Engineer",
            url="https://example.com/x",
            source="greenhouse",
            description="...",
            date_posted=date.today(),
        ),
        "extracted_requirements": req,
        "score_result": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


async def test_score_node_returns_jobscore(monkeypatch, temp_vault):
    from compass.pipeline.nodes import score

    async def fake_score(req, profile_text: str) -> JobScore:
        return JobScore(
            score=4.2,
            reasoning="Strong MCP match",
            matched_skills=["MCP"],
            missing_skills=["LangGraph"],
            tailoring_notes="Lead with Cisco MCP work.",
        )

    monkeypatch.setattr(score, "_score", fake_score)
    req = JobRequirements(
        required_skills=["MCP", "LangGraph"],
        nice_to_have_skills=[],
        years_experience=2,
        seniority="mid",
        remote_policy="remote",
        summary="...",
    )
    result = await score.score_node(_state(req))
    assert result["score_result"].score == 4.2
    assert "MCP" in result["score_result"].matched_skills


async def test_score_node_missing_requirements_errors(monkeypatch, temp_vault):
    from compass.pipeline.nodes import score

    state = _state(None)
    result = await score.score_node(state)
    assert result["score_result"] is None
    assert any("requirements" in e for e in result.get("errors", []))


async def test_score_node_passes_profile_to_llm(monkeypatch, temp_vault):
    """The profile_text passed to _score must include resume + skill-inventory content."""
    from compass.pipeline.nodes import score

    captured = {}

    async def fake_score(req, profile_text: str) -> JobScore:
        captured["profile_text"] = profile_text
        return JobScore(
            score=3.0, reasoning="", matched_skills=[], missing_skills=[], tailoring_notes=""
        )

    monkeypatch.setattr(score, "_score", fake_score)
    req = JobRequirements(
        required_skills=[],
        nice_to_have_skills=[],
        years_experience=None,
        seniority="mid",
        remote_policy="unknown",
        summary="",
    )
    await score.score_node(_state(req))
    assert "Fake resume body" in captured["profile_text"]
    assert "Python: 3" in captured["profile_text"]
