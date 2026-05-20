# Architecture Amendments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Amend the Compass pipeline to add a RAG retrieval layer, a properly-designed HiTL timeout mechanism, and parallel job processing — closing the three identified portfolio gaps before implementation begins.

**Architecture:** (1) A Chroma vector store indexes vault skill notes; `score_node` retrieves relevant profile context semantically instead of reading full markdown. (2) A SQLite state table tracks pending HiTL interrupts with timestamps; a Modal scheduled function polls and auto-resumes timed-out jobs. (3) `run_pipeline()` fans out one graph invocation per job via `asyncio.gather` with a semaphore concurrency cap, rather than processing jobs sequentially.

**Tech Stack:** ChromaDB, sentence-transformers (all-MiniLM-L6-v2), SQLite (aiosqlite), LangGraph Send API awareness, asyncio, Modal cron

---

## File Map

### New files
| File | Responsibility |
|---|---|
| `compass/rag/__init__.py` | Package marker |
| `compass/rag/indexer.py` | Build + update Chroma index from vault `skills/` and `_profile/skill-inventory.md` |
| `compass/rag/retriever.py` | Semantic retrieval — given extracted JD skills, return matching profile context chunks |
| `compass/hitl/state_store.py` | SQLite table for pending HiTL interrupts — thread_id, job_url, timestamp, status |
| `compass/hitl/timeout_checker.py` | Modal function: polls state_store, resumes timed-out graph checkpoints |
| `compass/hitl/__init__.py` | Package marker |
| `tests/test_rag.py` | Tests for indexer + retriever |
| `tests/test_hitl_state.py` | Tests for state_store CRUD |

### Modified files
| File | Change |
|---|---|
| `compass/config.py` | Add `CHROMA_PATH`, `HITL_STATE_DB`, `MAX_CONCURRENT_JOBS`, `EMBEDDING_MODEL` |
| `compass/pipeline/state.py` | Add `retrieved_context: list[str]` to `CompassState` |
| `compass/pipeline/nodes/score.py` | Implement: retrieve context via RAG, then score with context in prompt |
| `compass/pipeline/nodes/hitl.py` | Implement: write to state_store on interrupt, read thread_id from checkpointer |
| `compass/pipeline/graph.py` | Update `run_pipeline()` for parallel invocations; add `SqliteSaver` checkpointer |
| `compass/evals/runner.py` | Add retrieval quality metrics alongside score MAE |
| `pyproject.toml` | Add `chromadb`, `sentence-transformers`, `aiosqlite`, `modal` |

---

## Task 1: Dependencies + Config

**Files:**
- Modify: `pyproject.toml`
- Modify: `compass/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add new dependencies to pyproject.toml**

```toml
# Add to [project] dependencies:
"chromadb>=0.5",
"sentence-transformers>=3.0",
"aiosqlite>=0.20",
"modal>=0.67",
"langgraph-checkpoint-sqlite>=2.0",  # AsyncSqliteSaver ships separately from langgraph
```

- [ ] **Step 2: Add new config values to compass/config.py**

```python
# ── RAG ───────────────────────────────────────────────────────────────────────
CHROMA_PATH: Path = Path(os.getenv("CHROMA_PATH", str(Path.home() / ".compass" / "chroma")))
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# ── HiTL state ────────────────────────────────────────────────────────────────
HITL_STATE_DB: Path = Path(os.getenv("HITL_STATE_DB", str(Path.home() / ".compass" / "hitl.db")))
HITL_TIMEOUT_HOURS: int = int(os.getenv("HITL_TIMEOUT_HOURS", "4"))

# ── Parallelism ───────────────────────────────────────────────────────────────
MAX_CONCURRENT_JOBS: int = int(os.getenv("MAX_CONCURRENT_JOBS", "5"))
```

- [ ] **Step 3: Add to .env.example**

```bash
# RAG
CHROMA_PATH=~/.compass/chroma
EMBEDDING_MODEL=all-MiniLM-L6-v2

# HiTL
HITL_STATE_DB=~/.compass/hitl.db
HITL_TIMEOUT_HOURS=4

# Parallelism
MAX_CONCURRENT_JOBS=5
```

- [ ] **Step 4: Run uv sync to install**

```bash
cd ~/Documents/compass
uv sync
```

Expected: resolves without errors, chromadb + sentence-transformers installed.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml compass/config.py .env.example
git commit -m "chore: add rag, hitl, parallel deps and config"
```

---

## Task 2: RAG Indexer

Indexes vault skill notes into Chroma. Run once to seed, then incrementally on vault writes.

**Files:**
- Create: `compass/rag/__init__.py`
- Create: `compass/rag/indexer.py`
- Test: `tests/test_rag.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rag.py
import pytest
from pathlib import Path
from compass.rag.indexer import build_index, get_collection

@pytest.fixture
def tmp_vault(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "LangGraph.md").write_text(
        "---\nskill: LangGraph\nmy_level: learning\n---\n"
        "LangGraph is a library for building stateful multi-step agent workflows as directed graphs."
    )
    (skills_dir / "Snowflake.md").write_text(
        "---\nskill: Snowflake\nmy_level: proficient\n---\n"
        "Snowflake is a cloud data warehouse used in production in a prior role for log analysis pipelines."
    )
    return tmp_path

def test_build_index_creates_collection(tmp_vault, tmp_path):
    chroma_path = tmp_path / "chroma"
    collection = build_index(vault_path=tmp_vault, chroma_path=chroma_path)
    assert collection.count() == 2

def test_build_index_is_idempotent(tmp_vault, tmp_path):
    chroma_path = tmp_path / "chroma"
    build_index(vault_path=tmp_vault, chroma_path=chroma_path)
    collection = build_index(vault_path=tmp_vault, chroma_path=chroma_path)
    assert collection.count() == 2  # not 4
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_rag.py::test_build_index_creates_collection -v
```

