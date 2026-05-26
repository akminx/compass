"""Runner integration test — mocked LLM calls, real metric aggregation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from compass.evals.dataset import EvalRecord
from compass.evals.runner import run_against_judge, run_against_labels
from compass.pipeline.state import JobRequirements, JobScore


async def _fake_classify_role_family(jd_text: str) -> str:
    """Tests never want the real role-family LLM call. Returning an in-scope
    family that's NOT in `ROLE_FAMILY_SCORE_CAP` lets the stubbed score
    survive through the cap layer unchanged."""
    return "agent-engineer"


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
        tailoring_notes="lead with production MCP work",
    )


@pytest.mark.asyncio
async def test_run_against_labels_computes_aggregate(temp_vault):
    """JD bodies must mention the skills the stub returns — production
    `_normalize_skill_list` drops skills the LLM emits but the JD doesn't
    actually contain (anti-hallucination guard). Keep tests aligned with
    production behavior."""
    records = [
        EvalRecord(
            id="eval-001",
            jd_text="Build LangGraph agents in Python with MCP servers.",
            expected_score=4.0,
            expected_skills=["Python", "MCP", "LangGraph"],
        ),
        EvalRecord(
            id="eval-002",
            jd_text="Senior systems engineer working with Python MCP and LangGraph.",
            expected_score=1.0,
            expected_skills=["Kubernetes", "Go"],
        ),
    ]
    # Patch _score at its source (compass.pipeline.nodes.score) because the
    # runner now goes through `_score_ensemble` → `_score_with_retry` → `_score`,
    # and the inner call resolves the module-local symbol.
    with (
        patch("compass.evals.runner._extract", new=_fake_extract),
        patch("compass.evals.runner._classify_role_family_from_body", new=_fake_classify_role_family),
        patch("compass.pipeline.nodes.score._score", new=_fake_score),
    ):
        metrics, per_record = await run_against_labels(records)

    assert metrics.n == 2
    # Score MAE: |4.0-4.0| + |4.0-1.0| = 3.0, /2 → 1.5
    assert metrics.score_mae == 1.5
    # Bias: ((4-4)+(4-1))/2 = 1.5 — Compass over-scores eval-002 (1.0 → 4.0)
    assert metrics.score_bias == 1.5
    # Both JDs mention Python+MCP+LangGraph (post-normalization).
    # Record 1: extracted=[Python, MCP, LangGraph], expected=[Python, MCP, LangGraph] → recall 1.0
    # Record 2: extracted=[Python, MCP, LangGraph], expected=[Kubernetes, Go]        → recall 0.0
    assert metrics.extract_skill_recall == 0.5
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
        patch("compass.evals.runner._classify_role_family_from_body", new=_fake_classify_role_family),
        patch("compass.pipeline.nodes.score._score", new=_fake_score),
        patch("compass.evals.judge.judge_jd", new=fake_judge),
    ):
        metrics, per_record = await run_against_judge(records)

    assert metrics.n == 1
    # Compass scored 4.0, judge said 4.0 → MAE 0.0
    assert metrics.score_mae == 0.0
    assert "judge_reasoning" in per_record[0]
    assert per_record[0]["judge_reasoning"] == "Agent did fine."


@pytest.mark.asyncio
async def test_runner_applies_extract_normalization(temp_vault):
    """Regression: runner used to call `_extract` raw, skipping
    `_normalize_skill_list`. That made the recall metric measure something
    DIFFERENT from what the production pipeline persists. Now the runner
    runs the same normalization extract_node does — skills the LLM emits
    that don't appear in the JD body are dropped (anti-hallucination)."""

    async def hallucinating_extract(jd_text):
        # Stub emits skills the JD doesn't actually contain — production
        # drops these as likely-hallucinated.
        return JobRequirements(
            required_skills=["Python", "Kubernetes", "Federated Learning"],
            nice_to_have_skills=[],
            years_experience=2,
            seniority="mid",
            remote_policy="hybrid",
            summary="x",
        )

    records = [
        EvalRecord(
            id="eval-001",
            jd_text="Build a Python service that calls our API.",
            expected_score=3.0,
            expected_skills=["Python"],
        ),
    ]
    with (
        patch("compass.evals.runner._extract", new=hallucinating_extract),
        patch("compass.evals.runner._classify_role_family_from_body", new=_fake_classify_role_family),
        patch("compass.pipeline.nodes.score._score", new=_fake_score),
    ):
        metrics, per_record = await run_against_labels(records)

    # The stub returned ["Python", "Kubernetes", "Federated Learning"] but only
    # "Python" appears in the JD. Production drops the other two as hallucinations.
    extracted_n = per_record[0]["extracted_skills_n"]
    assert extracted_n == 1, f"expected 1 extracted skill after normalization, got {extracted_n}"
    assert "kubernetes" not in per_record[0].get("extra_skills", [])
    assert metrics.extract_skill_recall == 1.0  # "Python" found


@pytest.mark.asyncio
async def test_runner_applies_score_constraint(temp_vault):
    """Regression: runner used to skip `_constrain_to_jd_skills`, letting
    score_node hallucinations through to the metrics. Now matched/missing
    are filtered to the JD's actual skill universe before comparison."""

    async def hallucinating_score(req, profile_text, job=None):
        return JobScore(
            score=4.0,
            reasoning="Real reasoning ending with terminal punctuation.",
            # JD requested only Python — but the score LLM claims candidate
            # also has matches in skills the JD didn't list.
            matched_skills=["Python", "Rust", "Erlang"],
            missing_skills=["Haskell"],
            tailoring_notes="",
        )

    async def fake_extract_python_only(jd_text):
        return JobRequirements(
            required_skills=["Python"],
            nice_to_have_skills=[],
            years_experience=2,
            seniority="mid",
            remote_policy="hybrid",
            summary="x",
        )

    records = [
        EvalRecord(
            id="eval-001",
            jd_text="Build a Python service.",
            expected_score=4.0,
            expected_skills=["Python"],
        ),
    ]
    with (
        patch("compass.evals.runner._extract", new=fake_extract_python_only),
        patch("compass.evals.runner._classify_role_family_from_body", new=_fake_classify_role_family),
        patch("compass.pipeline.nodes.score._score", new=hallucinating_score),
    ):
        metrics, _per = await run_against_labels(records)

    # candidate_match_recall uses score_result.matched_skills — production
    # constrains to the JD universe. So "Rust" and "Erlang" are filtered
    # out; only "Python" remains; recall against expected=["Python"] is 1.0.
    assert metrics.candidate_match_recall == 1.0


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
        patch("compass.evals.runner._classify_role_family_from_body", new=_fake_classify_role_family),
        patch("compass.pipeline.nodes.score._score", new=_fake_score),
    ):
        metrics, per_record = await run_against_labels(records)

    assert metrics.n == 1  # only the good one aggregated
    assert per_record[0].get("error") == "extract or score failed"
    assert per_record[1]["predicted_score"] == 4.0
