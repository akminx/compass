# Compass Phase 1.B.1 — Real HiTL via `interrupt()` + `AsyncSqliteSaver` (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Phase 0.B/1.A auto-approve `hitl_node` with a real LangGraph `interrupt()`-based human approval flow, backed by `AsyncSqliteSaver` checkpointing and a SQLite-backed pending-approval queue. Add MCP tools (`pending_approvals`, `approve`) so the human approves/rejects scored-but-pre-tailor jobs from Claude Code or Cursor. Add a `timeout_checker` module that any cron (Modal cron lands in 1.B.3) can call to auto-cancel approvals older than `HITL_TIMEOUT_HOURS`. End state: above-threshold jobs pause at `hitl`, sit in `pending_approvals()` until a human acts, then resume into `tailor` + `vault_write` (or skip tailor on reject). Below-threshold jobs continue to auto-reject the same way they do today — no interrupt, no human prompt — so the cost of running the pipeline is unchanged for the long tail.

**Architecture:** Three new modules under `compass/hitl/`: `state_store.py` (aiosqlite-backed pending queue, one row per paused thread), `resume.py` (re-opens the checkpointer + recompiles the graph + calls `graph.ainvoke(Command(resume=...), config={"configurable": {"thread_id": ...}})`), `timeout_checker.py` (polls the queue, resumes timed-out threads with `{"approved": False}`). `hitl_node` becomes a one-line `interrupt(...)` call wrapped with a below-threshold short-circuit. `run_pipeline()` is restructured so the `AsyncSqliteSaver` is opened once per batch (`async with` block), the graph is compiled inside it, and the per-job invocation generates a deterministic `thread_id` from the job URL + scrape timestamp. After every batch, the orchestrator detects which jobs paused (via `__interrupt__` in returned state, registering them in the state store) versus which ran to completion. New MCP tools (`pending_approvals`, `approve`) wrap the resume entrypoint. No changes to `extract` / `score` / `reflect` / `tailor` / `vault_write` node bodies.

**Module-level discipline (carried forward from Phase 1.A):** any module that touches `VAULT_PATH`, `HITL_STATE_DB`, or `HITL_TIMEOUT_HOURS` must reference it via `compass.config.<NAME>` *inside the function body*, never as a module-level captured constant. The `temp_vault` and new `temp_hitl_db` pytest fixtures monkeypatch `compass.config`, which only affects code that re-reads the attribute each call.

**Tech Stack:** Python 3.12 · langgraph 1.2 (`langgraph.types.interrupt`, `langgraph.types.Command`) · langgraph-checkpoint-sqlite 3.1 (`langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver`) · aiosqlite 0.20 (for the pending-approval queue, kept separate from the checkpoint DB) · pytest + pytest-asyncio (`asyncio_mode = "auto"` already set).

**Authoritative spec:** `docs/superpowers/specs/2026-05-17-compass-mvp-to-portfolio-ship-design.md` § Phase 1.B
**Previous-phase handoff:** `docs/PHASE_1A_COMPLETE.md`

**Closes these deferred items from Phase 1.A:**
1. Real `interrupt()` + `AsyncSqliteSaver` checkpointing (P1.A handoff "What's deferred", row 1)
2. The `_route_after_hitl` three-way comment in `graph.py:48–58` that already anticipates this flow
3. The `HITL_STATE_DB` + `HITL_TIMEOUT_HOURS` env vars in `compass/config.py:46–47` and `.env.example:30–31` (defined for 1.B; used here for the first time)

**Does NOT touch in this phase:**
- RAG / Chroma — deferred to **Phase 1.B.2**
- Modal cron decorators (`modal_app.py`, `@app.function(schedule=Cron(...))`) — deferred to **Phase 1.B.3**. This phase ships `timeout_checker.py` as a callable module + plain CLI entrypoint (`python -m compass.hitl.timeout_checker`) so the 1.B.3 Modal cron just imports it.
- Langfuse callback API mismatch (bug #23) — deferred to **Phase 1.B.3** observability work
- `extract` / `score` / `reflect` / `tailor` / `vault_write` node bodies
- `compass/llm.py`, taxonomy, schemas, applications lifecycle

---

## File Structure

### New
- `compass/hitl/state_store.py` — async aiosqlite store of pending approvals; pure data access
- `compass/hitl/resume.py` — `resume_pending(thread_id, decision, feedback)` reopens the checkpointer, recompiles the graph, drives the resume
- `compass/hitl/timeout_checker.py` — `check_and_resume_timeouts()` plus `__main__` CLI entrypoint
- `compass/hitl/__init__.py` — re-export the public surface

### Test scaffolding (new)
- `tests/hitl/__init__.py`
- `tests/hitl/conftest.py` — `temp_hitl_db` fixture (monkeypatch `compass.config.HITL_STATE_DB` to a tmp path) and `frozen_now` fixture
- `tests/hitl/test_state_store.py`
- `tests/hitl/test_resume.py`
- `tests/hitl/test_timeout_checker.py`
- `tests/pipeline/test_hitl_node_interrupt.py` — replaces (does not extend) the auto-approve tests in `tests/pipeline/test_hitl_node.py`
- `tests/pipeline/test_graph_checkpointing.py` — end-to-end: invoke graph, confirm pause; resume via `resume_pending`; confirm tailor + vault_write fire
- `tests/mcp_server/test_pending_approvals.py`

### Modify
- `compass/pipeline/nodes/hitl.py` — replace auto-approve body with `interrupt(...)` + below-threshold short-circuit
- `compass/vault/schemas.py` — tighten `JobNote.hitl_decision` from `str | None` to `Literal["approved","rejected","auto_rejected","timed_out"] | None` (Task 2.5)
- `compass/pipeline/nodes/vault_write.py` — populate `hitl_decision` + `hitl_at` on the JobNote from `state["human_approved"]` so the vault carries the audit trail
- `compass/pipeline/graph.py` — open `AsyncSqliteSaver` once per `run_pipeline` invocation; compile graph inside the `async with`; generate deterministic `thread_id` per job; detect paused vs completed jobs; register paused jobs in the state store
- `compass/pipeline/state.py` — add `thread_id: str | None` to `CompassState` (so `hitl_node` and `vault_write_node` can read it from `RunnableConfig` and surface it in logs/state)
- `compass/mcp_server/server.py` — add `pending_approvals()` and `approve()` tools
- `compass/config.py` — `HITL_CHECKPOINT_DB` env var (defaults to `~/.compass/checkpoints.db`); keep `HITL_STATE_DB` (pending queue) and `HITL_TIMEOUT_HOURS` as-is
- `.env.example` — document `HITL_CHECKPOINT_DB`
- `tests/pipeline/test_routing.py` — remove the three existing `hitl_node` auto-approve tests (lines 46-66); the new behaviour is covered by `test_hitl_node_interrupt.py`
- `tests/pipeline/test_graph_integration.py` — add an `auto_approve_hitl` fixture (monkeypatches `compass.pipeline.nodes.hitl.interrupt` to a stub returning `{"approved": True}`); opt the three above-threshold integration tests into it so they still exercise the full pipeline without needing real checkpoint+resume

### Untouched
- `compass/pipeline/nodes/{intake,intake_filter,extract,score,reflect,tailor,vault_write}.py`
- `compass/pipeline/role_family.py`
- `compass/vault/*`, `compass/scrapers/*`, `compass/applications/*`, `compass/analysis/*`, `compass/llm.py`
- All Phase 1.A tests (must still pass)

### Decomposition rationale
The pending-approval queue (`state_store.py`) is intentionally separate from the LangGraph checkpoint DB. The checkpoint DB is LangGraph-owned (schema controlled by `AsyncSqliteSaver`) and stores graph node state; the pending queue is *our* schema, optimized for `pending_approvals()` (we don't need to deserialize a full checkpoint just to list pending jobs by company + title + score). Two SQLite files in `~/.compass/`. The `resume.py` module is the only place that mounts the checkpointer for resumes — keeping it focused makes it the single audit point for "did we recompile the graph correctly with the checkpointer". `timeout_checker.py` calls `resume_pending` rather than reimplementing resume, so the timeout path and the human path go through identical code.

---

## Task 0: Pre-flight

**Files:** none

- [ ] **Step 1: Verify clean tree on `phase-1a-application-tracking` tag**

```bash
cd ~/Documents/compass
git status                       # expected: clean
git describe --tags --abbrev=0   # expected: phase-1a-application-tracking
uv run pytest -q                 # expected: 204 passed
uv run ruff check                # expected: All checks passed
```

If working tree is dirty, STOP and ask the user before proceeding.

- [ ] **Step 2: Confirm LangGraph + checkpointer libs are at expected versions**

```bash
uv run python -c "
import importlib.metadata as m
print('langgraph', m.version('langgraph'))
print('langgraph-checkpoint-sqlite', m.version('langgraph-checkpoint-sqlite'))
from langgraph.types import interrupt, Command  # smoke
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # smoke
"
```

Expected: `langgraph >= 1.2`, `langgraph-checkpoint-sqlite >= 3.1`, both imports succeed. If lower, ask the user before bumping — version skew bit bug #4 in Phase 0.

- [ ] **Step 3: Create branch**

```bash
git checkout -b phase-1b1-hitl
```

---

## Task 1: Pending-approval state store (`compass/hitl/state_store.py`)

**Why first:** Pure data layer with no LangGraph dependency. We can TDD it without touching the graph, then plug it in from the orchestrator in Task 3.

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS pending_approvals (
  thread_id        TEXT PRIMARY KEY,
  job_url          TEXT NOT NULL,
  company          TEXT NOT NULL,
  title            TEXT NOT NULL,
  score            REAL NOT NULL,
  score_reasoning  TEXT NOT NULL,
  matched_skills   TEXT NOT NULL,   -- JSON array
  missing_skills   TEXT NOT NULL,   -- JSON array
  created_at       TEXT NOT NULL,   -- ISO8601 UTC
  status           TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','approved','rejected','timed_out','error')),
  resolved_at      TEXT,
  feedback         TEXT
);
CREATE INDEX IF NOT EXISTS idx_pending_status_created
  ON pending_approvals(status, created_at);
```

**Files:**
- Create: `compass/hitl/__init__.py` (empty for now)
- Create: `compass/hitl/state_store.py`
- Create: `tests/hitl/__init__.py`
- Create: `tests/hitl/conftest.py`
- Create: `tests/hitl/test_state_store.py`

- [ ] **Step 1: Write the `temp_hitl_db` fixture**

Create `tests/hitl/conftest.py`:

```python
"""Shared fixtures for HiTL tests."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest


@pytest.fixture
def temp_hitl_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HITL_STATE_DB at a fresh per-test SQLite file.

    The store reads `compass.config.HITL_STATE_DB` inside function bodies (per
    the module-level discipline rule), so monkeypatching the attribute is
    sufficient — no module reimport needed.
    """
    db = tmp_path / "pending.db"
    import compass.config as cfg
    monkeypatch.setattr(cfg, "HITL_STATE_DB", db)
    return db


@pytest.fixture
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> _dt.datetime:
    """Freeze the wall clock the state store uses."""
    fixed = _dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.timezone.utc)

    class _FrozenDT(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.astimezone(tz)

    import compass.hitl.state_store as ss
    monkeypatch.setattr(ss, "_now", lambda: fixed)
    return fixed
```

- [ ] **Step 2: Write the failing tests**

Create `tests/hitl/test_state_store.py`:

```python
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


async def test_list_pending_orders_oldest_first():
    """The MCP UI shows the queue oldest-first so things don't get lost."""
    import compass.hitl.state_store as ss
    # First insertion at frozen_now
    fixed = _dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.timezone.utc)
    ss._now = lambda: fixed
    await _add_one(thread_id="tid-old")
    ss._now = lambda: fixed + _dt.timedelta(minutes=5)
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


async def test_list_timed_out_returns_only_old_pending(frozen_now):
    import compass.hitl.state_store as ss
    # Insert one row "5 hours ago", one "1 hour ago"
    old = frozen_now - _dt.timedelta(hours=5)
    young = frozen_now - _dt.timedelta(hours=1)
    ss._now = lambda: old
    await _add_one(thread_id="tid-old")
    ss._now = lambda: young
    await _add_one(thread_id="tid-young")
    ss._now = lambda: frozen_now
    rows = await state_store.list_timed_out(timeout_hours=4)
    assert [r["thread_id"] for r in rows] == ["tid-old"]


async def test_get_pending_unknown_returns_none():
    assert await state_store.get_pending("nope") is None
```

Run:

```bash
uv run pytest tests/hitl/test_state_store.py -v
```

Expected: every test fails with `ModuleNotFoundError: compass.hitl.state_store` or `AttributeError`.

- [ ] **Step 3: Implement `state_store.py`**

Create `compass/hitl/state_store.py`:

```python
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

_VALID_STATUSES = {"pending", "approved", "rejected", "timed_out", "error"}

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
                   CHECK (status IN ('pending','approved','rejected','timed_out','error')),
  resolved_at      TEXT,
  feedback         TEXT
);
CREATE INDEX IF NOT EXISTS idx_pending_status_created
  ON pending_approvals(status, created_at);
