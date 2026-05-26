# Compass Phase 0.B — Pipeline MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire LLMs into the Phase 0.A foundation. End state: `MAX_JOBS_PER_RUN=5 uv run python -m compass.pipeline.graph` runs end-to-end against real ATS data, produces ≥5 scored JobNotes in `compass-vault/jobs/`, and regenerates `master-gap-plan.md`.

**Architecture:** Single-job LangGraph (extract → score → reflect → hitl → tailor → vault_write). `run_pipeline` scrapes once, builds the vault URL set once, filters dupes, then invokes the graph per job in a serial loop with bounded concurrency. Models routed per-node via `compass.llm.get_model(node)` which reads env vars at call time (not cached). HiTL remains auto-approve in 0.B (real `interrupt()` is Phase 1.B). **Langfuse callback wiring lands in 0.B** (even though the public-trace URL ships in 2.B) so every real run accumulates traces from day one. A `_meta/pipeline-runs.md` log records one row per run (timestamp, processed, written, errors, duration) — forensic trail + portfolio screenshot material.

**Tech Stack:** Python 3.12 · pydantic-ai 1.97 (OpenAI-compatible provider against OpenRouter) · LangGraph (single-node-at-a-time per invocation) · httpx · pytest + pytest-asyncio (no network in unit tests; live LLMs only in the final verification step).

**Authoritative spec:** `docs/superpowers/specs/2026-05-17-compass-mvp-to-portfolio-ship-design.md`

**Carries these Phase 0.A deferred edges forward:**

