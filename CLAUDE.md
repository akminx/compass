# CLAUDE.md — Compass: Career Coach

> This file governs how Claude Code and any MCP-capable agent thinks about and works inside this repository. Read this before touching anything.

---

## What Compass Is

Compass is an agentic career coaching system. It finds job postings, scores them against a candidate profile, identifies skill gaps, generates study plans, and produces tailored resume variants. It is NOT an auto-apply bot — it is a research and preparation tool that keeps a human in the loop for every application decision.

The system has three sides:
1. **The pipeline** (this repo) — Python, LangGraph, Pydantic AI, Langfuse, ChromaDB, ATS scrapers. Does the work.
2. **The product vault** (`~/Documents/compass-vault/`) — Obsidian markdown. Schema-enforced. Agent-written.
3. **The learning vault** (`~/Documents/learning-vault/`) — Free-form personal notes. Read-only to the agent, but the source of evidence for skill grading via `learning-vault://` URIs.

The `compass.vault.learning_bridge` module resolves those URIs; the `compass.analysis.skill_assessor` reads the evidence and regrades skills in compass-vault accordingly. This loop is what makes the system actively reflect the JD-market skill stack.

## Portfolio Context (read this — it shapes every decision)

This project exists to close specific skill gaps and produce a concrete interview story. The target roles are **tier-2 product engineering at agentic startups** and **tier-3 big-tech L3/L4 agentic roles**.

**FDE-track roles are out of scope for now** — handled by the `fde-eng` role-family cap rather than a hard filter, so the pipeline still surfaces strong-stack FDE matches without auto-routing them to apply-tier.

**What this project must demonstrate by the time it ships (Phase 2 complete per spec):**
- **LangGraph**: stateful graph, conditional edges, `interrupt()` for HiTL, `AsyncSqliteSaver` checkpointing (Phase 1.B)
- **RAG pipeline**: Chroma vector store, sentence-transformers embeddings, semantic retrieval over `_profile/skill-inventory.md` (Phase 1.B — replaces string-injection of MVP)
- **Langfuse**: self-hosted, full traces, cost per run, LLM-as-judge eval scoring (Phase 0.B + 2.A)
- **Pydantic AI**: structured extraction with typed schemas (Phase 0.B)
- **MCP server**: vault + pipeline + assessor + gap aggregator exposed as tools (already implemented)
- **Eval harness**: 30+ labeled JDs, score MAE, skill extraction recall, regression detection (Phase 2.A)
- **Modal**: serverless cron for daily scrape + weekly assessor (Phase 1.B)
- **Skill assessor loop** (unique angle): adversarial-grader Pydantic AI agent that reads evidence URIs from `learning-vault://` and regrades skills — meta-loop that makes Compass a real career coach not a job aggregator (already implemented)
- **Production patterns**: HiTL with externally-enforced timeout, parallel job processing with semaphore, secrets-in-Modal-Secrets, pre-commit secret scanning

**The interview story:** "I built the system I'm using to run my own job search — and I built an agent inside it that grades my skills against the live job market and tells me what to study next." The public Langfuse trace URL + master-gap-plan screenshot in the README are the headline portfolio signals.

**Authoritative spec:** `docs/superpowers/specs/2026-05-17-compass-mvp-to-portfolio-ship-design.md`. Phase plan, scope, and definition of done live there. This CLAUDE.md is the day-to-day conventions; the spec is the contract.

---

## Repository Layout

```
compass/
├── CLAUDE.md                  # This file — read first
├── docs/
│   ├── ROADMAP.md             # Master project plan — phases, sub-plans, skills closed
│   ├── ARCHITECTURE.md        # Full system design — read before coding
│   ├── STATUS.md              # What's built vs. planned — update as you ship
│   └── RUNBOOK.md             # How to run everything end to end
├── compass/
│   ├── pipeline/              # LangGraph pipeline nodes and graph definition
│   │   ├── graph.py           # Main graph — build_graph() + run_pipeline()
│   │   ├── nodes/             # One file per node
│   │   └── state.py           # TypedDict state schema (CompassState)
│   ├── rag/                   # RAG layer — Chroma index + semantic retriever
│   │   ├── indexer.py         # Build/refresh Chroma index from vault skills/
│   │   └── retriever.py       # Retrieve relevant profile chunks for a JD
│   ├── hitl/                  # HiTL timeout infrastructure
│   │   ├── state_store.py     # SQLite table tracking pending interrupts + timestamps
│   │   └── timeout_checker.py # Modal cron — resumes timed-out graph checkpoints
│   ├── scrapers/              # ATS API scrapers
│   │   ├── greenhouse.py
│   │   ├── lever.py
│   │   ├── ashby.py
│   │   └── jobspy_wrapper.py
│   ├── vault/                 # Obsidian vault read/write
│   │   ├── reader.py          # Read vault notes
│   │   ├── writer.py          # Write vault notes
│   │   └── schemas.py         # Frontmatter Pydantic schemas
│   ├── mcp_server/            # MCP server exposing vault + pipeline as tools
│   │   └── server.py
│   ├── evals/                 # Eval harness
│   │   ├── dataset.py         # Labeled dataset (EvalRecord schema)
│   │   └── runner.py          # Score MAE + skill recall + context recall
│   ├── analysis/              # Cross-job intelligence
│   │   ├── gap_aggregator.py  # Aggregate missing skills, ranked by frequency × match_score × tier_weight
│   │   └── skill_assessor.py  # Regrade skills against evidence URIs using rubric (adversarial grader)
│   ├── vault/
│   │   ├── reader.py
│   │   ├── writer.py
│   │   ├── schemas.py         # Pydantic frontmatter schemas — extended with SkillAssessment + GapPlanEntry
│   │   ├── taxonomy.py        # Load + normalize against compass-vault/_meta/skill-taxonomy.md
│   │   └── learning_bridge.py # Resolve learning-vault:// URIs into evidence artifacts
│   └── config.py              # All config, loaded from .env
├── tests/                     # Pytest tests
├── scripts/                   # One-off setup and maintenance scripts
├── pyproject.toml             # uv project definition
├── .env.example               # Environment variable template
└── .gitignore
```

