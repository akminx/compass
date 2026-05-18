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


async def test_run_pipeline_end_to_end(temp_vault, mocked_llms):
    """Run a single fake job through the full graph; verify vault state."""
    from compass.pipeline.graph import run_pipeline

    raw_jobs = [
        RawJob(
            company="Sierra",
            title="Agent Engineer",
            url="https://jobs.ashbyhq.com/sierra/test-uuid",
            source="ashby",
            description="Build agents at Sierra.",
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


async def test_run_pipeline_regenerates_gap_plan(temp_vault, mocked_llms):
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


async def test_run_pipeline_skips_tailor_when_below_threshold(monkeypatch, temp_vault):
    """Low-score jobs are still written but tailor must not fire — verifies graph routing."""
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
            reasoning="weak",
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
    # Job still written for analysis (per spec: rejected jobs persist for eval data):
    assert state["jobs_written"] == 1
    # But tailor was skipped:
    assert tailor_calls["count"] == 0
    # And no tailored_paragraph on the JobNote:
    job_files = list((temp_vault / "jobs").glob("*Sample*.md"))
    loaded = frontmatter.load(job_files[0])
    assert loaded.metadata.get("tailored_paragraph") is None


async def test_run_pipeline_appends_to_run_log(temp_vault, mocked_llms):
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