Expected: `ModuleNotFoundError: compass.rag.indexer`

- [ ] **Step 3: Create `compass/rag/__init__.py`** (empty)

- [ ] **Step 4: Implement `compass/rag/indexer.py`**

```python
"""
RAG indexer — builds and updates the Chroma vector index from vault skill notes.

Documents indexed:
  - skills/*.md  (one doc per skill note, includes frontmatter + body)
  - _profile/skill-inventory.md  (chunked by table row)

Run: uv run python -m compass.rag.indexer
"""
import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path
import frontmatter

from compass.config import CHROMA_PATH, VAULT_PATH, EMBEDDING_MODEL

COLLECTION_NAME = "compass_profile"


def get_collection(chroma_path: Path = CHROMA_PATH) -> chromadb.Collection:
    """Return the Chroma collection, creating it if it doesn't exist."""
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )
    return client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=ef)


def _load_skill_docs(vault_path: Path) -> list[tuple[str, str, dict]]:
    """Load all skills/*.md files. Returns (id, text, metadata) tuples."""
    docs = []
    skills_dir = vault_path / "skills"
    if not skills_dir.exists():
        return docs
    for path in skills_dir.glob("*.md"):
        post = frontmatter.load(str(path))
        skill_name = post.metadata.get("skill", path.stem)
        level = post.metadata.get("my_level", "unknown")
        text = f"Skill: {skill_name}\nLevel: {level}\n\n{post.content}".strip()
        docs.append((f"skill::{path.stem}", text, {"skill": skill_name, "level": level}))
    return docs


def build_index(
    vault_path: Path = VAULT_PATH,
    chroma_path: Path = CHROMA_PATH,
) -> chromadb.Collection:
    """
    Build or refresh the Chroma index from vault skill notes.
    Upserts all documents — safe to run repeatedly.
    """
    collection = get_collection(chroma_path)
    docs = _load_skill_docs(vault_path)
    if not docs:
        return collection

    ids, texts, metadatas = zip(*docs)
    collection.upsert(ids=list(ids), documents=list(texts), metadatas=list(metadatas))
    return collection


if __name__ == "__main__":
    col = build_index()
    print(f"Indexed {col.count()} skill documents into {CHROMA_PATH}")
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_rag.py -v
```

Expected: both pass.

- [ ] **Step 6: Commit**

```bash
git add compass/rag/ tests/test_rag.py
git commit -m "feat: rag indexer — build chroma index from vault skill notes"
```

---

## Task 3: RAG Retriever

Given extracted JD skills, retrieves the most relevant profile context chunks from Chroma.

**Files:**
- Create: `compass/rag/retriever.py`
- Test: `tests/test_rag.py` (extend)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_rag.py`:

```python
from compass.rag.retriever import retrieve_profile_context

def test_retriever_returns_relevant_skills(tmp_vault, tmp_path):
    chroma_path = tmp_path / "chroma"
    build_index(vault_path=tmp_vault, chroma_path=chroma_path)

    results = retrieve_profile_context(
        required_skills=["LangGraph", "stateful agents"],
        top_k=2,
        chroma_path=chroma_path,
    )
    assert len(results) > 0
    # LangGraph note should be top result for a LangGraph query
    assert any("LangGraph" in r for r in results)

def test_retriever_empty_index_returns_empty(tmp_path):
    chroma_path = tmp_path / "empty_chroma"
    results = retrieve_profile_context(
        required_skills=["Python"],
        top_k=3,
        chroma_path=chroma_path,
    )
    assert results == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_rag.py::test_retriever_returns_relevant_skills -v
```

Expected: `ModuleNotFoundError: compass.rag.retriever`

- [ ] **Step 3: Implement `compass/rag/retriever.py`**

```python
"""
RAG retriever — semantic retrieval of profile context for a given JD's required skills.

Called by score_node before the scoring LLM call.
Returns a list of text chunks (skill note snippets) most relevant to the JD's requirements.
"""
import chromadb
from pathlib import Path

from compass.config import CHROMA_PATH
from compass.rag.indexer import get_collection


