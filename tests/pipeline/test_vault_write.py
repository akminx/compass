"""Tests for vault_write_node."""

from datetime import date

import frontmatter

from compass.pipeline.state import CompassState, JobRequirements, JobScore, RawJob


def _state(
    skills_required: list[str], skills_matched: list[str], score: float = 4.2
) -> CompassState:
    return {
        "raw_jobs": [],
        "current_job": RawJob(
            company="Sierra",
            title="Agent Engineer",
            url="https://jobs.ashbyhq.com/sierra/abc-123",
            source="ashby",
            description="Build agentic systems.",
            location="NYC",
            date_posted=date(2026, 5, 17),
        ),
        "extracted_requirements": JobRequirements(
            required_skills=skills_required,
            nice_to_have_skills=[],
            years_experience=2,
            seniority="mid",
            remote_policy="hybrid",
            summary="Build agents.",
        ),
        "score_result": JobScore(
            score=score,
            reasoning="strong",
            matched_skills=skills_matched,
            missing_skills=[s for s in skills_required if s not in skills_matched],
            tailoring_notes="lead with MCP",
        ),
        "human_approved": True,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


async def test_vault_write_node_writes_jobnote(temp_vault):
    from compass.pipeline.nodes.vault_write import vault_write_node

    result = await vault_write_node(_state(["MCP", "LangGraph"], ["MCP"]))
    assert result["vault_written"] is True
    assert result["jobs_written"] == 1
    job_files = list((temp_vault / "jobs").glob("*.md"))
    assert len(job_files) == 1
    loaded = frontmatter.load(job_files[0])
    assert loaded.metadata["company"] == "Sierra"
    assert loaded.metadata["match_score"] == 4.2
    assert "MCP" in loaded.metadata["skills_required"]


async def test_vault_write_node_records_skills_on_jobnote(temp_vault):
    """The JobNote's skills_required field is the source of truth for which
    skills the JD asked for. gap_aggregator's _sync_skill_counters reads
    this and updates skills/<name>.md counters at end of each run — the
    vault_write_node no longer increments per-call (that path drifted)."""
    import frontmatter

    from compass.pipeline.nodes.vault_write import vault_write_node

    await vault_write_node(_state(["MCP", "LangGraph"], ["MCP"]))
    job_files = list((temp_vault / "jobs").glob("*.md"))
    assert len(job_files) == 1
    loaded = frontmatter.load(job_files[0])
    assert "MCP" in loaded.metadata["skills_required"]
    assert "LangGraph" in loaded.metadata["skills_required"]


async def test_vault_write_node_writes_company_note(temp_vault):
    from compass.pipeline.nodes.vault_write import vault_write_node

    await vault_write_node(_state(["MCP"], ["MCP"]))
    company_path = temp_vault / "companies" / "Sierra.md"
    assert company_path.exists()


async def test_vault_write_node_handles_missing_state(temp_vault):
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _state(["MCP"], ["MCP"])
    state["score_result"] = None
    result = await vault_write_node(state)
    assert result["vault_written"] is False
    assert any("score_result" in e for e in result.get("errors", []))


async def test_vault_write_node_persists_tailored_paragraph(temp_vault):
    """When state has tailored_paragraph, it lands on the JobNote."""
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _state(["MCP"], ["MCP"])
    state["tailored_paragraph"] = "Lead with your Cisco MCP server work."
    await vault_write_node(state)
    job_files = list((temp_vault / "jobs").glob("*.md"))
    loaded = frontmatter.load(job_files[0])
    assert loaded.metadata["tailored_paragraph"] == "Lead with your Cisco MCP server work."