"""


def _now() -> _dt.datetime:
    """Wall clock as UTC-aware. Indirected so tests can freeze it."""
    return _dt.datetime.now(_dt.timezone.utc)


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
    async with await _connect() as conn:
        await conn.execute(
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


async def get_pending(thread_id: str) -> dict[str, Any] | None:
    async with await _connect() as conn:
        async with conn.execute(
            "SELECT * FROM pending_approvals WHERE thread_id = ?", (thread_id,)
        ) as cur:
            row = await cur.fetchone()
    return _row_to_dict(row) if row else None


async def list_pending() -> list[dict[str, Any]]:
    async with await _connect() as conn:
        async with conn.execute(
            "SELECT * FROM pending_approvals WHERE status = 'pending' "
            "ORDER BY created_at ASC"
        ) as cur:
            rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def list_timed_out(*, timeout_hours: int) -> list[dict[str, Any]]:
    cutoff = (_now() - _dt.timedelta(hours=timeout_hours)).isoformat()
    async with await _connect() as conn:
        async with conn.execute(
            "SELECT * FROM pending_approvals "
            "WHERE status = 'pending' AND created_at < ? "
            "ORDER BY created_at ASC",
            (cutoff,),
        ) as cur:
            rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def mark_resolved(
    thread_id: str,
    *,
    status: str,
    feedback: str | None = None,
) -> None:
    if status not in _VALID_STATUSES or status == "pending":
        raise ValueError(f"invalid resolve status: {status!r}")
    async with await _connect() as conn:
        async with conn.execute(
            "SELECT 1 FROM pending_approvals WHERE thread_id = ?", (thread_id,)
        ) as cur:
            if not await cur.fetchone():
                raise LookupError(f"no pending row for thread_id {thread_id!r}")
        await conn.execute(
            "UPDATE pending_approvals "
            "SET status = ?, feedback = ?, resolved_at = ? "
            "WHERE thread_id = ?",
            (status, feedback, _now().isoformat(), thread_id),
        )
        await conn.commit()
```

- [ ] **Step 4: Run the tests, confirm pass**

```bash
uv run pytest tests/hitl/test_state_store.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add compass/hitl/__init__.py compass/hitl/state_store.py tests/hitl/__init__.py \
        tests/hitl/conftest.py tests/hitl/test_state_store.py
git commit -m "feat(hitl): aiosqlite-backed pending-approval state store"
```

---

## Task 2: Rewire `hitl_node` to call `interrupt()`

**Files:**
- Modify: `compass/pipeline/nodes/hitl.py`
- Replace: `tests/pipeline/test_hitl_node.py` → `tests/pipeline/test_hitl_node_interrupt.py`

**Design:**

```
hitl_node(state):
  score = state.get("score_result")
  if score is None or score.score < SCORE_THRESHOLD:
      # auto-reject for missing / low-score — exactly the 1.A behaviour.
      # No interrupt fires; the orchestrator never sees this thread.
      return {"human_approved": False}

  decision = interrupt({
      "kind": "approval_request",
      "job_url": state["current_job"].url,
      "company": state["current_job"].company,
      "title": state["current_job"].title,
      "score": score.score,
      "score_reasoning": score.reasoning,
      "matched_skills": score.matched_skills,
      "missing_skills": score.missing_skills,
  })

  # On resume, `decision` is whatever was passed to Command(resume=...)
  if not isinstance(decision, dict):
      return {"human_approved": False}
  return {
      "human_approved": bool(decision.get("approved", False)),
      "human_feedback": decision.get("feedback"),
  }
```

The `interrupt(...)` payload above is what the orchestrator captures (via the `__interrupt__` marker on the returned graph state) to populate `state_store.add_pending(...)`.

- [ ] **Step 1: Remove the three old auto-approve tests from `test_routing.py`**

The auto-approve tests live in `tests/pipeline/test_routing.py:46-66` (NOT in a standalone `test_hitl_node.py`). Delete the three test functions:

- `test_hitl_node_approves_when_score_meets_threshold`
- `test_hitl_node_rejects_when_score_below_threshold`
- `test_hitl_node_handles_missing_score`

…along with their shared `_state(score)` helper if it's no longer referenced elsewhere in the file. The `reflect_node` tests in the same file stay. Confirm with:

```bash
grep -n "hitl_node\|SCORE_THRESHOLD" tests/pipeline/test_routing.py
```

Expected: no matches after the deletion. If `_state` is still used by reflect tests, keep it; otherwise delete it too.

- [ ] **Step 2: Write the new interrupt-based tests**

Create `tests/pipeline/test_hitl_node_interrupt.py`:

```python
"""hitl_node calls interrupt() above threshold; auto-rejects below threshold."""

from __future__ import annotations

import datetime as _dt

import pytest

from compass.pipeline.nodes.hitl import hitl_node
from compass.pipeline.state import CompassState, JobScore, RawJob


def _state(score: float | None) -> CompassState:
    job = RawJob(
        company="Sierra",
        title="SWE, Agent",
        url="https://jobs.example.com/sierra-1",
        source="ashby",
        description="...",
        date_posted=_dt.date(2026, 5, 18),
    )
    sr = (
        None
        if score is None
        else JobScore(
            score=score,
            reasoning="ok",
            matched_skills=["MCP"],
            missing_skills=["LangGraph"],
            tailoring_notes="",
        )
    )
    return {
        "raw_jobs": [],
        "current_job": job,
        "extracted_requirements": None,
        "score_result": sr,
        "in_scope": True,
        "role_family": "agent-engineer",
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
        "thread_id": "tid-test",
    }


async def test_below_threshold_auto_rejects_without_interrupt(monkeypatch):
    """Below SCORE_THRESHOLD short-circuits — interrupt MUST NOT fire (no human prompt cost)."""
    called = {"interrupt": 0}

    def boom(_payload):
        called["interrupt"] += 1
        raise AssertionError("interrupt should not have been called")

    monkeypatch.setattr("compass.pipeline.nodes.hitl.interrupt", boom)
    result = await hitl_node(_state(score=2.0))
    assert result == {"human_approved": False}
    assert called["interrupt"] == 0


async def test_missing_score_auto_rejects():
    result = await hitl_node(_state(score=None))
    assert result == {"human_approved": False}


async def test_above_threshold_calls_interrupt_with_payload(monkeypatch):
    captured = {}

    def fake_interrupt(payload):
        captured.update(payload)
        # Simulate resume value (this is what Command(resume=...) sends back)
        return {"approved": True, "feedback": "Strong fit"}

    monkeypatch.setattr("compass.pipeline.nodes.hitl.interrupt", fake_interrupt)
    result = await hitl_node(_state(score=4.2))
    assert captured["kind"] == "approval_request"
    assert captured["company"] == "Sierra"
    assert captured["score"] == pytest.approx(4.2)
    assert captured["matched_skills"] == ["MCP"]
    assert result == {"human_approved": True, "human_feedback": "Strong fit"}


async def test_resume_rejection_propagates(monkeypatch):
    monkeypatch.setattr(
        "compass.pipeline.nodes.hitl.interrupt",
        lambda _p: {"approved": False, "feedback": "Not a fit"},
    )
    result = await hitl_node(_state(score=4.2))
    assert result == {"human_approved": False, "human_feedback": "Not a fit"}


async def test_malformed_resume_value_defaults_to_rejected(monkeypatch):
    """If Command(resume=...) somehow sends a non-dict, treat as reject not crash."""
    monkeypatch.setattr("compass.pipeline.nodes.hitl.interrupt", lambda _p: "bogus")
    result = await hitl_node(_state(score=4.2))
    assert result == {"human_approved": False}
```

Run:

```bash
uv run pytest tests/pipeline/test_hitl_node_interrupt.py -v
```

Expected: all fail (interrupt symbol not imported in hitl.py yet).

- [ ] **Step 3: Implement the new `hitl_node`**

Replace `compass/pipeline/nodes/hitl.py` entirely:

```python
"""hitl_node — Phase 1.B.1 real human-in-the-loop via LangGraph interrupt().