---

## Environment Setup

```bash
# Clone and set up
git clone https://github.com/akminx/compass
cd compass
uv sync

# Copy and fill in env vars
cp .env.example .env
# Edit .env with your keys

# Run Langfuse locally
docker compose up -d

# Run tests
uv run pytest tests/ -q

# Run the pipeline once
uv run python -m compass.pipeline.graph
```

---

## Environment Variables

```env
# LLM
OPENROUTER_API_KEY=sk-or-v1-...
COMPASS_MODEL=anthropic/claude-sonnet-4-6

# Langfuse (self-hosted)
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...

# Vaults
VAULT_PATH=/Users/akmini/Documents/compass-vault           # agent-owned product vault
LEARNING_VAULT_PATH=/Users/akmini/Documents/learning-vault # read-only, source of evidence URIs

# RAG
CHROMA_PATH=~/.compass/chroma          # Persistent Chroma index for skill notes
EMBEDDING_MODEL=all-MiniLM-L6-v2       # sentence-transformers model name

# HiTL
HITL_STATE_DB=~/.compass/hitl.db       # SQLite for pending interrupt tracking
HITL_TIMEOUT_HOURS=4                   # Hours before auto-cancel

# Pipeline
MAX_JOBS_PER_RUN=50
SCORE_THRESHOLD=3.5                    # Only write jobs scoring above this to vault
MAX_CONCURRENT_JOBS=5                  # Parallel graph invocations per run
```

---

## Coding Standards

**Language:** Python 3.12+. Use `uv` for all package management — never `pip install` directly.

**Type hints:** Required everywhere. Use `TypedDict` for LangGraph state. Use Pydantic models for all external data (JD extraction, vault frontmatter, API responses).

**Async:** Use `async/await` for all LLM calls and I/O. Use `asyncio.gather()` for parallel scoring.

**Error handling:** Every tool and node must return a structured result — never let exceptions propagate silently. Pattern:
```python
{"success": True, "data": ..., "error": None}
{"success": False, "data": None, "error": "description of what went wrong"}
```

**Imports:** Absolute imports only. No `from . import`.

**Tests:** Every scraper, vault writer, and eval function needs a test. Nodes need integration tests. Run `uv run pytest` before committing.

**Commits:** Conventional commits — `feat:`, `fix:`, `docs:`, `test:`, `refactor:`. One logical change per commit.

---

## LangGraph Conventions

**State schema** is defined in `compass/pipeline/state.py` as a `TypedDict`. All nodes receive the full state and return partial updates — only return keys you changed.

**Nodes** live in `compass/pipeline/nodes/` — one file per node. Each node is an `async def` function that takes `CompassState` and returns `dict`.

**The main graph** is in `compass/pipeline/graph.py`. Define the graph here, wire nodes and edges, export a compiled graph.

**Tracing:** Every graph invocation must include the Langfuse callback handler:
```python
from langfuse.callback import CallbackHandler
handler = CallbackHandler()
result = await graph.ainvoke(state, config={"callbacks": [handler]})
```

**Human-in-the-loop:** Use LangGraph's `interrupt()` for the human approval step. The interrupt checkpoints graph state and suspends — it does NOT have a built-in timer. The timeout is enforced externally: `compass/hitl/timeout_checker.py` is a Modal cron that polls `HiTLStateStore` every 30 minutes and resumes timed-out threads via `graph.ainvoke(Command(resume={"approved": False}), config={"configurable": {"thread_id": ...}})`. The `hitl_node` receives the actual LangGraph `thread_id` via its `config: RunnableConfig` parameter — not from state.

