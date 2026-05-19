"""Tests for vault_write_node."""

from datetime import date

import frontmatter

from compass.pipeline.state import CompassState, JobRequirements, JobScore, RawJob


def _build_state_for_score(
    *,
    score: float = 4.2,
    skills_required: list[str] | None = None,
    skills_matched: list[str] | None = None,
    human_approved: bool = True,
    human_feedback: str | None = None,
) -> CompassState:
    skills_required = skills_required if skills_required is not None else ["MCP", "LangGraph"]
    skills_matched = skills_matched if skills_matched is not None else ["MCP"]
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
        "in_scope": True,
        "role_family": "agent-engineer",
        "human_approved": human_approved,
        "human_feedback": human_feedback,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


async def test_vault_write_node_writes_jobnote(temp_vault):
    from compass.pipeline.nodes.vault_write import vault_write_node

    result = await vault_write_node(
        _build_state_for_score(skills_required=["MCP", "LangGraph"], skills_matched=["MCP"])
    )
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

    await vault_write_node(
        _build_state_for_score(skills_required=["MCP", "LangGraph"], skills_matched=["MCP"])
    )
    job_files = list((temp_vault / "jobs").glob("*.md"))
    assert len(job_files) == 1
    loaded = frontmatter.load(job_files[0])
    assert "MCP" in loaded.metadata["skills_required"]
    assert "LangGraph" in loaded.metadata["skills_required"]


async def test_vault_write_node_writes_company_note(temp_vault):
    from compass.pipeline.nodes.vault_write import vault_write_node

    await vault_write_node(_build_state_for_score(skills_required=["MCP"], skills_matched=["MCP"]))
    company_path = temp_vault / "companies" / "Sierra.md"
    assert company_path.exists()


async def test_vault_write_node_handles_missing_state(temp_vault):
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _build_state_for_score(skills_required=["MCP"], skills_matched=["MCP"])
    state["score_result"] = None
    result = await vault_write_node(state)
    assert result["vault_written"] is False
    assert any("score_result" in e for e in result.get("errors", []))


async def test_vault_write_node_persists_tailored_paragraph(temp_vault):
    """When state has tailored_paragraph, it lands on the JobNote."""
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _build_state_for_score(skills_required=["MCP"], skills_matched=["MCP"])
    state["tailored_paragraph"] = "Lead with your Cisco MCP server work."
    await vault_write_node(state)
    job_files = list((temp_vault / "jobs").glob("*.md"))
    loaded = frontmatter.load(job_files[0])
    assert loaded.metadata["tailored_paragraph"] == "Lead with your Cisco MCP server work."


async def test_vault_write_node_persists_full_jd_body(temp_vault):
    """vault_write_node passes job.description through to write_job_note so the
    raw JD is preserved in the JobNote body, not just the LLM summary."""
    import compass.pipeline.nodes.vault_write as vw

    state = _build_state_for_score(skills_required=["MCP"], skills_matched=["MCP"], score=4.2)
    state["current_job"] = state["current_job"].model_copy(
        update={"description": "VERY_DISTINCTIVE_RAW_JD_MARKER agentic engineering."}
    )
    await vw.vault_write_node(state)
    body = next((temp_vault / "jobs").glob("*Sierra*.md")).read_text()
    assert "## Full JD" in body
    assert "VERY_DISTINCTIVE_RAW_JD_MARKER" in body


async def test_low_score_in_scope_still_writes(temp_vault):
    """Phase 1.A: gap_aggregator needs stretch-role data → write all in-scope JDs
    regardless of match_score. Pre-1.A this returned vault_written=False."""
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _build_state_for_score(skills_required=["Python"], skills_matched=["Python"], score=1.5)
    state["in_scope"] = True
    state["role_family"] = "swe-backend"
    result = await vault_write_node(state)

    assert result["vault_written"] is True
    assert len(list((temp_vault / "jobs").glob("*Sierra*.md"))) == 1


async def test_role_family_threaded_to_jobnote(temp_vault):
    """role_family from state lands in JobNote frontmatter."""
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _build_state_for_score(
        skills_required=["LangGraph"], skills_matched=["LangGraph"], score=4.0
    )
    state["in_scope"] = True
    state["role_family"] = "agent-engineer"
    await vault_write_node(state)

    path = next((temp_vault / "jobs").glob("*Sierra*.md"))
    assert frontmatter.load(path).metadata["role_family"] == "agent-engineer"