Behaviour:
  • score < SCORE_THRESHOLD or score missing -> auto-reject, no interrupt fires
  • score >= SCORE_THRESHOLD -> interrupt() with the approval payload; the
    orchestrator catches the interrupt and registers the thread in
    compass.hitl.state_store. A human resumes via Command(resume={...}).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langgraph.types import interrupt

from compass.config import SCORE_THRESHOLD

if TYPE_CHECKING:
    from compass.pipeline.state import CompassState

logger = logging.getLogger(__name__)


async def hitl_node(state: "CompassState") -> dict:
    score = state.get("score_result")
    job = state.get("current_job")

    if score is None or score.score < SCORE_THRESHOLD:
        logger.info(
            "hitl: auto-reject %s (score=%s, threshold=%.2f)",
            job.url if job else "(unknown)",
            getattr(score, "score", None),
            SCORE_THRESHOLD,
        )
        return {"human_approved": False}

    payload = {
        "kind": "approval_request",
        "job_url": job.url if job else "",
        "company": job.company if job else "",
        "title": job.title if job else "",
        "score": score.score,
        "score_reasoning": score.reasoning,
        "matched_skills": list(score.matched_skills),
        "missing_skills": list(score.missing_skills),
    }
    logger.info("hitl: interrupting for approval — %s (score=%.2f)", payload["job_url"], score.score)
    decision = interrupt(payload)

    if not isinstance(decision, dict):
        logger.warning("hitl: malformed resume value %r — defaulting to reject", decision)
        return {"human_approved": False}
    return {
        "human_approved": bool(decision.get("approved", False)),
        "human_feedback": decision.get("feedback"),
    }
```

- [ ] **Step 4: Add `thread_id` to `CompassState`**

Edit `compass/pipeline/state.py`. Add inside the `CompassState` TypedDict, after `errors: list[str]`:

```python
    thread_id: str | None
```

- [ ] **Step 5: Update the three state-dict literals to include `thread_id`**

Three places: `compass/pipeline/graph.py:~120` (`_initial_state`), `compass/pipeline/graph.py:~190` (aggregate), `compass/mcp_server/server.py:~82` (the `score_jd` ad-hoc state). Confirm with `grep -n '"raw_jobs"' compass/` — there should be exactly three module-level matches.

For each: add `"thread_id": None,` to the literal. (We'll set a real value in Task 3.)

- [ ] **Step 6: Run the new hitl tests**

```bash
uv run pytest tests/pipeline/test_hitl_node_interrupt.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Add the `auto_approve_hitl` fixture for existing integration tests**

`tests/pipeline/test_graph_integration.py` has three tests that stub `score=4.2` (above threshold) and expect the pipeline to run to completion: `test_run_pipeline_end_to_end`, `test_run_pipeline_regenerates_gap_plan`, `test_run_pipeline_appends_to_run_log`. With real `interrupt()` they will now pause and the assertions on `jobs_written`, `tailored_paragraph`, etc. will fail.

Add this fixture at the top of `tests/pipeline/test_graph_integration.py` (next to `mocked_llms`):

```python
@pytest.fixture
def auto_approve_hitl(monkeypatch):
    """Stub the `interrupt()` call in hitl_node so the integration tests can
    exercise the full extract -> score -> hitl -> tailor -> vault_write path
    without needing a real human resume."""
    def fake_interrupt(_payload):
        return {"approved": True, "feedback": None}
    monkeypatch.setattr("compass.pipeline.nodes.hitl.interrupt", fake_interrupt)
```

Then add `auto_approve_hitl` to the parameter list of each above-threshold test:

```python
async def test_run_pipeline_end_to_end(temp_vault, mocked_llms, auto_approve_hitl):
async def test_run_pipeline_regenerates_gap_plan(temp_vault, mocked_llms, auto_approve_hitl):
async def test_run_pipeline_appends_to_run_log(temp_vault, mocked_llms, auto_approve_hitl):
```

Leave `test_run_pipeline_skips_tailor_when_below_threshold_but_still_writes` alone — it uses `score=2.0`, never reaches `interrupt()`.

Leave `test_run_pipeline_skips_dedup_urls` alone — it dedup-drops the job before the graph runs.

- [ ] **Step 8: Run the full suite — Phase 1.A tests must still pass**

```bash
uv run pytest -q
```

Expected: 204 (pre-existing) − 3 (deleted auto-approve tests in `test_routing.py`) + 5 (new `test_hitl_node_interrupt.py`) = **206 passed**.

If anything else fails: a state-literal somewhere is missing `thread_id` — find it and add `"thread_id": None,`. Or an above-threshold integration test was missed in Step 7 — opt it into `auto_approve_hitl`.

- [ ] **Step 9: Commit**

```bash
git add compass/pipeline/nodes/hitl.py compass/pipeline/state.py \
        compass/pipeline/graph.py compass/mcp_server/server.py \
        tests/pipeline/test_hitl_node_interrupt.py \
        tests/pipeline/test_routing.py \
        tests/pipeline/test_graph_integration.py
git commit -m "feat(hitl): replace auto-approve with LangGraph interrupt()"
```

---

## Task 2.5: Populate `hitl_decision` + `hitl_at` on the JobNote (audit trail)

**Why:** `JobNote` has `hitl_decision: str | None` and `hitl_at: datetime | None` fields ([compass/vault/schemas.py:62-63](compass/vault/schemas.py:62)) that have been unpopulated since Phase 0. The whole point of HiTL is that the vault becomes the audit trail for human decisions — without these fields populated, an Obsidian reader can't tell whether a JobNote was approved, rejected, or auto-rejected for low score.