def retrieve_profile_context(
    required_skills: list[str],
    top_k: int = 5,
    chroma_path: Path = CHROMA_PATH,
) -> list[str]:
    """
    Given a list of required skills from a JD, retrieve the most relevant
    profile context chunks from the Chroma index.

    Returns empty list if the index doesn't exist yet — score_node falls
    back to full markdown read in that case.
    """
    try:
        collection = get_collection(chroma_path)
        if collection.count() == 0:
            return []
    except Exception:
        return []

    # Join skills into a natural query so the embedding captures the full context
    query = "Candidate experience with: " + ", ".join(required_skills)

    results = collection.query(
        query_texts=[query],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    docs = results["documents"][0] if results["documents"] else []
    distances = results["distances"][0] if results["distances"] else []

    # Filter out low-relevance results (distance > 1.5 in L2 space = poor match)
    return [doc for doc, dist in zip(docs, distances) if dist < 1.5]
```

- [ ] **Step 4: Run all RAG tests**

```bash
uv run pytest tests/test_rag.py -v
```

Expected: all 4 pass.

- [ ] **Step 5: Commit**

```bash
git add compass/rag/retriever.py tests/test_rag.py
git commit -m "feat: rag retriever — semantic profile context retrieval for score_node"
```

---

## Task 4: Wire RAG into score_node

`score_node` now retrieves relevant profile context before scoring, instead of reading the full skill-inventory markdown.

**Files:**
- Modify: `compass/pipeline/state.py`
- Modify: `compass/pipeline/nodes/score.py`

- [ ] **Step 1: Add `retrieved_context` to CompassState**

In `compass/pipeline/state.py`, add to `CompassState`:

```python
# After score_result field:
retrieved_context: list[str]  # Chunks from RAG retrieval — populated by score_node
```

And update the initial state in `graph.py`'s `run_pipeline()`:
```python
"retrieved_context": [],
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_rag.py` (or create `tests/test_pipeline_score.py`):

```python
# tests/test_pipeline_score.py
import pytest
from unittest.mock import AsyncMock, patch
from compass.pipeline.state import CompassState, RawJob, JobRequirements
from compass.pipeline.nodes.score import score_node
from datetime import date

@pytest.fixture
def minimal_state():
    return CompassState(
        raw_jobs=[],
        current_job=RawJob(
            company="Sierra AI",
            title="AI Engineer",
            url="https://example.com/job/1",
            source="greenhouse",
            description="Build LLM agents using LangGraph and Pydantic AI.",
        ),
        extracted_requirements=JobRequirements(
            required_skills=["LangGraph", "Pydantic AI", "Python"],
            nice_to_have_skills=["Langfuse"],
            seniority="mid",
            remote_policy="remote",
            summary="Build production LLM agents.",
        ),
        score_result=None,
        retrieved_context=[],
        human_approved=None,
        human_feedback=None,
        vault_written=False,
        jobs_processed=0,
        jobs_written=0,
        errors=[],
    )

@pytest.mark.asyncio
async def test_score_node_populates_retrieved_context(minimal_state):
    """score_node must populate retrieved_context before calling the LLM."""
    with patch("compass.pipeline.nodes.score.retrieve_profile_context") as mock_retrieve, \
         patch("compass.pipeline.nodes.score.run_score_llm") as mock_llm:
        mock_retrieve.return_value = ["LangGraph: learning level. Used in career coach project."]
        mock_llm.return_value = AsyncMock(score=4.0, reasoning="Good match", matched_skills=[], missing_skills=[], tailoring_notes="")
        result = await score_node(minimal_state)
    mock_retrieve.assert_called_once()
    assert len(result["retrieved_context"]) > 0

@pytest.mark.asyncio
async def test_score_node_handles_empty_retrieval(minimal_state):
    """score_node must not crash if RAG returns no results."""
    with patch("compass.pipeline.nodes.score.retrieve_profile_context", return_value=[]), \
         patch("compass.pipeline.nodes.score.run_score_llm") as mock_llm:
        mock_llm.return_value = AsyncMock(score=3.0, reasoning="Weak match", matched_skills=[], missing_skills=[], tailoring_notes="")
        result = await score_node(minimal_state)
    assert "score_result" in result
```

- [ ] **Step 3: Run to confirm failure**

```bash
uv run pytest tests/test_pipeline_score.py -v
```

Expected: `NotImplementedError: score_node not yet implemented`

- [ ] **Step 4: Implement `compass/pipeline/nodes/score.py`**

```python
"""
score_node — scores a job against the candidate profile.

Flow:
  1. Retrieve relevant profile context from Chroma (RAG)
  2. Read vault profile as fallback if RAG returns nothing
  3. Call LLM with JD requirements + retrieved context
  4. Return JobScore with score, reasoning, matched/missing skills

All LLM calls are traced via Langfuse callbacks passed in config.
"""
from pathlib import Path
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from compass.pipeline.state import CompassState, JobScore, JobRequirements
from compass.rag.retriever import retrieve_profile_context
from compass.config import VAULT_PATH, COMPASS_MODEL, OPENROUTER_API_KEY


def _read_skill_inventory_fallback(vault_path: Path = VAULT_PATH) -> str:
    """Fallback: read full skill-inventory.md if RAG returns nothing."""
    path = vault_path / "_profile" / "skill-inventory.md"
    if path.exists():
        return path.read_text()
    return "No skill inventory found."


def _build_score_prompt(
    requirements: JobRequirements,
    context_chunks: list[str],
    fallback_profile: str,
) -> str:
    if context_chunks:
        profile_section = "CANDIDATE PROFILE (relevant excerpts retrieved semantically):\n" + \
                          "\n---\n".join(context_chunks)
    else:
        profile_section = "CANDIDATE PROFILE (full skill inventory):\n" + fallback_profile

    return f"""You are evaluating a candidate's fit for a job.

{profile_section}

JOB REQUIREMENTS:
Required skills: {', '.join(requirements.required_skills)}
Nice to have: {', '.join(requirements.nice_to_have_skills)}
Seniority: {requirements.seniority}
Remote policy: {requirements.remote_policy}
Summary: {requirements.summary}

Score the candidate's fit from 0.0 to 5.0:
- 5.0: all required skills at proficient+, seniority matches, domain fits
- 4.0-4.9: 1-2 gaps at learning level, everything else strong
- 3.5-3.9: 2-3 gaps, at least one P1, but core skills present
- 3.0-3.4: multiple gaps, borderline
- below 3.0: significant gaps

Return a JSON object matching the JobScore schema."""


_score_agent = Agent(
    OpenAIModel(
        COMPASS_MODEL,
        provider=OpenAIProvider(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        ),
    ),
    result_type=JobScore,
    system_prompt="You are a precise job-fit evaluator. Score honestly — inflated scores waste the candidate's time.",
)


async def run_score_llm(prompt: str) -> JobScore:
    """Thin wrapper so tests can mock the LLM call cleanly."""
    result = await _score_agent.run(prompt)
    return result.data


async def score_node(state: CompassState) -> dict:
    """Score the current job against the candidate profile via RAG retrieval + LLM."""
    job = state["current_job"]
    requirements = state.get("extracted_requirements")

    if not requirements:
        return {"errors": state["errors"] + [f"score_node: no requirements for {job.url}"]}

    # Step 1: RAG retrieval
    context_chunks = retrieve_profile_context(
        required_skills=requirements.required_skills + requirements.nice_to_have_skills,
        top_k=6,
    )

    # Step 2: Fallback if index empty
    fallback = _read_skill_inventory_fallback() if not context_chunks else ""

    # Step 3: Score
    prompt = _build_score_prompt(requirements, context_chunks, fallback)
    try:
        score_result = await run_score_llm(prompt)
    except Exception as e:
        return {"errors": state["errors"] + [f"score_node LLM error: {e}"]}

    return {
        "retrieved_context": context_chunks,
        "score_result": score_result,
    }
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_pipeline_score.py -v
```

Expected: both pass.

- [ ] **Step 6: Commit**

```bash
git add compass/pipeline/state.py compass/pipeline/nodes/score.py tests/test_pipeline_score.py
git commit -m "feat: score_node — rag retrieval + pydantic-ai scoring"
```

---

## Task 5: HiTL State Store

A SQLite table that persists pending HiTL interrupts with timestamps. This is what makes the timeout mechanism real — without it, `interrupt()` just waits forever.

**Files:**
- Create: `compass/hitl/__init__.py`
- Create: `compass/hitl/state_store.py`
- Test: `tests/test_hitl_state.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_hitl_state.py
import pytest
import asyncio
from datetime import datetime, timedelta
from compass.hitl.state_store import HiTLStateStore, InterruptRecord

@pytest.fixture
async def store(tmp_path):
    db_path = tmp_path / "hitl.db"
    s = HiTLStateStore(db_path=db_path)
    await s.init()
    return s

@pytest.mark.asyncio
async def test_insert_and_retrieve(store):
    await store.insert(thread_id="abc123", job_url="https://example.com/job/1")
    record = await store.get("abc123")
    assert record is not None
    assert record.thread_id == "abc123"
    assert record.status == "pending"

@pytest.mark.asyncio
async def test_mark_resolved(store):
    await store.insert(thread_id="abc123", job_url="https://example.com/job/1")
    await store.resolve("abc123", approved=True)
    record = await store.get("abc123")
    assert record.status == "approved"

@pytest.mark.asyncio
async def test_get_timed_out(store):
    await store.insert(thread_id="old_thread", job_url="https://example.com/job/2")
    # Manually backdate the created_at to simulate timeout
    import aiosqlite
    async with aiosqlite.connect(store.db_path) as db:
        past = (datetime.utcnow() - timedelta(hours=5)).isoformat()
        await db.execute(
            "UPDATE hitl_interrupts SET created_at = ? WHERE thread_id = ?",
            (past, "old_thread"),
        )
        await db.commit()

    timed_out = await store.get_timed_out(timeout_hours=4)
    assert len(timed_out) == 1
    assert timed_out[0].thread_id == "old_thread"
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_hitl_state.py -v
```

Expected: `ModuleNotFoundError: compass.hitl.state_store`

- [ ] **Step 3: Create `compass/hitl/__init__.py`** (empty)

- [ ] **Step 4: Implement `compass/hitl/state_store.py`**

```python
"""
HiTL state store — SQLite table tracking pending LangGraph interrupt checkpoints.

Schema:
  thread_id   TEXT PRIMARY KEY  — LangGraph thread ID (checkpointer key)
  job_url     TEXT              — the job being reviewed (for display)
  created_at  TEXT              — ISO timestamp when interrupt was created
  status      TEXT              — pending | approved | rejected | timed_out

The timeout_checker (Modal cron) queries get_timed_out() every 30 minutes and
resumes any pending threads that have exceeded HITL_TIMEOUT_HOURS.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import aiosqlite

from compass.config import HITL_STATE_DB


@dataclass
class InterruptRecord:
    thread_id: str
    job_url: str
    created_at: datetime
    status: str  # pending | approved | rejected | timed_out


class HiTLStateStore:
    def __init__(self, db_path: Path = HITL_STATE_DB):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        """Create the table if it doesn't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS hitl_interrupts (
                    thread_id  TEXT PRIMARY KEY,
                    job_url    TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status     TEXT NOT NULL DEFAULT 'pending'
                )
            """)
            await db.commit()

    async def insert(self, thread_id: str, job_url: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO hitl_interrupts (thread_id, job_url, created_at, status) VALUES (?, ?, ?, 'pending')",
                (thread_id, job_url, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def resolve(self, thread_id: str, approved: bool) -> None:
        status = "approved" if approved else "rejected"
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE hitl_interrupts SET status = ? WHERE thread_id = ?",
                (status, thread_id),
            )
            await db.commit()

    async def get(self, thread_id: str) -> Optional[InterruptRecord]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT thread_id, job_url, created_at, status FROM hitl_interrupts WHERE thread_id = ?",
                (thread_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return InterruptRecord(
                    thread_id=row[0],
                    job_url=row[1],
                    created_at=datetime.fromisoformat(row[2]),
                    status=row[3],
                )

    async def get_timed_out(self, timeout_hours: int) -> list[InterruptRecord]:
        """Return all pending interrupts older than timeout_hours."""
        cutoff = (datetime.utcnow() - timedelta(hours=timeout_hours)).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT thread_id, job_url, created_at, status FROM hitl_interrupts "
                "WHERE status = 'pending' AND created_at < ?",
                (cutoff,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    InterruptRecord(
                        thread_id=r[0], job_url=r[1],
                        created_at=datetime.fromisoformat(r[2]), status=r[3],
                    )
                    for r in rows
                ]
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_hitl_state.py -v
```

Expected: all 3 pass.

- [ ] **Step 6: Commit**

```bash
git add compass/hitl/ tests/test_hitl_state.py
git commit -m "feat: hitl state store — sqlite tracking for pending graph interrupts"
```

---

## Task 6: HiTL Node + Timeout Checker

Implement `hitl_node` using the state store, and the Modal timeout checker that auto-resumes timed-out threads.

**Files:**
- Modify: `compass/pipeline/nodes/hitl.py`
- Create: `compass/hitl/timeout_checker.py`
- Modify: `compass/pipeline/graph.py` (add SqliteSaver checkpointer)

- [ ] **Step 1: Add SqliteSaver checkpointer to graph.py**

In `compass/pipeline/graph.py`, update `build_graph()` and `run_pipeline()`:

```python
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from compass.config import HITL_STATE_DB

def build_graph(checkpointer=None) -> StateGraph:
    builder = StateGraph(CompassState)
    # ... (existing nodes + edges unchanged) ...
    return builder.compile(checkpointer=checkpointer)

# NOTE: Remove the module-level `graph = build_graph()` line that currently exists
# at the bottom of graph.py. Compiling at import time without a checkpointer means
# interrupt() will fail silently — the graph has nowhere to persist state.
# Instead, compile inside run_pipeline() where the checkpointer is available.

async def run_pipeline(raw_jobs=None) -> CompassState:
    # ... (existing scraper logic unchanged) ...

    # Checkpointer enables interrupt() to persist state between calls
    HITL_STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(HITL_STATE_DB)) as checkpointer:
        compiled_graph = build_graph(checkpointer=checkpointer)
        # ... invoke as before, but pass thread_id in config ...
        import uuid
        thread_id = str(uuid.uuid4())
        result = await compiled_graph.ainvoke(
            initial_state,
            config={
                "callbacks": [langfuse_handler],
                "configurable": {"thread_id": thread_id},
            },
        )
    return result
```

- [ ] **Step 2: Implement `compass/pipeline/nodes/hitl.py`**

```python
"""
hitl_node — pauses the graph for human review using LangGraph interrupt().