1. `extract_node` normalizes every extracted skill through `taxonomy.normalize()`. Unknown skills are dropped from `required_skills`/`nice_to_have_skills` (so gap_aggregator doesn't count noise) BUT every unknown skill is recorded to `compass-vault/_meta/unknown-skills-log.md` (one append per skill per sighting) so the user can review weekly and decide to (a) graduate the skill to the canonical taxonomy, (b) add it as a synonym to an existing canonical, or (c) leave it as noise. Frequency aggregation across the log is left to a future helper script. Downstream nodes never see raw/unknown skill strings.
2. `run_pipeline` builds the vault URL set **once per batch** using `list_job_notes()`. The graph never calls `job_url_exists()` per-job; that O(N) scan is gone.
3. `compass/llm.py` reads `EXTRACT_MODEL` / `SCORE_MODEL` / `REFLECT_MODEL` / `TAILOR_MODEL` / `OPENROUTER_API_KEY` at function-call time, NOT at import. No `@lru_cache` on the resolver. Test fixtures can swap env between tests.
4. `vault_write_node` only routes through the existing `write_job_note` (idempotent on URL) — no new file-creation paths introduced.
5. LangGraph state stays single-job (`current_job` set externally per invocation by `run_pipeline`). No in-graph fan-out.
6. `hitl_node` docstring is explicit: auto-approve is intentional Phase 0.B behavior; real `interrupt()` + `AsyncSqliteSaver` ships in Phase 1.B.

---

## File Structure

### New
- `compass/llm.py` — model resolver + Agent factory

### Schema additions (NEW — needed to avoid clobbering)
- `compass/pipeline/state.py` — add `tailored_paragraph: str | None` to `CompassState`
- `compass/vault/schemas.py` — add `tailored_paragraph: str | None = None` to `JobNote`

### Test scaffolding
- `tests/pipeline/__init__.py`
- `tests/pipeline/test_extract.py`
- `tests/pipeline/test_score.py`
- `tests/pipeline/test_tailor.py`
- `tests/pipeline/test_routing.py` (reflect + hitl + graph routing predicates)
- `tests/pipeline/test_intake.py`
- `tests/pipeline/test_vault_write.py`
- `tests/pipeline/test_graph_integration.py`
- `tests/test_llm.py`

### Modify (replace `NotImplementedError` / restructure)
- `compass/pipeline/nodes/intake.py`
- `compass/pipeline/nodes/extract.py`
- `compass/pipeline/nodes/score.py`
- `compass/pipeline/nodes/reflect.py`
- `compass/pipeline/nodes/hitl.py`
- `compass/pipeline/nodes/tailor.py`
- `compass/pipeline/nodes/vault_write.py`
- `compass/pipeline/graph.py` (restructure `run_pipeline`)
- `tests/conftest.py` (add `fake_agent_response` helper)

### Untouched (existing; don't modify in this phase)
- `compass/scrapers/*.py` — Phase 0.A
- `compass/vault/*.py` — Phase 0.A (except writer is called, not modified)
- `compass/analysis/*.py` — already done in earlier session
- `compass/config.py` — already extended
- `compass/mcp_server/server.py` — Phase 1.A will refine

### Decomposition rationale
Each pipeline node is one file with one responsibility — `compass/pipeline/nodes/{name}.py` exposes one `*_node(state)` function plus its private `_extract()` / `_score()` / `_tailor()` wrapper for the LLM call. The wrappers are the monkeypatch surface for tests. `compass/llm.py` is small (≤40 LoC) and isolated from the nodes — every node imports `get_model` or `make_agent` from there. Tests live in `tests/pipeline/` mirroring `compass/pipeline/nodes/` — easy to find, easy to ignore for live-API verification.

---

## Task 0: Pre-flight

**Files:** none

- [ ] **Step 1: Verify clean tree on phase-0a-foundation tag**

```bash
cd ~/Documents/compass
git status   # expected: clean
git describe --tags --abbrev=0   # expected: phase-0a-foundation
```

If working tree is dirty, STOP and ask the user before proceeding.

- [ ] **Step 2: Verify `.env` exists with `OPENROUTER_API_KEY`**

```bash
test -f .env && grep -q '^OPENROUTER_API_KEY=sk-or-' .env && echo "OK" || echo "MISSING"
```

Expected: `OK`. If `MISSING`, ask the user to paste their OpenRouter key into `.env` (do NOT paste keys in chat). The smoke step in Task 9 will fail without a real key.

- [ ] **Step 3: Verify existing tests still pass**

```bash
uv run pytest -q
```

Expected: 27 passed.

- [ ] **Step 4: Verify ruff is clean**

```bash
uv run ruff check compass tests && uv run ruff format --check compass tests
```

Expected: `All checks passed!` and `43 files already formatted`.

- [ ] **Step 5: Create the pipeline test scaffold**

```bash
mkdir -p tests/pipeline
touch tests/pipeline/__init__.py
```

- [ ] **Step 6: Commit**

```bash
git add tests/pipeline/__init__.py
git commit -m "chore: add tests/pipeline scaffold for Phase 0.B"
```

---

## Task 0.5: Schema additions — keep score's pitch and tailor's paragraph separate

**Files:**
- Modify: `compass/pipeline/state.py`
- Modify: `compass/vault/schemas.py`

The spec says `score_node` produces a one-sentence tailoring pitch; `tailor_node` produces a polished paragraph. These are DIFFERENT artifacts and must not overwrite each other. Add a separate state field and JobNote field for the polished paragraph.

- [ ] **Step 1: Extend `CompassState`**

In `compass/pipeline/state.py`, add `tailored_paragraph: str | None` to the `CompassState` TypedDict (after `human_feedback`):

```python
class CompassState(TypedDict):
    """Full pipeline state passed between all LangGraph nodes."""
    raw_jobs: list[RawJob]

    current_job: RawJob | None
    extracted_requirements: JobRequirements | None
    score_result: JobScore | None

    human_approved: bool | None
    human_feedback: str | None
    tailored_paragraph: str | None  # set by tailor_node, persisted on JobNote

    vault_written: bool
    jobs_processed: int
    jobs_written: int

    errors: list[str]
```

- [ ] **Step 2: Extend `JobNote`**

In `compass/vault/schemas.py`, add `tailored_paragraph: str | None = None` to `JobNote` (after `jd_summary`):

```python
class JobNote(BaseModel):
    # ... existing fields ...
    jd_summary: str = ""
    tailored_paragraph: str | None = None  # populated by tailor_node when approved
    hitl_decision: str | None = None
    # ... rest unchanged ...
```

- [ ] **Step 3: Verify tests still pass**

```bash
cd ~/Documents/compass
uv run pytest -q
```

Expected: 27 passed (no new field is exercised yet but no existing test should break — both fields default to None).

- [ ] **Step 4: Commit**

```bash
git add compass/pipeline/state.py compass/vault/schemas.py
git commit -m "feat(schemas): separate score.tailoring_notes (sentence) from JobNote.tailored_paragraph (paragraph)"
```

---

## Task 1: `compass/llm.py` — model resolver

**Files:**
- Create: `compass/llm.py`
- Create: `tests/test_llm.py`

The resolver reads env vars at call time. Returns a configured pydantic-ai `Agent`. No caching of model objects — `Agent` construction is cheap and we want tests to swap env between runs.

- [ ] **Step 1: Write the failing test**

Write `tests/test_llm.py`:

```python
"""Tests for compass.llm — the model resolver + Agent factory."""
import os

import pytest


def test_get_model_id_reads_env_at_call_time(monkeypatch):
    """Changing the env between calls must change the resolved model id."""
    from compass.llm import get_model_id

    monkeypatch.setenv("EXTRACT_MODEL", "google/gemini-2.5-flash")
    assert get_model_id("extract") == "google/gemini-2.5-flash"

    monkeypatch.setenv("EXTRACT_MODEL", "anthropic/claude-haiku-4-5")
    assert get_model_id("extract") == "anthropic/claude-haiku-4-5"


def test_get_model_id_unknown_node_raises():
    from compass.llm import get_model_id

    with pytest.raises(ValueError, match="unknown node"):
        get_model_id("nonexistent_node")


def test_get_model_id_missing_env_raises(monkeypatch):
    from compass.llm import get_model_id

    monkeypatch.delenv("EXTRACT_MODEL", raising=False)
    with pytest.raises(ValueError, match="no model configured"):
        get_model_id("extract")


def test_make_agent_returns_pydantic_ai_agent(monkeypatch):
    """make_agent should construct a pydantic-ai Agent wired to OpenRouter."""
    from pydantic import BaseModel
    from pydantic_ai import Agent

    from compass.llm import make_agent

    monkeypatch.setenv("EXTRACT_MODEL", "google/gemini-2.5-flash")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    class Result(BaseModel):
        answer: str

    agent = make_agent("extract", output_type=Result, system_prompt="hi")
    assert isinstance(agent, Agent)


def test_make_agent_requires_keyword_args(monkeypatch):
    """Positional args after `node` must fail — keeps call sites explicit."""
    from pydantic import BaseModel

    from compass.llm import make_agent

    monkeypatch.setenv("EXTRACT_MODEL", "google/gemini-2.5-flash")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    class Result(BaseModel):
        answer: str

    with pytest.raises(TypeError):
        make_agent("extract", Result, "hi")  # type: ignore[misc]
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_llm.py -v
```

Expected: 4 FAILs (ModuleNotFoundError on `compass.llm`).

- [ ] **Step 3: Implement `compass/llm.py`**

Write `compass/llm.py`:

```python
"""
Model resolver + Agent factory for Compass pipeline nodes.

Routes per-node model selection through OpenRouter. Env vars are read at
call time (not import or cache) so tests can swap models per-test and
production hot-reloads pick up `.env` changes after a restart only.
"""
from __future__ import annotations

import os

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_NODE_ENV: dict[str, str] = {
    "extract": "EXTRACT_MODEL",
    "score": "SCORE_MODEL",
    "reflect": "REFLECT_MODEL",
    "tailor": "TAILOR_MODEL",
    "assessor": "ASSESSOR_MODEL",
}


def get_model_id(node: str) -> str:
    """Return the OpenRouter model id for a node, reading env at call time."""
    env_name = _NODE_ENV.get(node)
    if env_name is None:
        raise ValueError(f"unknown node {node!r}; expected one of {sorted(_NODE_ENV)}")
    model_id = os.environ.get(env_name)
    if not model_id:
        raise ValueError(f"no model configured for node {node!r} (env {env_name} unset)")
    return model_id


def _get_model(node: str) -> OpenAIChatModel:
    """Build a pydantic-ai OpenAIChatModel pointed at OpenRouter for this node."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not set")
    provider = OpenAIProvider(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    return OpenAIChatModel(get_model_id(node), provider=provider)


def make_agent(
    node: str,
    *,
    output_type: type[BaseModel],
    system_prompt: str,
) -> Agent:
    """Construct a pydantic-ai Agent for a node with the routed model + provider.

    Explicit keyword-only args (no **kwargs) so call sites are self-documenting
    and typos surface at type-check time, not at runtime.
    """
    return Agent(_get_model(node), output_type=output_type, system_prompt=system_prompt)
```

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest tests/test_llm.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add compass/llm.py tests/test_llm.py
git commit -m "feat(llm): add per-node OpenRouter model resolver + Agent factory"
```

---

## Task 2: `extract_node` — Pydantic AI structured extraction + skill normalization

**Files:**
- Modify: `compass/pipeline/nodes/extract.py`
- Create: `tests/pipeline/test_extract.py`

The node calls an LLM that returns a `JobRequirements`. Every skill in `required_skills` and `nice_to_have_skills` is normalized through `taxonomy.normalize()` before being stored in state. Unknown skills are dropped + logged. This closes deferred edge #1.

- [ ] **Step 1: Write the failing test**

Write `tests/pipeline/test_extract.py`:

```python
"""Tests for compass.pipeline.nodes.extract — JD extraction + skill normalization."""
from datetime import date

import pytest

from compass.pipeline.state import CompassState, JobRequirements, RawJob


def _state(jd_text: str) -> CompassState:
    return {
        "raw_jobs": [],
        "current_job": RawJob(
            company="sample", title="Engineer", url="https://example.com/x",
            source="greenhouse", description=jd_text, date_posted=date.today(),
        ),
        "extracted_requirements": None,
        "score_result": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


async def test_extract_node_normalizes_known_skills(monkeypatch):
    """Returned skills are mapped to canonical taxonomy names."""
    from compass.pipeline.nodes import extract

    async def fake_extract(jd_text: str) -> JobRequirements:
        return JobRequirements(
            required_skills=["langgraph", "py", "MCP"],
            nice_to_have_skills=["fastapi"],
            years_experience=2,
            seniority="mid",
            remote_policy="hybrid",
            summary="Build agents.",
        )

    monkeypatch.setattr(extract, "_extract", fake_extract)
    result = await extract.extract_node(_state("anything"))
    req = result["extracted_requirements"]
    assert req.required_skills == ["LangGraph", "Python", "MCP"]
    assert req.nice_to_have_skills == ["FastAPI"]


async def test_extract_node_drops_unknown_skills_but_records_them(monkeypatch, temp_vault):
    """Unknown skills are dropped from requirements but written to the unknown-skills log."""
    from compass.pipeline.nodes import extract

    async def fake_extract(jd_text: str) -> JobRequirements:
        return JobRequirements(
            required_skills=["LangGraph", "NotARealSkillXyz123", "MojoLang"],
            nice_to_have_skills=["AlsoFake"],
            years_experience=None,
            seniority="mid",
            remote_policy="remote",
            summary="...",
        )

    monkeypatch.setattr(extract, "_extract", fake_extract)
    result = await extract.extract_node(_state("anything"))

    # Unknown skills dropped from extracted requirements:
    assert result["extracted_requirements"].required_skills == ["LangGraph"]
    assert result["extracted_requirements"].nice_to_have_skills == []

    # Unknown skills recorded to log for human review:
    log_path = temp_vault / "_meta" / "unknown-skills-log.md"
    assert log_path.exists(), "unknown-skills-log.md should be created on first unknown skill"
    log_text = log_path.read_text()
    assert "NotARealSkillXyz123" in log_text
    assert "MojoLang" in log_text
    assert "AlsoFake" in log_text


async def test_extract_node_with_missing_current_job_returns_error(monkeypatch):
    from compass.pipeline.nodes import extract

    state = _state("anything")
    state["current_job"] = None
    result = await extract.extract_node(state)
    assert result["extracted_requirements"] is None
    assert any("current_job" in e for e in result.get("errors", []))
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/pipeline/test_extract.py -v
```

Expected: 3 FAILs (NotImplementedError on `extract_node`).

- [ ] **Step 3: Implement `compass/pipeline/nodes/extract.py`**

Replace the file with:

```python
"""
extract_node — Pydantic AI structured extraction of JobRequirements from JD text.

Skill normalization: every extracted skill is mapped to its canonical name via
compass.vault.taxonomy.normalize(). Unknown skills are dropped + logged. This
guarantees downstream nodes (score, vault_write) never see raw or non-canonical
skill strings.

Model: EXTRACT_MODEL (default google/gemini-2.5-flash). Routed via compass.llm.
"""
from __future__ import annotations

import logging
from datetime import datetime

from compass.config import VAULT_PATH
from compass.llm import make_agent
from compass.pipeline.state import CompassState, JobRequirements
from compass.vault.taxonomy import normalize

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You extract structured requirements from a job description.

Return a JobRequirements with:
- required_skills: technical skills the JD explicitly requires (frameworks, languages, tools).
- nice_to_have_skills: technical skills the JD lists as preferred/bonus.
- years_experience: minimum years stated, or null if not stated.
- seniority: one of junior | mid | senior | staff | unknown.
- remote_policy: one of remote | hybrid | onsite | unknown.
- summary: one short paragraph (~2 sentences) of what the role does.

Only include genuinely technical skills (not soft skills, not credentials, not industries).
"""


def _build_agent():
    return make_agent("extract", output_type=JobRequirements, system_prompt=_SYSTEM_PROMPT)


async def _extract(jd_text: str) -> JobRequirements:
    """The LLM call. Tests monkeypatch this wrapper rather than the underlying Agent."""
    agent = _build_agent()
    result = await agent.run(jd_text)
    return result.output


def _normalize_skill_list(skills: list[str], unknown_sink: list[str] | None = None) -> list[str]:
    """Map each raw skill to canonical; drop unknowns but record them for later review.

    Unknown skills are appended to `unknown_sink` (if provided) so the caller can
    persist them to the unknown-skills log for weekly review.
    """
    out: list[str] = []
    for raw in skills:
        canon = normalize(raw)
        if canon is None:
            logger.info("extract: unknown skill %r (not in canonical taxonomy)", raw)
            if unknown_sink is not None:
                unknown_sink.append(raw)
            continue
        if canon not in out:
            out.append(canon)
    return out


def _record_unknown_skills(skills: list[str], job_url: str) -> None:
    """Append seen unknown skills to compass-vault/_meta/unknown-skills-log.md.

    Format is a plain markdown log so the user can scan it weekly and decide
    whether to (a) graduate to canonical, (b) add as a synonym, (c) ignore.
    A separate helper script can aggregate frequencies — out of scope for 0.B.
    """
    if not skills:
        return
    log_path = VAULT_PATH / "_meta" / "unknown-skills-log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Create with header on first write
    if not log_path.exists():
        log_path.write_text(
            "# Unknown Skills Log\n\n"
            "Skills seen in scraped JDs that don't match a canonical entry in "
            "`_meta/skill-taxonomy.md`. Review weekly; either add to canonical, "
            "add as a synonym to an existing canonical, or ignore.\n\n"
            "Format: `[ISO timestamp] skill_name (from job_url)`\n\n---\n\n",
            encoding="utf-8",
        )
    now = datetime.now().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as f:
        for skill in skills:
            f.write(f"[{now}] {skill}  (from {job_url})\n")


async def extract_node(state: CompassState) -> dict:
    """Extract JobRequirements from state.current_job.description."""
    job = state.get("current_job")
    if job is None:
        return {
            "extracted_requirements": None,
            "errors": [*state.get("errors", []), "extract_node: current_job is None"],
        }

    try:
        raw_req = await _extract(job.description)
    except Exception as e:
        logger.warning("extract_node: LLM call failed for %s — %s", job.url, e)
        return {
            "extracted_requirements": None,
            "errors": [*state.get("errors", []), f"extract_node: {e}"],
        }

    unknown: list[str] = []
    normalized = JobRequirements(
        required_skills=_normalize_skill_list(raw_req.required_skills, unknown),
        nice_to_have_skills=_normalize_skill_list(raw_req.nice_to_have_skills, unknown),
        years_experience=raw_req.years_experience,
        seniority=raw_req.seniority,
        remote_policy=raw_req.remote_policy,
        summary=raw_req.summary,
    )
    if unknown:
        _record_unknown_skills(unknown, job.url)
    return {"extracted_requirements": normalized}
```

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest tests/pipeline/test_extract.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add compass/pipeline/nodes/extract.py tests/pipeline/test_extract.py
git commit -m "feat(pipeline): implement extract_node with taxonomy normalization"
```

---

## Task 3: `score_node` — JobScore against the candidate profile

**Files:**
- Modify: `compass/pipeline/nodes/score.py`
- Create: `tests/pipeline/test_score.py`

`score_node` takes `extracted_requirements` + reads `resume.md` + `skill-inventory.md` from the vault and produces a `JobScore` (0.0–5.0 + matched/missing/tailoring_notes). LLM call wrapped in `_score()` for test monkeypatch.

- [ ] **Step 1: Write the failing test**

Write `tests/pipeline/test_score.py`:

```python
"""Tests for compass.pipeline.nodes.score."""
from datetime import date

import pytest

from compass.pipeline.state import CompassState, JobRequirements, JobScore, RawJob


def _state(req: JobRequirements) -> CompassState:
    return {
        "raw_jobs": [],
        "current_job": RawJob(
            company="sample", title="Engineer", url="https://example.com/x",
            source="greenhouse", description="...", date_posted=date.today(),
        ),
        "extracted_requirements": req,
        "score_result": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


async def test_score_node_returns_jobscore(monkeypatch, temp_vault):
    from compass.pipeline.nodes import score

    async def fake_score(req, profile_text: str) -> JobScore:
        return JobScore(
            score=4.2, reasoning="Strong MCP match",
            matched_skills=["MCP"], missing_skills=["LangGraph"],
            tailoring_notes="Lead with production MCP work.",
        )

    monkeypatch.setattr(score, "_score", fake_score)
    req = JobRequirements(
        required_skills=["MCP", "LangGraph"], nice_to_have_skills=[],
        years_experience=2, seniority="mid", remote_policy="remote",
        summary="...",
    )
    result = await score.score_node(_state(req))
    assert result["score_result"].score == 4.2
    assert "MCP" in result["score_result"].matched_skills


async def test_score_node_missing_requirements_errors(monkeypatch, temp_vault):
    from compass.pipeline.nodes import score
    state = _state(None)  # type: ignore[arg-type]
    result = await score.score_node(state)
    assert result["score_result"] is None
    assert any("requirements" in e for e in result.get("errors", []))


async def test_score_node_passes_profile_to_llm(monkeypatch, temp_vault):
    """The profile_text passed to _score must include resume + skill-inventory content."""
    from compass.pipeline.nodes import score

    captured = {}

    async def fake_score(req, profile_text: str) -> JobScore:
        captured["profile_text"] = profile_text
        return JobScore(score=3.0, reasoning="", matched_skills=[], missing_skills=[], tailoring_notes="")

    monkeypatch.setattr(score, "_score", fake_score)
    req = JobRequirements(
        required_skills=[], nice_to_have_skills=[], years_experience=None,
        seniority="mid", remote_policy="unknown", summary="",
    )
    await score.score_node(_state(req))
    assert "Fake resume body" in captured["profile_text"]
    assert "Python: 3" in captured["profile_text"]
```

- [ ] **Step 2: Run to verify they fail**

Expected: 3 FAILs.

- [ ] **Step 3: Implement `compass/pipeline/nodes/score.py`**

Replace with:

```python
"""
score_node — score a job against the candidate profile.

Reads resume.md + skill-inventory.md from the vault and passes them as context to
the LLM. Returns a JobScore (0.0–5.0) with matched/missing/tailoring breakdown.

Model: SCORE_MODEL (default google/gemini-2.5-flash).
"""
from __future__ import annotations

import logging

from compass.llm import make_agent
from compass.pipeline.state import CompassState, JobRequirements, JobScore
from compass.vault.reader import read_resume, read_skill_inventory

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You score a job description against a candidate's profile.

Score 0.0–5.0:
- 5.0 = perfect match, candidate has every required skill at production level
- 4.0 = strong match, candidate has ~80% of required skills with real evidence
- 3.0 = decent match, candidate has core skills but missing some required ones
- 2.0 = stretch, candidate has adjacent skills but lacks several required ones
- 1.0 = poor match, fundamental skill gaps
- 0.0 = wrong field entirely

Be honest. Score conservatively when evidence is conceptual rather than shipped.

Return a JobScore with:
- score: float 0.0–5.0
- reasoning: 2–3 sentences justifying the score
- matched_skills: canonical skills the candidate has (level >= 2)
- missing_skills: canonical skills the JD requires but the candidate lacks (level < 2)
- tailoring_notes: ONE sentence suggesting how to frame the application (skip if score < 3.0)
"""


def _build_agent():
    return make_agent("score", output_type=JobScore, system_prompt=_SYSTEM_PROMPT)


def _format_prompt(req: JobRequirements, profile_text: str) -> str:
    return (
        f"# CANDIDATE PROFILE\n{profile_text}\n\n"
        f"# JOB REQUIREMENTS\n"
        f"required: {', '.join(req.required_skills) or '(none)'}\n"
        f"nice-to-have: {', '.join(req.nice_to_have_skills) or '(none)'}\n"
        f"years_experience: {req.years_experience}\n"
        f"seniority: {req.seniority}\n"
        f"remote_policy: {req.remote_policy}\n"
        f"summary: {req.summary}\n"
    )


async def _score(req: JobRequirements, profile_text: str) -> JobScore:
    """The LLM call. Tests monkeypatch this wrapper rather than the underlying Agent."""
    agent = _build_agent()
    result = await agent.run(_format_prompt(req, profile_text))
    return result.output


def _profile_text() -> str:
    return f"## RESUME\n{read_resume()}\n\n## SKILL INVENTORY\n{read_skill_inventory()}"


async def score_node(state: CompassState) -> dict:
    req = state.get("extracted_requirements")
    if req is None:
        return {
            "score_result": None,
            "errors": [*state.get("errors", []), "score_node: extracted_requirements is None"],
        }

    try:
        result = await _score(req, _profile_text())
    except Exception as e:
        logger.warning("score_node: LLM call failed — %s", e)
        return {
            "score_result": None,
            "errors": [*state.get("errors", []), f"score_node: {e}"],
        }

    return {"score_result": result}
```

- [ ] **Step 4: Run to verify they pass**

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add compass/pipeline/nodes/score.py tests/pipeline/test_score.py
git commit -m "feat(pipeline): implement score_node with profile context injection"
```

---

## Task 4: `tailor_node` — one-paragraph tailoring (Sonnet)

**Files:**
- Modify: `compass/pipeline/nodes/tailor.py`
- Create: `tests/pipeline/test_tailor.py`

Only fires when `human_approved=True`. Produces a `tailoring_notes` string. Per spec, uses Sonnet for writing quality. Output is just a single paragraph; we use a `TailoringResult` Pydantic model for structured output.

- [ ] **Step 1: Write the failing test**

Write `tests/pipeline/test_tailor.py`:

```python
"""Tests for compass.pipeline.nodes.tailor."""
from datetime import date

import pytest

from compass.pipeline.state import CompassState, JobRequirements, JobScore, RawJob


def _state(approved: bool = True) -> CompassState:
    return {
        "raw_jobs": [],
        "current_job": RawJob(
            company="AgentCo", title="Agent Engineer", url="https://example.com/x",
            source="ashby", description="Build agentic systems.", date_posted=date.today(),
        ),
        "extracted_requirements": JobRequirements(
            required_skills=["LangGraph", "MCP"], nice_to_have_skills=[],
            years_experience=2, seniority="mid", remote_policy="hybrid",
            summary="Build agents.",
        ),
        "score_result": JobScore(
            score=4.2, reasoning="Strong MCP", matched_skills=["MCP"],
            missing_skills=["LangGraph"], tailoring_notes="lead with MCP",
        ),
        "human_approved": approved,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


async def test_tailor_node_writes_tailored_paragraph(monkeypatch, temp_vault):
    """The polished paragraph lands on a separate state field — NOT on score.tailoring_notes."""
    from compass.pipeline.nodes import tailor

    async def fake_tailor(*a, **kw):
        return "Lead with your production MCP servers work and a 4-server MCP architecture."

    monkeypatch.setattr(tailor, "_tailor", fake_tailor)
    state = _state(approved=True)
    score_pitch_before = state["score_result"].tailoring_notes
    result = await tailor.tailor_node(state)
    # New polished paragraph on dedicated state field:
    assert "MCP" in result["tailored_paragraph"]
    # Score's original short pitch is NOT clobbered:
    assert "score_result" not in result  # tailor doesn't touch score
    # Sanity: original score pitch unchanged in the input state:
    assert state["score_result"].tailoring_notes == score_pitch_before


async def test_tailor_node_skips_when_not_approved(monkeypatch, temp_vault):
    from compass.pipeline.nodes import tailor

    called = {"count": 0}

    async def fake_tailor(*a, **kw):
        called["count"] += 1
        return "should not run"

    monkeypatch.setattr(tailor, "_tailor", fake_tailor)
    result = await tailor.tailor_node(_state(approved=False))
    assert called["count"] == 0
    assert result == {}  # no state mutation
```

- [ ] **Step 2: Run to verify they fail**

Expected: 2 FAILs.

- [ ] **Step 3: Implement `compass/pipeline/nodes/tailor.py`**

Replace with:

```python
"""
tailor_node — Sonnet-quality one-paragraph tailoring suggestion.

Only fires when state['human_approved'] is True. Updates the existing JobScore's
tailoring_notes field in place. Sonnet (or TAILOR_MODEL override) for writing quality.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

from compass.llm import make_agent
from compass.pipeline.state import CompassState
from compass.vault.reader import read_profile_section, read_resume

logger = logging.getLogger(__name__)


class TailoringResult(BaseModel):
    """Structured output: a single tailoring paragraph."""
    paragraph: str


_SYSTEM_PROMPT = """You write tailoring suggestions for job applications.

Output ONE concrete paragraph (3–5 sentences) suggesting how the candidate
should frame their application for this specific role. Reference concrete
projects/work from the candidate's profile that match the role's requirements.

Avoid generic advice. Be specific. Mention real projects and concrete numbers
when the profile provides them.
"""


def _build_agent():
    return make_agent("tailor", output_type=TailoringResult, system_prompt=_SYSTEM_PROMPT)


# Sonnet handles long context fine, but trimming keeps tailor calls predictable in cost.
# 6000 chars ≈ ~1500 tokens of JD body — enough signal for one paragraph of tailoring.
_MAX_JD_CHARS_FOR_TAILOR = 6000


async def _tailor(job_summary: str, profile_text: str, missing: list[str], matched: list[str]) -> str:
    """The LLM call. Tests monkeypatch this wrapper rather than the underlying Agent."""
    agent = _build_agent()
    prompt = (
        f"CANDIDATE PROFILE\n{profile_text}\n\n"
        f"JOB SUMMARY\n{job_summary}\n\n"
        f"Skills matched: {', '.join(matched) or '(none)'}\n"
        f"Skills missing: {', '.join(missing) or '(none)'}\n"
    )
    result = await agent.run(prompt)
    return result.output.paragraph


async def tailor_node(state: CompassState) -> dict:
    if not state.get("human_approved"):
        return {}

    score = state.get("score_result")
    job = state.get("current_job")
    if score is None or job is None:
        return {}

    profile = f"{read_resume()}\n\n{read_profile_section('role-clarifications')}"

    try:
        paragraph = await _tailor(
            job.description[:_MAX_JD_CHARS_FOR_TAILOR],
            profile,
            score.missing_skills,
            score.matched_skills,
        )
    except Exception as e:
        logger.warning("tailor_node: LLM call failed for %s — %s", job.url, e)
        return {"errors": [*state.get("errors", []), f"tailor_node: {e}"]}

    return {"tailored_paragraph": paragraph}
```

- [ ] **Step 4: Run to verify they pass**

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add compass/pipeline/nodes/tailor.py tests/pipeline/test_tailor.py
git commit -m "feat(pipeline): implement tailor_node (Sonnet, approved-only)"
```

---

## Task 5: `reflect_node` + `hitl_node` — pass-through / auto-approve

**Files:**
- Modify: `compass/pipeline/nodes/reflect.py`
- Modify: `compass/pipeline/nodes/hitl.py`
- Create: `tests/pipeline/test_routing.py`

Both are simple in 0.B. `reflect` is a no-op; `hitl` auto-approves when score ≥ threshold. Combined test file because both are routing/control nodes with no LLM.

- [ ] **Step 1: Write the failing test**

Write `tests/pipeline/test_routing.py`:

```python
"""Tests for reflect_node + hitl_node — control-flow nodes (no LLM in 0.B)."""
from datetime import date

import pytest

from compass.config import SCORE_THRESHOLD
from compass.pipeline.state import CompassState, JobScore, RawJob


def _state(score_value: float) -> CompassState:
    return {
        "raw_jobs": [],
        "current_job": RawJob(
            company="x", title="y", url="https://example.com/z",
            source="greenhouse", description="...", date_posted=date.today(),
        ),
        "extracted_requirements": None,
        "score_result": JobScore(
            score=score_value, reasoning="", matched_skills=[], missing_skills=[],
            tailoring_notes="",
        ),
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


async def test_reflect_node_is_passthrough():
    from compass.pipeline.nodes.reflect import reflect_node
    state = _state(3.2)
    result = await reflect_node(state)
    assert result == {}


async def test_hitl_node_approves_when_score_meets_threshold():
    from compass.pipeline.nodes.hitl import hitl_node
    result = await hitl_node(_state(SCORE_THRESHOLD))
    assert result["human_approved"] is True


async def test_hitl_node_rejects_when_score_below_threshold():
    from compass.pipeline.nodes.hitl import hitl_node
    result = await hitl_node(_state(SCORE_THRESHOLD - 0.5))
    assert result["human_approved"] is False


async def test_hitl_node_handles_missing_score():
    from compass.pipeline.nodes.hitl import hitl_node
    state = _state(0.0)
    state["score_result"] = None
    result = await hitl_node(state)
    assert result["human_approved"] is False
```

- [ ] **Step 2: Run to verify they fail**

Expected: 4 FAILs.

- [ ] **Step 3: Implement both nodes**

Replace `compass/pipeline/nodes/reflect.py`:

```python
"""
reflect_node — Phase 0.B no-op pass-through.

Future role (Phase 2): re-examine borderline scores (3.0–4.0) with a stricter
rubric. For Phase 0.B we don't have eval data showing where reflection would
help, so we wait. See spec section "Phase 0.B → 2.A" for the upgrade trigger.
"""
from __future__ import annotations

from compass.pipeline.state import CompassState


async def reflect_node(state: CompassState) -> dict:
    """No-op for Phase 0.B. Returns {} (no state mutation)."""
    return {}
```

Replace `compass/pipeline/nodes/hitl.py`:

```python
"""
hitl_node — Phase 0.B auto-approve based on SCORE_THRESHOLD.

This is INTENTIONALLY auto-approve for 0.B. Real LangGraph `interrupt()` +
`AsyncSqliteSaver` checkpointing + an MCP-tool-driven approval surface ship in
Phase 1.B per the spec. Auto-approve unblocks the end-to-end pipeline so we
can collect real eval data first.
"""
from __future__ import annotations

import logging

from compass.config import SCORE_THRESHOLD
from compass.pipeline.state import CompassState

logger = logging.getLogger(__name__)


async def hitl_node(state: CompassState) -> dict:
    """Auto-approve if score >= SCORE_THRESHOLD, else reject. No human interaction in 0.B."""
    score = state.get("score_result")
    if score is None:
        logger.info("hitl: no score_result, rejecting by default")
        return {"human_approved": False}

    approved = score.score >= SCORE_THRESHOLD
    job = state.get("current_job")
    job_id = job.url if job else "(unknown)"
    logger.info(
        "hitl: auto-%s job %s (score=%.2f, threshold=%.2f)",
        "approve" if approved else "reject", job_id, score.score, SCORE_THRESHOLD,
    )
    return {"human_approved": approved}
```

- [ ] **Step 4: Run to verify they pass**

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add compass/pipeline/nodes/reflect.py compass/pipeline/nodes/hitl.py tests/pipeline/test_routing.py
git commit -m "feat(pipeline): implement reflect (no-op) + hitl (auto-approve in 0.B)"
```

---

## Task 6: `intake_node` — Phase 0.B no-op (dedup moves to run_pipeline)

**Files:**
- Modify: `compass/pipeline/nodes/intake.py`
- Create: `tests/pipeline/test_intake.py`

Dedup is **batch-level** in `run_pipeline` (Task 8). The graph never per-job-scans the vault. `intake_node` becomes a sanity check that `current_job` is set. Closes deferred edge #2.

- [ ] **Step 1: Write the failing test**

Write `tests/pipeline/test_intake.py`:

```python
"""Tests for intake_node — Phase 0.B is a sanity gate, not the dedup point."""
from datetime import date

import pytest

from compass.pipeline.state import CompassState, RawJob


def _state(job: RawJob | None) -> CompassState:
    return {
        "raw_jobs": [],
        "current_job": job,
        "extracted_requirements": None,
        "score_result": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


async def test_intake_node_passes_when_current_job_set():
    from compass.pipeline.nodes.intake import intake_node
    job = RawJob(
        company="x", title="y", url="https://example.com/z",
        source="greenhouse", description="...", date_posted=date.today(),
    )
    result = await intake_node(_state(job))
    assert result == {}


async def test_intake_node_errors_when_current_job_missing():
    from compass.pipeline.nodes.intake import intake_node
    result = await intake_node(_state(None))
    assert any("current_job" in e for e in result.get("errors", []))
```

- [ ] **Step 2: Run to verify they fail**

Expected: 2 FAILs.

- [ ] **Step 3: Implement `compass/pipeline/nodes/intake.py`**

Replace with:

```python
"""
intake_node — Phase 0.B sanity gate.

Dedup happens BATCH-LEVEL in `run_pipeline` (build URL set once via
list_job_notes, filter raw_jobs before graph iteration). This node just
confirms `current_job` is set; future filtering logic (e.g., seniority
pre-filter, excluded-company list) can land here without restructuring.
"""
from __future__ import annotations

from compass.pipeline.state import CompassState


async def intake_node(state: CompassState) -> dict:
    if state.get("current_job") is None:
        return {"errors": [*state.get("errors", []), "intake_node: current_job is None"]}
    return {}
```

- [ ] **Step 4: Run to verify they pass**

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add compass/pipeline/nodes/intake.py tests/pipeline/test_intake.py
git commit -m "feat(pipeline): implement intake_node as sanity gate (dedup moves to run_pipeline)"
```

---

## Task 7: `vault_write_node` — JobNote + Company + Skills

**Files:**
- Modify: `compass/pipeline/nodes/vault_write.py`
- Create: `tests/pipeline/test_vault_write.py`

Builds a `JobNote` from `current_job` + `score_result` + `extracted_requirements`, writes it via `write_job_note`. Then increments matched-skill counters via `update_skill_note`. Then upserts the company. All skills are already canonicalized (extract_node did the work). Per deferred edge #4: only path to a file write is via `write_job_note` (idempotent).

- [ ] **Step 1: Write the failing test**

Write `tests/pipeline/test_vault_write.py`:

```python
"""Tests for vault_write_node."""
from datetime import date

import frontmatter

from compass.pipeline.state import CompassState, JobRequirements, JobScore, RawJob


def _state(skills_required: list[str], skills_matched: list[str], score: float = 4.2) -> CompassState:
    return {
        "raw_jobs": [],
        "current_job": RawJob(
            company="AgentCo", title="Agent Engineer",
            url="https://jobs.ashbyhq.com/agentco/abc-123",
            source="ashby", description="Build agentic systems.",
            location="NYC", date_posted=date(2026, 5, 17),
        ),
        "extracted_requirements": JobRequirements(
            required_skills=skills_required, nice_to_have_skills=[],
            years_experience=2, seniority="mid", remote_policy="hybrid",
            summary="Build agents.",
        ),
        "score_result": JobScore(
            score=score, reasoning="strong", matched_skills=skills_matched,
            missing_skills=[s for s in skills_required if s not in skills_matched],
            tailoring_notes="lead with MCP",
        ),
        "human_approved": True,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


async def test_vault_write_node_writes_jobnote(temp_vault):
    from compass.pipeline.nodes.vault_write import vault_write_node
    result = await vault_write_node(_state(["MCP", "LangGraph"], ["MCP"]))
    assert result["vault_written"] is True
    assert result["jobs_written"] == 1
    job_files = list((temp_vault / "jobs").glob("*.md"))
    assert len(job_files) == 1
    loaded = frontmatter.load(job_files[0])
    assert loaded.metadata["company"] == "AgentCo"
    assert loaded.metadata["match_score"] == 4.2
    assert "MCP" in loaded.metadata["skills_required"]


async def test_vault_write_node_increments_skill_counters(temp_vault):
    from compass.pipeline.nodes.vault_write import vault_write_node
    await vault_write_node(_state(["MCP", "LangGraph"], ["MCP"]))
    skill_files = list((temp_vault / "skills").glob("*.md"))
    skills_written = {f.stem for f in skill_files}
    assert "MCP" in skills_written
    assert "LangGraph" in skills_written


async def test_vault_write_node_writes_company_note(temp_vault):
    from compass.pipeline.nodes.vault_write import vault_write_node
    await vault_write_node(_state(["MCP"], ["MCP"]))
    company_path = temp_vault / "companies" / "AgentCo.md"
    assert company_path.exists()


async def test_vault_write_node_handles_missing_state(temp_vault):
    from compass.pipeline.nodes.vault_write import vault_write_node
    state = _state(["MCP"], ["MCP"])
    state["score_result"] = None
    result = await vault_write_node(state)
    assert result["vault_written"] is False
    assert any("score_result" in e for e in result.get("errors", []))
```

- [ ] **Step 2: Run to verify they fail**

Expected: 4 FAILs.

- [ ] **Step 3: Implement `compass/pipeline/nodes/vault_write.py`**

Replace with:

```python
"""
vault_write_node — persist a scored job to the compass vault.

Writes three things:
1. JobNote -> jobs/YYYY-MM-DD-Company-Title.md (idempotent on URL via write_job_note)
2. Increments appears_in_jobs on each skill the JD requires (via update_skill_note)
3. Upserts companies/Company.md (via write_company_note)

All skills passed downstream are already canonical (extract_node normalized them).
This node never normalizes — if a non-canonical skill appears here, that's an
upstream bug.
"""
from __future__ import annotations

import logging
from datetime import date

from compass.pipeline.state import CompassState
from compass.vault.schemas import CompanyNote, JobNote
from compass.vault.writer import update_skill_note, write_company_note, write_job_note

logger = logging.getLogger(__name__)


async def vault_write_node(state: CompassState) -> dict:
    job = state.get("current_job")
    score = state.get("score_result")
    req = state.get("extracted_requirements")

    if job is None or score is None or req is None:
        missing = [n for n, v in [("current_job", job), ("score_result", score), ("extracted_requirements", req)] if v is None]
        return {
            "vault_written": False,
            "errors": [*state.get("errors", []), f"vault_write_node: missing {missing}"],
        }

    note = JobNote(
        company=job.company,
        title=job.title,
        url=job.url,
        source=job.source,
        date_found=job.date_posted or date.today(),
        match_score=score.score,
        score_reasoning=score.reasoning,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        location=job.location,
        remote=None,
        seniority=req.seniority,
        years_required=req.years_experience,
        skills_required=req.required_skills,
        skills_nice_to_have=req.nice_to_have_skills,
        skills_matched=score.matched_skills,
        skills_missing=score.missing_skills,
        jd_summary=req.summary,
        tailored_paragraph=state.get("tailored_paragraph"),  # set by tailor_node when approved
    )
    write_job_note(note)

    for canonical in req.required_skills:
        update_skill_note(canonical, job.url)

    # TODO(Phase 1.A): read company tier from target-companies.md instead of "unknown".
    # `write_company_note` is idempotent, so roles_seen=1 currently never increments;
    # Phase 1.A application-tracking will rewire this to read-merge-write properly.
    write_company_note(CompanyNote(company=job.company, tier="unknown", roles_seen=1))

    return {
        "vault_written": True,
        "jobs_written": state.get("jobs_written", 0) + 1,
    }
```

- [ ] **Step 4: Run to verify they pass**

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add compass/pipeline/nodes/vault_write.py tests/pipeline/test_vault_write.py
git commit -m "feat(pipeline): implement vault_write_node (job + skills + company)"
```

---

## Task 8: Restructure `run_pipeline` + integration test

**Files:**
- Modify: `compass/pipeline/graph.py`
- Create: `tests/pipeline/test_graph_integration.py`

`run_pipeline` now:
1. Scrapes (or accepts) raw_jobs
2. Builds **batch URL set** from `list_job_notes()` + frontmatter parse (deferred edge #2)
3. Filters raw_jobs to exclude already-seen URLs
4. For each surviving job: invokes `graph.ainvoke(state with current_job=job)` serially
5. Calls `gap_aggregator.regenerate()` after all jobs are processed

Single-job graph (no fan-out). `MAX_CONCURRENT_JOBS` from config is honored via `asyncio.Semaphore`. Integration test runs the FULL graph through one fake JD with all three LLM calls (extract/score/tailor) monkeypatched.

- [ ] **Step 1: Write the failing integration test**

Write `tests/pipeline/test_graph_integration.py`:

```python
"""End-to-end integration test for the Compass pipeline with mocked LLMs."""
from datetime import date

import frontmatter
import pytest

from compass.pipeline.state import JobRequirements, JobScore, RawJob


@pytest.fixture
def mocked_llms(monkeypatch):
    """Patch all three LLM calls so the test runs without network or API key."""
    from compass.pipeline.nodes import extract, score, tailor

    async def fake_extract(jd_text: str) -> JobRequirements:
        return JobRequirements(
            required_skills=["MCP", "LangGraph", "Python"],
            nice_to_have_skills=["FastAPI"],
            years_experience=2, seniority="mid", remote_policy="hybrid",
            summary="Build agentic systems with LangGraph and MCP.",
        )

    async def fake_score(req, profile_text):
        return JobScore(
            score=4.2, reasoning="Strong MCP + LangGraph match",
            matched_skills=["MCP", "Python"], missing_skills=["LangGraph"],
            tailoring_notes="lead with production MCP work",
        )

    async def fake_tailor(*args, **kwargs):
        return "Open with the production MCP servers work and a 4-server MCP architecture."

    monkeypatch.setattr(extract, "_extract", fake_extract)
    monkeypatch.setattr(score, "_score", fake_score)
    monkeypatch.setattr(tailor, "_tailor", fake_tailor)


async def test_run_pipeline_end_to_end(temp_vault, mocked_llms):
    """Run a single fake job through the full graph; verify vault state."""
    from compass.pipeline.graph import run_pipeline

    raw_jobs = [
        RawJob(
            company="AgentCo", title="Agent Engineer",
            url="https://jobs.ashbyhq.com/agentco/test-uuid",
            source="ashby", description="Build agents at AgentCo.",
            location="NYC", date_posted=date(2026, 5, 17),
        ),
    ]
    state = await run_pipeline(raw_jobs=raw_jobs)
    assert state["jobs_processed"] == 1
    assert state["jobs_written"] == 1

    # JobNote exists
    job_files = list((temp_vault / "jobs").glob("*AgentCo*.md"))
    assert len(job_files) == 1
    loaded = frontmatter.load(job_files[0])
    assert loaded.metadata["match_score"] == 4.2
    # The polished paragraph from tailor_node is persisted to the JobNote:
    assert loaded.metadata.get("tailored_paragraph") is not None
    assert "production MCP" in loaded.metadata["tailored_paragraph"]
    # The short pitch from score_node is preserved in score_reasoning OR matched_skills logic;
    # score.tailoring_notes from the fake is not overwritten:
    assert loaded.metadata.get("score_reasoning") == "Strong MCP + LangGraph match"
    # Skills were incremented
    assert (temp_vault / "skills" / "MCP.md").exists()
    assert (temp_vault / "skills" / "LangGraph.md").exists()
    # Company was upserted
    assert (temp_vault / "companies" / "AgentCo.md").exists()


async def test_run_pipeline_skips_dedup_urls(temp_vault, mocked_llms):
    """A URL already in the vault is filtered out before the graph runs."""
    from compass.pipeline.graph import run_pipeline

    # Seed a prior write
    (temp_vault / "jobs" / "2026-05-15-AgentCo-Prior.md").write_text(
        "---\ntype: job\nurl: https://jobs.ashbyhq.com/agentco/test-uuid\ncompany: AgentCo\n"
        "title: Prior\nmatch_score: 0\nsource: ashby\ndate_found: 2026-05-15\n---\n# Prior\n"
    )
    raw_jobs = [
        RawJob(
            company="AgentCo", title="Agent Engineer",
            url="https://jobs.ashbyhq.com/agentco/test-uuid",
            source="ashby", description="...", date_posted=date(2026, 5, 17),
        ),
    ]
    state = await run_pipeline(raw_jobs=raw_jobs)
    assert state["jobs_processed"] == 0
    assert state["jobs_written"] == 0


async def test_run_pipeline_regenerates_gap_plan(temp_vault, mocked_llms):
    """After processing, master-gap-plan.md should be regenerated."""
    from compass.pipeline.graph import run_pipeline

    raw_jobs = [
        RawJob(
            company="AgentCo", title="Agent Engineer",
            url="https://jobs.ashbyhq.com/agentco/test-uuid",
            source="ashby", description="...", date_posted=date(2026, 5, 17),
        ),
    ]
    await run_pipeline(raw_jobs=raw_jobs)
    plan_path = temp_vault / "study-plans" / "master-gap-plan.md"
    assert plan_path.exists()
    assert "generated_by: gap_aggregator" in plan_path.read_text()


async def test_run_pipeline_skips_tailor_when_below_threshold(monkeypatch, temp_vault):
    """Low-score jobs are still written but tailor must not fire — verifies graph routing."""
    from compass.pipeline.graph import run_pipeline
    from compass.pipeline.nodes import extract, score, tailor

    tailor_calls = {"count": 0}

    async def fake_extract(jd_text):
        return JobRequirements(
            required_skills=["MCP"], nice_to_have_skills=[],
            years_experience=2, seniority="mid", remote_policy="hybrid",
            summary="Build agents.",
        )

    async def fake_score(req, profile_text):
        return JobScore(
            score=2.0, reasoning="weak", matched_skills=[],
            missing_skills=["MCP"], tailoring_notes="",
        )

    async def fake_tailor(*args, **kwargs):
        tailor_calls["count"] += 1
        return "should not run"

    monkeypatch.setattr(extract, "_extract", fake_extract)
    monkeypatch.setattr(score, "_score", fake_score)
    monkeypatch.setattr(tailor, "_tailor", fake_tailor)

    raw_jobs = [
        RawJob(
            company="Sample", title="Engineer",
            url="https://example.com/low-score",
            source="greenhouse", description="...", date_posted=date(2026, 5, 17),
        ),
    ]
    state = await run_pipeline(raw_jobs=raw_jobs)
    # Job still written for analysis (per spec: rejected jobs persist for eval data):
    assert state["jobs_written"] == 1
    # But tailor was skipped:
    assert tailor_calls["count"] == 0
    # And no tailored_paragraph on the JobNote:
    job_files = list((temp_vault / "jobs").glob("*Sample*.md"))
    loaded = frontmatter.load(job_files[0])
    assert loaded.metadata.get("tailored_paragraph") is None


async def test_run_pipeline_appends_to_run_log(temp_vault, mocked_llms):
    """Every run_pipeline invocation appends a row to _meta/pipeline-runs.md."""
    from compass.pipeline.graph import run_pipeline

    raw_jobs = [
        RawJob(
            company="AgentCo", title="Agent Engineer",
            url="https://jobs.ashbyhq.com/agentco/run-log-test",
            source="ashby", description="...", date_posted=date(2026, 5, 17),
        ),
    ]
    await run_pipeline(raw_jobs=raw_jobs)
    log_path = temp_vault / "_meta" / "pipeline-runs.md"
    assert log_path.exists()
    log_text = log_path.read_text()
    assert "| Timestamp |" in log_text  # header was written
    assert "| 1 |" in log_text  # one job processed
```

- [ ] **Step 2: Run to verify they fail**

Expected: 3 FAILs (run_pipeline restructure not yet in place).

- [ ] **Step 3: Restructure `compass/pipeline/graph.py`**

Replace with:

```python
"""
Compass LangGraph pipeline — main graph + orchestration.

Single-job graph: each invocation processes one RawJob via current_job. The
orchestrator `run_pipeline()` does scraping, batch-level URL dedup, parallel
graph invocations bounded by MAX_CONCURRENT_JOBS, and post-batch gap-plan
regeneration.

Graph flow (per job):
    START -> intake -> extract -> score -> reflect -> hitl ->
        (approved) -> tailor -> vault_write -> END
        (rejected) -> vault_write -> END   (low-score jobs still written for analysis)
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta

import frontmatter
from langgraph.graph import END, START, StateGraph

from compass.analysis import gap_aggregator
from compass.config import MAX_CONCURRENT_JOBS, VAULT_PATH
from compass.pipeline.nodes.extract import extract_node
from compass.pipeline.nodes.hitl import hitl_node
from compass.pipeline.nodes.intake import intake_node
from compass.pipeline.nodes.reflect import reflect_node
from compass.pipeline.nodes.score import score_node
from compass.pipeline.nodes.tailor import tailor_node
from compass.pipeline.nodes.vault_write import vault_write_node
from compass.pipeline.state import CompassState, RawJob
from compass.vault.reader import list_job_notes

logger = logging.getLogger(__name__)


def _route_after_hitl(state: CompassState) -> str:
    """If approved, run tailor; otherwise skip directly to vault_write."""
    return "tailor" if state.get("human_approved") else "vault_write"


def build_graph():
    """Build and compile the single-job Compass graph."""
    builder = StateGraph(CompassState)
    builder.add_node("intake", intake_node)
    builder.add_node("extract", extract_node)
    builder.add_node("score", score_node)
    builder.add_node("reflect", reflect_node)
    builder.add_node("hitl", hitl_node)
    builder.add_node("tailor", tailor_node)
    builder.add_node("vault_write", vault_write_node)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "extract")
    builder.add_edge("extract", "score")
    builder.add_edge("score", "reflect")
    builder.add_edge("reflect", "hitl")
    builder.add_conditional_edges("hitl", _route_after_hitl, {
        "tailor": "tailor",
        "vault_write": "vault_write",
    })
    builder.add_edge("tailor", "vault_write")
    builder.add_edge("vault_write", END)

    return builder.compile()


def _vault_url_set() -> set[str]:
    """Build the set of URLs already in the vault — ONCE per batch.

    A malformed frontmatter file is logged (NOT silently dropped from the set).
    Without the log, a corrupt note silently causes a duplicate write next run.
    """
    urls: set[str] = set()
    for path in list_job_notes():
        try:
            post = frontmatter.load(path)
        except Exception as e:
            logger.warning("dedup: failed to parse %s — %s", path.name, e)
            continue
        url = post.metadata.get("url")
        if isinstance(url, str):
            urls.add(url)
    return urls


def _initial_state(job: RawJob) -> CompassState:
    return {
        "raw_jobs": [],
        "current_job": job,
        "extracted_requirements": None,
        "score_result": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


def _langfuse_config() -> dict:
    """Return a LangGraph config dict with the Langfuse callback if usable.

    Returns {} when Langfuse env is unset or langfuse fails to import — the
    pipeline never blocks on observability. This wires traces from Phase 0.B
    onward so by 2.B (public-trace polish) we have history to show.
    """
    from compass.config import LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

    if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
        return {}
    try:
        from langfuse.langchain import CallbackHandler  # noqa: PLC0415

        handler = CallbackHandler(
            host=LANGFUSE_HOST,
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
        )
        return {"callbacks": [handler]}
    except Exception as e:
        logger.warning("langfuse: failed to init callback, continuing without traces — %s", e)
        return {}


async def _process_one(graph, job: RawJob, sem: asyncio.Semaphore) -> CompassState:
    async with sem:
        try:
            return await graph.ainvoke(_initial_state(job), config=_langfuse_config())
        except Exception as e:
            # logger.exception preserves the traceback to stderr; the string version
            # below is still aggregated into state for the run summary.
            logger.exception("pipeline: graph crashed on %s", job.url)
            return {**_initial_state(job), "errors": [f"graph: {type(e).__name__}: {e}"]}


async def run_pipeline(raw_jobs: list[RawJob] | None = None) -> CompassState:
    """Scrape (or accept) jobs, dedup, run per-job graph, regenerate gap plan."""
    start = time.monotonic()
    if raw_jobs is None:
        raw_jobs = await _scrape_all()

    seen_urls = _vault_url_set()
    fresh = [j for j in raw_jobs if j.url not in seen_urls]
    dropped = len(raw_jobs) - len(fresh)
    if dropped:
        logger.info("pipeline: dropping %d/%d jobs already in vault", dropped, len(raw_jobs))

    graph = build_graph()
    sem = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
    results = await asyncio.gather(*[_process_one(graph, j, sem) for j in fresh])

    aggregate = {
        "raw_jobs": raw_jobs,
        "current_job": None,
        "extracted_requirements": None,
        "score_result": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": any(r.get("vault_written") for r in results),
        "jobs_processed": len(fresh),
        "jobs_written": sum(int(bool(r.get("vault_written"))) for r in results),
        "errors": [e for r in results for e in r.get("errors", [])],
    }

    if aggregate["jobs_written"] > 0:
        gap_aggregator.regenerate(write=True)

    duration_s = time.monotonic() - start
    _append_run_log(aggregate, duration_s)
    unknown_count = _count_unknown_skills_seen_this_run(start)
    logger.info(
        "pipeline: processed=%d written=%d errors=%d unknown_skills_seen=%d duration=%.1fs",
        aggregate["jobs_processed"], aggregate["jobs_written"],
        len(aggregate["errors"]), unknown_count, duration_s,
    )
    return aggregate


def _count_unknown_skills_seen_this_run(start_monotonic: float) -> int:
    """Count rows appended to the unknown-skills log since `start_monotonic`.

    Cheap heuristic: count lines whose timestamp is >= the run start wall-clock.
    Used only to surface a "review me" hint to the user; not a metric for scoring.
    """
    log_path = VAULT_PATH / "_meta" / "unknown-skills-log.md"
    if not log_path.exists():
        return 0
    # Convert monotonic start to wall-clock approximation
    approx_wall = datetime.now() - timedelta(seconds=time.monotonic() - start_monotonic)
    cutoff = approx_wall.isoformat(timespec="seconds")
    return sum(
        1 for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("[") and line[1:20] >= cutoff[:19]
    )


def _append_run_log(state: CompassState, duration_s: float) -> None:
    """Append one row per run to `_meta/pipeline-runs.md` — forensic trail + portfolio artifact."""
    log_path = VAULT_PATH / "_meta" / "pipeline-runs.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.write_text(
            "# Pipeline Run Log\n\n"
            "| Timestamp | Processed | Written | Errors | Duration |\n"
            "|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    ts = datetime.now().isoformat(timespec="seconds")
    row = (
        f"| {ts} | {state['jobs_processed']} | {state['jobs_written']} | "
        f"{len(state['errors'])} | {duration_s:.1f}s |\n"
    )
    with log_path.open("a", encoding="utf-8") as f:
        f.write(row)


async def _scrape_all() -> list[RawJob]:
    """Scrape all configured sources concurrently, interleave round-robin, cap.

    Interleaving prevents a single high-volume source from exhausting
    MAX_JOBS_PER_RUN before quieter sources get a chance.
    """
    from compass.config import ASHBY_BOARDS, GREENHOUSE_BOARDS, LEVER_COMPANIES, MAX_JOBS_PER_RUN
    from compass.scrapers.ashby import scrape_ashby_many
    from compass.scrapers.greenhouse import scrape_greenhouse_many
    from compass.scrapers.lever import scrape_lever_many

    gh, lv, ash = await asyncio.gather(
        scrape_greenhouse_many(GREENHOUSE_BOARDS),
        scrape_lever_many(LEVER_COMPANIES),
        scrape_ashby_many(ASHBY_BOARDS),
    )
    interleaved: list[RawJob] = []
    iters = [iter(gh), iter(lv), iter(ash)]
    while iters:
        next_iters = []
        for it in iters:
            try:
                interleaved.append(next(it))
                next_iters.append(it)
            except StopIteration:
                pass
        iters = next_iters
    return interleaved[:MAX_JOBS_PER_RUN]


if __name__ == "__main__":
    result = asyncio.run(run_pipeline())
    print(
        f"Processed: {result['jobs_processed']} | "
        f"Written: {result['jobs_written']} | "
        f"Errors: {len(result['errors'])}"
    )
```

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest tests/pipeline/ -v
```

Expected: all pipeline tests PASSED (extract, score, tailor, routing, intake, vault_write, graph_integration).

- [ ] **Step 5: Run full suite to verify nothing else broke**

```bash
uv run pytest -q
```

Expected: 27 (Phase 0.A) + new Phase 0.B tests, all passing.

- [ ] **Step 6: Commit**

```bash
git add compass/pipeline/graph.py tests/pipeline/test_graph_integration.py
git commit -m "feat(pipeline): restructure run_pipeline (batch dedup, serial graph, gap_aggregator post-hook)"
```

---

## Task 9: Live end-to-end verification + tag `phase-0b-pipeline-mvp`

**Files:** none (verification only)

The first test against real LLM calls. Requires `OPENROUTER_API_KEY` in `.env`. Will write 5 real JobNotes to `compass-vault/jobs/`. Cost estimate: ~$0.10.

- [ ] **Step 1: Sanity check ruff + format**

```bash
uv run ruff check compass tests && uv run ruff format --check compass tests
```

Expected: clean.

- [ ] **Step 2: Live pipeline run on 5 AgentCo jobs (small batch)**

```bash
cd ~/Documents/compass
MAX_JOBS_PER_RUN=5 \
  GREENHOUSE_BOARDS= \
  LEVER_COMPANIES= \
  ASHBY_BOARDS=agentco \
  uv run python -m compass.pipeline.graph
```

Expected:
- Exits with "Processed: K | Written: K | Errors: 0" where K ≤ 5
- **K may be < 5 if some AgentCo URLs are already in the vault from earlier runs** (dedup drops them). To force a full 5-job run, delete recent `compass-vault/jobs/2026-*AgentCo*` files first, OR use a different `ASHBY_BOARDS` slug (e.g. `botco`, `traversal`, `acme`)
- K new files in `compass-vault/jobs/2026-*` matching the Ashby slug used
- `compass-vault/study-plans/master-gap-plan.md` has been regenerated with a non-empty Top 10 table

- [ ] **Step 3: Spot-check one written JobNote**

```bash
ls -la ~/Documents/compass-vault/jobs/2026-*AgentCo* | head -3
cat ~/Documents/compass-vault/jobs/$(ls ~/Documents/compass-vault/jobs/2026-*AgentCo* | head -1 | xargs basename) | head -30
```

Expected: frontmatter has `match_score`, `skills_required`, `skills_matched`, `skills_missing` populated; body has the `# AgentCo — <Title>` heading + `jd_summary`.

- [ ] **Step 4: Verify master-gap-plan.md regenerated**

```bash
cat ~/Documents/compass-vault/study-plans/master-gap-plan.md | head -25
```

Expected: top-of-file `last_generated:` timestamp is now (within last 5 min), top-10 table has rows.

- [ ] **Step 5: Confirm gap_aggregator + assess_skills MCP-style smoke**

```bash
VAULT_PATH=~/Documents/compass-vault OPENROUTER_API_KEY=stub \
  uv run python -m compass.analysis.gap_aggregator 2>&1 | tail -10
```

Expected: prints top 10 gaps including some AgentCo-relevant skills (LangGraph, MCP, Python, etc. depending on what the JDs required).

- [ ] **Step 6: Full pytest run one more time**

```bash
uv run pytest -q
```

Expected: all tests still passing.

- [ ] **Step 7: Tag Phase 0.B**

```bash
git tag -a phase-0b-pipeline-mvp -m "Phase 0.B complete: pipeline scrapes, scores, writes; gap plan regenerates"
```

- [ ] **Step 8: Confirm Phase 0.B definition of done**

Verify each of the following:
- ✅ `MAX_JOBS_PER_RUN=5 uv run python -m compass.pipeline.graph` completes without unhandled exceptions
- ✅ ≥ 5 valid JobNote files in `compass-vault/jobs/` with Pydantic-passing frontmatter
- ✅ `master-gap-plan.md` regenerated with non-empty top-10
- ✅ All pytest tests passing (Phase 0.A 27 + Phase 0.B tests)
- ✅ Ruff lint + format clean
- ✅ Skill notes for required skills exist in `compass-vault/skills/` with incremented `appears_in_jobs` counters

If all six are checked, Phase 0.B is done.

---

## Quick reference

| Action | Command |
|---|---|
| Run all tests | `uv run pytest -q` |
| Run pipeline tests only | `uv run pytest tests/pipeline/ -v` |
| Live pipeline (small batch) | `MAX_JOBS_PER_RUN=5 ASHBY_BOARDS=agentco uv run python -m compass.pipeline.graph` |
| Live pipeline (full set) | `uv run python -m compass.pipeline.graph` |
| Regen gap plan only | `uv run python -m compass.analysis.gap_aggregator` |
| Ruff + format | `uv run ruff check compass tests && uv run ruff format compass tests` |

**Total expected LoC:** ~750 net new across 14 files (8 production + 6 test). Increase from initial 600 LoC budget reflects the audit additions: Langfuse callback wiring, `_meta/pipeline-runs.md` log, unknown-skills review log, below-threshold integration test.

**If a step fails:** stop, read the error, fix the smallest thing that addresses it, re-run. Do NOT modify tests to make them pass — that's a red flag the implementation is wrong, not the test.

---

## Deferred edges revisited

| Edge | How this plan handles it |
|---|---|
| `update_skill_note` "language" fallback for unknown skills | `extract_node._normalize_skill_list()` drops unknown skills from requirements BUT records each to `_meta/unknown-skills-log.md` so the user can review and graduate/synonymize/ignore weekly |
| O(N) URL-dedup scan per write | `run_pipeline._vault_url_set()` builds the set ONCE; logs warnings on malformed frontmatter instead of silent skip |
| `taxonomy.py @lru_cache` brittleness | `compass/llm.py` does NOT cache — reads `EXTRACT_MODEL` / `SCORE_MODEL` / `OPENROUTER_API_KEY` at every `get_model_id()` / `_get_model()` call |
| `_safe_segment` collisions | No new file-creation paths added — `vault_write_node` only calls `write_job_note` (idempotent on URL) + `update_skill_note` (idempotent on canonical name) + `write_company_note` (idempotent on company) |
| In-graph fan-out vs external loop | `run_pipeline` loops over fresh jobs externally with `asyncio.Semaphore` for bounded concurrency; graph stays single-job |
| HiTL auto-approve | `hitl_node` docstring is explicit; Phase 1.B will add real `interrupt()` + `AsyncSqliteSaver` |

## Audit-pass additions (Phase 0.B-internal improvements)

| Addition | Where | Rationale |
|---|---|---|
| Langfuse callback wiring with graceful degradation | `compass/pipeline/graph._langfuse_config()` | Resolves CLAUDE.md drift; accumulates trace history from day one for the 2.B public-trace polish |
| `_meta/pipeline-runs.md` log | `compass/pipeline/graph._append_run_log()` | Forensic trail for Modal cron debugging + portfolio screenshot of "history of runs" |
| `_meta/unknown-skills-log.md` (review queue) | `compass/pipeline/nodes/extract._record_unknown_skills()` | Don't lose JD-market signal about taxonomy gaps |
| Below-threshold integration test | `tests/pipeline/test_graph_integration.py` | Verifies conditional `hitl → vault_write` edge (was only tested at unit level before) |
| Explicit `make_agent` signature (no `**kwargs`) | `compass/llm.make_agent` | Typos surface at type-check time; reads as deliberate API not AI-generated |
| `logger.exception` in `_process_one` | `compass/pipeline/graph._process_one` | Preserves tracebacks instead of stringifying them into state |
| `_MAX_JD_CHARS_FOR_TAILOR = 6000` constant | `compass/pipeline/nodes/tailor.py` | Named magic number with rationale |
| `# TODO(Phase 1.A)` on company `tier="unknown"` | `compass/pipeline/nodes/vault_write.py` | Explicit deferred-work marker so a code reader doesn't think it's broken |

## Future-debt to track for Phase 1.A / 1.B

| Issue | When it bites | Where to fix |
|---|---|---|
| `update_skill_note` re-reads + re-writes every skill file per increment (~500 file ops per 50-job batch) | Becomes hot at >100 jobs/run | Phase 1.A: batch increments before writing |
| `_vault_url_set` parses every job file's frontmatter each run | Becomes the long-pole at >1000 vault notes | Phase 1.B: replace with a SQLite index alongside the HiTL state store |
| Single-job graph + external loop will need `AsyncSqliteSaver` + per-job `thread_id` | When real HiTL `interrupt()` is wired | Phase 1.B per spec |
| Company `tier=unknown` and `roles_seen=1` never update | Cosmetic noise in the vault | Phase 1.A application-tracking refactor (already TODO-tagged) |