**Mapping:**
- `state["human_approved"] is True` → `hitl_decision = "approved"`
- `state["human_approved"] is False` and score < threshold → `hitl_decision = "auto_rejected"`
- `state["human_approved"] is False` and score ≥ threshold → `hitl_decision = "rejected"` (human said no on resume)
- `state["human_approved"] is False` and feedback startswith `"auto-cancelled after"` → `hitl_decision = "timed_out"` (timeout_checker path)
- `hitl_at = datetime.now()` whenever any decision was made (i.e. always, except the never-reached-hitl branch which doesn't go through vault_write anyway)

**Files:**
- Modify: `compass/pipeline/nodes/vault_write.py`
- Modify: `tests/pipeline/test_vault_write.py`

- [ ] **Step 1: Tighten the `JobNote.hitl_decision` type**

In `compass/vault/schemas.py`, change:

```python
hitl_decision: str | None = None
```

to:

```python
HitlDecision = Literal["approved", "rejected", "auto_rejected", "timed_out"]
# ... and on JobNote:
hitl_decision: HitlDecision | None = None
```

`Literal` is already imported. All existing vault JobNotes have `hitl_decision: null` (never populated since Phase 0), so the tightening doesn't break round-tripping existing notes.

- [ ] **Step 2: Rename the test helper if it exists; otherwise create it**

`tests/pipeline/test_vault_write.py` currently has a `_state(skills_required, skills_matched, score=4.2)` helper at the top of the file used by multiple tests. **Rename it to `_build_state_for_score`** and extend the signature:

```python
def _build_state_for_score(
    *,
    score: float = 4.2,
    skills_required: list[str] | None = None,
    skills_matched: list[str] | None = None,
    skills_missing: list[str] | None = None,
    human_approved: bool = True,
    human_feedback: str | None = None,
) -> "CompassState":
    ...
```

Update the existing test call sites in the file to use the new name + kwargs (mechanical find/replace; tests that called `_state(4.2, [...], [...])` become `_build_state_for_score(score=4.2, skills_required=[...], skills_matched=[...])`).

- [ ] **Step 3: Write the failing tests**

Append to `tests/pipeline/test_vault_write.py`:

```python
async def test_vault_write_records_approved_decision(temp_vault):
    """state['human_approved'] = True -> hitl_decision='approved', hitl_at set."""
    import datetime as _dt
    import frontmatter
    from compass.pipeline.nodes.vault_write import vault_write_node
    from compass.pipeline.state import JobScore, JobRequirements, RawJob

    state = _build_state_for_score(  # existing helper in this file
        score=4.5,
        human_approved=True,
        human_feedback="LGTM",
    )
    await vault_write_node(state)
    job_file = next((temp_vault / "jobs").glob("*.md"))
    md = frontmatter.load(job_file).metadata
    assert md["hitl_decision"] == "approved"
    assert "hitl_at" in md and md["hitl_at"] is not None


async def test_vault_write_records_auto_rejected_for_low_score(temp_vault):
    """Below-threshold path: hitl never interrupts; decision is 'auto_rejected'."""
    import frontmatter
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _build_state_for_score(score=2.0, human_approved=False, human_feedback=None)
    await vault_write_node(state)
    job_file = next((temp_vault / "jobs").glob("*.md"))
    md = frontmatter.load(job_file).metadata
    assert md["hitl_decision"] == "auto_rejected"


async def test_vault_write_records_rejected_when_human_said_no(temp_vault):
    """Above-threshold path with human_approved=False = explicit reject."""
    import frontmatter
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _build_state_for_score(score=4.2, human_approved=False, human_feedback="not a fit")
    await vault_write_node(state)
    job_file = next((temp_vault / "jobs").glob("*.md"))
    md = frontmatter.load(job_file).metadata
    assert md["hitl_decision"] == "rejected"


async def test_vault_write_records_timed_out(temp_vault):
    """Timeout-checker resume sets feedback='auto-cancelled after Xh timeout'."""
    import frontmatter
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _build_state_for_score(
        score=4.2,
        human_approved=False,
        human_feedback="auto-cancelled after 4h timeout",
    )
    await vault_write_node(state)
    job_file = next((temp_vault / "jobs").glob("*.md"))
    md = frontmatter.load(job_file).metadata
    assert md["hitl_decision"] == "timed_out"
```

Run:

```bash
uv run pytest tests/pipeline/test_vault_write.py -v -k "hitl_decision or auto_rejected or rejected_when_human or timed_out"
```

Expected: 4 failures (the fields aren't populated yet).

- [ ] **Step 4: Implement the mapping in `vault_write_node`**

In `compass/pipeline/nodes/vault_write.py`, before building the `JobNote(...)` kwargs, add:

```python
def _derive_hitl_decision(state: "CompassState") -> tuple[str | None, "datetime | None"]:
    """Map state -> (hitl_decision, hitl_at). Returns (None, None) if hitl never ran."""
    from datetime import datetime as _dt

    from compass.config import SCORE_THRESHOLD

    approved = state.get("human_approved")
    if approved is None:
        # hitl never reached (e.g. extract/score errored). Leave fields null.
        return (None, None)

    feedback = (state.get("human_feedback") or "").lower()
    score = state.get("score_result")
    score_value = score.score if score is not None else 0.0

    if approved is True:
        decision = "approved"
    elif feedback.startswith("auto-cancelled after"):
        decision = "timed_out"
    elif score_value < SCORE_THRESHOLD:
        decision = "auto_rejected"
    else:
        decision = "rejected"
    return (decision, _dt.now())
```

Wire it into the JobNote construction (replace the existing `JobNote(...)` call's tailored_paragraph line region):

```python
    hitl_decision, hitl_at = _derive_hitl_decision(state)
    note = JobNote(
        # … all existing fields …
        tailored_paragraph=state.get("tailored_paragraph"),
        hitl_decision=hitl_decision,
        hitl_at=hitl_at,
    )
```

- [ ] **Step 5: Run the new tests**

```bash
uv run pytest tests/pipeline/test_vault_write.py -v
```

Expected: all previous + 4 new pass.

- [ ] **Step 6: Full suite**

```bash
uv run pytest -q
```

Expected: 210 passed (206 from Task 2 + 4 new).

- [ ] **Step 7: Commit**

```bash
git add compass/pipeline/nodes/vault_write.py tests/pipeline/test_vault_write.py \
        compass/vault/schemas.py
git commit -m "feat(hitl): record hitl_decision + hitl_at on JobNote"
```

---

## Task 3: Wire `AsyncSqliteSaver` + register paused threads in `run_pipeline`

**The risky one.** This is where the new graph topology meets the new state store. Key invariants we must preserve:

1. **The checkpointer is opened ONCE per `run_pipeline` invocation**, inside an `async with` block. Reusing a closed checkpointer across batches is a known LangGraph foot-gun.
2. **`build_graph()` is called inside the `async with`** so the compiled graph holds the open checkpointer. Compiling at module level (or before the `async with`) silently breaks `interrupt()`. Do not refactor this for "neatness" later — the Phase 1.A handoff calls this out by name.
3. **The `thread_id` is deterministic from `(job.url, scrape_timestamp)`** so a rerun of the same batch reuses the same paused checkpoint. We hash `f"{job.url}|{start_wall.isoformat()}"` with SHA-1 truncated to 16 chars.
4. **After `graph.ainvoke(...)` returns**, inspect the result for `__interrupt__` markers. If present, the job is paused — call `state_store.add_pending(...)` and treat it as "not written, not errored, pending". Otherwise the job ran to completion as before.

**Files:**
- Modify: `compass/pipeline/graph.py`
- Modify: `compass/config.py` (add `HITL_CHECKPOINT_DB`)
- Modify: `.env.example`
- Create: `tests/pipeline/test_graph_checkpointing.py`

- [ ] **Step 1: Add `HITL_CHECKPOINT_DB` to config**

Edit `compass/config.py`, in the `── HiTL ──` section:

```python
HITL_STATE_DB: Path = Path(os.getenv("HITL_STATE_DB", "~/.compass/hitl.db")).expanduser()
HITL_CHECKPOINT_DB: Path = Path(
    os.getenv("HITL_CHECKPOINT_DB", "~/.compass/checkpoints.db")
).expanduser()
HITL_TIMEOUT_HOURS: int = int(os.getenv("HITL_TIMEOUT_HOURS", "4"))
```

Edit `.env.example`, in the `── HiTL ──` section:

```
HITL_STATE_DB=~/.compass/hitl.db
HITL_CHECKPOINT_DB=~/.compass/checkpoints.db
HITL_TIMEOUT_HOURS=4
```

- [ ] **Step 2: Write the integration test for graph checkpointing**

Create `tests/pipeline/test_graph_checkpointing.py`:

```python
"""End-to-end: graph pauses at hitl, state_store gets the row,
   resume_pending finishes the run.

   These tests STUB the LLM-touching nodes (extract, score, tailor) — we only
   exercise the graph machinery + interrupt + checkpointer + state_store
   interaction. Real LLM calls live in the live-smoke check in Task 7."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from compass.hitl import state_store
from compass.pipeline.state import CompassState, JobRequirements, JobScore, RawJob


@pytest.fixture
def stub_llm_nodes(monkeypatch):
    """Replace extract / score / tailor / vault_write with deterministic stubs."""
    async def fake_extract(state: CompassState) -> dict:
        return {
            "extracted_requirements": JobRequirements(
                required_skills=["MCP", "Python"],
                nice_to_have_skills=["LangGraph"],
                seniority="mid",
                remote_policy="remote",
                summary="An agent role.",
            )
        }

    async def fake_score(state: CompassState) -> dict:
        return {
            "score_result": JobScore(
                score=4.2,
                reasoning="Strong match.",
                matched_skills=["MCP"],
                missing_skills=["LangGraph"],
                tailoring_notes="Lead with MCP.",
            )
        }

    async def fake_tailor(state: CompassState) -> dict:
        return {"tailored_paragraph": "Tailored: lead with MCP work."}

    async def fake_vault_write(state: CompassState) -> dict:
        return {"vault_written": True, "jobs_written": 1}

    async def fake_intake_filter(state: CompassState) -> dict:
        return {"in_scope": True, "role_family": "agent-engineer"}

    monkeypatch.setattr("compass.pipeline.graph.extract_node", fake_extract)
    monkeypatch.setattr("compass.pipeline.graph.score_node", fake_score)
    monkeypatch.setattr("compass.pipeline.graph.tailor_node", fake_tailor)
    monkeypatch.setattr("compass.pipeline.graph.vault_write_node", fake_vault_write)
    monkeypatch.setattr("compass.pipeline.graph.intake_filter_node", fake_intake_filter)


@pytest.fixture
def checkpoint_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "checkpoints.db"
    import compass.config as cfg
    monkeypatch.setattr(cfg, "HITL_CHECKPOINT_DB", db)
    return db


def _job(url: str = "https://jobs.example.com/sierra-1") -> RawJob:
    return RawJob(
        company="Sierra",
        title="SWE, Agent",
        url=url,
        source="ashby",
        description="An agent engineering role at Sierra.",
        date_posted=_dt.date(2026, 5, 18),
    )


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "stub_llm_nodes")
async def test_above_threshold_job_pauses_and_registers_in_state_store(monkeypatch):
    """run_pipeline with a single above-threshold job: paused=1, written=0,
       state_store has a row."""
    from compass.pipeline.graph import run_pipeline

    # No real scraping — pass the job in directly.
    result = await run_pipeline(raw_jobs=[_job()])

    assert result["jobs_processed"] == 1
    assert result["jobs_written"] == 0  # paused before vault_write
    assert result["jobs_paused"] == 1
    rows = await state_store.list_pending()
    assert len(rows) == 1
    assert rows[0]["company"] == "Sierra"
    assert rows[0]["score"] == pytest.approx(4.2)
    assert rows[0]["job_url"] == "https://jobs.example.com/sierra-1"


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "stub_llm_nodes")
async def test_below_threshold_job_runs_to_completion_no_state_store_row(monkeypatch):
    """Below-threshold path is unchanged from 1.A — no interrupt, vault_write fires."""
    async def low_score(state: CompassState) -> dict:
        return {
            "score_result": JobScore(
                score=2.0,
                reasoning="Mismatched.",
                matched_skills=[],
                missing_skills=["A", "B"],
                tailoring_notes="",
            )
        }
    monkeypatch.setattr("compass.pipeline.graph.score_node", low_score)
    from compass.pipeline.graph import run_pipeline

    result = await run_pipeline(raw_jobs=[_job()])
    assert result["jobs_written"] == 1
    assert result["jobs_paused"] == 0
    assert await state_store.list_pending() == []


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "stub_llm_nodes")
async def test_thread_id_is_deterministic_for_same_url_and_batch():
    """Re-running the SAME batch (same start_wall) reuses the same thread_id —
       second run hits the idempotent INSERT OR IGNORE path."""
    from compass.pipeline.graph import _thread_id_for
    tid_a = _thread_id_for("https://jobs.example.com/x", _dt.datetime(2026, 5, 19, 9, 0, 0))
    tid_b = _thread_id_for("https://jobs.example.com/x", _dt.datetime(2026, 5, 19, 9, 0, 0))
    tid_c = _thread_id_for("https://jobs.example.com/y", _dt.datetime(2026, 5, 19, 9, 0, 0))
    assert tid_a == tid_b
    assert tid_a != tid_c
    assert len(tid_a) == 16
```

Run:

```bash
uv run pytest tests/pipeline/test_graph_checkpointing.py -v
```

Expected: all three fail (run_pipeline doesn't take `raw_jobs` paths through this flow yet, `_thread_id_for` doesn't exist, `jobs_paused` not in aggregate).

- [ ] **Step 3: Rewrite the relevant chunks of `graph.py`**

Apply the following surgical edits to `compass/pipeline/graph.py`:

**3a. Add new imports near the top:**

```python
import hashlib

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from compass.hitl import state_store
```

**3b. Add `_thread_id_for` as a module-level helper, just above `_initial_state`:**

```python
def _thread_id_for(job_url: str, batch_started_at: datetime) -> str:
    """Deterministic 16-char SHA-1 of (url, batch start) — same batch + same job = same thread."""
    raw = f"{job_url}|{batch_started_at.isoformat()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
```

**3c. Extend `_initial_state` to accept and store `thread_id`:**

```python
def _initial_state(job: RawJob, thread_id: str | None = None) -> CompassState:
    return {
        "raw_jobs": [],
        "current_job": job,
        "extracted_requirements": None,
        "score_result": None,
        "in_scope": None,
        "role_family": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
        "thread_id": thread_id,
    }
```

**3d. Replace `_process_one` with a checkpointer-aware version that detects paused state:**

```python
async def _process_one(
    graph,
    job: RawJob,
    sem: asyncio.Semaphore,
    thread_id: str,
) -> tuple[CompassState, bool]:
    """Invoke the graph for one job. Returns (final_state, was_paused)."""
    config = {
        "configurable": {"thread_id": thread_id},
        **_langfuse_config(),
    }
    async with sem:
        try:
            result = await graph.ainvoke(_initial_state(job, thread_id=thread_id), config=config)
        except Exception as e:
            logger.exception("pipeline: graph crashed on %s", job.url)
            return (
                {**_initial_state(job, thread_id=thread_id), "errors": [f"graph: {type(e).__name__}: {e}"]},
                False,
            )

    # When interrupt() fires, ainvoke returns with state containing the
    # __interrupt__ marker AND without progressing past the hitl node.
    # vault_written stays False, jobs_written stays 0 — that's our signal.
    if "__interrupt__" in result and result["__interrupt__"]:
        interrupts = result["__interrupt__"]
        payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
        if isinstance(payload, dict) and payload.get("kind") == "approval_request":
            await state_store.add_pending(
                thread_id=thread_id,
                job_url=payload["job_url"],
                company=payload["company"],
                title=payload["title"],
                score=float(payload["score"]),
                score_reasoning=payload["score_reasoning"],
                matched_skills=list(payload["matched_skills"]),
                missing_skills=list(payload["missing_skills"]),
            )
            logger.info(
                "pipeline: paused %s for approval (thread_id=%s, score=%.2f)",
                job.url, thread_id, payload["score"],
            )
            return (result, True)
        # Unknown interrupt shape — DO NOT silently swallow. Phase 0 bug pattern:
        # a future interrupt() added elsewhere in the graph would otherwise
        # disappear into a "succeeded with jobs_paused=0" black hole. Log loudly
        # and still count as paused so the caller's bookkeeping reflects reality.
        logger.error(
            "pipeline: graph paused at UNKNOWN interrupt kind for %s — payload=%r",
            job.url, payload,
        )
        return (result, True)
    return (result, False)
```

**3e. Restructure `run_pipeline` to mount the checkpointer:**

```python
async def run_pipeline(raw_jobs: list[RawJob] | None = None) -> CompassState:
    """Scrape (or accept) jobs, dedup, run per-job graph under a single
    AsyncSqliteSaver, regenerate gap plan."""
    from compass.config import HITL_CHECKPOINT_DB

    start_monotonic = time.monotonic()
    start_wall = datetime.now()
    if raw_jobs is None:
        raw_jobs = await _scrape_all()

    seen_urls = _vault_url_set()
    fresh = [j for j in raw_jobs if j.url not in seen_urls]
    dropped = len(raw_jobs) - len(fresh)
    if dropped:
        logger.info("pipeline: dropping %d/%d jobs already in vault", dropped, len(raw_jobs))

    HITL_CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(HITL_CHECKPOINT_DB)) as checkpointer:
        # Enable WAL on the checkpoint DB once per process. Cheap if already set.
        # See state_store._connect for the rationale.
        try:
            await checkpointer.conn.execute("PRAGMA journal_mode=WAL")
            await checkpointer.conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            logger.debug("checkpoint: WAL pragma set already or unsupported; continuing")
        graph = build_graph(checkpointer=checkpointer)
        sem = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
        coros = [
            _process_one(graph, j, sem, thread_id=_thread_id_for(j.url, start_wall))
            for j in fresh
        ]
        results = await asyncio.gather(*coros)

    pairs = results  # list of (state, was_paused)
    paused_count = sum(int(p) for _, p in pairs)
    final_states = [s for s, _ in pairs]

    aggregate: CompassState = {
        "raw_jobs": raw_jobs,
        "current_job": None,
        "extracted_requirements": None,
        "score_result": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": any(r.get("vault_written") for r in final_states),
        "jobs_processed": len(fresh),
        "jobs_written": sum(int(bool(r.get("vault_written"))) for r in final_states),
        "errors": [e for r in final_states for e in r.get("errors", [])],
        "in_scope": None,
        "role_family": None,
        "thread_id": None,
    }
    # `jobs_paused` is informational only — not in CompassState TypedDict.
    # Returned via the aggregate dict; orchestrators (CLI, MCP) read it.
    aggregate["jobs_paused"] = paused_count  # type: ignore[typeddict-unknown-key]

    if aggregate["jobs_written"] > 0:
        gap_aggregator.regenerate(write=True)

    duration_s = time.monotonic() - start_monotonic
    _append_run_log(aggregate, duration_s)
    unknown_count = _count_unknown_skills_seen_this_run(start_wall)
    logger.info(
        "pipeline: processed=%d written=%d paused=%d errors=%d unknown_skills_seen=%d duration=%.1fs",
        aggregate["jobs_processed"], aggregate["jobs_written"], paused_count,
        len(aggregate["errors"]), unknown_count, duration_s,
    )
    return aggregate
```

**3f. Make `build_graph` accept a checkpointer:**

```python
def build_graph(checkpointer=None):
    builder = StateGraph(CompassState)
    # ... unchanged node + edge wiring ...
    return builder.compile(checkpointer=checkpointer)
```

**3g. Update `_append_run_log` to record the paused column:**

```python
def _append_run_log(state: CompassState, duration_s: float) -> None:
    log_path = VAULT_PATH / "_meta" / "pipeline-runs.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.write_text(
            "# Pipeline Run Log\n\n"
            "| Timestamp | Processed | Written | Paused | Errors | Duration |\n"
            "|---|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    ts = datetime.now().isoformat(timespec="seconds")
    paused = state.get("jobs_paused", 0)  # type: ignore[typeddict-item]
    row = (
        f"| {ts} | {state['jobs_processed']} | {state['jobs_written']} | "
        f"{paused} | {len(state['errors'])} | {duration_s:.1f}s |\n"
    )
    with log_path.open("a", encoding="utf-8") as f:
        f.write(row)
```

**3h. Update the `__main__` print:**

```python
if __name__ == "__main__":
    result = asyncio.run(run_pipeline())
    print(
        f"Processed: {result['jobs_processed']} | "
        f"Written: {result['jobs_written']} | "
        f"Paused: {result.get('jobs_paused', 0)} | "
        f"Errors: {len(result['errors'])}"
    )
```

- [ ] **Step 4: Run the new checkpointing tests**

```bash
uv run pytest tests/pipeline/test_graph_checkpointing.py -v
```

Expected: 3 passed. If a test fails because `__interrupt__` isn't in the returned state, drop a `print(result)` after the ainvoke to inspect the exact shape — LangGraph 1.x has been seen to also expose interrupts via `graph.get_state(config).next` instead. If so, switch the detection to `state = await graph.aget_state(config); was_paused = bool(state.next)`.

- [ ] **Step 5: Run the full suite — Phase 1.A tests must still pass**

```bash
uv run pytest -q
```

Expected: 213 passed (210 from Task 2.5 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add compass/pipeline/graph.py compass/config.py .env.example \
        tests/pipeline/test_graph_checkpointing.py
git commit -m "feat(hitl): mount AsyncSqliteSaver in run_pipeline; register paused threads"
```

---

## Task 4: Resume entrypoint (`compass/hitl/resume.py`)

**Files:**
- Create: `compass/hitl/resume.py`
- Create: `tests/hitl/test_resume.py`

- [ ] **Step 1: Write failing tests**

Create `tests/hitl/test_resume.py`:

```python
"""resume_pending re-opens the checkpointer, recompiles the graph, and drives
   the resume via Command(resume=...). Verifies vault_write fires on approve
   and tailor is skipped on reject."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from compass.hitl import state_store
from compass.pipeline.state import CompassState, JobRequirements, JobScore, RawJob


@pytest.fixture
def checkpoint_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "checkpoints.db"
    import compass.config as cfg
    monkeypatch.setattr(cfg, "HITL_CHECKPOINT_DB", db)
    return db


@pytest.fixture
def stub_llm_nodes(monkeypatch):
    async def fake_extract(_): return {"extracted_requirements": JobRequirements(
        required_skills=["MCP"], nice_to_have_skills=[], seniority="mid",
        remote_policy="remote", summary="agent role")}

    async def fake_score(_): return {"score_result": JobScore(
        score=4.5, reasoning="ok", matched_skills=["MCP"], missing_skills=[],
        tailoring_notes="")}

    async def fake_tailor(_): return {"tailored_paragraph": "lead with MCP."}

    written = {"calls": 0, "with_tailor": 0}
    async def fake_vault_write(state):
        written["calls"] += 1
        if state.get("tailored_paragraph"):
            written["with_tailor"] += 1
        return {"vault_written": True, "jobs_written": 1}

    async def fake_intake_filter(_): return {"in_scope": True, "role_family": "agent-engineer"}

    monkeypatch.setattr("compass.pipeline.graph.extract_node", fake_extract)
    monkeypatch.setattr("compass.pipeline.graph.score_node", fake_score)
    monkeypatch.setattr("compass.pipeline.graph.tailor_node", fake_tailor)
    monkeypatch.setattr("compass.pipeline.graph.vault_write_node", fake_vault_write)
    monkeypatch.setattr("compass.pipeline.graph.intake_filter_node", fake_intake_filter)
    return written


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db")
async def test_resume_approve_runs_tailor_then_vault_write(stub_llm_nodes):
    from compass.hitl.resume import resume_pending
    from compass.pipeline.graph import run_pipeline

    job = RawJob(company="Sierra", title="SWE", url="https://x/1", source="ashby",
                 description="...", date_posted=_dt.date(2026, 5, 18))
    pre = await run_pipeline(raw_jobs=[job])
    assert pre["jobs_paused"] == 1

    pending = await state_store.list_pending()
    tid = pending[0]["thread_id"]

    final = await resume_pending(tid, decision={"approved": True, "feedback": "LGTM"})
    assert final["vault_written"] is True
    assert final["human_approved"] is True
    assert stub_llm_nodes["with_tailor"] == 1
    row = await state_store.get_pending(tid)
    assert row["status"] == "approved"
    assert row["feedback"] == "LGTM"


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db")
async def test_resume_reject_skips_tailor_writes_to_vault(stub_llm_nodes):
    from compass.hitl.resume import resume_pending
    from compass.pipeline.graph import run_pipeline

    job = RawJob(company="Sierra", title="SWE", url="https://x/2", source="ashby",
                 description="...", date_posted=_dt.date(2026, 5, 18))
    await run_pipeline(raw_jobs=[job])
    tid = (await state_store.list_pending())[0]["thread_id"]

    final = await resume_pending(tid, decision={"approved": False})
    assert final["human_approved"] is False
    assert stub_llm_nodes["with_tailor"] == 0
    assert stub_llm_nodes["calls"] == 1  # vault_write still fired (rejected branch)
    row = await state_store.get_pending(tid)
    assert row["status"] == "rejected"


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db")
async def test_resume_unknown_thread_raises():
    from compass.hitl.resume import resume_pending
    with pytest.raises(LookupError, match="thread"):
        await resume_pending("nope-1234", decision={"approved": True})


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db")
async def test_resume_already_resolved_is_noop(stub_llm_nodes):
    from compass.hitl.resume import resume_pending
    from compass.pipeline.graph import run_pipeline

    job = RawJob(company="Sierra", title="SWE", url="https://x/3", source="ashby",
                 description="...", date_posted=_dt.date(2026, 5, 18))
    await run_pipeline(raw_jobs=[job])
    tid = (await state_store.list_pending())[0]["thread_id"]
    await resume_pending(tid, decision={"approved": True})

    # Second resume call should not crash and should not re-fire vault_write
    before = stub_llm_nodes["calls"]
    with pytest.raises(ValueError, match="already resolved"):
        await resume_pending(tid, decision={"approved": True})
    assert stub_llm_nodes["calls"] == before
```

Run — expect all 4 failing with `ModuleNotFoundError`.

- [ ] **Step 2: Implement `resume.py`**

Create `compass/hitl/resume.py`:

```python
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
        raise ValueError(f"thread {thread_id!r} already resolved ({row['status']})")

    # Late import to avoid circular: graph.py imports state_store
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
```

- [ ] **Step 3: Run resume tests**

```bash
uv run pytest tests/hitl/test_resume.py -v
```

Expected: 4 passed.

- [ ] **Step 4: Full suite**

```bash
uv run pytest -q
```

Expected: 217 passed (213 + 4).

- [ ] **Step 5: Commit**

```bash
git add compass/hitl/resume.py tests/hitl/test_resume.py
git commit -m "feat(hitl): resume_pending entrypoint via Command(resume=...)"
```

---

## Task 5: Timeout checker

**Files:**
- Create: `compass/hitl/timeout_checker.py`
- Create: `tests/hitl/test_timeout_checker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/hitl/test_timeout_checker.py`:

```python
"""timeout_checker resumes pending rows older than HITL_TIMEOUT_HOURS with
   {"approved": False}, marks them as 'timed_out' in the state store, and
   leaves young pending rows untouched."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from compass.hitl import state_store
from compass.pipeline.state import JobRequirements, JobScore, RawJob


@pytest.fixture
def checkpoint_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "checkpoints.db"
    import compass.config as cfg
    monkeypatch.setattr(cfg, "HITL_CHECKPOINT_DB", db)
    return db


@pytest.fixture
def stub_llm_nodes(monkeypatch):
    async def fake_extract(_): return {"extracted_requirements": JobRequirements(
        required_skills=["MCP"], nice_to_have_skills=[], seniority="mid",
        remote_policy="remote", summary="x")}
    async def fake_score(_): return {"score_result": JobScore(
        score=4.5, reasoning="ok", matched_skills=["MCP"], missing_skills=[],
        tailoring_notes="")}
    async def fake_vault_write(_): return {"vault_written": True, "jobs_written": 1}
    async def fake_intake_filter(_): return {"in_scope": True, "role_family": "agent-engineer"}
    async def fake_tailor(_): return {"tailored_paragraph": "..."}
    monkeypatch.setattr("compass.pipeline.graph.extract_node", fake_extract)
    monkeypatch.setattr("compass.pipeline.graph.score_node", fake_score)
    monkeypatch.setattr("compass.pipeline.graph.tailor_node", fake_tailor)
    monkeypatch.setattr("compass.pipeline.graph.vault_write_node", fake_vault_write)
    monkeypatch.setattr("compass.pipeline.graph.intake_filter_node", fake_intake_filter)


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "stub_llm_nodes")
async def test_timeout_checker_resumes_old_pending_as_rejected(monkeypatch):
    from compass.hitl import timeout_checker
    from compass.pipeline.graph import run_pipeline

    job = RawJob(company="Sierra", title="SWE", url="https://x/1", source="ashby",
                 description="...", date_posted=_dt.date(2026, 5, 18))
    await run_pipeline(raw_jobs=[job])
    tid = (await state_store.list_pending())[0]["thread_id"]

    # Force the row's created_at to look 5h old
    import aiosqlite
    from compass.config import HITL_STATE_DB
    five_h_ago = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=5)).isoformat()
    async with aiosqlite.connect(HITL_STATE_DB) as conn:
        await conn.execute(
            "UPDATE pending_approvals SET created_at = ? WHERE thread_id = ?",
            (five_h_ago, tid),
        )
        await conn.commit()

    n = await timeout_checker.check_and_resume_timeouts(timeout_hours=4)
    assert n == 1
    row = await state_store.get_pending(tid)
    assert row["status"] == "timed_out"
    # Spec DoD line 230 — timeout must be logged to _meta/agent-log.md
    from compass.config import AGENT_LOG_PATH
    log_text = AGENT_LOG_PATH.read_text(encoding="utf-8")
    assert "hitl-timeout" in log_text
    assert tid in log_text


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "stub_llm_nodes")
async def test_timeout_checker_leaves_young_pending_alone():
    from compass.hitl import timeout_checker
    from compass.pipeline.graph import run_pipeline

    job = RawJob(company="Sierra", title="SWE", url="https://x/2", source="ashby",
                 description="...", date_posted=_dt.date(2026, 5, 18))
    await run_pipeline(raw_jobs=[job])
    n = await timeout_checker.check_and_resume_timeouts(timeout_hours=4)
    assert n == 0
    rows = await state_store.list_pending()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"


