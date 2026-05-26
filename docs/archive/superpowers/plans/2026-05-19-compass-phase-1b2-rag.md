# Compass Phase 1.B.2 — RAG via Chroma + Phase 1.B.1 carryover cleanup (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `score_node`'s wholesale-inject of `_profile/skill-inventory.md` with semantic retrieval against a Chroma vector index (closes the spec's RAG portfolio claim). Also close two Phase 1.B.1 carryover defects flagged in the post-smoke adversarial reviews: LangGraph msgpack deprecation warnings on `RawJob` / `JobRequirements` / `JobScore` (will break paused threads on the next LangGraph major) and `checkpoints.db` bloat from never-deleted resolved-thread checkpoint blobs.

**Architecture:** New `compass/rag/` package with two modules. `indexer.py` parses `_profile/skill-inventory.md` into one Chroma document per `## SkillName` section, embeds via `sentence-transformers` (`all-MiniLM-L6-v2`), persists to `CHROMA_PATH`. Idempotent on re-run (upsert by stable id = skill heading). `retriever.py` exposes `retrieve(query, k=8) -> list[Chunk]` with lazy index init (build-on-miss). `score_node._profile_text()` is rewritten to retrieve top-k chunks given the JD's `required_skills + nice_to_have + summary` joined as a query, instead of injecting the whole inventory. Resume markdown still ships in full (it's small and load-bearing for context). Token-cost savings: ~2,500 tokens → ~750 tokens per scored JD. Two small infrastructure cleanups land alongside: a serde registration for the three Pydantic state types via `JsonPlusSerializer.register_pydantic_class()` (closes msgpack warnings) and a `_purge_thread_checkpoints(thread_id)` step at the end of `resume_pending` (closes the bloat).

**Module-level discipline (carried forward from 1.A + 1.B.1):** every module that touches `compass.config.CHROMA_PATH`, `EMBEDDING_MODEL`, `SKILL_INVENTORY_PATH`, `HITL_CHECKPOINT_DB`, or `VAULT_PATH` must reference it via `import compass.config as cfg; cfg.<NAME>` *inside function bodies*, never as module-level captured constants. The `temp_*` test fixtures monkeypatch these attributes.

**Tech Stack:** Python 3.12 · chromadb 1.5 (`PersistentClient`) · sentence-transformers 5.5 (`all-MiniLM-L6-v2`, ~90MB local model cache) · langgraph 1.2 (`from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer`) · pytest + pytest-asyncio (`auto` mode, no `asyncio.run` in tests).

**Authoritative spec:** `docs/superpowers/specs/2026-05-17-compass-mvp-to-portfolio-ship-design.md` § Phase 1.B
**Previous-phase handoff:** Phase 1.B.1 retrospective lives in this branch's commits between `phase-1a-application-tracking` and `phase-1b1-hitl`. See `docs/PHASE_1A_COMPLETE.md` for the broader handoff and adversarial-review pattern.

**Closes these deferred items from Phase 1.B.1:**
1. **I-2 (Phase 1.B.1 post-smoke pass 6)** — `~/.compass/checkpoints.db` bloat from never-purged resolved-thread blobs. Fix lands in Task 2.
2. **I1 (Phase 1.B.1 post-smoke pass 4)** — LangGraph msgpack `Deserializing unregistered type compass.pipeline.state.RawJob` warnings. Will become hard errors when `LANGGRAPH_STRICT_MSGPACK=true` defaults on (currently False, verified by `langgraph.checkpoint.serde.jsonplus`). Fix lands in Task 1.

