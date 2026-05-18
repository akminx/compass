"""Tests for intake_node — Phase 0.B is a sanity gate, not the dedup point."""

from datetime import date

from compass.pipeline.state import RawJob


def _state(job):
    return {
        "raw_jobs": [],
        "current_job": job,
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


async def test_intake_node_passes_when_current_job_set():
    from compass.pipeline.nodes.intake import intake_node

    job = RawJob(
        company="x",
        title="y",
        url="https://example.com/z",
        source="greenhouse",
        description="...",
        date_posted=date.today(),
    )
    result = await intake_node(_state(job))
    assert result == {}


async def test_intake_node_errors_when_current_job_missing():
    from compass.pipeline.nodes.intake import intake_node

    result = await intake_node(_state(None))
    assert any("current_job" in e for e in result.get("errors", []))