@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "stub_llm_nodes")
async def test_timeout_checker_continues_after_one_resume_failure(monkeypatch):
    """A single broken thread (e.g. checkpoint corrupted) must not block the
       rest of the queue from timing out."""
    from compass.hitl import timeout_checker

    # Two rows, both stale
    await state_store.add_pending(
        thread_id="tid-broken", job_url="x://1", company="C", title="T",
        score=4.0, score_reasoning="r", matched_skills=[], missing_skills=[],
    )
    await state_store.add_pending(
        thread_id="tid-ok", job_url="x://2", company="C", title="T",
        score=4.0, score_reasoning="r", matched_skills=[], missing_skills=[],
    )
    # Backdate both
    import aiosqlite
    from compass.config import HITL_STATE_DB
    five_h_ago = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=5)).isoformat()
    async with aiosqlite.connect(HITL_STATE_DB) as conn:
        await conn.execute("UPDATE pending_approvals SET created_at = ?", (five_h_ago,))
        await conn.commit()

    # Make resume_pending raise for tid-broken
    async def flaky(thread_id, **kw):
        if thread_id == "tid-broken":
            raise RuntimeError("checkpoint missing")
        from compass.hitl.state_store import mark_resolved
        await mark_resolved(thread_id, status="timed_out")
    monkeypatch.setattr("compass.hitl.timeout_checker.resume_pending", flaky)

    n = await timeout_checker.check_and_resume_timeouts(timeout_hours=4)
    assert n == 1  # one succeeded, one failed
    row_broken = await state_store.get_pending("tid-broken")
    assert row_broken["status"] == "error"