**Does NOT touch in this phase:**
- HiTL flow (Phase 1.B.1 — done; only carryover cleanup is in scope)
- I4 race claim_pending (deferred to Phase 1.B.3; documented in 1.B.1 plan's deferred table)
- Modal cron + Langfuse callback fix + URL-dedup for filtered-jobs → **Phase 1.B.3**
- 30-JD eval harness → **Phase 2.A**
- Do not modify Phase 1.B.1 HiTL code outside the explicit carryover fixes in Tasks 1–2.

---

## File Structure

### New
- `compass/rag/__init__.py` — empty
- `compass/rag/indexer.py` — parse skill-inventory.md → embed → persist to Chroma; `build_index(force_rebuild=False)`; `__main__` CLI entrypoint
- `compass/rag/retriever.py` — `retrieve(query, k=8) -> list[RetrievedChunk]`; lazy index init (build if missing)
- `tests/rag/__init__.py`
- `tests/rag/conftest.py` — `temp_chroma_path` fixture (monkeypatches `compass.config.CHROMA_PATH`); `tiny_inventory` fixture (writes a small 3-section inventory to the temp vault); model-cache reuse fixture so the 90MB sentence-transformers model is only fetched once per test session
- `tests/rag/test_indexer.py`
- `tests/rag/test_retriever.py`
- `tests/pipeline/test_score_node_rag.py` — verifies score_node uses retrieved chunks instead of full inventory

### Modify
- `compass/pipeline/nodes/score.py` — `_profile_text()` rewritten to call retriever; keep resume inline; signature compatibility preserved
- `compass/pipeline/graph.py` — pass `serde=JsonPlusSerializer(...)` to `AsyncSqliteSaver.from_conn_string(...)` AND register the three Pydantic state types
- `compass/hitl/resume.py` — call `_purge_thread_checkpoints(thread_id)` after `mark_resolved` succeeds (only on `vault_written=True`, mirrors the regen pattern)

### Untouched
- All Phase 1.B.1 HiTL infrastructure (`compass/hitl/{state_store,timeout_checker,__init__}.py`)
- All other pipeline nodes (`intake`, `intake_filter`, `extract`, `reflect`, `hitl`, `tailor`, `vault_write`)
- Vault schemas, vault writer, scrapers, applications lifecycle
- MCP server tools

### Decomposition rationale
The two HiTL cleanups (msgpack + checkpoint purge) are intentionally Tasks 1 and 2 — small, isolated, and lower-risk than the RAG work. They land FIRST so the new tests pass against a stable baseline before any RAG changes. RAG splits across three files: `indexer.py` (write path), `retriever.py` (read path), and the `score_node` integration. The indexer/retriever split lets tests exercise each side in isolation (build an index; query an index) without needing the full pipeline. The retriever is the only one `score_node` depends on, keeping the dependency arrow one-way. `temp_chroma_path` is per-test to avoid sentence-transformer-cache leakage across tests, but the model itself (≈90MB) is loaded once per session via a module-cached factory.

---

## Task 0: Pre-flight

**Files:** none

- [ ] **Step 1: Verify clean tree on `phase-1b1-hitl` tag**

```bash
cd /Users/<user>/Documents/compass
git status                       # expected: clean
git describe --tags --abbrev=0   # expected: phase-1b1-hitl
uv run pytest -q                 # expected: 239 passed
uv run ruff check                # expected: All checks passed
```

If working tree is dirty, STOP and ask the user before proceeding.

- [ ] **Step 2: Confirm Chroma + sentence-transformers + langgraph serde availability AND verify the construction form actually suppresses warnings**

```bash
uv run python -c "
import chromadb, sentence_transformers, logging, datetime
print('chromadb', chromadb.__version__)  # expected: 1.x
print('sentence_transformers', sentence_transformers.__version__)  # expected: 5.x
from chromadb import PersistentClient
import langgraph.checkpoint.serde.jsonplus as _jp
_jp._warned_unregistered_types.clear()  # reset module-level once-only set
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from compass.pipeline.state import RawJob, JobRequirements, JobScore

# Pass the allowlist at construction — `with_msgpack_allowlist` is a no-op
# when `allowed_msgpack_modules=True` (langgraph's non-STRICT default).
captured = []
class H(logging.Handler):
    def emit(self, r):
        msg = r.getMessage()
        if 'unregistered' in msg or 'fingerprint' in msg.lower():
            captured.append(msg)
logging.getLogger('langgraph').addHandler(H())

serde = JsonPlusSerializer(allowed_msgpack_modules=[
    ('compass.pipeline.state', 'RawJob'),
    ('compass.pipeline.state', 'JobRequirements'),
    ('compass.pipeline.state', 'JobScore'),
])
rj = RawJob(company='C', title='T', url='u://x', source='ashby', description='d', date_posted=datetime.date(2026,5,19))
ser = serde.dumps_typed(rj)
restored = serde.loads_typed(ser)
assert isinstance(restored, RawJob), f'expected RawJob, got {type(restored).__name__}'
assert not captured, f'allowlist did not suppress warnings: {captured}'
print('serde tuple-list allowlist verified — no warnings, types preserved')
"
```

Expected: prints `serde tuple-list allowlist verified — no warnings, types preserved`. If it fails with warnings still captured OR `restored` is not a RawJob, the allowlist API has shifted; STOP and inspect `inspect.signature(JsonPlusSerializer)` for the current constructor signature before continuing.

**Lesson:** the deprecation warning text is misleading — it says "add to allowed_msgpack_modules" suggesting you can call a method after construction. You cannot. The allowlist MUST be passed at construction time as `(module, classname)` tuples.

- [ ] **Step 2.5: Confirm checkpoint DB table names match what Task 2 will DELETE from**

```bash
sqlite3 ~/.compass/checkpoints.db "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
```

Expected: exactly `checkpoints` and `writes`. If the table names differ, Task 2's DELETE statements must be updated to match — there's no try/except wrapper to mask a mismatch.

- [ ] **Step 3: Verify `_profile/skill-inventory.md` structure (drives chunking)**

```bash
grep -c '^## ' ~/Documents/compass-vault/_profile/skill-inventory.md
```

Expected: ≥ 15 level-2 headings. If the structure has materially changed, the chunking strategy (`## SkillName` per chunk) needs revisiting first.

- [ ] **Step 4: Create branch**

```bash
git checkout -b phase-1b2-rag
```

---

## Task 1: Register Pydantic state types with LangGraph checkpointer serde (carryover I1)

**Why first:** Smallest, lowest-risk fix. Closes the msgpack deprecation warnings logged on every resume in Phase 1.B.1's smoke. Lands at the top of the phase so all subsequent tests benefit from a quieter log.

**Files:**
- Modify: `compass/pipeline/graph.py`
- Create: `tests/pipeline/test_checkpoint_serde.py`

**Background:** LangGraph 1.2 uses msgpack for checkpoint serialization. When it encounters an unregistered class (our `RawJob`, `JobRequirements`, `JobScore` Pydantic models), it logs `Deserializing unregistered type ... This will be blocked in a future version`. The clean fix is to construct a `JsonPlusSerializer` with explicit type registration and pass it to `AsyncSqliteSaver(serde=...)`.

- [ ] **Step 1: Write the failing test**

Create `tests/pipeline/test_checkpoint_serde.py`:

```python
"""Verify LangGraph checkpoint serde explicitly allowlists the
   compass.pipeline.state module so the 'Deserializing unregistered type'
   warnings (logged in 1.B.1 smoke) don't recur, and so a future
   LANGGRAPH_STRICT_MSGPACK=true default doesn't break paused-thread
   deserialization."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def checkpoint_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "checkpoints.db"
    import compass.config as cfg
    monkeypatch.setattr(cfg, "HITL_CHECKPOINT_DB", db)
    return db


async def test_build_checkpoint_serde_allowlists_state_module():
    """_build_checkpoint_serde must return a JsonPlusSerializer whose
       allowlist suppresses the 'unregistered type' warning AND preserves
       the Pydantic class on round-trip."""
    import langgraph.checkpoint.serde.jsonplus as _jp
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from compass.pipeline.graph import _build_checkpoint_serde

    # langgraph caches "already warned for this type" in a module-level set;
    # clear it so this test sees a clean slate regardless of prior imports.
    _jp._warned_unregistered_types.clear()

    serde = _build_checkpoint_serde()
    assert isinstance(serde, JsonPlusSerializer)

    from compass.pipeline.state import RawJob
    import logging
    captured = []
    class _H(logging.Handler):
        def emit(self, r):
            if "unregistered type" in r.getMessage() or "fingerprint" in r.getMessage().lower():
                captured.append(r.getMessage())
    h = _H()
    logging.getLogger("langgraph").addHandler(h)
    try:
        import datetime
        rj = RawJob(company="C", title="T", url="u://x", source="ashby",
                    description="d", date_posted=datetime.date(2026, 5, 19))
        ser = serde.dumps_typed(rj)
        restored = serde.loads_typed(ser)
        assert isinstance(restored, RawJob)
    finally:
        logging.getLogger("langgraph").removeHandler(h)
    assert not captured, f"serde still emitted unregistered-type warnings: {captured}"


async def test_run_pipeline_emits_no_unregistered_warnings(checkpoint_db, monkeypatch, temp_vault):
    """Smoke: run_pipeline mounts AsyncSqliteSaver with our serde, not the
       default. No 'unregistered type' warnings should be emitted during
       a checkpoint round-trip."""
    import langgraph.checkpoint.serde.jsonplus as _jp
    from compass.pipeline.state import JobRequirements, JobScore, RawJob
    import datetime as _dt
    import logging

    # See note in test_build_checkpoint_serde_allowlists_state_module — clear
    # the once-only warned-types set so this test isn't fooled by warnings
    # already emitted in earlier imports.
    _jp._warned_unregistered_types.clear()

    captured = []
    class _Handler(logging.Handler):
        def emit(self, record):
            if "unregistered type" in record.getMessage():
                captured.append(record.getMessage())
    handler = _Handler()
    logging.getLogger("langgraph").addHandler(handler)

    # Stub the LLM-touching nodes (existing pattern from test_graph_checkpointing.py)
    async def fake_intake_filter(_): return {"in_scope": True, "role_family": "agent-engineer"}
    async def fake_extract(_): return {"extracted_requirements": JobRequirements(
        required_skills=["MCP"], nice_to_have_skills=[], seniority="mid",
        remote_policy="remote", summary="x")}
    async def fake_score(_): return {"score_result": JobScore(
        score=4.5, reasoning="ok", matched_skills=["MCP"], missing_skills=[],
        tailoring_notes=""), "score_threshold": 3.5}
    async def fake_tailor(_): return {"tailored_paragraph": "..."}
    async def fake_vault_write(_): return {"vault_written": True, "jobs_written": 1}
    monkeypatch.setattr("compass.pipeline.graph.intake_filter_node", fake_intake_filter)
    monkeypatch.setattr("compass.pipeline.graph.extract_node", fake_extract)
    monkeypatch.setattr("compass.pipeline.graph.score_node", fake_score)
    monkeypatch.setattr("compass.pipeline.graph.tailor_node", fake_tailor)
    monkeypatch.setattr("compass.pipeline.graph.vault_write_node", fake_vault_write)
    # Auto-approve interrupt so the graph completes
    monkeypatch.setattr("compass.pipeline.nodes.hitl.interrupt",
                        lambda _: {"approved": True, "feedback": None})

    from compass.pipeline.graph import run_pipeline
    await run_pipeline(raw_jobs=[RawJob(
        company="AgentCo", title="SWE", url="u://x/1", source="ashby",
        description="...", date_posted=_dt.date(2026, 5, 19),
    )])

    logging.getLogger("langgraph").removeHandler(handler)
    assert not captured, f"Expected no 'unregistered type' warnings, got: {captured}"
```

Run: `uv run pytest tests/pipeline/test_checkpoint_serde.py -v` — expect both to fail (`_build_checkpoint_serde` doesn't exist).

- [ ] **Step 2: Implement `_build_checkpoint_serde` in `compass/pipeline/graph.py`**

Add near the existing checkpointer imports:

```python
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
```

Add as a module-level helper just above `build_graph`:

```python
def _build_checkpoint_serde() -> JsonPlusSerializer:
    """Allow our Pydantic state classes on the msgpack allowlist.

    Must be set at construction — `with_msgpack_allowlist` is a no-op when the
    default `allowed_msgpack_modules=True` (langgraph's non-STRICT default).
    """
    return JsonPlusSerializer(
        allowed_msgpack_modules=[
            ("compass.pipeline.state", "RawJob"),
            ("compass.pipeline.state", "JobRequirements"),
            ("compass.pipeline.state", "JobScore"),
        ]
    )
```

- [ ] **Step 3: Wire the serde into `AsyncSqliteSaver.from_conn_string`**

In `run_pipeline`, change:

```python
async with AsyncSqliteSaver.from_conn_string(str(HITL_CHECKPOINT_DB)) as checkpointer:
```

to:

```python
async with AsyncSqliteSaver.from_conn_string(str(HITL_CHECKPOINT_DB)) as checkpointer:
    checkpointer.serde = _build_checkpoint_serde()
```

(`from_conn_string(conn_string: str)` in checkpoint-sqlite 3.1 doesn't accept `serde=`. Setting `checkpointer.serde` after entering the context manager is the supported pattern.)

Apply the same change in `compass/hitl/resume.py`'s `async with AsyncSqliteSaver.from_conn_string(...)` block — same pattern, same one line. Otherwise resume reuses the default serde and the warnings recur.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/pipeline/test_checkpoint_serde.py -v
```

Expected: 2 passed. If the second test still captures warnings, the serde isn't being applied to the active checkpointer — re-inspect `run_pipeline` and `resume.py`.

- [ ] **Step 5: Full suite + lint**

```bash
uv run pytest -q
uv run ruff check && uv run ruff format --check
```

Expected: 241 passed (239 + 2 new). Ruff clean.

- [ ] **Step 6: Commit**

```bash
git add compass/pipeline/graph.py compass/hitl/resume.py tests/pipeline/test_checkpoint_serde.py
git commit -m "feat(hitl): register Pydantic state types with checkpoint serde"
```

---

## Task 2: Purge resolved-thread checkpoint blobs (carryover I-2)

**Background:** Phase 1.B.1 left ~7.6MB in `~/.compass/checkpoints.db` after the smoke. Every paused thread accumulates ~10 checkpoint blobs and is never deleted post-resolution. At 50 jobs/day ÷ 5 paused, the file grows ~1MB/day forever.

**Files:**
- Modify: `compass/hitl/resume.py` — `_purge_thread_checkpoints(thread_id)` called inside the `async with checkpointer` block after `mark_resolved` succeeds
- Modify: `tests/hitl/test_resume.py` — add a regression test

- [ ] **Step 1: Write the failing test**

Append to `tests/hitl/test_resume.py`:

```python
@pytest.mark.usefixtures("temp_hitl_db", "checkpoint_db", "temp_vault")
async def test_resume_purges_thread_checkpoint_blobs(stub_llm_nodes):
    """After a thread is resolved (approved OR rejected), its checkpoint rows
       in HITL_CHECKPOINT_DB must be deleted — otherwise the DB grows
       unboundedly. Phase 1.B.1 post-smoke I-2 finding."""
    import aiosqlite
    from compass.config import HITL_CHECKPOINT_DB
    from compass.hitl.resume import resume_pending
    from compass.pipeline.graph import run_pipeline

    job = RawJob(company="AgentCo", title="SWE", url="u://purge-probe",
                 source="ashby", description="...", date_posted=_dt.date(2026, 5, 19))
    pre = await run_pipeline(raw_jobs=[job])
    assert pre["jobs_paused"] == 1
    tid = (await state_store.list_pending())[0]["thread_id"]

    # Verify checkpoint rows exist before resume
    async with aiosqlite.connect(HITL_CHECKPOINT_DB) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (tid,)
        ) as cur:
            (pre_count,) = await cur.fetchone()
    assert pre_count > 0, f"setup error: no checkpoint rows for {tid}"

    await resume_pending(tid, decision={"approved": True, "feedback": "test"})

    # Verify checkpoint rows for this thread are gone (state_store row is
    # what stays — that's the audit trail, not the LangGraph internals).
    async with aiosqlite.connect(HITL_CHECKPOINT_DB) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (tid,)
        ) as cur:
            (post_count,) = await cur.fetchone()
    assert post_count == 0, f"checkpoint rows for resolved thread {tid} were not purged"
```

Run: `uv run pytest tests/hitl/test_resume.py::test_resume_purges_thread_checkpoint_blobs -v` — expect failure.

- [ ] **Step 2: Implement `_purge_thread_checkpoints` in `compass/hitl/resume.py`**

Add a private helper at the bottom of the file:

```python
async def _purge_thread_checkpoints(thread_id: str) -> None:
    """Drop LangGraph per-step history for a resolved thread; state_store is the audit trail."""
    import aiosqlite

    from compass.config import HITL_CHECKPOINT_DB

    async with aiosqlite.connect(HITL_CHECKPOINT_DB) as conn:
        await conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        await conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
        await conn.commit()
```

Wire the call inside `resume_pending` AFTER `mark_resolved` succeeds AND AFTER the `async with AsyncSqliteSaver(...)` block exits — `_purge_thread_checkpoints` opens its own connection, so it doesn't need the saver's context:

```python
    async with AsyncSqliteSaver.from_conn_string(str(HITL_CHECKPOINT_DB)) as checkpointer:
        checkpointer.serde = _build_checkpoint_serde()  # carried from Task 1
        graph = build_graph(checkpointer=checkpointer)
        final = await graph.ainvoke(Command(resume=decision), config=config)

    if status_override is not None:
        resolved_status = status_override
    else:
        resolved_status = "approved" if final.get("human_approved") is True else "rejected"
    await state_store.mark_resolved(
        thread_id, status=resolved_status, feedback=decision.get("feedback"),
    )
    await _purge_thread_checkpoints(thread_id)

    if final.get("vault_written"):
        from compass.analysis import gap_aggregator
        try:
            gap_aggregator.regenerate(write=True)
        except Exception:
            logger.exception("hitl: gap_aggregator.regenerate failed after resume")
```

- [ ] **Step 3: Run the test**

```bash
uv run pytest tests/hitl/test_resume.py -v
```

Expected: all 6 (5 prior + 1 new) pass.

- [ ] **Step 4: Full suite + lint**

```bash
uv run pytest -q
uv run ruff check && uv run ruff format --check
```

Expected: 242 passed (241 + 1). Ruff clean.

- [ ] **Step 5: Commit**

```bash
git add compass/hitl/resume.py tests/hitl/test_resume.py
git commit -m "fix(hitl): purge thread checkpoint blobs on resume (bound checkpoints.db growth)"
```

---

## Task 3: RAG indexer (`compass/rag/indexer.py`)

**Files:**
- Create: `compass/rag/__init__.py` (empty)
- Create: `compass/rag/indexer.py`
- Create: `tests/rag/__init__.py`
- Create: `tests/rag/conftest.py`
- Create: `tests/rag/test_indexer.py`

**Chunking strategy:** one chunk per `## SkillName` heading in `_profile/skill-inventory.md`. The chunk's `id` is the kebab-cased skill name (deterministic across rebuilds). The chunk's `metadata` carries `skill` (raw heading text), `section` (parent grouping if applicable; for now just "skill"), `source` ("skill-inventory.md"). The chunk's `document` is the section body text (heading + everything until the next `## ` or EOF).

**Embedding model:** `all-MiniLM-L6-v2` via sentence-transformers. The model downloads on first use (~90MB to `~/.cache/torch/sentence_transformers/`); for tests we use a session-scoped fixture so it loads once.

- [ ] **Step 1: Write the conftest**

Create `tests/rag/conftest.py`:

```python
"""Shared fixtures for RAG tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def temp_chroma_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test Chroma index path — avoids cross-test pollution."""
    p = tmp_path / "chroma"
    import compass.config as cfg
    monkeypatch.setattr(cfg, "CHROMA_PATH", p)
    return p


@pytest.fixture
def tiny_inventory(temp_vault, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write a small skill-inventory.md to the temp vault — 3 distinct sections
    so retrieval tests can verify which section gets surfaced."""
    inv = temp_vault / "_profile" / "skill-inventory.md"
    inv.parent.mkdir(parents=True, exist_ok=True)
    inv.write_text(
        "# Skill Inventory\n\n"
        "## Python\n\n"
        "Level 4. 5 years building backends and agents in Python. "
        "production MCP servers, LangGraph pipelines, FastAPI services.\n\n"
        "## LangGraph\n\n"
        "Level 3. Built Compass pipeline with stateful graph, conditional "
        "edges, interrupt()+AsyncSqliteSaver checkpointing for HITL.\n\n"
        "## React\n\n"
        "Level 1. Touched in school projects. Not a primary skill.\n",
        encoding="utf-8",
    )
    return inv


@pytest.fixture(scope="session")
def embedding_model_cached():
    """Pre-load the sentence-transformers model once per test session.
    Subsequent fixtures + tests reuse the in-process cache."""
    from sentence_transformers import SentenceTransformer
    # Touch it to force download/cache. Use the same name as compass.config.
    SentenceTransformer("all-MiniLM-L6-v2")
```

- [ ] **Step 2: Write the failing indexer tests**

Create `tests/rag/test_indexer.py`:

```python
"""indexer parses skill-inventory.md by ## SkillName, embeds, persists.
   Idempotent on rebuild (upsert by stable id = kebab-cased skill name).

   These tests use real sentence-transformers (the model is cached at session
   scope; ~90MB on first run). They do NOT touch the network beyond the
   initial model download."""

from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.usefixtures("embedding_model_cached")


async def test_indexer_builds_one_chunk_per_section(tiny_inventory, temp_chroma_path):
    from compass.rag import indexer

    count = await indexer.build_index()
    assert count == 3, f"expected 3 chunks (Python/LangGraph/React), got {count}"


async def test_indexer_uses_kebab_case_ids(tiny_inventory, temp_chroma_path):
    from compass.rag import indexer

    await indexer.build_index()
    client = indexer._client()
    col = client.get_collection("skill_inventory")
    got_ids = set(col.get()["ids"])
    assert got_ids == {"python", "langgraph", "react"}


async def test_indexer_metadata_carries_skill_and_source(tiny_inventory, temp_chroma_path):
    from compass.rag import indexer

    await indexer.build_index()
    client = indexer._client()
    col = client.get_collection("skill_inventory")
    res = col.get(ids=["python"])
    assert res["metadatas"][0]["skill"] == "Python"
    assert res["metadatas"][0]["source"] == "skill-inventory.md"


async def test_indexer_is_idempotent_on_rebuild(tiny_inventory, temp_chroma_path):
    """A second build_index() must not duplicate rows. Upsert by id."""
    from compass.rag import indexer

    await indexer.build_index()
    await indexer.build_index()  # second call
    client = indexer._client()
    col = client.get_collection("skill_inventory")
    assert col.count() == 3


async def test_indexer_force_rebuild_clears_stale_chunks(tiny_inventory, temp_chroma_path):
    """If the inventory shrinks (skill removed), force_rebuild=True must remove
       the stale chunk; otherwise the old embedding lingers and pollutes retrieval."""
    from compass.rag import indexer

    await indexer.build_index()
    tiny_inventory.write_text(
        "# Skill Inventory\n\n## Python\n\nLevel 4.\n",
        encoding="utf-8",
    )
    await indexer.build_index(force_rebuild=True)
    client = indexer._client()
    col = client.get_collection("skill_inventory")
    got_ids = set(col.get()["ids"])
    assert got_ids == {"python"}


async def test_indexer_repairs_stale_l2_collection(temp_vault, temp_chroma_path):
    """An existing L2 collection from a pre-1.B.2 install must be dropped+recreated
    with the cosine metric — otherwise the retriever score formula breaks silently."""
    from chromadb import PersistentClient

    from compass.rag import indexer

    # Simulate pre-1.B.2 state: collection exists with default (L2) metric.
    client = PersistentClient(path=str(temp_chroma_path))
    client.create_collection(name="skill_inventory")  # no cosine metadata

    col = indexer._collection(client)
    assert (col.metadata or {}).get("hnsw:space") == "cosine"


async def test_indexer_excludes_assessor_grades_heading(temp_vault, temp_chroma_path):
    """Auto-generated `## Assessor-current grades` is metadata, not a skill —
    must NOT land in the index or it pollutes retrieval with every skill name."""
    inv = temp_vault / "_profile" / "skill-inventory.md"
    inv.parent.mkdir(parents=True, exist_ok=True)
    inv.write_text(
        "## Python\n\nLevel 4.\n\n"
        "## Assessor-current grades\n\nPython: 4 / LangGraph: 3 / MCP: 5\n",
        encoding="utf-8",
    )
    from compass.rag import indexer

    n = await indexer.build_index()
    assert n == 1
    col = indexer._collection(indexer._client())
    assert set(col.get()["ids"]) == {"python"}


async def test_indexer_handles_empty_inventory_gracefully(temp_vault, temp_chroma_path):
    """No ## sections — count is 0, no crash, no collection bloat."""
    inv = temp_vault / "_profile" / "skill-inventory.md"
    inv.parent.mkdir(parents=True, exist_ok=True)
    inv.write_text("# Skill Inventory\n\nNo skills yet.\n", encoding="utf-8")
    from compass.rag import indexer

    count = await indexer.build_index()
    assert count == 0
```

Run: `uv run pytest tests/rag/test_indexer.py -v` — expect all to fail with `ModuleNotFoundError: compass.rag.indexer`.

- [ ] **Step 3: Implement `compass/rag/indexer.py`**

```python
"""Chroma index of _profile/skill-inventory.md.

One chunk per `## SkillName` section. Collection metric is cosine — the
retriever's similarity score formula depends on this.
"""

from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "skill_inventory"
_SECTION_RE = re.compile(r"^## +(.+)$", re.M)
# Auto-generated assessor output; not a skill — exclude from the index.
_EXCLUDED_HEADINGS = {"Assessor-current grades"}


def _client():
    import compass.config as cfg
    from chromadb import PersistentClient

    cfg.CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    return PersistentClient(path=str(cfg.CHROMA_PATH))


def _collection(client):
    """Return the skill_inventory collection pinned to cosine distance.

    `get_or_create_collection` does NOT update an existing collection's
    metadata — so a pre-existing L2 collection would silently keep the wrong
    metric and break the retriever's score formula. Drop and recreate if so.
    """
    existing = {c.name for c in client.list_collections()}
    if _COLLECTION_NAME in existing:
        col = client.get_collection(_COLLECTION_NAME)
        if (col.metadata or {}).get("hnsw:space") == "cosine":
            return col
        client.delete_collection(_COLLECTION_NAME)
    return client.create_collection(
        name=_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def _kebab(name: str) -> str:
    # Drop parenthetical asides and em-dash commentary — they're not identity.
    # `Fine-Tuning (awareness only — ...)` -> `fine-tuning`
    # `MCP — your strongest cluster` -> `mcp`
    primary = re.sub(r"\s*(?:\(|[—–]\s).*$", "", name).strip()
    return re.sub(r"[^a-z0-9]+", "-", primary.lower()).strip("-") or "untitled"


def _parse_inventory(text: str) -> list[tuple[str, str]]:
    """Return [(skill_name, section_text), ...] — one entry per ## heading.

    Skips headings in _EXCLUDED_HEADINGS (auto-generated metadata that isn't
    a real skill and would otherwise pollute retrieval).
    """
    matches = list(_SECTION_RE.finditer(text))
    sections = []
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        if any(name.startswith(prefix) for prefix in _EXCLUDED_HEADINGS):
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((name, text[m.start():end].strip()))
    return sections


def _embed(documents: list[str]) -> list[list[float]]:
    import compass.config as cfg
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(cfg.EMBEDDING_MODEL)
    arr = model.encode(documents, convert_to_numpy=True, show_progress_bar=False)
    return [vec.tolist() for vec in arr]


async def build_index(force_rebuild: bool = False) -> int:
    """Embed each `## Section` of skill-inventory.md and upsert into Chroma.

    Idempotent — repeat calls upsert by stable id. Pass `force_rebuild=True`
    to drop the collection first (use when the inventory shrinks; otherwise
    deleted skills' stale chunks linger).
    """
    import compass.config as cfg

    if not cfg.SKILL_INVENTORY_PATH.exists():
        logger.warning("rag: skill-inventory.md not found at %s", cfg.SKILL_INVENTORY_PATH)
        return 0

    sections = _parse_inventory(cfg.SKILL_INVENTORY_PATH.read_text(encoding="utf-8"))
    if not sections:
        logger.info("rag: 0 ## sections in skill-inventory.md; nothing to index")
        return 0

    client = _client()
    if force_rebuild and _COLLECTION_NAME in {c.name for c in client.list_collections()}:
        client.delete_collection(_COLLECTION_NAME)
    collection = _collection(client)

    documents = [body for _, body in sections]
    embeddings = await asyncio.to_thread(_embed, documents)

    collection.upsert(
        ids=[_kebab(name) for name, _ in sections],
        documents=documents,
        embeddings=embeddings,
        metadatas=[
            {"skill": name, "source": "skill-inventory.md"} for name, _ in sections
        ],
    )
    logger.info("rag: indexed %d sections at %s", len(sections), cfg.CHROMA_PATH)
    return len(sections)


def _main() -> None:
    import argparse

    import compass.config as cfg

    parser = argparse.ArgumentParser(description="Rebuild Chroma index of skill-inventory.md")
    parser.add_argument("--force", action="store_true", help="Drop+rebuild the collection")
    n = asyncio.run(build_index(force_rebuild=parser.parse_args().force))
    print(f"Indexed {n} sections from {cfg.SKILL_INVENTORY_PATH}")


if __name__ == "__main__":
    _main()
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/rag/test_indexer.py -v
```

Expected: 8 passed. First run downloads the model (~90MB, 30-60s on first install). Subsequent runs are fast.

If a test fails because Chroma's `get_or_create_collection` API differs in your installed version, check the actual `chromadb` 1.5 API and adjust the call. The public surface has been stable in 0.5+.

- [ ] **Step 5: Full suite + lint**

```bash
uv run pytest -q
uv run ruff check && uv run ruff format --check
```

Expected: 250 passed (242 + 8). Ruff clean.

- [ ] **Step 6: Commit**

```bash
git add compass/rag/__init__.py compass/rag/indexer.py tests/rag/__init__.py \
        tests/rag/conftest.py tests/rag/test_indexer.py
git commit -m "feat(rag): chroma index of skill-inventory.md (one chunk per ## section)"
```

---

## Task 4: RAG retriever (`compass/rag/retriever.py`)

**Files:**
- Create: `compass/rag/retriever.py`
- Create: `tests/rag/test_retriever.py`

- [ ] **Step 1: Write the failing retriever tests**

Create `tests/rag/test_retriever.py`:

```python
"""retriever.retrieve(query, k) returns top-k chunks from the Chroma index.
   Lazy-init: builds the index on miss so first-run usage doesn't crash."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.usefixtures("embedding_model_cached")


async def test_retrieve_returns_top_k_relevant_chunks(tiny_inventory, temp_chroma_path):
    from compass.rag import indexer, retriever

    await indexer.build_index()

    hits = await retriever.retrieve("Python backend agent work", k=2)
    assert len(hits) == 2
    # Soft assertion — embedding-model top-1 can flap on a 3-doc corpus.
    # The real contract is "Python ranks in the top-2", not "exactly first".
    skills = [h.skill for h in hits]
    assert "Python" in skills
    assert any("production MCP" in h.document for h in hits)  # body content present
    assert all(0.0 <= h.score <= 1.0 for h in hits)  # normalized similarity scores


async def test_retrieve_lazy_inits_index_on_miss(tiny_inventory, temp_chroma_path):
    """If no index exists yet, retrieve() builds one before querying."""
    from compass.rag import retriever

    # No build_index() call beforehand
    hits = await retriever.retrieve("LangGraph stateful pipeline", k=1)
    assert len(hits) == 1
    assert hits[0].skill == "LangGraph"


async def test_retrieve_returns_empty_when_inventory_empty(temp_vault, temp_chroma_path):
    """No sections in inventory → retrieve returns [] gracefully (no crash)."""
    inv = temp_vault / "_profile" / "skill-inventory.md"
    inv.parent.mkdir(parents=True, exist_ok=True)
    inv.write_text("# Empty\n", encoding="utf-8")
    from compass.rag import retriever

    hits = await retriever.retrieve("anything", k=5)
    assert hits == []


async def test_retrieve_k_larger_than_corpus_returns_all(tiny_inventory, temp_chroma_path):
    from compass.rag import indexer, retriever

    await indexer.build_index()
    hits = await retriever.retrieve("python or react", k=99)
    assert 1 <= len(hits) <= 3  # corpus has 3 chunks; can't exceed
```

Run: `uv run pytest tests/rag/test_retriever.py -v` — expect failures (`compass.rag.retriever` doesn't exist).

- [ ] **Step 2: Implement `compass/rag/retriever.py`**

```python
"""Top-k retrieval over the skill-inventory Chroma index.

Lazy-init on first call so scoring works before any explicit indexer run.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from compass.rag import indexer


@dataclass
class RetrievedChunk:
    skill: str
    document: str
    score: float  # cosine similarity in [0, 1]; 1.0 = identical


async def retrieve(query: str, k: int = 8) -> list[RetrievedChunk]:
    if not (query or "").strip():
        return []

    collection = indexer._collection(indexer._client())
    if collection.count() == 0 and await indexer.build_index() == 0:
        return []

    [query_emb] = await asyncio.to_thread(indexer._embed, [query])
    res = collection.query(
        query_embeddings=[query_emb],
        n_results=min(k, collection.count()),
    )

    # Collection is pinned to cosine (see indexer._collection); distance ∈ [0, 2].
    return [
        RetrievedChunk(skill=m["skill"], document=d, score=max(0.0, 1.0 - dist / 2.0))
        for m, d, dist in zip(
            res["metadatas"][0], res["documents"][0], res["distances"][0], strict=True
        )
    ]
```

- [ ] **Step 3: Run the tests**

```bash
uv run pytest tests/rag/test_retriever.py -v
```

Expected: 4 passed.

- [ ] **Step 4: Full suite + lint**

```bash
uv run pytest -q
uv run ruff check && uv run ruff format --check
```

Expected: 254 passed (250 + 4). Ruff clean.

- [ ] **Step 5: Commit**

```bash
git add compass/rag/retriever.py tests/rag/test_retriever.py
git commit -m "feat(rag): semantic retriever with lazy index init"
```

---

## Task 5: Wire retriever into `score_node`

**Files:**
- Modify: `compass/pipeline/nodes/score.py`
- Create: `tests/pipeline/test_score_node_rag.py`

**Strategy:** the existing `_profile_text()` returns `## RESUME\n{full resume}\n\n## SKILL INVENTORY\n{full inventory}`. The new version returns `## RESUME\n{full resume}\n\n## RELEVANT SKILLS\n{top-k chunks joined}`. Resume stays inline (it's small and contextual); inventory is replaced by retrieval.

**Query construction:** join the JD's `required_skills + nice_to_have_skills + summary` into a single string. This embeds the candidate-relevant query in one shot. K=8 covers most expected coverage.

- [ ] **Step 1: Write the failing test**

Create `tests/pipeline/test_score_node_rag.py`:

```python
"""score_node uses RAG retrieval to build profile context, not full inventory."""

from __future__ import annotations

import pytest

from compass.pipeline.state import JobRequirements


pytestmark = pytest.mark.usefixtures("embedding_model_cached")


def _stub_req(**overrides) -> JobRequirements:
    base = dict(
        required_skills=["Python", "LangGraph"],
        nice_to_have_skills=["MCP"],
        seniority="senior",
        remote_policy="remote",
        summary="Build agentic systems.",
    )
    base.update(overrides)
    return JobRequirements(**base)


async def test_profile_text_includes_resume_and_retrieved_chunks(monkeypatch):
    from compass.pipeline.nodes import score as score_mod
    from compass.rag.retriever import RetrievedChunk

    async def fake_retrieve(query, k=8):
        return [RetrievedChunk(skill="Python", document="## Python\nLevel 4.", score=0.9)]

    monkeypatch.setattr("compass.pipeline.nodes.score.rag_retrieve", fake_retrieve)
    monkeypatch.setattr("compass.pipeline.nodes.score.read_resume", lambda: "RESUME TEXT")

    text = await score_mod._profile_text(_stub_req())
    assert "RESUME TEXT" in text
    assert "## Python\nLevel 4." in text


async def test_retrieval_query_carries_jd_skills_and_summary(monkeypatch):
    from compass.pipeline.nodes import score as score_mod
    from compass.rag.retriever import RetrievedChunk

    captured: dict[str, object] = {}

    async def fake_retrieve(query, k=8):
        captured["query"] = query
        return [RetrievedChunk(skill="Python", document="## Python", score=0.9)]

    monkeypatch.setattr("compass.pipeline.nodes.score.rag_retrieve", fake_retrieve)
    monkeypatch.setattr("compass.pipeline.nodes.score.read_resume", lambda: "")

    await score_mod._profile_text(_stub_req())
    q = captured["query"]
    assert "Python" in q and "LangGraph" in q and "MCP" in q
    assert "Build agentic systems" in q


async def test_score_node_handles_empty_jd_skills(monkeypatch):
    """A JD with no required/nice-to-have skills falls back to summary only."""
    from compass.pipeline.nodes import score as score_mod
    from compass.rag.retriever import RetrievedChunk

    async def fake_retrieve(query: str, k: int = 8):
        return [RetrievedChunk(skill="Python", document="## Python\nLevel 4.", score=0.9)]

    monkeypatch.setattr("compass.pipeline.nodes.score.rag_retrieve", fake_retrieve)
    monkeypatch.setattr("compass.pipeline.nodes.score.read_resume", lambda: "RESUME")

    req = JobRequirements(
        required_skills=[], nice_to_have_skills=[],
        seniority="mid", remote_policy="remote", summary="Just a summary.",
    )
    text = await score_mod._profile_text(req)
    assert "RESUME" in text
    assert "Python" in text  # still got a retrieved chunk


async def test_score_node_handles_empty_retrieval(monkeypatch):
    """If retriever returns [] (e.g. empty corpus), the profile context still
       includes the resume — score_node doesn't crash."""
    from compass.pipeline.nodes import score as score_mod

    async def fake_retrieve(query: str, k: int = 8):
        return []

    monkeypatch.setattr("compass.pipeline.nodes.score.rag_retrieve", fake_retrieve)
    monkeypatch.setattr("compass.pipeline.nodes.score.read_resume", lambda: "RESUME ONLY")

    req = JobRequirements(
        required_skills=["X"], nice_to_have_skills=[],
        seniority="mid", remote_policy="remote", summary="x",
    )
    text = await score_mod._profile_text(req)
    assert "RESUME ONLY" in text
    # No "## RELEVANT SKILLS" block when retrieval is empty
```

Run: `uv run pytest tests/pipeline/test_score_node_rag.py -v` — expect failures (the score module doesn't import rag_retrieve and _profile_text is currently sync).

- [ ] **Step 2: Rewrite `_profile_text` in `compass/pipeline/nodes/score.py`**

Two edits to the file:

**2a. Add the import near the top (alongside `read_resume` / `read_skill_inventory`):**

```python
from compass.rag.retriever import retrieve as rag_retrieve
```

You can REMOVE the `read_skill_inventory` import from `score.py` only — `_profile_text` no longer uses it. **Do NOT** delete `read_skill_inventory` from `compass/vault/reader.py` — `tests/vault/test_reader.py` still exercises it, and the function may be useful for future tooling outside the pipeline.

**2b. Rewrite `_profile_text` from sync to async, accepting `req: JobRequirements`:**

```python
async def _profile_text(req: JobRequirements) -> str:
    """Build the candidate-profile context for the score prompt.

    RAG via Chroma replaces the prior wholesale-inject of skill-inventory.md.
    Resume stays inline (small, load-bearing); inventory is now top-k chunks
    retrieved against the JD's skill + summary query.
    """
    query_parts = [*req.required_skills, *req.nice_to_have_skills]
    if req.summary:
        query_parts.append(req.summary)
    query = " ".join(query_parts).strip()

    chunks = await rag_retrieve(query, k=8) if query else []

    profile = f"## RESUME\n{read_resume()}"
    if chunks:
        ranked = "\n\n".join(c.document for c in chunks)
        profile += f"\n\n## RELEVANT SKILLS (top-{len(chunks)} by similarity)\n{ranked}"
    return profile
```

**2c. Update the caller in `score_node`:**

```python
        profile = await _profile_text(req)
        result = await _score_with_retry(req, profile)
```

(Currently it's `await _score_with_retry(req, _profile_text())` — split into two lines and pass `req` to the new async helper. **Do not modify the `return {...}` block at the end of `score_node` — the `"score_threshold": SCORE_THRESHOLD` key was added in Phase 1.B.1 and must stay.**)

- [ ] **Step 3: Run the new tests**

```bash
uv run pytest tests/pipeline/test_score_node_rag.py -v
```

Expected: 4 passed.

- [ ] **Step 4: Confirm existing score_node tests still pass**

```bash
uv run pytest tests/pipeline/ -v
```

Expected: all green. If existing tests fail because they assumed `_profile_text()` is sync, the test file needs minor updates — usually wrapping a sync `_profile_text()` call site with `asyncio.run()` or making the test async. Inspect the test names that fail and patch them; do NOT change the production code to compensate.

- [ ] **Step 5: Full suite + lint**

```bash
uv run pytest -q
uv run ruff check && uv run ruff format --check
```

Expected: 258 passed (254 + 4). Ruff clean.

- [ ] **Step 6: Commit**

```bash
git add compass/pipeline/nodes/score.py tests/pipeline/test_score_node_rag.py
git commit -m "feat(rag): score_node uses Chroma retrieval instead of full skill-inventory inject"
```

---

## Task 6: Live smoke + retro

> **PAUSE HERE before running this task.** Step 3 hits real OpenRouter on at least one JD with the new RAG-injected context. Confirm with the user before running. Cost: ~$0.01 for a single re-score, ~$0.05 for a full small-board pipeline run.

**Goal:** Prove three things tests cannot prove:
1. The Chroma index actually builds against the real `~/Documents/compass-vault/_profile/skill-inventory.md` (21 sections, not the test fixture's 3)
2. Retrieval against a real JD's skills returns sensible chunks
3. score_node with RAG produces a score consistent with the pre-RAG score (no major drift)

- [ ] **Step 1: Snapshot the vault and DBs**

```bash
cp -r ~/Documents/compass-vault/jobs ~/Documents/compass-vault/jobs.preB2.bak 2>/dev/null || true
cp ~/.compass/hitl.db ~/.compass/hitl.db.preB2.bak 2>/dev/null || true
cp ~/.compass/checkpoints.db ~/.compass/checkpoints.db.preB2.bak 2>/dev/null || true
```

- [ ] **Step 2: Build the index against the real inventory**

```bash
uv run python -m compass.rag.indexer --force
```

Expected output: `Indexed: N chunks` where N matches `grep -c '^## ' ~/Documents/compass-vault/_profile/skill-inventory.md` (currently 21).

Verify the index exists:

```bash
ls -la ~/.compass/chroma/
```

Expected: at least one `.sqlite3` file present. First run may also populate `~/.cache/torch/sentence_transformers/` with the ~90MB model.

- [ ] **Step 3: Probe retrieval against a real JD profile**

```bash
uv run python -c "
import asyncio
from compass.rag.retriever import retrieve
async def main():
    hits = await retrieve('agentic AI engineer with LangGraph MCP Python production systems', k=5)
    for h in hits:
        print(f'{h.score:.3f}  {h.skill}')
asyncio.run(main())
"
```

Expected: top-5 results include skills like Python, MCP, LangGraph, Agent Frameworks, RAG (or similar — the inventory's strongest sections). Scores should range roughly 0.4–0.7. If top-5 has irrelevant skills (e.g. "Voice", "Fine-Tuning"), the embedding model isn't separating the inventory well — flag as a quality concern but don't block.

- [ ] **Step 4: Re-score one existing JobNote with the new pipeline**

Pick any previously-approved JobNote (e.g. `~/Documents/compass-vault/jobs/2024-10-05-devco-Special_Projects_Engineer-5343fadf.md` from the Phase 1.B.1 smoke, if it still exists; otherwise pick any JobNote with a known pre-RAG match_score). Note the pre-RAG score; expect the post-RAG score to land within ±0.5.

```bash
# Re-score via the MCP score_jd tool — bypasses vault writes
uv run python -c "
import asyncio
from compass.mcp_server.server import score_jd
async def main():
    jd_text = open('/Users/<user>/Documents/compass-vault/jobs/2024-10-05-devco-Special_Projects_Engineer-5343fadf.md').read()
    result = await score_jd(jd_text)
    print(f'RAG score: {result[\"score\"][\"score\"]}')
    print(f'matched: {result[\"score\"][\"matched_skills\"]}')
    print(f'missing: {result[\"score\"][\"missing_skills\"]}')
asyncio.run(main())
"
```

Expected: score within 2.5–3.5 (pre-RAG was 3.0). If the new score is wildly different (e.g. 0.5 or 5.0), the retrieval context is missing something critical — investigate the retrieved chunks vs the full inventory before proceeding.

- [ ] **Step 5: Run a small live pipeline**

```bash
MAX_JOBS_PER_RUN=5 \
  GREENHOUSE_BOARDS=anthropic \
  LEVER_COMPANIES= \
  ASHBY_BOARDS=botco \
  uv run python -m compass.pipeline.graph
```

Expected output: pipeline completes with no `Deserializing unregistered type` warnings (Task 1 closes them) and no abnormal score drift. Inspect `_meta/agent-log.md` for any errors related to RAG.

- [ ] **Step 6: Verify checkpoint DB stays bounded**

After Step 5 + any resume action:

```bash
sqlite3 ~/.compass/checkpoints.db "SELECT COUNT(DISTINCT thread_id) FROM checkpoints;"
```

Expected: count equals the number of still-pending threads (not the total number of threads ever paused). Task 2's purge keeps it bounded.

- [ ] **Step 7: Tag the phase**

```bash
git tag phase-1b2-rag
```

- [ ] **Step 8: Cleanup or keep backups**

If everything looks healthy:

```bash
rm -rf ~/Documents/compass-vault/jobs.preB2.bak ~/.compass/hitl.db.preB2.bak ~/.compass/checkpoints.db.preB2.bak
```

If anything looks wrong, restore:

```bash
rm -rf ~/Documents/compass-vault/jobs && mv ~/Documents/compass-vault/jobs.preB2.bak ~/Documents/compass-vault/jobs
mv ~/.compass/hitl.db.preB2.bak ~/.compass/hitl.db
mv ~/.compass/checkpoints.db.preB2.bak ~/.compass/checkpoints.db
```

---

## Definition of Done

**Code & tests**
- 258 tests passing (`uv run pytest -q`)
- Ruff clean (`uv run ruff check && uv run ruff format --check`)
- No module-level captures of `CHROMA_PATH`, `EMBEDDING_MODEL`, `SKILL_INVENTORY_PATH` — every reference is inside a function body
- `_build_checkpoint_serde` is called inside the `async with AsyncSqliteSaver(...)` block in BOTH `run_pipeline` and `resume_pending` (carry forward the Phase 1.A discipline)
- `_purge_thread_checkpoints` runs only after `mark_resolved` succeeds, and inside the open checkpointer context

**Behaviour (verified empirically in Task 6)**
- `python -m compass.rag.indexer --force` indexes all 21 sections of the real inventory
- Retrieval against a real JD-skills query surfaces sensible top-5 chunks
- A re-score of one existing JobNote produces a score within ±0.5 of the pre-RAG score
- A full small-board pipeline run completes with no `Deserializing unregistered type` warnings
- `checkpoints.db` size stays bounded — resolved threads' rows are deleted

**Docs**
- Plan file's "What's deferred" table updated if any new items surface
- Phase 1.B.2 retrospective (optional but recommended) saved to `docs/PHASE_1B2_COMPLETE.md`

---

## What's deferred (and to which sub-phase)

| Concern | Severity | Phase | Why deferred |
|---|---|---|---|
| 30-JD eval harness comparing pre-RAG vs post-RAG score MAE | Portfolio claim | **2.A** | Needs labeled dataset; out of 1.B.2 scope |
| Modal cron + Langfuse callback fix + URL-dedup for filtered-jobs | Required for "no babysitting" | **1.B.3** | Spec phase ordering |
| I4 double-resume race claim_pending (Phase 1.B.1 deferred item) | Important | **1.B.3** | Cron is the real-world race trigger |
| Embedding-model upgrade (e.g. `nomic-embed-text` for higher quality) | Quality polish | **2.B** | `all-MiniLM-L6-v2` is good enough for v1; cost-free swap later |
| Skill-inventory re-indexing on Obsidian write (file-watch) | UX | **3+** | Manual `python -m compass.rag.indexer` is fine for solo use |
| Per-chunk metadata enrichment (level, category, calibration) | Quality | **2.B** | Current metadata = {skill, source} suffices for top-k retrieval |

---

## Critical lessons to carry forward (from Phases 0 + 1.A + 1.B.1)

1. **Tests check shape; only adversarial real-data inspection catches data-correctness bugs.** Task 6 is non-optional — do not declare 1.B.2 done from green CI alone.
2. **Module-level config captures freeze at import time** and silently break test fixtures. Always late-bind inside function bodies (`CHROMA_PATH`, `EMBEDDING_MODEL`, `SKILL_INVENTORY_PATH`, `HITL_CHECKPOINT_DB`).
3. **A graph compiled without a checkpointer silently breaks `interrupt()`** — apply the same discipline to the new serde: `_build_checkpoint_serde` must be called INSIDE the `async with` block, NEVER stashed in a module-level constant.
4. **JSON-serializability of MCP return shapes.** Phase 1.A bug #11: `date` objects don't serialize through FastMCP. Same applies to RAG retrieval — if any future MCP tool returns `RetrievedChunk`, convert to a plain dict first.
5. **`or`-fallback against falsy values is a recurring trap.** Phase 1.B.1 caught `state.get("score_threshold") or SCORE_THRESHOLD` would mis-fallback on 0.0. Same pattern applies anywhere we read state with a defensible-falsy default — use `is None` checks instead.
6. **The audit-trail/state-store/JobNote consistency triad is load-bearing.** Phase 1.B.1's C1 silent divergence (state_store said "approved", JobNote said "auto_rejected") was caught only by adversarial cross-checking. Apply the same rigor here: after any pipeline change, sample real JobNotes and confirm `match_score`, `matched_skills`, `missing_skills` are consistent with what RAG retrieved.

---

## Plan Review Loop

Before executing this plan, dispatch a single plan-document-reviewer subagent with:
- Path to this plan: `docs/superpowers/plans/2026-05-19-compass-phase-1b2-rag.md`
- Path to spec: `docs/superpowers/specs/2026-05-17-compass-mvp-to-portfolio-ship-design.md`
- Phase scope reference: this plan's "Closes these deferred items" section

If the reviewer flags issues, fix in place and re-dispatch. Cap at 3 iterations.

---

## Execution handoff

Once approved, two options:

1. **Subagent-Driven (recommended)** — Use `superpowers:subagent-driven-development`. Fresh implementer per Task 1–5, combined spec+quality reviewer between tasks, hard pause before Task 6 (live LLM + real vault). Same pattern that worked in Phase 1.B.1.

2. **Inline Execution** — Use `superpowers:executing-plans`. Single session, batch through Tasks 1–5 with checkpoints, hard pause before Task 6.

Phase 1.B.1 used Subagent-Driven and it caught 5+ real bugs across tasks. Keep the pattern.