What happens:
  1. Records the interrupt in HiTLStateStore (actual LangGraph thread_id + timestamp)
  2. Calls interrupt() — graph checkpoints here and suspends
  3. When resumed via Command(resume={...}), interrupt() returns the resume value
  4. The timeout_checker resumes timed-out threads with Command(resume={"approved": False})

Key: interrupt() does NOT return the value passed into it — it raises GraphInterrupt
and suspends. When the graph is later resumed, interrupt() returns whatever was
passed to Command(resume=...). The timer for the timeout lives in timeout_checker.py,
not here.
"""
from langgraph.types import interrupt
from langchain_core.runnables import RunnableConfig
from compass.pipeline.state import CompassState
from compass.hitl.state_store import HiTLStateStore


_store = HiTLStateStore()


async def hitl_node(state: CompassState, config: RunnableConfig) -> dict:
    """Pause for human review. Resumes via the timeout checker or human action."""
    job = state["current_job"]
    score = state.get("score_result")

    # Get the actual LangGraph thread_id from config — this is what the checkpointer
    # uses as a key. We must store this (not job.url) so the timeout_checker can
    # resume the correct checkpoint.
    thread_id = config.get("configurable", {}).get("thread_id", job.url)

    await _store.init()
    await _store.insert(thread_id=thread_id, job_url=job.url)

    # interrupt() suspends the graph here. When resumed via Command(resume=value),
    # that value is returned by interrupt().
    human_response = interrupt({
        "job": job.model_dump(),
        "score": score.model_dump() if score else None,
        "message": f"Review {job.company} — {job.title} (score: {score.score if score else 'N/A'}). Approve?",
    })

    # human_response is whatever was passed to Command(resume=...) on resume
    approved = bool(human_response.get("approved", False)) if isinstance(human_response, dict) else False
    feedback = human_response.get("feedback", "") if isinstance(human_response, dict) else ""

    await _store.resolve(thread_id=thread_id, approved=approved)

    return {
        "human_approved": approved,
        "human_feedback": feedback,
    }
```

- [ ] **Step 3: Implement `compass/hitl/timeout_checker.py`**

```python
"""
HiTL timeout checker — Modal cron that resumes timed-out graph interrupts.

