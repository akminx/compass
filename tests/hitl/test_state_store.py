"""state_store CRUD: add/get/list/resolve + status transitions + serialisation."""

from __future__ import annotations

import datetime as _dt

import pytest

from compass.hitl import state_store

pytestmark = pytest.mark.usefixtures("temp_hitl_db")


async def _add_one(thread_id: str = "tid-1", **overrides) -> None:
    defaults = dict(
        thread_id=thread_id,
        job_url="https://jobs.example.com/abc",
        company="Sierra",
        title="Software Engineer, Agent",
        score=4.2,
        score_reasoning="Strong match on MCP + LangGraph.",
        matched_skills=["MCP", "Python"],
        missing_skills=["LangGraph"],
    )
    defaults.update(overrides)
    await state_store.add_pending(**defaults)


async def test_add_and_get_round_trips(frozen_now):
    await _add_one()
    row = await state_store.get_pending("tid-1")
    assert row is not None
    assert row["thread_id"] == "tid-1"
    assert row["company"] == "Sierra"
    assert row["score"] == pytest.approx(4.2)
    assert row["matched_skills"] == ["MCP", "Python"]
    assert row["missing_skills"] == ["LangGraph"]
    assert row["status"] == "pending"
    assert row["created_at"] == frozen_now.isoformat()
    assert row["resolved_at"] is None
    assert row["feedback"] is None


async def test_add_pending_is_idempotent_on_thread_id():
    """Re-running a pipeline that re-pauses the same thread_id is a no-op, not a crash."""
    await _add_one()
    # Second call with same thread_id but different score should be a no-op
    # (we don't overwrite — the resume must use the original checkpoint).
    await _add_one(score=2.0)
    row = await state_store.get_pending("tid-1")
    assert row["score"] == pytest.approx(4.2)


async def test_list_pending_only_returns_pending_status():
    await _add_one(thread_id="tid-pending")
    await _add_one(thread_id="tid-approved")
    await state_store.mark_resolved("tid-approved", status="approved")
    rows = await state_store.list_pending()
    assert [r["thread_id"] for r in rows] == ["tid-pending"]


async def test_list_pending_orders_oldest_first(monkeypatch):
    """The MCP UI shows the queue oldest-first so things don't get lost."""
    import compass.hitl.state_store as ss

    fixed = _dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.UTC)
    monkeypatch.setattr(ss, "_now", lambda: fixed)
    await _add_one(thread_id="tid-old")
    monkeypatch.setattr(ss, "_now", lambda: fixed + _dt.timedelta(minutes=5))
    await _add_one(thread_id="tid-new")
    rows = await state_store.list_pending()
    assert [r["thread_id"] for r in rows] == ["tid-old", "tid-new"]


async def test_mark_resolved_records_status_and_timestamp(frozen_now):
    await _add_one()
    await state_store.mark_resolved("tid-1", status="approved", feedback="LGTM")
    row = await state_store.get_pending("tid-1")
    assert row["status"] == "approved"
    assert row["feedback"] == "LGTM"
    assert row["resolved_at"] == frozen_now.isoformat()


async def test_mark_resolved_rejects_unknown_status():
    await _add_one()
    with pytest.raises(ValueError, match="status"):
        await state_store.mark_resolved("tid-1", status="bogus")


async def test_mark_resolved_unknown_thread_raises():
    with pytest.raises(LookupError):
        await state_store.mark_resolved("tid-missing", status="approved")


async def test_list_timed_out_returns_only_old_pending(frozen_now, monkeypatch):
    import compass.hitl.state_store as ss

    old = frozen_now - _dt.timedelta(hours=5)
    young = frozen_now - _dt.timedelta(hours=1)
    monkeypatch.setattr(ss, "_now", lambda: old)
    await _add_one(thread_id="tid-old")
    monkeypatch.setattr(ss, "_now", lambda: young)
    await _add_one(thread_id="tid-young")
    monkeypatch.setattr(ss, "_now", lambda: frozen_now)
    rows = await state_store.list_timed_out(timeout_hours=4)
    assert [r["thread_id"] for r in rows] == ["tid-old"]


async def test_get_pending_unknown_returns_none():
    assert await state_store.get_pending("nope") is None


async def test_mark_resolved_rejects_already_resolved_row():
    """Concurrent resolvers race: second one must see ValueError, not silent overwrite."""
    await _add_one()
    await state_store.mark_resolved("tid-1", status="approved", feedback="first")
    with pytest.raises(ValueError, match="already resolved"):
        await state_store.mark_resolved("tid-1", status="timed_out")
    # Confirm the first resolution stuck — no silent overwrite
    row = await state_store.get_pending("tid-1")
    assert row["status"] == "approved"
    assert row["feedback"] == "first"
