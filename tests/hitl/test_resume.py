"""resume_pending re-opens the checkpointer, recompiles the graph, and drives
the resume via Command(resume=...). Verifies vault_write fires on approve
and tailor is skipped on reject."""

from __future__ import annotations

import datetime as _dt
from typing import TYPE_CHECKING

import pytest

from compass.hitl import state_store
from compass.pipeline.state import JobRequirements, JobScore, RawJob

if TYPE_CHECKING:
    from pathlib import Path


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
                summary="agent role",
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

    async def fake_tailor(_):
        return {"tailored_paragraph": "lead with MCP."}

    written = {"calls": 0, "with_tailor": 0}

    async def fake_vault_write(state):
        written["calls"] += 1
        if state.get("tailored_paragraph"):
            written["with_tailor"] += 1
        return {"vault_written": True, "jobs_written": 1}

    async def fake_intake_filter(_):
        return {"in_scope": True, "role_family": "agent-engineer"}

    monkeypatch.setattr("compass.pipeline.graph.extract_node", fake_extract)
    monkeypatch.setattr("compass.pipeline.graph.score_node", fake_score)
    monkeypatch.setattr("compass.pipeline.graph.tailor_node", fake_tailor)
    monkeypatch.setattr("compass.pipeline.graph.vault_write_node", fake_vault_write)
    monkeypatch.setattr("compass.pipeline.graph.intake_filter_node", fake_intake_filter)
    return written


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "temp_vault")
async def test_resume_approve_runs_tailor_then_vault_write(stub_llm_nodes):
    from compass.hitl.resume import resume_pending
    from compass.pipeline.graph import run_pipeline

    job = RawJob(
        company="Sierra",
        title="SWE",
        url="https://x/1",
        source="ashby",
        description="...",
        date_posted=_dt.date(2026, 5, 18),
    )
    pre = await run_pipeline(raw_jobs=[job])
    assert pre["jobs_paused"] == 1

    pending = await state_store.list_pending()
    tid = pending[0]["thread_id"]

    final = await resume_pending(tid, decision={"approved": True, "feedback": "LGTM"})
    assert final["vault_written"] is True
    assert final["human_approved"] is True
    assert stub_llm_nodes["with_tailor"] == 1
    row = await state_store.get_pending(tid)
    assert row["status"] == "approved"
    assert row["feedback"] == "LGTM"


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "temp_vault")
async def test_resume_reject_skips_tailor_writes_to_vault(stub_llm_nodes):
    from compass.hitl.resume import resume_pending
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
    tid = (await state_store.list_pending())[0]["thread_id"]

    final = await resume_pending(tid, decision={"approved": False})
    assert final["human_approved"] is False
    assert stub_llm_nodes["with_tailor"] == 0
    assert stub_llm_nodes["calls"] == 1  # vault_write still fired (rejected branch)
    row = await state_store.get_pending(tid)
    assert row["status"] == "rejected"


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "temp_vault")
async def test_resume_unknown_thread_raises():
    from compass.hitl.resume import resume_pending

    with pytest.raises(LookupError, match="thread"):
        await resume_pending("nope-1234", decision={"approved": True})


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "temp_vault")
async def test_resume_already_resolved_raises(stub_llm_nodes):
    from compass.hitl.resume import resume_pending
    from compass.pipeline.graph import run_pipeline

    job = RawJob(
        company="Sierra",
        title="SWE",
        url="https://x/3",
        source="ashby",
        description="...",
        date_posted=_dt.date(2026, 5, 18),
    )
    await run_pipeline(raw_jobs=[job])
    tid = (await state_store.list_pending())[0]["thread_id"]
    await resume_pending(tid, decision={"approved": True})

    # Second resume call should not crash and should not re-fire vault_write
    before = stub_llm_nodes["calls"]
    with pytest.raises(ValueError, match="already resolved"):
        await resume_pending(tid, decision={"approved": True})
    assert stub_llm_nodes["calls"] == before
