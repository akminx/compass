"""timeout_checker resumes pending rows older than HITL_TIMEOUT_HOURS with
{"approved": False}, marks them as 'timed_out' in the state store, appends
a row to _meta/agent-log.md (spec § DoD line 230), and leaves young
pending rows untouched."""

from __future__ import annotations

import datetime as _dt
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from compass.hitl import state_store
from compass.pipeline.state import JobRequirements, JobScore, RawJob


@pytest.fixture
def checkpoint_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "checkpoints.db"
    import compass.config as cfg

    monkeypatch.setattr(cfg, "HITL_CHECKPOINT_DB", db)
    return db


@pytest.fixture
def stub_llm_nodes(monkeypatch):
    async def fake_extract(_):
        return {
            "extracted_requirements": JobRequirements(
                required_skills=["MCP"],
                nice_to_have_skills=[],
                seniority="mid",
                remote_policy="remote",
                summary="x",
            )
        }

    async def fake_score(_):
        return {
            "score_result": JobScore(
                score=4.5,
                reasoning="ok",
                matched_skills=["MCP"],
                missing_skills=[],
                tailoring_notes="",
            )
        }

    async def fake_vault_write(_):
        return {"vault_written": True, "jobs_written": 1}

    async def fake_intake_filter(_):
        return {"in_scope": True, "role_family": "agent-engineer"}

    async def fake_tailor(_):
        return {"tailored_paragraph": "..."}

    monkeypatch.setattr("compass.pipeline.graph.extract_node", fake_extract)
    monkeypatch.setattr("compass.pipeline.graph.score_node", fake_score)
    monkeypatch.setattr("compass.pipeline.graph.tailor_node", fake_tailor)
    monkeypatch.setattr("compass.pipeline.graph.vault_write_node", fake_vault_write)
    monkeypatch.setattr("compass.pipeline.graph.intake_filter_node", fake_intake_filter)


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "stub_llm_nodes", "temp_vault")
async def test_timeout_checker_resumes_old_pending_as_rejected(monkeypatch):
    from compass.hitl import timeout_checker
    from compass.pipeline.graph import run_pipeline

    job = RawJob(
        company="Sierra",
        title="SWE",
        url="https://x/1",
        source="ashby",
        description="...",
        date_posted=_dt.date(2026, 5, 18),
    )
    await run_pipeline(raw_jobs=[job])
    tid = (await state_store.list_pending())[0]["thread_id"]

    # Force the row's created_at to look 5h old
    import aiosqlite

    from compass.config import HITL_STATE_DB

    five_h_ago = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(hours=5)).isoformat()
    async with aiosqlite.connect(HITL_STATE_DB) as conn:
        await conn.execute(
            "UPDATE pending_approvals SET created_at = ? WHERE thread_id = ?",
            (five_h_ago, tid),
        )
        await conn.commit()

    n = await timeout_checker.check_and_resume_timeouts(timeout_hours=4)
    assert n == 1
    row = await state_store.get_pending(tid)
    assert row["status"] == "timed_out"
    # Spec DoD line 230 — timeout must be logged to _meta/agent-log.md
    from compass.config import AGENT_LOG_PATH

    log_text = AGENT_LOG_PATH.read_text(encoding="utf-8")
    assert "hitl-timeout" in log_text
    assert tid in log_text


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "stub_llm_nodes", "temp_vault")
async def test_timeout_checker_leaves_young_pending_alone():
    from compass.hitl import timeout_checker
    from compass.pipeline.graph import run_pipeline

    job = RawJob(
        company="Sierra",
        title="SWE",
        url="https://x/2",
        source="ashby",
        description="...",
        date_posted=_dt.date(2026, 5, 18),
    )
    await run_pipeline(raw_jobs=[job])
    n = await timeout_checker.check_and_resume_timeouts(timeout_hours=4)
    assert n == 0
    rows = await state_store.list_pending()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "stub_llm_nodes", "temp_vault")
async def test_timeout_checker_continues_after_one_resume_failure(monkeypatch):
    """A single broken thread (e.g. checkpoint corrupted) must not block the
    rest of the queue from timing out."""
    from compass.hitl import timeout_checker

    # Two rows, both stale
    await state_store.add_pending(
        thread_id="tid-broken",
        job_url="x://1",
        company="C",
        title="T",
        score=4.0,
        score_reasoning="r",
        matched_skills=[],
        missing_skills=[],
    )
    await state_store.add_pending(
        thread_id="tid-ok",
        job_url="x://2",
        company="C",
        title="T",
        score=4.0,
        score_reasoning="r",
        matched_skills=[],
        missing_skills=[],
    )
    # Backdate both
    import aiosqlite

    from compass.config import HITL_STATE_DB

    five_h_ago = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(hours=5)).isoformat()
    async with aiosqlite.connect(HITL_STATE_DB) as conn:
        await conn.execute("UPDATE pending_approvals SET created_at = ?", (five_h_ago,))
        await conn.commit()

    # Make resume_pending raise for tid-broken
    async def flaky(thread_id, **kw):
        if thread_id == "tid-broken":
            raise RuntimeError("checkpoint missing")
        from compass.hitl.state_store import mark_resolved

        await mark_resolved(thread_id, status="timed_out")

    monkeypatch.setattr("compass.hitl.timeout_checker.resume_pending", flaky)

    n = await timeout_checker.check_and_resume_timeouts(timeout_hours=4)
    assert n == 1  # one succeeded, one failed
    row_broken = await state_store.get_pending("tid-broken")
    assert row_broken["status"] == "error"