Runs every 30 minutes. Finds all pending HiTL interrupts older than
HITL_TIMEOUT_HOURS and resumes them with human_approved=False.

This is what makes the "4-hour timeout" actually work — LangGraph interrupt()
is a synchronous pause, not a timer. The timer lives here, externally.

Deploy: modal deploy compass/hitl/timeout_checker.py
"""
import asyncio
import modal
from langgraph.types import Command
from compass.hitl.state_store import HiTLStateStore
from compass.config import HITL_TIMEOUT_HOURS, HITL_STATE_DB

app = modal.App("compass-hitl-checker")

image = modal.Image.debian_slim().pip_install(
    "langgraph>=0.2", "aiosqlite>=0.20", "langchain-anthropic>=0.3"
)


@app.function(
    image=image,
    schedule=modal.Period(minutes=30),
    secrets=[modal.Secret.from_name("compass-secrets")],
)
async def check_and_resume_timed_out():
    """Find timed-out HiTL interrupts and resume them as rejected."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from compass.pipeline.graph import build_graph

    store = HiTLStateStore(db_path=HITL_STATE_DB)
    await store.init()
    timed_out = await store.get_timed_out(timeout_hours=HITL_TIMEOUT_HOURS)

    if not timed_out:
        print("No timed-out interrupts.")
        return

    async with AsyncSqliteSaver.from_conn_string(str(HITL_STATE_DB)) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        for record in timed_out:
            print(f"Resuming timed-out thread: {record.thread_id} ({record.job_url})")
            try:
                # Must resume via Command(resume=...) — this is what interrupt() returns
                # when the graph is continued. Passing a plain state dict would restart
                # from scratch rather than resuming the paused interrupt.
                await graph.ainvoke(
                    Command(resume={"approved": False, "feedback": "auto-rejected: timeout"}),
                    config={"configurable": {"thread_id": record.thread_id}},
                )
                await store.resolve(thread_id=record.thread_id, approved=False)
            except Exception as e:
                print(f"Error resuming {record.thread_id}: {e}")
                # Mark as resolved so it doesn't retry on every subsequent cron tick
                await store.resolve(thread_id=record.thread_id, approved=False)