```

- [ ] **Step 2: Implement `timeout_checker.py`**

Create `compass/hitl/timeout_checker.py`:

```python
"""Auto-cancel pending approvals older than HITL_TIMEOUT_HOURS.

Module entrypoint (CLI):  python -m compass.hitl.timeout_checker
Async API:                check_and_resume_timeouts(timeout_hours: int | None = None)

In Phase 1.B.1 this is human-run. In Phase 1.B.3 a Modal cron will import and
schedule it — see modal_app.py."""

from __future__ import annotations

import asyncio
import logging

from compass.hitl import state_store
from compass.hitl.resume import resume_pending

logger = logging.getLogger(__name__)


async def check_and_resume_timeouts(*, timeout_hours: int | None = None) -> int:
    """Resume every stale pending row with {"approved": False}. Returns the
       count successfully timed-out (i.e. exclude rows that errored)."""
    from compass.config import HITL_TIMEOUT_HOURS

    hrs = timeout_hours if timeout_hours is not None else HITL_TIMEOUT_HOURS
    stale = await state_store.list_timed_out(timeout_hours=hrs)
    if not stale:
        return 0

    logger.info("hitl: %d pending approval(s) past %dh timeout", len(stale), hrs)
    timed_out = 0
    for row in stale:
        tid = row["thread_id"]
        try:
            await resume_pending(
                tid,
                decision={"approved": False, "feedback": f"auto-cancelled after {hrs}h timeout"},
                status_override="timed_out",
            )
            # Spec § DoD line 230: HiTL timeout must log to _meta/agent-log.md
            _log_to_agent_log(
                f"hitl-timeout: auto-cancelled {tid} ({row['company']} / {row['title']}, "
                f"score={row['score']:.2f}) after {hrs}h"
            )
            timed_out += 1
        except Exception as e:
            logger.exception("hitl: timeout resume failed for %s — marking as error", tid)
            try:
                await state_store.mark_resolved(tid, status="error", feedback=f"resume error: {e}")
                _log_to_agent_log(f"hitl-timeout-error: {tid} resume failed: {e}")
            except Exception:
                logger.exception("hitl: also failed to mark %s as error", tid)
    return timed_out