async def test_tier_resolved_from_target_companies(temp_vault):
    """target-companies.md says Sierra=apply-now → JobNote.tier == 'apply-now'."""
    (temp_vault / "_profile" / "target-companies.md").write_text(
        "## Tier `apply-now`\n\n| Company | Geo |\n|---|---|\n| Sierra | SF |\n"
    )
    import compass.vault.target_companies as tc

    tc.refresh()

    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _build_state_for_score(skills_required=["MCP"], skills_matched=["MCP"], score=4.5)
    state["in_scope"] = True
    state["role_family"] = "agent-engineer"
    await vault_write_node(state)

    path = next((temp_vault / "jobs").glob("*Sierra*.md"))
    assert frontmatter.load(path).metadata["tier"] == "apply-now"


async def test_unknown_company_tier_remains_unknown(temp_vault):
    """No target-companies.md entry → JobNote.tier == 'unknown'."""
    import compass.vault.target_companies as tc

    tc.refresh()

    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _build_state_for_score(skills_required=["MCP"], skills_matched=["MCP"], score=4.5)
    state["in_scope"] = True
    state["role_family"] = "agent-engineer"
    state["current_job"] = state["current_job"].model_copy(update={"company": "RandomCo"})
    await vault_write_node(state)

    path = next((temp_vault / "jobs").glob("*RandomCo*.md"))
    assert frontmatter.load(path).metadata["tier"] == "unknown"


async def test_human_edited_company_tier_preserved(temp_vault):
    """Bug #15 regression: if Akash edits a CompanyNote's tier in Obsidian to
    override what target-companies.md says, vault_write must NOT clobber that
    edit on the next pipeline run."""
    from compass.vault.schemas import CompanyNote
    from compass.vault.writer import write_company_note

    write_company_note(CompanyNote(company="Sierra", tier="stretch", roles_seen=3))

    (temp_vault / "_profile" / "target-companies.md").write_text(
        "## Tier `apply-now`\n\n| Company | Notes |\n|---|---|\n| Sierra | x |\n"
    )
    import compass.vault.target_companies as tc

    tc.refresh()

    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _build_state_for_score(skills_required=["MCP"], skills_matched=["MCP"], score=4.5)
    state["in_scope"] = True
    state["role_family"] = "agent-engineer"
    await vault_write_node(state)

    md = frontmatter.load(temp_vault / "companies" / "Sierra.md").metadata
    assert md["tier"] == "stretch", "human-edited CompanyNote tier was clobbered"

    job_path = next((temp_vault / "jobs").glob("*Sierra*.md"))
    assert frontmatter.load(job_path).metadata["tier"] == "apply-now"


async def test_vault_write_records_approved_decision(temp_vault):
    """state['human_approved'] = True -> hitl_decision='approved', hitl_at set."""
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _build_state_for_score(
        score=4.5,
        human_approved=True,
        human_feedback="LGTM",
    )
    await vault_write_node(state)
    job_file = next((temp_vault / "jobs").glob("*.md"))
    md = frontmatter.load(job_file).metadata
    assert md["hitl_decision"] == "approved"
    assert "hitl_at" in md and md["hitl_at"] is not None


async def test_vault_write_records_auto_rejected_for_low_score(temp_vault):
    """Below-threshold path: hitl never interrupts; decision is 'auto_rejected'."""
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _build_state_for_score(score=2.0, human_approved=False, human_feedback=None)
    await vault_write_node(state)
    job_file = next((temp_vault / "jobs").glob("*.md"))
    md = frontmatter.load(job_file).metadata
    assert md["hitl_decision"] == "auto_rejected"


async def test_vault_write_records_rejected_when_human_said_no(temp_vault):
    """Above-threshold path with human_approved=False = explicit reject."""
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _build_state_for_score(score=4.2, human_approved=False, human_feedback="not a fit")
    await vault_write_node(state)
    job_file = next((temp_vault / "jobs").glob("*.md"))
    md = frontmatter.load(job_file).metadata
    assert md["hitl_decision"] == "rejected"


async def test_vault_write_records_timed_out(temp_vault):
    """Timeout-checker resume sets feedback='auto-cancelled after Xh timeout'."""
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _build_state_for_score(
        score=4.2,
        human_approved=False,
        human_feedback="auto-cancelled after 4h timeout",
    )
    await vault_write_node(state)
    job_file = next((temp_vault / "jobs").glob("*.md"))
    md = frontmatter.load(job_file).metadata
    assert md["hitl_decision"] == "timed_out"
