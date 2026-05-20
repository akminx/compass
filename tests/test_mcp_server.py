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

    async def fake_score(req, profile_text, job=None):
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

    write_job_note(
        JobNote(
            company="acme",
            title="Agent Engineer",
            url="https://x/1",
            source="manual",
            date_found=date(2026, 5, 18),
            match_score=4.2,
            jd_summary="LangGraph + MCP role",
        )
    )
    write_job_note(
        JobNote(
            company="other",
            title="Frontend Engineer",
            url="https://x/2",
            source="manual",
            date_found=date(2026, 5, 18),
            match_score=2.0,
            jd_summary="React + TypeScript role",
        )
    )
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


def test_get_skill_gaps_case_insensitive(temp_vault, monkeypatch):
    """Bug E regression: get_skill_gaps substring match must be case-insensitive
    so capitalized user queries find lowercase-filename JobNotes."""
    import compass.mcp_server.server as mcp_mod

    monkeypatch.setattr(mcp_mod, "VAULT_PATH", temp_vault)
    from datetime import date

    from compass.mcp_server.server import get_skill_gaps
    from compass.vault.schemas import JobNote
    from compass.vault.writer import write_job_note

    # Scraper-style lowercase company
    write_job_note(
        JobNote(
            company="sierra",
            title="Agent Engineer",
            url="https://x/1",
            source="manual",
            date_found=date(2026, 5, 18),
            match_score=4.2,
            skills_required=["Python", "LangGraph"],
            skills_matched=["Python"],
            skills_missing=["LangGraph"],
        )
    )
    # Human types capital S
    result = get_skill_gaps("Sierra-Agent_Engineer")
    assert "error" not in result
    assert "Python" in result["skills_matched"]
    assert "LangGraph" in result["skills_missing"]


from datetime import date


def _seed_sierra_jobnote(vault):
    from compass.vault.schemas import JobNote
    from compass.vault.writer import write_job_note

    write_job_note(
        JobNote(
            company="Sierra",
            title="Agent Engineer",
            url="https://x/sierra-agent",
            source="manual",
            date_found=date(2026, 5, 10),
            match_score=4.5,
        )
    )


def test_mcp_add_application_creates_note(temp_vault):
    """The MCP tool wraps lifecycle.add_application — exercising it end-to-end
    via the MCP registration confirms wiring."""
    from compass.mcp_server.server import add_application

    _seed_sierra_jobnote(temp_vault)
    result = add_application(job_id="Sierra-Agent_Engineer")

    assert "error" not in result
    assert result["company"] == "Sierra"
    assert result["status"] == "applied"
    assert any((temp_vault / "applications").glob("*Sierra*.md"))


def test_mcp_add_application_unknown_job_returns_error(temp_vault):
    from compass.mcp_server.server import add_application

    result = add_application(job_id="not-a-real-job")
    assert "error" in result
    assert "no JobNote matched" in result["error"]


def test_mcp_add_application_reapply_returns_error_without_force(temp_vault):
    """Bug F regression: re-applying without force=True must return error,
    not silently overwrite the existing ApplicationNote."""
    from compass.mcp_server.server import add_application

    _seed_sierra_jobnote(temp_vault)
    first = add_application(job_id="Sierra-Agent_Engineer")
    assert "error" not in first

    second = add_application(job_id="Sierra-Agent_Engineer")
    assert "error" in second
    assert "already has status" in second["error"]


def test_mcp_add_application_force_overrides(temp_vault):
    """force=True bypasses the overwrite guard (for reposted jobs)."""
    from compass.mcp_server.server import add_application

    _seed_sierra_jobnote(temp_vault)
    add_application(job_id="Sierra-Agent_Engineer")
    forced = add_application(job_id="Sierra-Agent_Engineer", force=True)
    assert "error" not in forced
    assert forced["status"] == "applied"


def test_mcp_update_application_status_valid_transition(temp_vault):
    from compass.mcp_server.server import add_application, update_application_status

    _seed_sierra_jobnote(temp_vault)
    add_application(job_id="Sierra")
    today_iso = date.today().isoformat()

    result = update_application_status(
        app_id=f"{today_iso}-Sierra",
        status="screen",
        next_action="prep recruiter call",
        next_action_date="2026-05-25",
    )
    assert "error" not in result
    assert result["status"] == "screen"
    assert result["next_action"] == "prep recruiter call"


def test_mcp_update_application_status_invalid_transition(temp_vault):
    from compass.mcp_server.server import add_application, update_application_status

    _seed_sierra_jobnote(temp_vault)
    add_application(job_id="Sierra")
    today_iso = date.today().isoformat()

    result = update_application_status(app_id=f"{today_iso}-Sierra", status="offer")
    assert "error" in result
    assert "invalid transition" in result["error"]


def test_mcp_update_application_status_clear_flag_clears_field(temp_vault):
    """clear_next_action=True must clear the existing next_action."""
    from compass.mcp_server.server import add_application, update_application_status

    _seed_sierra_jobnote(temp_vault)
    add_application(job_id="Sierra")
    today_iso = date.today().isoformat()

    # Set a next_action
    update_application_status(
        app_id=f"{today_iso}-Sierra",
        status="screen",
        next_action="prep call",
    )
    # Clear it via flag
    result = update_application_status(
        app_id=f"{today_iso}-Sierra",
        status="onsite",
        clear_next_action=True,
    )
    assert result["next_action"] == ""


def test_mcp_list_pending_actions_returns_due_rows(temp_vault):
    from compass.mcp_server.server import (
        add_application,
        list_pending_actions,
        update_application_status,
    )

    _seed_sierra_jobnote(temp_vault)
    add_application(job_id="Sierra")
    today_iso = date.today().isoformat()
    update_application_status(
        app_id=f"{today_iso}-Sierra",
        status="screen",
        next_action="follow up",
        next_action_date=today_iso,
    )

    pending = list_pending_actions(through_date=today_iso)
    assert len(pending) == 1
    assert pending[0]["company"] == "Sierra"

    # Regression: result must be JSON-serializable end-to-end (no raw `date`
    # objects), since FastMCP transmits this list over the wire.
    import json

    json.dumps(pending)  # raises if any field is non-serializable


def test_mcp_list_pending_filters_future_dates(temp_vault):
    from compass.mcp_server.server import (
        add_application,
        list_pending_actions,
        update_application_status,
    )

    _seed_sierra_jobnote(temp_vault)
    add_application(job_id="Sierra")
    today_iso = date.today().isoformat()
    update_application_status(
        app_id=f"{today_iso}-Sierra",
        status="screen",
        next_action_date="2099-01-01",
    )

    pending = list_pending_actions(through_date=today_iso)
    assert pending == []


async def test_mcp_tailor_resume_reads_existing_paragraph(temp_vault):
    """tailor_resume returns the already-computed tailored_paragraph from the
    JobNote frontmatter. It does NOT re-run the LLM."""
    from compass.mcp_server.server import tailor_resume
    from compass.vault.schemas import JobNote
    from compass.vault.writer import write_job_note

    write_job_note(
        JobNote(
            company="Sierra",
            title="Agent Engineer",
            url="https://x/sierra-agent",
            source="manual",
            date_found=date(2026, 5, 10),
            match_score=4.5,
            tailored_paragraph="Lead with production MCP project.",
        )
    )
    result = await tailor_resume(job_id="Sierra-Agent_Engineer")
    assert "error" not in result
    assert result["tailored_paragraph"] == "Lead with production MCP project."
