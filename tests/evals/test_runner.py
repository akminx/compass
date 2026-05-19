"""Runner integration test — mocked LLM calls, real metric aggregation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from compass.evals.dataset import EvalRecord
from compass.evals.runner import run_against_judge, run_against_labels
from compass.pipeline.state import JobRequirements, JobScore


async def _fake_extract(jd_text: str) -> JobRequirements:
    """Deterministic stub — pretends extract found Python + MCP from every JD."""
    return JobRequirements(
        required_skills=["Python", "MCP"],
        nice_to_have_skills=["LangGraph"],
        years_experience=2,
        seniority="mid",
        remote_policy="hybrid",
        summary="Build agents.",
    )


async def _fake_score(req, profile_text, job=None) -> JobScore:
    """Deterministic stub — 4.0 with matched=Python+MCP, missed=LangGraph."""
    return JobScore(
        score=4.0,
        reasoning="Strong MCP + Python match. Score reasoning ends with period.",
        matched_skills=["Python", "MCP"],
        missing_skills=["LangGraph"],
        tailoring_notes="lead with Cisco MCP work",
    )


@pytest.mark.asyncio
async def test_run_against_labels_computes_aggregate(temp_vault):
    records = [
        EvalRecord(
            id="eval-001",
            jd_text="Build LangGraph agents.",
            expected_score=4.0,
            expected_skills=["Python", "MCP", "LangGraph"],
        ),
        EvalRecord(
            id="eval-002",
            jd_text="Senior systems engineer.",
            expected_score=1.0,
            expected_skills=["Kubernetes", "Go"],
        ),
    ]
    with (
        patch("compass.evals.runner._extract", new=_fake_extract),
        patch("compass.evals.runner._score", new=_fake_score),
    ):
        metrics, per_record = await run_against_labels(records)

    assert metrics.n == 2
    # Score MAE: |4.0-4.0| + |4.0-1.0| = 3.0, /2 → 1.5
    assert metrics.score_mae == 1.5
    # Bias: ((4-4)+(4-1))/2 = 1.5 — Compass over-scores eval-002 (1.0 → 4.0)
    assert metrics.score_bias == 1.5
    # Record 1: extracted=[Python, MCP, LangGraph], expected=[Python, MCP, LangGraph] → recall 1.0
    # Record 2: extracted=[Python, MCP, LangGraph], expected=[Kubernetes, Go]      → recall 0.0
    assert metrics.extract_skill_recall == 0.5
    # Per-record output has missed/extra skills
    assert per_record[0]["missed_skills"] == []
    assert "kubernetes" in per_record[1]["missed_skills"]
    assert "go" in per_record[1]["missed_skills"]


@pytest.mark.asyncio
async def test_run_against_judge_uses_judge_verdict(temp_vault):
    """Judge mode replaces expected_score/expected_skills with LLM judge output.
    EvalRecord's own expected_* fields are ignored."""
    from compass.evals.judge import JudgeVerdict

    async def fake_judge(jd_text, profile, predicted_skills, predicted_score):
        return JudgeVerdict(
            expected_skills=["Python", "MCP"],
            expected_score=4.0,
            reasoning="Agent did fine.",
        )

    records = [
        EvalRecord(
            id="eval-001",
            jd_text="Build agents.",
            expected_score=2.5,  # ignored in judge mode
            expected_skills=["DontUseThis"],  # ignored in judge mode
        ),
    ]
    with (
        patch("compass.evals.runner._extract", new=_fake_extract),
        patch("compass.evals.runner._score", new=_fake_score),
        patch("compass.evals.judge.judge_jd", new=fake_judge),
    ):
        metrics, per_record = await run_against_judge(records)

    assert metrics.n == 1
    # Compass scored 4.0, judge said 4.0 → MAE 0.0
    assert metrics.score_mae == 0.0
    assert "judge_reasoning" in per_record[0]
    assert per_record[0]["judge_reasoning"] == "Agent did fine."


@pytest.mark.asyncio
async def test_run_against_labels_handles_extract_failure(temp_vault):
    """If extract fails for one JD, that record is logged but the others
    still aggregate — pipeline never blocks on one bad JD."""

    async def flaky_extract(jd_text):
        if "broken" in jd_text:
            raise RuntimeError("simulated extract failure")
        return await _fake_extract(jd_text)

    records = [
        EvalRecord(id="eval-001", jd_text="broken jd", expected_score=4.0, expected_skills=["X"]),
        EvalRecord(
            id="eval-002",
            jd_text="good jd",
            expected_score=4.0,
            expected_skills=["Python", "MCP"],
        ),
    ]
    with (
        patch("compass.evals.runner._extract", new=flaky_extract),
        patch("compass.evals.runner._score", new=_fake_score),
    ):
        metrics, per_record = await run_against_labels(records)

    assert metrics.n == 1  # only the good one aggregated
    assert per_record[0].get("error") == "extract or score failed"
    assert per_record[1]["predicted_score"] == 4.0
