"""Pending-approval queue for the HiTL flow — aiosqlite, separate from the
LangGraph checkpoint DB.

Public surface (all coroutines):
  add_pending(thread_id, job_url, company, title, score, score_reasoning,
              matched_skills, missing_skills)
  get_pending(thread_id) -> row | None
  list_pending() -> list[row]                  # oldest first
  list_timed_out(timeout_hours) -> list[row]   # pending AND older than cutoff
  mark_resolved(thread_id, status, feedback=None)

A "row" is a plain dict with the schema documented in the implementation plan.
matched_skills / missing_skills are JSON-encoded in the DB and decoded on read.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_VALID_STATUSES = {"pending", "resuming", "approved", "rejected", "timed_out", "error"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_approvals (
  thread_id        TEXT PRIMARY KEY,
  job_url          TEXT NOT NULL,
  company          TEXT NOT NULL,
  title            TEXT NOT NULL,
  score            REAL NOT NULL,
  score_reasoning  TEXT NOT NULL,
  matched_skills   TEXT NOT NULL,
  missing_skills   TEXT NOT NULL,
  created_at       TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','resuming','approved','rejected','timed_out','error')),
  resolved_at      TEXT,
  feedback         TEXT
);
CREATE INDEX IF NOT EXISTS idx_pending_status_created
  ON pending_approvals(status, created_at);
"""


def _now() -> _dt.datetime:
    """Wall clock as UTC-aware. Indirected so tests can freeze it."""
    return _dt.datetime.now(_dt.UTC)


def _db_path():
    """Late-bound HITL_STATE_DB lookup — see module-level discipline rule."""
    import compass.config as cfg

    cfg.HITL_STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    return cfg.HITL_STATE_DB


async def _connect() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(_db_path())
    conn.row_factory = aiosqlite.Row
    # WAL mode lets concurrent readers + a single writer coexist without
    # exclusive-lock contention. Phase 1.B.3 Modal cron + a human pressing
    # `approve` in MCP will race on this file; cheaper to set the pragma now
    # than debug a flaky lock-timeout in production. PRAGMA is per-DB and
    # persists across opens.
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=5000")  # 5s retry on transient lock
    await conn.executescript(_SCHEMA)
    await conn.commit()
    return conn


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    d = dict(row)
    d["matched_skills"] = json.loads(d["matched_skills"])
    d["missing_skills"] = json.loads(d["missing_skills"])
    return d


async def add_pending(
    *,
    thread_id: str,
    job_url: str,
    company: str,
    title: str,
    score: float,
    score_reasoning: str,
    matched_skills: list[str],
    missing_skills: list[str],
) -> None:
    """Insert a new pending row. INSERT OR IGNORE — re-pausing the same thread_id is a no-op."""
    conn = await _connect()
    try:
        cursor = await conn.execute(
            """
            INSERT OR IGNORE INTO pending_approvals
              (thread_id, job_url, company, title, score, score_reasoning,
               matched_skills, missing_skills, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                thread_id,
                job_url,
                company,
                title,
                float(score),
                score_reasoning,
                json.dumps(matched_skills),
                json.dumps(missing_skills),
                _now().isoformat(),
            ),
        )
        await conn.commit()
        if cursor.rowcount == 0:
            logger.info("hitl: re-pause ignored for thread_id=%s (already pending)", thread_id)
    finally:
        await conn.close()


async def get_pending(thread_id: str) -> dict[str, Any] | None:
    conn = await _connect()
    try:
        async with conn.execute(
            "SELECT * FROM pending_approvals WHERE thread_id = ?", (thread_id,)
        ) as cur:
            row = await cur.fetchone()
    finally:
        await conn.close()
    return _row_to_dict(row) if row else None


async def list_pending() -> list[dict[str, Any]]:
    conn = await _connect()
    try:
        async with conn.execute(
            "SELECT * FROM pending_approvals WHERE status = 'pending' ORDER BY created_at ASC"
        ) as cur:
            rows = await cur.fetchall()
    finally:
        await conn.close()
    return [_row_to_dict(r) for r in rows]


async def list_timed_out(*, timeout_hours: int) -> list[dict[str, Any]]:
    cutoff = (_now() - _dt.timedelta(hours=timeout_hours)).isoformat()
    conn = await _connect()
    try:
        async with conn.execute(
            "SELECT * FROM pending_approvals "
            "WHERE status = 'pending' AND created_at < ? "
            "ORDER BY created_at ASC",
            (cutoff,),
        ) as cur:
            rows = await cur.fetchall()
    finally:
        await conn.close()
    return [_row_to_dict(r) for r in rows]


async def claim_pending(thread_id: str) -> bool:
    """Atomic single-writer claim: transitions `pending → resuming` if and only
    if the row is currently 'pending'. Returns True on successful claim,
    False if another consumer beat us to it (row is already resuming, approved,
    rejected, timed_out, or doesn't exist).

    This is the race fix between Modal cron's timeout-checker and an MCP
    `approve_job` call landing on the same thread_id at the same time.
    Without it, both consumers' get_pending+status='pending' check would
    pass, both would call graph.ainvoke on the same checkpoint, and we'd
    get conflicting JobNote writes (one "timed_out", one "approved").
    """
    conn = await _connect()
    try:
        cursor = await conn.execute(
            "UPDATE pending_approvals SET status = 'resuming' "
            "WHERE thread_id = ? AND status = 'pending'",
            (thread_id,),
        )
        await conn.commit()
        return cursor.rowcount > 0
    finally:
        await conn.close()


async def mark_resolved(
    thread_id: str,
    *,
    status: str,
    feedback: str | None = None,
) -> None:
    if status not in _VALID_STATUSES or status in ("pending", "resuming"):
        raise ValueError(f"invalid resolve status: {status!r}")

    conn = await _connect()
    try:
        # Atomic guarded UPDATE: only transitions rows currently in-flight
        # (pending = never claimed; resuming = claim_pending succeeded but
        # the graph hasn't finalized yet). Accepts both so callers can either
        # claim+finalize (the new race-safe path) or directly finalize a
        # never-claimed row (the legacy/test path).
        cursor = await conn.execute(
            "UPDATE pending_approvals "
            "SET status = ?, feedback = ?, resolved_at = ? "
            "WHERE thread_id = ? AND status IN ('pending', 'resuming')",
            (status, feedback, _now().isoformat(), thread_id),
        )
        await conn.commit()

        if cursor.rowcount == 0:
            # Distinguish "no such thread" from "already resolved" for the caller.
            async with conn.execute(
                "SELECT status FROM pending_approvals WHERE thread_id = ?",
                (thread_id,),
            ) as cur:
                existing = await cur.fetchone()
            if existing is None:
                raise LookupError(f"no pending row for thread_id {thread_id!r}")
            raise ValueError(f"thread {thread_id!r} already resolved ({existing['status']!r})")
    finally:
        await conn.close()

    logger.info("hitl: thread %s resolved as %s", thread_id, status)
