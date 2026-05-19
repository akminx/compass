"""Resume a paused LangGraph thread by re-opening the checkpointer and
recompiling the graph. Single source of truth for resumes — the timeout
checker and MCP `approve` tool both go through here."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from compass.hitl import state_store

logger = logging.getLogger(__name__)


async def resume_pending(
    thread_id: str,
    *,
    decision: dict[str, Any],
    status_override: str | None = None,
) -> dict:
    """Drive a paused thread to completion.

    decision: passed as `Command(resume=decision)`. Expected shape
              {"approved": bool, "feedback": str | None}.
    status_override: optional explicit status to write to the state store
                     (timeout_checker uses "timed_out"). If None, derived from
                     decision["approved"]: True -> "approved", False -> "rejected".
    Raises LookupError if the thread isn't in the state store.
    Raises ValueError if the thread is already resolved.
    """
    from compass.config import HITL_CHECKPOINT_DB

    row = await state_store.get_pending(thread_id)
    if row is None:
        raise LookupError(f"no pending thread {thread_id!r}")
    if row["status"] != "pending":
        raise ValueError(f"thread {thread_id!r} already resolved ({row['status']!r})")

    # Late import to avoid potential circular import: graph.py imports state_store
    from compass.pipeline.graph import _build_checkpoint_serde, build_graph

    config = {"configurable": {"thread_id": thread_id}}
    async with AsyncSqliteSaver.from_conn_string(str(HITL_CHECKPOINT_DB)) as checkpointer:
        checkpointer.serde = _build_checkpoint_serde()
        graph = build_graph(checkpointer=checkpointer)
        final = await graph.ainvoke(Command(resume=decision), config=config)

    if status_override is not None:
        resolved_status = status_override
    else:
        # Derive from the FINAL graph state, not the input decision. A graph that
        # auto-rejected on resume (e.g. SCORE_THRESHOLD edited between pause and
        # resume, hitl_node short-circuited before consuming interrupt()) would
        # otherwise be recorded as "approved" in state_store while the JobNote
        # carries hitl_decision="auto_rejected" — audit-trail divergence.
        resolved_status = "approved" if final.get("human_approved") is True else "rejected"
    await state_store.mark_resolved(
        thread_id,
        status=resolved_status,
        feedback=decision.get("feedback"),
    )
    await _purge_thread_checkpoints(thread_id)

    if final.get("vault_written"):
        # Resumed thread wrote a JobNote — derived counters (skills/appears_in_jobs,
        # companies/roles_seen) now drift unless we resync. Phase 0 bug #12 + Phase
        # 1.A bug #1 family: run_pipeline() calls regenerate() at end of batch, but
        # resume paths (MCP approve + timeout_checker) bypass that. Call it here so
        # every resume keeps the vault internally consistent.
        from compass.analysis import gap_aggregator

        try:
            gap_aggregator.regenerate(write=True)
        except Exception:
            # Counter sync failure must not block the resume — log and continue.
            logger.exception("hitl: gap_aggregator.regenerate failed after resume")

    logger.info("hitl: resumed thread %s -> %s", thread_id, resolved_status)
    return final


async def _purge_thread_checkpoints(thread_id: str) -> None:
    """Drop LangGraph per-step history for a resolved thread; state_store is the audit trail."""
    import aiosqlite

    from compass.config import HITL_CHECKPOINT_DB

    async with aiosqlite.connect(HITL_CHECKPOINT_DB) as conn:
        await conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        await conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
        await conn.commit()