if __name__ == "__main__":
    asyncio.run(check_and_resume_timed_out())
```

- [ ] **Step 4: Run existing tests to confirm nothing broke**

```bash
uv run pytest tests/ -v
```

Expected: all existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add compass/pipeline/nodes/hitl.py compass/hitl/timeout_checker.py compass/pipeline/graph.py
git commit -m "feat: hitl node + modal timeout checker — externally-enforced 4hr timeout"
```

---

## Task 7: Parallel Job Processing

Replace sequential single-job processing with concurrent graph invocations, one per job, bounded by a semaphore.

**Files:**
- Modify: `compass/pipeline/graph.py`

The key insight: the graph itself stays single-job (clean, debuggable). Parallelism lives in the runner — `asyncio.gather` launches N graph invocations concurrently, each with its own state and thread_id.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_parallel.py
import pytest
from unittest.mock import AsyncMock, patch
from compass.pipeline.graph import run_pipeline
from compass.pipeline.state import RawJob
from datetime import date

def make_job(n: int) -> RawJob:
    return RawJob(
        company=f"Company{n}",
        title="AI Engineer",
        url=f"https://example.com/job/{n}",
        source="greenhouse",
        description=f"Build LLM agents. Job {n}.",
    )

@pytest.mark.asyncio
async def test_run_pipeline_processes_multiple_jobs(tmp_path, monkeypatch):
    """Pipeline must attempt to process all jobs, not just the first one."""
    # Point HITL_STATE_DB to a tmp file so the test doesn't touch ~/.compass
    monkeypatch.setattr("compass.pipeline.graph.HITL_STATE_DB", tmp_path / "hitl.db")

    jobs = [make_job(i) for i in range(3)]
    processed = []

    async def fake_invoke(state, config):
        processed.append(state["current_job"].url)
        return {**state, "vault_written": True, "jobs_processed": 1, "jobs_written": 1, "errors": []}

    mock_graph = AsyncMock()
    mock_graph.ainvoke = fake_invoke

    with patch("compass.pipeline.graph.build_graph", return_value=mock_graph), \
         patch("compass.pipeline.graph.AsyncSqliteSaver") as mock_saver:
        # Make the checkpointer context manager a no-op
        mock_saver.from_conn_string.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_saver.from_conn_string.return_value.__aexit__ = AsyncMock(return_value=False)
        await run_pipeline(raw_jobs=jobs)

    assert len(processed) == 3
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_parallel.py -v
```

Expected: fails — current `run_pipeline` processes jobs sequentially or not at all.

- [ ] **Step 3: Rewrite `run_pipeline()` in graph.py**

Replace the existing `run_pipeline` function:

```python
async def run_pipeline(raw_jobs: list[RawJob] | None = None) -> dict:
    """
    Run the Compass pipeline on a list of jobs.
    Each job gets its own graph invocation and thread_id.
    Concurrency is bounded by MAX_CONCURRENT_JOBS to avoid rate limiting.
    """
    import asyncio
    import uuid
    from compass.scrapers.greenhouse import scrape_greenhouse_many
    from compass.scrapers.lever import scrape_lever_many
    from compass.scrapers.ashby import scrape_ashby_many
    from compass.config import (
        GREENHOUSE_BOARDS, LEVER_COMPANIES, ASHBY_BOARDS,
        MAX_CONCURRENT_JOBS, HITL_STATE_DB,
    )

    if raw_jobs is None:
        gh, lv, ash = await asyncio.gather(
            scrape_greenhouse_many(GREENHOUSE_BOARDS),
            scrape_lever_many(LEVER_COMPANIES),
            scrape_ashby_many(ASHBY_BOARDS),
        )
        raw_jobs = gh + lv + ash

    langfuse_handler = CallbackHandler()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

    # Open ONE checkpointer for the whole run — concurrent SQLite writers to the
    # same file cause "database is locked" errors. The semaphore limits concurrency;
    # the shared checkpointer serializes writes safely.
    HITL_STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(HITL_STATE_DB)) as checkpointer:
        compiled = build_graph(checkpointer=checkpointer)

        async def process_one(job: RawJob) -> dict:
            async with semaphore:
                thread_id = str(uuid.uuid4())
                initial: CompassState = {
                    "raw_jobs": [job],
                    "current_job": job,
                    "extracted_requirements": None,
                    "score_result": None,
                    "retrieved_context": [],
                    "human_approved": None,
                    "human_feedback": None,
                    "vault_written": False,
                    "jobs_processed": 0,
                    "jobs_written": 0,
                    "errors": [],
                }
                return await compiled.ainvoke(
                    initial,
                    config={
                        "callbacks": [langfuse_handler],
                        "configurable": {"thread_id": thread_id},
                    },
                )

        results = await asyncio.gather(*[process_one(job) for job in raw_jobs], return_exceptions=True)

    total_written = sum(r.get("jobs_written", 0) for r in results if isinstance(r, dict))
    errors = [str(r) for r in results if isinstance(r, Exception)]

    return {
        "jobs_processed": len(raw_jobs),
        "jobs_written": total_written,
        "errors": errors,
    }
