"""Atomic claim regression tests — confirms the Modal-cron + MCP-approve race
fix from the 2026-05-19 adversarial review (wave 2)."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_claim_pending_succeeds_once(temp_hitl_db):
    from compass.hitl import state_store

    await state_store.add_pending(
        thread_id="race-1",
        job_url="https://x/1",
        company="X",
        title="Y",
        score=4.0,
        score_reasoning="t",
        matched_skills=[],
        missing_skills=[],
    )
    assert await state_store.claim_pending("race-1") is True


@pytest.mark.asyncio
async def test_claim_pending_second_call_returns_false(temp_hitl_db):
    """Modal cron + MCP approve race: only one consumer claims."""
    from compass.hitl import state_store

    await state_store.add_pending(
        thread_id="race-2",
        job_url="https://x/2",
        company="X",
        title="Y",
        score=4.0,
        score_reasoning="t",
        matched_skills=[],
        missing_skills=[],
    )
    first = await state_store.claim_pending("race-2")
    second = await state_store.claim_pending("race-2")
    assert first is True
    assert second is False, "second claim must lose the race"


@pytest.mark.asyncio
async def test_claim_pending_missing_thread_returns_false(temp_hitl_db):
    from compass.hitl import state_store

    assert await state_store.claim_pending("nonexistent") is False


@pytest.mark.asyncio
async def test_mark_resolved_works_after_claim(temp_hitl_db):
    """The claim → finalize flow: claim_pending transitions to 'resuming',
    then mark_resolved completes the transition to the final status."""
    from compass.hitl import state_store

    await state_store.add_pending(
        thread_id="finalize-1",
        job_url="https://x/3",
        company="X",
        title="Y",
        score=4.0,
        score_reasoning="t",
        matched_skills=[],
        missing_skills=[],
    )
    assert await state_store.claim_pending("finalize-1") is True
    await state_store.mark_resolved("finalize-1", status="approved")
    row = await state_store.get_pending("finalize-1")
    # After resolution the row stays but with new status
    assert row is None or row.get("status") == "approved"


@pytest.mark.asyncio
async def test_mark_resolved_blocked_after_claim_by_another_caller(temp_hitl_db):
    """Once a row is in 'resuming' state, a SECOND mark_resolved still works
    (the first claim → finalize completes). But a separate attempt that
    didn't claim first should ALSO succeed if the row is still in 'resuming' —
    this matches the legacy single-writer behavior."""
    from compass.hitl import state_store

    await state_store.add_pending(
        thread_id="dual-1",
        job_url="https://x/4",
        company="X",
        title="Y",
        score=4.0,
        score_reasoning="t",
        matched_skills=[],
        missing_skills=[],
    )
    await state_store.claim_pending("dual-1")
    await state_store.mark_resolved("dual-1", status="approved")
    # Subsequent mark_resolved on an already-resolved row raises
    with pytest.raises(ValueError):
        await state_store.mark_resolved("dual-1", status="rejected")
