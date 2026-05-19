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
    from compass.pipeline.graph import build_graph

    config = {"configurable": {"thread_id": thread_id}}
    async with AsyncSqliteSaver.from_conn_string(str(HITL_CHECKPOINT_DB)) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        final = await graph.ainvoke(Command(resume=decision), config=config)

    if status_override is not None:
        resolved_status = status_override
    else:
        resolved_status = "approved" if decision.get("approved") else "rejected"
    await state_store.mark_resolved(
        thread_id,
        status=resolved_status,
        feedback=decision.get("feedback"),
    )
    logger.info("hitl: resumed thread %s -> %s", thread_id, resolved_status)
    return final
