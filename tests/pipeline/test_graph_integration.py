"""End-to-end integration test for the Compass pipeline with mocked LLMs."""

from datetime import date

import frontmatter
import pytest

from compass.pipeline.state import JobRequirements, JobScore, RawJob


@pytest.fixture
def mocked_llms(monkeypatch):
    """Patch all three LLM calls so the test runs without network or API key."""
    from compass.pipeline.nodes import extract, score, tailor

    async def fake_extract(jd_text: str) -> JobRequirements:
        return JobRequirements(
            required_skills=["MCP", "LangGraph", "Python"],
            nice_to_have_skills=["FastAPI"],
            years_experience=2,
            seniority="mid",
            remote_policy="hybrid",
            summary="Build agentic systems with LangGraph and MCP.",
        )

    async def fake_score(req, profile_text):
        return JobScore(
            score=4.2,
            reasoning="Strong MCP + LangGraph match",
            matched_skills=["MCP", "Python"],
            missing_skills=["LangGraph"],
            tailoring_notes="lead with Cisco MCP work",
        )

    async def fake_tailor(*args, **kwargs):
        return "Open with the Cisco MCP server work and Minx's 4-server architecture."

    monkeypatch.setattr(extract, "_extract", fake_extract)
    monkeypatch.setattr(score, "_score", fake_score)
    monkeypatch.setattr(tailor, "_tailor", fake_tailor)


@pytest.fixture
def auto_approve_hitl(monkeypatch):
    """Stub the `interrupt()` call in hitl_node so the integration tests can
    exercise the full extract -> score -> hitl -> tailor -> vault_write path
    without needing a real human resume."""

    def fake_interrupt(_payload):
        return {"approved": True, "feedback": None}

    monkeypatch.setattr("compass.pipeline.nodes.hitl.interrupt", fake_interrupt)


async def test_run_pipeline_end_to_end(temp_vault, mocked_llms, auto_approve_hitl):
    """Run a single fake job through the full graph; verify vault state."""
    from compass.pipeline.graph import run_pipeline

    raw_jobs = [
        RawJob(
            company="Sierra",
            title="Agent Engineer",
            url="https://jobs.ashbyhq.com/sierra/test-uuid",
            source="ashby",
            description="Build agents at Sierra with Python, LangGraph, MCP, and FastAPI.",
            location="NYC",
            date_posted=date(2026, 5, 17),
        ),
    ]
    state = await run_pipeline(raw_jobs=raw_jobs)
    assert state["jobs_processed"] == 1
    assert state["jobs_written"] == 1

    # JobNote exists
    job_files = list((temp_vault / "jobs").glob("*Sierra*.md"))
    assert len(job_files) == 1
    loaded = frontmatter.load(job_files[0])
    assert loaded.metadata["match_score"] == 4.2
    # The polished paragraph from tailor_node is persisted to the JobNote:
    assert loaded.metadata.get("tailored_paragraph") is not None
    assert "Cisco MCP" in loaded.metadata["tailored_paragraph"]
    # The short pitch from score_node is preserved in score_reasoning:
    assert loaded.metadata.get("score_reasoning") == "Strong MCP + LangGraph match"
    # Skills were incremented
    assert (temp_vault / "skills" / "MCP.md").exists()
    assert (temp_vault / "skills" / "LangGraph.md").exists()
    # Company was upserted
    assert (temp_vault / "companies" / "Sierra.md").exists()


async def test_run_pipeline_skips_dedup_urls(temp_vault, mocked_llms):
    """A URL already in the vault is filtered out before the graph runs."""
    from compass.pipeline.graph import run_pipeline

    # Seed a prior write with frontmatter that vault reader can parse
    (temp_vault / "jobs" / "2026-05-15-Sierra-Prior.md").write_text(
        "---\ntype: job\nurl: https://jobs.ashbyhq.com/sierra/test-uuid\ncompany: Sierra\n"
        "title: Prior\nmatch_score: 0\nsource: ashby\ndate_found: 2026-05-15\n---\n# Prior\n"
    )
    raw_jobs = [
        RawJob(
            company="Sierra",
            title="Agent Engineer",
            url="https://jobs.ashbyhq.com/sierra/test-uuid",
            source="ashby",
            description="...",
            date_posted=date(2026, 5, 17),
        ),
    ]
    state = await run_pipeline(raw_jobs=raw_jobs)
    assert state["jobs_processed"] == 0
    assert state["jobs_written"] == 0