```

Also add the missing imports at top of graph.py:
```python
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from compass.pipeline.state import RawJob
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_parallel.py tests/test_rag.py tests/test_hitl_state.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add compass/pipeline/graph.py tests/test_parallel.py
git commit -m "feat: parallel job processing — asyncio.gather with semaphore concurrency cap"
```

---

## Task 8: Update ARCHITECTURE.md

Update the architecture doc to reflect the three amendments so the README and interview story are accurate.

**Files:**
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Update the RAG section**

In the `score_node` description, replace:
> "Compares `JobRequirements` against candidate profile from vault (`_profile/skill-inventory.md`)"

With:
> "Retrieves relevant profile context via semantic search against the Chroma skill index (RAG). Falls back to full `_profile/skill-inventory.md` read if index is empty. Stores retrieved chunks in `retrieved_context` state field for eval tracing."

- [ ] **Step 2: Update the HiTL section**

Replace the current HiTL description with:
> "`hitl_node` uses LangGraph `interrupt()` to pause the graph. It records the interrupt in `HiTLStateStore` (SQLite) with a timestamp. A Modal cron (`compass/hitl/timeout_checker.py`) runs every 30 minutes, finds pending interrupts older than `HITL_TIMEOUT_HOURS`, and resumes them with `human_approved=False`. The timer lives externally — `interrupt()` is a synchronous pause, not a countdown."

- [ ] **Step 3: Update the Layer 2 overview with parallel processing**

Replace:
> "`score_node` (fan-out — runs in parallel for all queued jobs)"

With a note in the graph overview that `run_pipeline()` launches one graph invocation per job via `asyncio.gather`, bounded by `MAX_CONCURRENT_JOBS` semaphore.

- [ ] **Step 4: Add RAG as Layer 2.5**

Add a new section between Layer 2 and Layer 3:

```markdown
## Layer 2.5 — RAG Profile Index (Chroma)

**Purpose:** Enable semantic retrieval of relevant candidate profile context for each JD, instead of loading the full skill inventory on every scoring call.

**Implementation:**
- `compass/rag/indexer.py` — builds a persistent Chroma collection from `skills/*.md` notes using sentence-transformers (all-MiniLM-L6-v2)
- `compass/rag/retriever.py` — given extracted JD skills, queries Chroma and returns the top-k most relevant profile chunks
- `score_node` calls the retriever before every LLM call; falls back to full markdown read if index is empty

**Why not full markdown read:**
The skill inventory is ~150 lines. At scale (50 JDs/day), that's 7,500 lines of profile context per pipeline run. Semantic retrieval limits each LLM call to 5-6 relevant chunks — faster, cheaper, and demonstrates the RAG pattern for portfolio purposes.

**Eval dimension added:**
Context precision (are the retrieved chunks actually relevant to the JD?) is tracked in the eval harness, giving a retrieval quality metric alongside score MAE.
```

- [ ] **Step 5: Commit**

```bash
git add docs/ARCHITECTURE.md
git commit -m "docs: update architecture for rag layer, hitl timeout, parallel processing"
```

---

## Task 9: Update eval harness for retrieval metrics

The eval harness should now measure retrieval quality (context precision) in addition to score MAE.

**Files:**
- Modify: `compass/evals/dataset.py`
- Modify: `compass/evals/runner.py`

- [ ] **Step 1: Update dataset schema to include expected retrieved skills**

In `compass/evals/dataset.py`, ensure the eval record includes `expected_retrieved_skills` — the skills a human would expect to be retrieved for this JD. This lets the runner compute context recall.

```python
from pydantic import BaseModel
from typing import Optional

