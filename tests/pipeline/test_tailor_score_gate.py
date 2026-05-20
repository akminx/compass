"""Regression: tailor_node used to fire on any `human_approved=True` job
regardless of score. A mis-click in the HiTL UI on a score=1.0 row would
burn a Sonnet call. Fixed 2026-05-19 wave-2 review."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from compass.pipeline.state import JobScore, RawJob


def _state(score_value: float, threshold: float = 3.5):
    return {
        "raw_jobs": [],
        "current_job": RawJob(
            company="X",
            title="Y",
            url="https://x",
            source="manual",
            description="t",
            date_posted=date.today(),
        ),
        "extracted_requirements": None,
        "score_result": JobScore(
            score=score_value,
            reasoning="reason ending properly.",
            matched_skills=[],
            missing_skills=[],
            tailoring_notes="",
        ),
        "in_scope": True,
        "role_family": "agent-engineer",
        "agent_signal_count": 2,
        "human_approved": True,  # human clicked approve
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
        "thread_id": None,
        "score_threshold": threshold,
    }


@pytest.mark.asyncio
async def test_tailor_skipped_when_score_below_threshold(monkeypatch, temp_vault):
    from compass.pipeline.nodes import tailor

    called = AsyncMock()
    monkeypatch.setattr(tailor, "_tailor", called)

    # Score 1.0, threshold 3.5 — human_approved=True doesn't override
    out = await tailor.tailor_node(_state(score_value=1.0))
    called.assert_not_called()
    assert out == {}


@pytest.mark.asyncio
async def test_tailor_runs_when_score_meets_threshold(monkeypatch, temp_vault):
    from compass.pipeline.nodes import tailor

    async def fake(*args, **kwargs):
        return "tailored paragraph"

    monkeypatch.setattr(tailor, "_tailor", fake)

    out = await tailor.tailor_node(_state(score_value=4.0, threshold=3.5))
    assert out.get("tailored_paragraph") == "tailored paragraph"


@pytest.mark.asyncio
async def test_tailor_uses_state_threshold_over_config(monkeypatch, temp_vault):
    """If `score_threshold` is in state (sticky from score_node), use it
    rather than the live SCORE_THRESHOLD config — supports threshold drift."""
    from compass.pipeline.nodes import tailor

    called = AsyncMock()
    monkeypatch.setattr(tailor, "_tailor", called)

    # Sticky threshold 4.5, score 4.0 — score below sticky threshold, skip
    out = await tailor.tailor_node(_state(score_value=4.0, threshold=4.5))
    called.assert_not_called()
    assert out == {}
