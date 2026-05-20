"""MCP wrappers around state_store + resume_pending — JSON-serializable
return shapes (no datetime objects, no Pydantic instances)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from compass.hitl import state_store

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def checkpoint_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "checkpoints.db"
    import compass.config as cfg

    monkeypatch.setattr(cfg, "HITL_CHECKPOINT_DB", db)
    return db


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db")
async def test_pending_approvals_tool_returns_jsonable_rows():
    from compass.mcp_server.server import pending_approvals

    await state_store.add_pending(
        thread_id="tid-1",
        job_url="https://x/1",
        company="Sierra",
        title="SWE Agent",
        score=4.2,
        score_reasoning="solid",
        matched_skills=["MCP"],
        missing_skills=["LangGraph"],
    )
    rows = await pending_approvals()
    assert len(rows) == 1
    assert rows[0]["thread_id"] == "tid-1"
    # Must be plain JSON-serialisable
    json.dumps(rows)


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db")
async def test_approve_tool_invokes_resume(monkeypatch):
    from compass.mcp_server import server as mcp_server

    captured = {}

    async def fake_resume(thread_id, *, decision, status_override=None):
        captured["thread_id"] = thread_id
        captured["decision"] = decision
        captured["status_override"] = status_override
        return {"vault_written": True, "human_approved": decision["approved"]}

    monkeypatch.setattr(mcp_server, "_resume_pending", fake_resume)

    result = await mcp_server.approve(thread_id="tid-x", approved=True, feedback="LGTM")
    assert result == {"vault_written": True, "human_approved": True, "human_feedback": None}
    assert captured == {
        "thread_id": "tid-x",
        "decision": {"approved": True, "feedback": "LGTM"},
        "status_override": None,
    }


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db")
async def test_approve_tool_handles_unknown_thread_as_error_dict():
    from compass.mcp_server.server import approve

    result = await approve(thread_id="missing", approved=False)
    assert "error" in result and "missing" in result["error"]