class EvalRecord(BaseModel):
    id: str
    jd_text: str
    expected_score: float
    expected_skills: list[str]       # skills the JD requires
    expected_retrieved_skills: list[str]  # skills that SHOULD appear in retrieved context
    notes: str = ""
```

- [ ] **Step 2: Implement the eval runner with retrieval metrics**

In `compass/evals/runner.py`:

```python
"""
Eval harness runner.

Metrics:
  - score_mae: mean absolute error between pipeline score and human label
  - skill_extraction_recall: fraction of expected_skills the extractor found
  - context_recall: fraction of expected_retrieved_skills that appeared in retrieved_context
  - cost_per_run: total USD from Langfuse traces
"""
import asyncio
import json
from pathlib import Path
from compass.evals.dataset import EvalRecord
from compass.rag.indexer import build_index
from compass.rag.retriever import retrieve_profile_context
from compass.pipeline.nodes.extract import extract_node
from compass.pipeline.nodes.score import score_node
from compass.pipeline.state import CompassState, RawJob

DATASET_PATH = Path(__file__).parent / "dataset.json"


def load_dataset() -> list[EvalRecord]:
    records = json.loads(DATASET_PATH.read_text())
    return [EvalRecord(**r) for r in records]


async def run_eval_record(record: EvalRecord) -> dict:
    """Run extract + retrieve + score on one eval record. Return metrics."""
    job = RawJob(
        company="EvalCo", title="Eval Role", url=f"eval://{record.id}",
        source="eval", description=record.jd_text,
    )
    state: CompassState = {
        "raw_jobs": [job], "current_job": job, "extracted_requirements": None,
        "score_result": None, "retrieved_context": [],
        "human_approved": None, "human_feedback": None,
        "vault_written": False, "jobs_processed": 0, "jobs_written": 0, "errors": [],
    }

    state.update(await extract_node(state))
    state.update(await score_node(state))

    requirements = state.get("extracted_requirements")
    extracted_skills = set(requirements.required_skills) if requirements else set()
    expected_skills = set(record.expected_skills)
    skill_recall = len(extracted_skills & expected_skills) / len(expected_skills) if expected_skills else 0.0

    retrieved = set(
        chunk for chunk in state.get("retrieved_context", [])
        for skill in record.expected_retrieved_skills
        if skill.lower() in chunk.lower()
    )
    context_recall = len(retrieved) / len(record.expected_retrieved_skills) if record.expected_retrieved_skills else 1.0

    score = state["score_result"].score if state.get("score_result") else 0.0
    score_mae = abs(score - record.expected_score)

    return {
        "id": record.id,
        "score_mae": score_mae,
        "skill_extraction_recall": skill_recall,
        "context_recall": context_recall,
        "errors": state["errors"],
    }


async def run_eval() -> dict:
    build_index()  # Ensure index is fresh
    records = load_dataset()
    results = await asyncio.gather(*[run_eval_record(r) for r in records])

    mean_mae = sum(r["score_mae"] for r in results) / len(results)
    mean_skill_recall = sum(r["skill_extraction_recall"] for r in results) / len(results)
    mean_context_recall = sum(r["context_recall"] for r in results) / len(results)

    summary = {
        "n": len(results),
        "score_mae": round(mean_mae, 3),
        "skill_extraction_recall": round(mean_skill_recall, 3),
        "context_recall": round(mean_context_recall, 3),
    }
    print(summary)
    return summary


if __name__ == "__main__":
    asyncio.run(run_eval())
```

- [ ] **Step 3: Run to verify it imports cleanly (dataset.json doesn't exist yet — that's Phase 3)**

```bash
uv run python -c "from compass.evals.runner import run_eval; print('imports ok')"
```

Expected: `imports ok`

- [ ] **Step 4: Commit**

```bash
git add compass/evals/ 
git commit -m "feat: eval harness — score mae + skill extraction recall + context recall"
```

---

## Verification

After all tasks complete:

```bash
# Full test suite
uv run pytest tests/ -v

# Verify RAG index builds
uv run python -m compass.rag.indexer

# Verify config loads
uv run python -c "import compass.config; print('config ok')"

# Verify graph imports
uv run python -c "from compass.pipeline.graph import build_graph; print('graph ok')"
```

Expected: all tests pass, no import errors.

---

## Interview Story — What You Can Now Say

**On RAG:**
> "The scoring step uses semantic retrieval against a Chroma index of my skill notes rather than loading the full skill inventory on every call. The retriever uses sentence-transformers to embed the JD's required skills, queries for the most semantically similar profile chunks, and passes those as context to the scoring LLM. The eval harness measures context recall — whether the chunks that should be relevant actually get retrieved."

**On HiTL timeout:**
> "LangGraph's `interrupt()` is a synchronous pause — it checkpoints the graph state but doesn't have a built-in timer. The timeout lives externally: a Modal cron runs every 30 minutes, queries a SQLite table of pending interrupts, and resumes any thread older than 4 hours with `human_approved=False`. This is the same pattern you'd use in production for any human-approval workflow with a deadline."

**On parallel processing:**
> "`run_pipeline()` launches one graph invocation per job concurrently using `asyncio.gather`, bounded by a semaphore set to `MAX_CONCURRENT_JOBS` to avoid hitting rate limits. Each job gets its own thread ID and checkpointer connection. The graph itself is single-job — parallelism is in the runner, not the graph topology. At 5 concurrent jobs with ~10s per LLM chain, 50 daily jobs process in about 100 seconds instead of 500."
