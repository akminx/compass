"""End-to-end: graph pauses at hitl, state_store gets the row,
resume_pending finishes the run.

These tests STUB the LLM-touching nodes (extract, score, tailor) — we only
exercise the graph machinery + interrupt + checkpointer + state_store
interaction. Real LLM calls live in the live-smoke check in Task 7."""

from __future__ import annotations

import datetime as _dt
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from compass.hitl import state_store
from compass.pipeline.state import CompassState, JobRequirements, JobScore, RawJob


@pytest.fixture
def stub_llm_nodes(monkeypatch):
    """Replace extract / score / tailor / vault_write / intake_filter with deterministic stubs."""

    async def fake_extract(state: CompassState) -> dict:
        return {
            "extracted_requirements": JobRequirements(
                required_skills=["MCP", "Python"],
                nice_to_have_skills=["LangGraph"],
                seniority="mid",
                remote_policy="remote",
                summary="An agent role.",
            )
        }

    async def fake_score(state: CompassState) -> dict:
        return {
            "score_result": JobScore(
                score=4.2,
                reasoning="Strong match.",
                matched_skills=["MCP"],
                missing_skills=["LangGraph"],
                tailoring_notes="Lead with MCP.",
            )
        }

    async def fake_tailor(state: CompassState) -> dict:
        return {"tailored_paragraph": "Tailored: lead with MCP work."}

    async def fake_vault_write(state: CompassState) -> dict:
        return {"vault_written": True, "jobs_written": 1}

    async def fake_intake_filter(state: CompassState) -> dict:
        return {"in_scope": True, "role_family": "agent-engineer"}

    monkeypatch.setattr("compass.pipeline.graph.extract_node", fake_extract)
    monkeypatch.setattr("compass.pipeline.graph.score_node", fake_score)
    monkeypatch.setattr("compass.pipeline.graph.tailor_node", fake_tailor)
    monkeypatch.setattr("compass.pipeline.graph.vault_write_node", fake_vault_write)
    monkeypatch.setattr("compass.pipeline.graph.intake_filter_node", fake_intake_filter)


@pytest.fixture
def checkpoint_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "checkpoints.db"
    import compass.config as cfg

    monkeypatch.setattr(cfg, "HITL_CHECKPOINT_DB", db)
    return db


def _job(url: str = "https://jobs.example.com/sierra-1") -> RawJob:
    return RawJob(
        company="Sierra",
        title="SWE, Agent",
        url=url,
        source="ashby",
        description="An agent engineering role at Sierra.",
        date_posted=_dt.date(2026, 5, 18),
    )


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "stub_llm_nodes", "temp_vault")
async def test_above_threshold_job_pauses_and_registers_in_state_store(monkeypatch):
    """run_pipeline with a single above-threshold job: paused=1, written=0,
    state_store has a row."""
    from compass.pipeline.graph import run_pipeline

    # No real scraping — pass the job in directly.
    result = await run_pipeline(raw_jobs=[_job()])

    assert result["jobs_processed"] == 1
    assert result["jobs_written"] == 0  # paused before vault_write
    assert result["jobs_paused"] == 1
    rows = await state_store.list_pending()
    assert len(rows) == 1
    assert rows[0]["company"] == "Sierra"
    assert rows[0]["score"] == pytest.approx(4.2)
    assert rows[0]["job_url"] == "https://jobs.example.com/sierra-1"


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "stub_llm_nodes", "temp_vault")
async def test_below_threshold_job_runs_to_completion_no_state_store_row(monkeypatch):
    """Below-threshold path is unchanged from 1.A — no interrupt, vault_write fires."""

    async def low_score(state: CompassState) -> dict:
        return {
            "score_result": JobScore(
                score=2.0,
                reasoning="Mismatched.",
                matched_skills=[],
                missing_skills=["A", "B"],
                tailoring_notes="",
            )
        }

    monkeypatch.setattr("compass.pipeline.graph.score_node", low_score)
    from compass.pipeline.graph import run_pipeline

    result = await run_pipeline(raw_jobs=[_job()])
    assert result["jobs_written"] == 1
    assert result["jobs_paused"] == 0
    assert await state_store.list_pending() == []


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "stub_llm_nodes", "temp_vault")
async def test_thread_id_is_deterministic_for_same_url_and_batch_same_process(monkeypatch):
    """Re-running the SAME batch (same start_wall) within the same process
    reuses the same thread_id — second run hits the idempotent INSERT OR IGNORE path."""
    import os

    from compass.pipeline.graph import _thread_id_for

    monkeypatch.setattr(os, "getpid", lambda: 12345)
    tid_a = _thread_id_for("https://jobs.example.com/x", _dt.datetime(2026, 5, 19, 9, 0, 0))
    tid_b = _thread_id_for("https://jobs.example.com/x", _dt.datetime(2026, 5, 19, 9, 0, 0))
    tid_c = _thread_id_for("https://jobs.example.com/y", _dt.datetime(2026, 5, 19, 9, 0, 0))
    assert tid_a == tid_b
    assert tid_a != tid_c
    assert len(tid_a) == 16