def _log_to_agent_log(line: str) -> None:
    """Append a timestamped row to compass-vault/_meta/agent-log.md.

    Late-binds via compass.vault.writer.append_agent_log so the temp_vault
    fixture works in tests.
    """
    from compass.vault.writer import append_agent_log
    try:
        append_agent_log(line)
    except Exception:
        logger.exception("hitl: failed to write to agent-log.md")


if __name__ == "__main__":
    n = asyncio.run(check_and_resume_timeouts())
    print(f"Timed out: {n}")
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/hitl/test_timeout_checker.py -v
```

Expected: 3 passed.

- [ ] **Step 4: Full suite**

```bash
uv run pytest -q
```

Expected: 220 passed (217 + 3).

- [ ] **Step 5: Commit**

```bash
git add compass/hitl/timeout_checker.py tests/hitl/test_timeout_checker.py
git commit -m "feat(hitl): timeout_checker auto-cancels stale approvals"
```

---

## Task 6: MCP tools (`pending_approvals` + `approve`)

**Files:**
- Modify: `compass/mcp_server/server.py`
- Create: `tests/mcp_server/__init__.py` if missing
- Create: `tests/mcp_server/test_pending_approvals.py`

- [ ] **Step 1: Write failing tests**

Create `tests/mcp_server/test_pending_approvals.py`:

```python
"""MCP wrappers around state_store + resume_pending — JSON-serializable
   return shapes (no datetime objects, no Pydantic instances)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from compass.hitl import state_store


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
        thread_id="tid-1", job_url="https://x/1", company="Sierra",
        title="SWE Agent", score=4.2, score_reasoning="solid",
        matched_skills=["MCP"], missing_skills=["LangGraph"],
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
    assert result == {"vault_written": True, "human_approved": True}
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
```

- [ ] **Step 2: Add the MCP tools**

Append to `compass/mcp_server/server.py` (after the existing `tailor_resume` block):

```python
# ── HiTL approvals ───────────────────────────────────────────────────────────

from compass.hitl import state_store as _state_store
from compass.hitl.resume import resume_pending as _resume_pending


@mcp.tool()
async def pending_approvals() -> list[dict]:
    """List jobs paused at hitl awaiting human approval. Oldest first."""
    rows = await _state_store.list_pending()
    # rows are already plain dicts of JSON-safe primitives + list[str]
    return rows


@mcp.tool()
async def approve(thread_id: str, approved: bool, feedback: str | None = None) -> dict:
    """Resume a paused thread. approved=True runs tailor + vault_write;
       approved=False skips tailor and writes the rejected JobNote."""
    try:
        final = await _resume_pending(
            thread_id,
            decision={"approved": approved, "feedback": feedback},
        )
    except (LookupError, ValueError) as e:
        return {"error": str(e)}
    # Strip non-JSON-safe state from the return (current_job is a Pydantic model)
    return {
        "vault_written": bool(final.get("vault_written")),
        "human_approved": bool(final.get("human_approved")),
        "human_feedback": final.get("human_feedback"),
    }
```

Also update the module docstring's tool listing to include `pending_approvals()` and `approve(thread_id, approved, feedback)`.

- [ ] **Step 3: Run MCP tests**

```bash
mkdir -p tests/mcp_server && touch tests/mcp_server/__init__.py
uv run pytest tests/mcp_server/test_pending_approvals.py -v
```

Expected: 3 passed.

- [ ] **Step 4: Full suite**

```bash
uv run pytest -q
```

Expected: 223 passed (220 + 3).

- [ ] **Step 5: Lint**

```bash
uv run ruff check
uv run ruff format --check
```

Expected: clean. If `format --check` complains, run `uv run ruff format` and re-stage.

- [ ] **Step 6: Commit**

```bash
git add compass/mcp_server/server.py tests/mcp_server/__init__.py \
        tests/mcp_server/test_pending_approvals.py
git commit -m "feat(mcp): pending_approvals + approve tools"
```

---

## Task 7: Live smoke + checkpoint-survives-restart verification

> **PAUSE HERE before running this task.** Step 2 hits real OpenRouter + writes to the user's real vault + writes to `~/.compass/checkpoints.db`. Confirm with the user before running. This is the only LLM-touching step in the whole plan.

**Goal:** Prove the three things tests cannot prove:
1. A real graph invocation with a real LLM score actually pauses at hitl
2. The pause SURVIVES a Python process restart (closing + re-opening the AsyncSqliteSaver from a fresh process)
3. Resume via `approve()` MCP tool produces a real JobNote with a real tailored paragraph

**Files:** none

- [ ] **Step 1: Snapshot vault + DBs**

```bash
cp -r ~/Documents/compass-vault/jobs ~/Documents/compass-vault/jobs.preB1.bak 2>/dev/null || true
cp ~/.compass/hitl.db ~/.compass/hitl.db.preB1.bak 2>/dev/null || true
cp ~/.compass/checkpoints.db ~/.compass/checkpoints.db.preB1.bak 2>/dev/null || true
```

- [ ] **Step 2: Run pipeline against one apply-now board, expect paused jobs**

```bash
cd ~/Documents/compass
MAX_JOBS_PER_RUN=10 \
  GREENHOUSE_BOARDS= \
  LEVER_COMPANIES= \
  ASHBY_BOARDS=sierra \
  uv run python -m compass.pipeline.graph
```

Expected output:
```
Processed: N | Written: M | Paused: K | Errors: 0
```
where `K >= 1` (at least one above-threshold Sierra job should pause).

- [ ] **Step 3: Confirm pending row exists from a SEPARATE Python process**

This is the critical "checkpoint survives restart" check. Run a fresh process:

```bash
uv run python -c "
import asyncio
from compass.hitl import state_store
async def main():
    rows = await state_store.list_pending()
    print(f'Pending: {len(rows)}')
    for r in rows:
        print(f'  {r[\"thread_id\"]}  {r[\"company\"]} / {r[\"title\"]}  score={r[\"score\"]}')
asyncio.run(main())
"
```

Expected: at least one row printed with a real Sierra job.

- [ ] **Step 4: Resume one thread via the MCP path, confirm JobNote written**

Pick a `thread_id` from Step 3's output, then run (replace `<TID>`):

```bash
uv run python -c "
import asyncio
from compass.hitl.resume import resume_pending
async def main():
    final = await resume_pending('<TID>', decision={'approved': True, 'feedback': 'smoke test'})
    print('vault_written =', final.get('vault_written'))
    print('human_approved =', final.get('human_approved'))
asyncio.run(main())
"
```

Expected: `vault_written = True`, `human_approved = True`. Then verify the JobNote:

```bash
ls -ltr ~/Documents/compass-vault/jobs/ | tail -3
```

The most recent file should be the Sierra job. Open it and confirm:
- `tailored_paragraph:` is populated with real Sonnet output (not empty)
- `match_score:` is the same float seen in Step 3
- `hitl_decision: approved` in the frontmatter (NOT `human_approved` — that key lives in pipeline state, not the JobNote)
- `hitl_at:` is a recent ISO timestamp

- [ ] **Step 5: Run `timeout_checker` against an empty queue, confirm 0 timed out**

```bash
uv run python -m compass.hitl.timeout_checker
```

Expected: `Timed out: 0` (the one row we approved is no longer pending).

- [ ] **Step 6: Restore backups if anything went wrong; otherwise delete them**

```bash
# If anything looks wrong (no tailored paragraph, mis-sorted, etc.), restore:
#   rm -rf ~/Documents/compass-vault/jobs && mv ~/Documents/compass-vault/jobs.preB1.bak ~/Documents/compass-vault/jobs
#   mv ~/.compass/hitl.db.preB1.bak ~/.compass/hitl.db
#   mv ~/.compass/checkpoints.db.preB1.bak ~/.compass/checkpoints.db
# If everything looks good:
rm -rf ~/Documents/compass-vault/jobs.preB1.bak ~/.compass/hitl.db.preB1.bak ~/.compass/checkpoints.db.preB1.bak
```

- [ ] **Step 7: Tag the phase**

```bash
git tag phase-1b1-hitl
```

---

## Definition of Done

All of the following must hold before declaring Phase 1.B.1 complete:

**Code & tests**
- 223 tests passing (`uv run pytest -q`)
- Ruff clean (`uv run ruff check && uv run ruff format --check`)
- No module-level `from compass.config import HITL_*` — every reference is inside a function body
- `build_graph()` accepts an optional `checkpointer` parameter; called only from inside the `async with AsyncSqliteSaver(...)` block in `run_pipeline` AND from `resume_pending`

**Behaviour (verified empirically in Task 7)**
- A real above-threshold job pauses at `hitl`, registers in `~/.compass/hitl.db`, does NOT write a JobNote
- The pending row is visible from a fresh Python process (proves the checkpoint isn't process-local)
- `resume_pending(tid, decision={"approved": True})` writes a JobNote with a non-empty `tailored_paragraph` and `hitl_decision: approved`
- `resume_pending(tid, decision={"approved": False})` writes a JobNote with `hitl_decision: rejected` and no `tailored_paragraph`
- `timeout_checker.check_and_resume_timeouts()` resumes only rows older than `HITL_TIMEOUT_HOURS`, marks them `timed_out`, AND appends a row to `_meta/agent-log.md` (spec § DoD line 230)
- Below-threshold jobs are unchanged from Phase 1.A — no interrupt fires, no state-store row
- An unknown `interrupt()` payload (anything not `kind == "approval_request"`) is logged at ERROR and counted as `jobs_paused`, never silently dropped

**Docs**
- `.env.example` documents `HITL_CHECKPOINT_DB`
- This plan's "What's deferred" cross-references are accurate (RAG → 1.B.2, Modal cron → 1.B.3)
- Final commit message of Task 7: `git tag phase-1b1-hitl`

---

## What's deferred (and to which sub-phase)

| Concern | Severity | Phase | Why deferred |
|---|---|---|---|
| Chroma RAG for profile retrieval | Portfolio claim | **1.B.2** | Independent of HiTL; separate plan |
| Modal cron schedule (`@app.function(schedule=Cron(...))`) for `timeout_checker` + daily scrape + weekly assessor | Required for "no babysitting" | **1.B.3** | This phase ships the callable; 1.B.3 wires the schedule |
| Modal Secrets for `OPENROUTER_API_KEY`, `LANGFUSE_*` | Cloud deploy | **1.B.3** | Same — couples with cron deploy |
| Langfuse callback API mismatch (`host=` kwarg) | Observability | **1.B.3** | Bug #23 from Phase 0; dedicated 1.B.3 work |
| URL dedup for `intake_filter`-rejected JDs | Cost + log growth | **1.B.3** | Natural fit with caching layer |
| Hebbia Greenhouse 404 cleanup in `.env.example` | Coverage | **1.B.3** | Bundle with config restructure for Modal Secrets |
| `approve(thread_id, approved=None)` "request changes" branch | UX | post-1.B | Today binary; if needed, ship as third decision dict key |
| Per-thread auth (anyone with MCP access can approve) | Security | post-1.B | Solo-user system; revisit if hosted |
| Surface `pending_approvals` in the Dataview dashboard | UX polish | **2.B** | Dataview can't read SQLite; needs a tiny exporter |

---

## Critical lessons to carry forward (from Phases 0 + 1.A)

These bit us before; they will bite us again if we forget them:

1. **Tests check shape; only adversarial real-data inspection catches data-correctness bugs.** Task 7 is non-optional — do not declare 1.B.1 done from green CI alone.
2. **Module-level `from compass.config import X` freezes the value at import time** and silently breaks the `temp_*_db` fixtures. Always late-bind inside function bodies (e.g. `from compass.config import HITL_CHECKPOINT_DB` *inside* `run_pipeline`).
3. **A graph compiled without a checkpointer silently breaks `interrupt()`.** Never compile `build_graph()` at module level. The only call sites are inside the `async with AsyncSqliteSaver(...)` block in `run_pipeline` and `resume_pending`.
4. **Two-stage review (spec compliance → code quality) catches ~1 issue per task.** Don't skip even on "mechanical" tasks — the CompanyNote tier race (Phase 1.A bug #1) and the Greenhouse `?content=true` flag (Phase 0 bug #1) both looked mechanical and shipped silent data bugs.
5. **JSON-serializability of MCP return shapes.** Phase 1.A bug #11: `date` objects don't serialise through FastMCP. Use `model_dump(mode="json")` or hand-build plain-dict rows (which `state_store._row_to_dict` already does).
6. **Don't trust the tag until you've resumed a real paused thread across a process restart.** Task 7 Step 3 is specifically that check.

---

## Plan Review Loop

Before executing this plan, dispatch a single plan-document-reviewer subagent with:
- Path to this plan: `docs/superpowers/plans/2026-05-18-compass-phase-1b1-hitl.md`
- Path to spec: `docs/superpowers/specs/2026-05-17-compass-mvp-to-portfolio-ship-design.md`
- Phase scope reference: `docs/PHASE_1A_COMPLETE.md` § "How to start Phase 1.B"

If the reviewer flags issues, fix them in place and re-dispatch the reviewer on the whole plan. Cap at 3 iterations before escalating.

---

## Execution handoff

Once the plan is approved, two execution options:

1. **Subagent-Driven (recommended)** — Use `superpowers:subagent-driven-development`. Fresh implementer subagent per Task 1–6, two-stage reviewer (spec compliance → code quality) between tasks. Task 7 PAUSES for human confirmation before live-LLM run.

2. **Inline Execution** — Use `superpowers:executing-plans`. Single session, batch through Tasks 1–6, hard checkpoint before Task 7.

Phase 1.A used Subagent-Driven and it worked — keep the pattern. Task 7 always pauses for the human regardless of approach because it costs real money and writes to the real vault.