**Graph compilation:** Never compile `build_graph()` at module level. Always compile inside `run_pipeline()` where the `AsyncSqliteSaver` checkpointer is available. A graph compiled without a checkpointer silently breaks `interrupt()`.

---

## Vault Conventions

The vault is at `$VAULT_PATH` (from .env). It is a directory of markdown files with YAML frontmatter.

**Never** write raw markdown manually — always use the `vault/writer.py` functions which enforce the frontmatter schema and prevent malformed notes.

**Never** delete vault files programmatically — the vault is append-only from the pipeline's perspective. Humans delete notes manually in Obsidian.

**Frontmatter schemas** are Pydantic models in `vault/schemas.py`. Every note type (job, skill, company, application) has a schema. Validate before writing.

**File naming convention:**
- Jobs: `jobs/YYYY-MM-DD-CompanyName-RoleTitle.md`
- Applications: `applications/YYYY-MM-DD-CompanyName-RoleTitle.md`
- Skills: `skills/SkillName.md` (create once, update in place)
- Companies: `companies/CompanyName.md` (create once, update in place)

---

## ATS Scraper Conventions

**Use public APIs first** — Greenhouse, Lever, Ashby all have unauthenticated public endpoints. No ToS issues, no rate limits to worry about.

**JobSpy is a fallback** — useful for aggregation but LinkedIn rate-limits aggressively. Design gracefully: if LinkedIn returns 0 results, log it and continue.

**Deduplication:** Hash on `(company, title, url)`. If a job already exists in the vault (check by URL), skip it rather than overwriting. Log skips.

**Rate limiting:** Add 1-2 second delays between ATS API calls. Be a good citizen.

---

## MCP Server

The MCP server in `compass/mcp_server/server.py` exposes the vault and pipeline as tools for Claude Code and Cursor.

Tools exposed:
- `score_jd(jd_text)` — score a raw JD against the profile (no vault write)
- `search_jobs(query, limit)` — substring search over vault job notes
- `get_skill_gaps(job_id)` — matched + missing skills for a job
- `get_profile(section)` — read a `_profile/` file (resume, skill-inventory, preferences, etc.)
- `read_learning_artifact(uri)` — resolve a `learning-vault://` URI
- `assess_skills(scope=None)` — regrade evidence-backed skills with the adversarial rubric
- `regenerate_gap_plan()` — recompute master-gap-plan.md
- `get_master_gap_plan()` — read current top gaps
- `suggest_evidence(skill, search_terms)` — surface candidate learning-vault files to cite
- `list_canonical_skills()` — enumerate the taxonomy
- `tailor_resume(job_id)` — tailoring suggestions for a specific job
- `add_application(job_id)` — create an applications/ note

Run the MCP server:
```bash
uv run python -m compass.mcp_server.server
```

Add to Claude Code's MCP config:
```json
{
  "mcpServers": {
    "compass": {
      "command": "uv",
      "args": ["run", "python", "-m", "compass.mcp_server.server"],
      "cwd": "/path/to/compass"
    }
  }
}
```

---

## Common Tasks (Slash Commands)

When working in Claude Code on this repo, these are the standard tasks:

**Run the full pipeline once:**
```
Run the Compass pipeline: scrape jobs, score against profile, write results to vault. Use the graph in compass/pipeline/graph.py. Log all Langfuse traces.
```

**Add a new ATS scraper:**
```
Add a scraper for [ATS name]. Follow the pattern in compass/scrapers/greenhouse.py. Must use the public unauthenticated API endpoint, return a list of RawJob Pydantic objects, handle rate limiting, and have a pytest test.
```

**Run the eval harness:**
```
Run the eval harness in compass/evals/runner.py against the labeled dataset in compass/evals/dataset.json. Log results to Langfuse. Print a summary table of precision, cost per run, and tokens per node.
```

**Update the vault schema:**
```
Update the frontmatter schema for [note type] in compass/vault/schemas.py. Also update the writer function in compass/vault/writer.py to use the new schema. Run tests after.
```

**Score a specific job:**
```
Score this job description against the candidate profile in the vault. [paste JD]. Return the score, reasoning, matched skills, missing skills, and a one-paragraph resume tailoring suggestion.
```

---

## What the Agent Can Do Autonomously
- Read any file in the repo
- Write to `compass/` Python files
- Write to `tests/`
- Run `uv run pytest`
- Run `uv run python -m compass...` scripts
- Read vault files

## What Requires Human Confirmation
- Modifying `.env` or any secrets
- Deleting any file
- Committing to git
- Writing to the vault (unless explicitly asked to run the pipeline)
- Installing new packages (`uv add <package>` — ask first)
- Changing the vault schema (high impact — affects all existing notes)