async def test_run_pipeline_regenerates_gap_plan(temp_vault, mocked_llms, auto_approve_hitl):
    """After processing, master-gap-plan.md should be regenerated."""
    from compass.pipeline.graph import run_pipeline

    raw_jobs = [
        RawJob(
            company="Sierra",
            title="Agent Engineer",
            url="https://jobs.ashbyhq.com/sierra/test-uuid",
            source="ashby",
            description="...",
            date_posted=date(2026, 5, 17),
        ),
    ]
    await run_pipeline(raw_jobs=raw_jobs)
    plan_path = temp_vault / "study-plans" / "master-gap-plan.md"
    assert plan_path.exists()
    assert "generated_by: gap_aggregator" in plan_path.read_text()


async def test_run_pipeline_skips_tailor_when_below_threshold_but_still_writes(
    monkeypatch, temp_vault
):
    """Phase 1.A: low-score jobs are still written to vault so gap_aggregator can
    surface stretch-role gaps. Tailor (Sonnet cost) is still skipped for low scores
    because hitl_node auto-rejects below SCORE_THRESHOLD.
    """
    from compass.pipeline.graph import run_pipeline
    from compass.pipeline.nodes import extract, score, tailor

    tailor_calls = {"count": 0}

    async def fake_extract(jd_text):
        return JobRequirements(
            required_skills=["MCP"],
            nice_to_have_skills=[],
            years_experience=2,
            seniority="mid",
            remote_policy="hybrid",
            summary="Build agents.",
        )

    async def fake_score(req, profile_text):
        return JobScore(
            score=2.0,
            reasoning="weak match against requirements.",
            matched_skills=[],
            missing_skills=["MCP"],
            tailoring_notes="",
        )

    async def fake_tailor(*args, **kwargs):
        tailor_calls["count"] += 1
        return "should not run"

    monkeypatch.setattr(extract, "_extract", fake_extract)
    monkeypatch.setattr(score, "_score", fake_score)
    monkeypatch.setattr(tailor, "_tailor", fake_tailor)

    raw_jobs = [
        RawJob(
            company="Sample",
            title="Engineer",
            url="https://example.com/low-score",
            source="greenhouse",
            description="...",
            date_posted=date(2026, 5, 17),
        ),
    ]
    state = await run_pipeline(raw_jobs=raw_jobs)
    # Phase 1.A: vault write no longer gated on score — stretch-role data feeds gap_aggregator.
    assert state["jobs_written"] == 1
    assert len(list((temp_vault / "jobs").glob("*Sample*.md"))) == 1
    # Tailor (Sonnet cost) is still skipped — hitl_node auto-rejects below SCORE_THRESHOLD.
    assert tailor_calls["count"] == 0


async def test_run_pipeline_appends_to_run_log(temp_vault, mocked_llms, auto_approve_hitl):
    """Every run_pipeline invocation appends a row to _meta/pipeline-runs.md."""
    from compass.pipeline.graph import run_pipeline

    raw_jobs = [
        RawJob(
            company="Sierra",
            title="Agent Engineer",
            url="https://jobs.ashbyhq.com/sierra/run-log-test",
            source="ashby",
            description="...",
            date_posted=date(2026, 5, 17),
        ),
    ]
    await run_pipeline(raw_jobs=raw_jobs)
    log_path = temp_vault / "_meta" / "pipeline-runs.md"
    assert log_path.exists()
    log_text = log_path.read_text()
    assert "| Timestamp |" in log_text  # header was written
    assert "| 1 |" in log_text  # one job processed


async def test_run_log_migrates_5col_to_6col_on_first_post_1b1_append(temp_vault):
    """A pre-1.B.1 pipeline-runs.md with 5-col rows gets migrated to 6-col on
    the next append. Existing data preserved with Paused=0."""
    log_path = temp_vault / "_meta" / "pipeline-runs.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "# Pipeline Run Log\n\n"
        "| Timestamp | Processed | Written | Errors | Duration |\n"
        "|---|---|---|---|---|\n"
        "| 2026-05-17T10:00:00 | 20 | 5 | 0 | 7.2s |\n"
        "| 2026-05-18T10:00:00 | 15 | 3 | 1 | 5.4s |\n",
        encoding="utf-8",
    )

    from compass.pipeline.graph import _append_run_log

    state = {
        "raw_jobs": [],
        "current_job": None,
        "extracted_requirements": None,
        "score_result": None,
        "in_scope": None,
        "role_family": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 10,
        "jobs_written": 2,
        "errors": [],
        "thread_id": None,
        "score_threshold": None,
    }
    state["jobs_paused"] = 1  # type: ignore[typeddict-unknown-key]
    _append_run_log(state, 4.1)

    text = log_path.read_text(encoding="utf-8")
    assert "| Timestamp | Processed | Written | Paused | Errors | Duration |" in text
    assert "| 2026-05-17T10:00:00 | 20 | 5 | 0 | 0 | 7.2s |" in text  # migrated
    assert "| 2026-05-18T10:00:00 | 15 | 3 | 0 | 1 | 5.4s |" in text
