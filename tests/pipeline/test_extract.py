"""Tests for compass.pipeline.nodes.extract — JD extraction + skill normalization."""

from datetime import date

from compass.pipeline.state import CompassState, JobRequirements, RawJob


def _state(jd_text: str) -> CompassState:
    return {
        "raw_jobs": [],
        "current_job": RawJob(
            company="sample",
            title="Engineer",
            url="https://example.com/x",
            source="greenhouse",
            description=jd_text,
            date_posted=date.today(),
        ),
        "extracted_requirements": None,
        "score_result": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


async def test_extract_node_normalizes_known_skills(monkeypatch):
    """Returned skills are mapped to canonical taxonomy names."""
    from compass.pipeline.nodes import extract

    async def fake_extract(jd_text: str) -> JobRequirements:
        return JobRequirements(
            required_skills=["langgraph", "py", "MCP"],
            nice_to_have_skills=["fastapi"],
            years_experience=2,
            seniority="mid",
            remote_policy="hybrid",
            summary="Build agents.",
        )

    monkeypatch.setattr(extract, "_extract", fake_extract)
    result = await extract.extract_node(_state("anything"))
    req = result["extracted_requirements"]
    assert req.required_skills == ["LangGraph", "Python", "MCP"]
    assert req.nice_to_have_skills == ["FastAPI"]


async def test_extract_node_drops_unknown_skills_but_records_them(monkeypatch, temp_vault):
    """Unknown skills are dropped from requirements but written to the unknown-skills log."""
    from compass.pipeline.nodes import extract

    async def fake_extract(jd_text: str) -> JobRequirements:
        return JobRequirements(
            required_skills=["LangGraph", "NotARealSkillXyz123", "MojoLang"],
            nice_to_have_skills=["AlsoFake"],
            years_experience=None,
            seniority="mid",
            remote_policy="remote",
            summary="...",
        )

    monkeypatch.setattr(extract, "_extract", fake_extract)
    result = await extract.extract_node(_state("anything"))

    # Unknown skills dropped from extracted requirements:
    assert result["extracted_requirements"].required_skills == ["LangGraph"]
    assert result["extracted_requirements"].nice_to_have_skills == []

    # Unknown skills recorded to log for human review:
    log_path = temp_vault / "_meta" / "unknown-skills-log.md"
    assert log_path.exists(), "unknown-skills-log.md should be created on first unknown skill"
    log_text = log_path.read_text()
    assert "NotARealSkillXyz123" in log_text
    assert "MojoLang" in log_text
    assert "AlsoFake" in log_text


async def test_extract_node_with_missing_current_job_returns_error(monkeypatch):
    from compass.pipeline.nodes import extract

    state = _state("anything")
    state["current_job"] = None
    result = await extract.extract_node(state)
    assert result["extracted_requirements"] is None
    assert any("current_job" in e for e in result.get("errors", []))
