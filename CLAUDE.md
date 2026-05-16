# CLAUDE.md — Compass: Career Coach

> This file governs how Claude Code and any MCP-capable agent thinks about and works inside this repository. Read this before touching anything.

---

## What Compass Is

Compass is an agentic career coaching system. It finds job postings, scores them against a candidate profile, identifies skill gaps, generates study plans, and produces tailored resume variants. It is NOT an auto-apply bot — it is a research and preparation tool that keeps a human in the loop for every application decision.

The system has two sides:
1. **The pipeline** (this repo) — Python, LangGraph, Pydantic, Langfuse, ATS scrapers. Does the work.
2. **The vault** (`~/Documents/compass-vault/`) — Obsidian markdown. Stores everything durably.

---

## Repository Layout

```
compass/
├── CLAUDE.md                  # This file — read first
├── docs/
│   ├── ARCHITECTURE.md        # Full system design — read before coding
│   ├── STATUS.md              # What's built vs. planned — update as you ship
│   └── RUNBOOK.md             # How to run everything end to end
├── compass/
│   ├── pipeline/              # LangGraph pipeline nodes and graph definition
│   │   ├── graph.py           # Main graph definition
│   │   ├── nodes/             # One file per node
│   │   └── state.py           # TypedDict state schema
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
│   │   ├── dataset.py         # Labeled dataset management
│   │   └── runner.py          # Nightly eval runs
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

# Vault
VAULT_PATH=/Users/akash/Documents/compass-vault

# Pipeline
MAX_JOBS_PER_RUN=50
SCORE_THRESHOLD=3.5        # Only write jobs scoring above this to vault
HITL_TIMEOUT_HOURS=4       # Hours to wait for human approval before auto-cancel
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

**Human-in-the-loop:** Use LangGraph's `interrupt()` for the human approval step. The interrupt saves state, waits for external input, and resumes. Do not use sleep loops.

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

Tools to expose:
- `search_jobs(query: str) -> list[JobNote]` — semantic search over vault job notes
- `get_skill_gaps(job_id: str) -> list[str]` — compare JD skills to skill-inventory.md
- `score_jd(jd_text: str) -> JobScore` — score a raw JD against the candidate profile
- `get_study_plan(skills: list[str]) -> StudyPlan` — generate a learning roadmap
- `add_application(job_id: str) -> None` — mark a job as applied

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
