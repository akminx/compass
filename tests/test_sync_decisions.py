"""Tests for compass.hitl.sync_decisions — bulk-apply user-edited statuses from
hitl-pending/*.md frontmatter back into the state_store + graph."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import frontmatter
import pytest

from compass.hitl import state_store, sync_decisions, vault_view


async def _seed_pending(thread_id: str, company: str = "Snowflake", title: str = "SWE"):
    await state_store.add_pending(
        thread_id=thread_id,
        job_url=f"https://x/{thread_id}",
        company=company,
        title=title,
        score=3.5,
        score_reasoning="ok",
        matched_skills=["Python"],
        missing_skills=["Go"],
    )
    row = await state_store.get_pending(thread_id)
    vault_view.write_pending_note(row)
    return row


def _edit_status(temp_vault, thread_id: str, status: str, feedback: str | None = None):
    matches = list((temp_vault / "hitl-pending").glob(f"{thread_id}-*.md"))
    assert matches, f"no pending note for thread_id={thread_id}"
    post = frontmatter.load(matches[0])
    post["status"] = status
    if feedback is not None:
        post["feedback"] = feedback
    matches[0].write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_sync_no_pending_dir_returns_empty(temp_vault):
    result = await sync_decisions.sync_decisions()
    assert result == {"processed": [], "skipped": [], "errors": []}


@pytest.mark.asyncio
async def test_sync_skips_pending_status_unchanged(temp_vault, temp_hitl_db):
    await _seed_pending("aaaa11112222")
    # User hasn't edited — status still pending
    result = await sync_decisions.sync_decisions()
    assert result["processed"] == []


@pytest.mark.asyncio
async def test_sync_approves_edited_note(temp_vault, temp_hitl_db):
    await _seed_pending("bbbb22223333", company="Anthropic", title="Applied AI Engineer")
    _edit_status(temp_vault, "bbbb22223333", "approved", feedback="strong fit")

    fake_final = {"vault_written": True, "human_approved": True, "human_feedback": "strong fit"}
    with patch.object(sync_decisions, "resume_pending", AsyncMock(return_value=fake_final)) as m:
        result = await sync_decisions.sync_decisions()

    assert len(result["processed"]) == 1
    p = result["processed"][0]
    assert p["action"] == "approved"
    assert p["company"] == "Anthropic"
    assert p["vault_written"] is True
    # resume_pending called with the right args
    m.assert_called_once()
    args, kwargs = m.call_args
    assert args[0] == "bbbb22223333"
    assert kwargs["decision"]["approved"] is True
    assert kwargs["decision"]["feedback"] == "strong fit"


@pytest.mark.asyncio
async def test_sync_rejects_edited_note(temp_vault, temp_hitl_db):
    await _seed_pending("cccc33334444")
    _edit_status(temp_vault, "cccc33334444", "rejected", feedback="too senior")

    fake_final = {"vault_written": True, "human_approved": False, "human_feedback": "too senior"}
    with patch.object(sync_decisions, "resume_pending", AsyncMock(return_value=fake_final)) as m:
        result = await sync_decisions.sync_decisions()

    assert result["processed"][0]["action"] == "rejected"
    kwargs = m.call_args.kwargs
    assert kwargs["decision"]["approved"] is False


@pytest.mark.asyncio
async def test_sync_skips_already_resolved_in_db(temp_vault, temp_hitl_db):
    """If state_store says the thread is already resolved (race condition or
    second sync run), skip cleanly — don't try to resume again."""
    await _seed_pending("dddd44445555")
    _edit_status(temp_vault, "dddd44445555", "approved")
    # Pre-resolve in DB
    await state_store.mark_resolved("dddd44445555", status="approved")

    with patch.object(sync_decisions, "resume_pending", AsyncMock()) as m:
        result = await sync_decisions.sync_decisions()

    assert result["processed"] == []
    assert len(result["skipped"]) == 1
    assert "already" in result["skipped"][0]["reason"]
    m.assert_not_called()


@pytest.mark.asyncio
async def test_sync_handles_multiple_decisions(temp_vault, temp_hitl_db):
    await _seed_pending("a" * 12, company="A", title="role A")
    await _seed_pending("b" * 12, company="B", title="role B")
    await _seed_pending("c" * 12, company="C", title="role C")
    _edit_status(temp_vault, "a" * 12, "approved")
    _edit_status(temp_vault, "b" * 12, "rejected")
    # c stays pending

    fake_final = {"vault_written": True, "human_approved": True}
    with patch.object(sync_decisions, "resume_pending", AsyncMock(return_value=fake_final)):
        result = await sync_decisions.sync_decisions()

    assert len(result["processed"]) == 2
    actions = {p["company"]: p["action"] for p in result["processed"]}
    assert actions == {"A": "approved", "B": "rejected"}


@pytest.mark.asyncio
async def test_sync_records_resume_errors(temp_vault, temp_hitl_db):
    await _seed_pending("eeee55556666")
    _edit_status(temp_vault, "eeee55556666", "approved")

    with patch.object(
        sync_decisions,
        "resume_pending",
        AsyncMock(side_effect=LookupError("no such thread")),
    ):
        result = await sync_decisions.sync_decisions()

    assert result["processed"] == []
    assert len(result["errors"]) == 1
    assert "no such thread" in result["errors"][0]["error"]
