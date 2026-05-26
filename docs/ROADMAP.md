# Compass — Project Roadmap

> **How to use this doc:** This is the single source of truth for where Compass is, where it's going, and what comes next. Read this at the start of any work session. Each phase links to a detailed sub-plan. Update the status column as things ship.

---

## North Star

Ship a working agentic job search pipeline that runs daily, produces real Langfuse traces, and closes 7 portfolio skill gaps simultaneously. The interview story: *"I built the system I'm using to run my own job search."*

**Brag-worthy definition:** A recruiter can clone the repo, run `uv sync && docker compose up -d && uv run python -m compass.pipeline.graph`, and watch real jobs flow through a LangGraph pipeline with Langfuse traces appearing at `localhost:3000`. The README has a live public trace URL and a precision-vs-cost chart.

---

## Phase Summary

| Phase | Goal | Status | Sub-plan |
|---|---|---|---|
| 0 — Foundation | Scaffold, docs, vault setup | ✅ Done | — |
| 1 — Data Layer | Scrapers + vault writers working + tests passing | ⬜ Up next | [Phase 1 plan](superpowers/plans/phase-1-data-layer.md) |
| 2 — Core Pipeline | First end-to-end run: scrape → score → vault write | ⬜ Upcoming | [Phase 2 plan](superpowers/plans/phase-2-core-pipeline.md) |
| 3 — Intelligence | HiTL, eval harness, parallel processing, aggregate gap analyzer + master study plan | ⬜ Upcoming | [Phase 3 plan](superpowers/plans/phase-3-intelligence.md) |
| 4 — Portfolio Polish | MCP server, Modal deployment, public trace URL, README | ⬜ Upcoming | [Phase 4 plan](superpowers/plans/phase-4-polish.md) |
| 5 — Live & Learning | Daily use, MLflow, blog post | ⬜ Upcoming | — |

**Amendments plan** (cross-phase architectural decisions already designed):
→ [`docs/superpowers/plans/2026-05-16-architecture-amendments.md`](superpowers/plans/2026-05-16-architecture-amendments.md)

---

## Phase 0 — Foundation ✅

**Goal:** Everything needed to start coding is in place.

**What was done:**
- Repo scaffolded (`uv init`, directory structure, `pyproject.toml`)
- All architecture decisions made and documented (`docs/ARCHITECTURE.md`)
- Three architectural amendments designed, peer-reviewed, and approved (`docs/superpowers/plans/2026-05-16-architecture-amendments.md`)
  - RAG layer: Chroma + sentence-transformers for semantic skill retrieval
  - HiTL timeout: SQLite state store + Modal cron (externally enforced, not a sleep loop)
  - Parallel processing: `asyncio.gather` + semaphore, single shared checkpointer
- Vault seeded: profile docs copied into `compass-vault/_profile/`, playbooks in `_meta/playbooks/`
- `CLAUDE.md` written with portfolio context, coding standards, vault conventions
- `docs/ROADMAP.md` (this file) created

**Definition of done:** ✅ Complete

---

## Phase 1 — Data Layer

**Goal:** Real job data flows in, gets normalized, and lands cleanly in the vault. Tests pass.

**Why first:** Everything else depends on having real `RawJob` objects to process. Scrapers are also the simplest isolated units — good for building test habits before the pipeline gets complex.

**Deliverables:**
- [ ] Greenhouse scraper — public API → `list[RawJob]`, rate limited, tests passing
- [ ] Lever scraper — same
- [ ] Ashby scraper — same
- [ ] JobSpy wrapper — supplemental, graceful fallback when LinkedIn rate-limits
- [ ] Vault writer — `write_job_note()`, `update_skill_note()`, `write_company_note()` with frontmatter validation
- [ ] Vault reader — `read_skill_inventory()`, `read_profile_section()`
- [ ] RAG indexer — `build_index()` populates Chroma from `skills/*.md`, idempotent
- [ ] `uv run pytest tests/test_scrapers.py tests/test_vault.py tests/test_rag.py` all green

**Definition of done:** Running `uv run python -c "from compass.scrapers.greenhouse import scrape_greenhouse; import asyncio; jobs = asyncio.run(scrape_greenhouse('databricks')); print(f'{len(jobs)} jobs scraped')"` returns real jobs. Running `uv run pytest` is all green.

**Sub-plan:** [`docs/superpowers/plans/phase-1-data-layer.md`](superpowers/plans/phase-1-data-layer.md) ← *to be written before starting*

**Brag moment after Phase 1:** "I have scrapers hitting Greenhouse, Lever, and Ashby public APIs, normalizing into Pydantic models, with full test coverage." Not flashy but solid. The foundation that makes everything else real.

---

## Phase 2 — Core Pipeline

**Goal:** First end-to-end run — a real job goes from scraper through the full LangGraph pipeline and lands in the vault as a structured note with a Langfuse trace.

**Why second:** Once scrapers work, wire the pipeline. No HiTL yet — just `START → intake → extract → score → vault_write → END`. Get the happy path working before adding complexity.

**Deliverables:**
- [ ] Langfuse self-hosted running at `localhost:3000` (Docker)
- [ ] `extract_node` — Pydantic AI extracts `JobRequirements` from JD text, traced
- [ ] RAG retriever — `retrieve_profile_context()` returns relevant skill chunks
- [ ] `score_node` — retrieves context via RAG, scores with LLM, returns `JobScore`, traced
- [ ] `reflection_node` — re-scores borderline jobs (3.0–4.0) with stricter rubric
- [ ] `vault_write_node` — writes `JobNote` with full frontmatter, updates skill + company notes, appends to agent-log
- [ ] Graph wired: `START → intake → extract → score → [reflect] → vault_write → END`
- [ ] `AsyncSqliteSaver` checkpointer in place (required for HiTL in Phase 3)
- [ ] One complete pipeline run with real jobs, real Langfuse traces visible

**Definition of done:** Running `uv run python -m compass.pipeline.graph` scrapes real jobs, runs them through the pipeline, writes at least one job note to the vault, and Langfuse shows a trace with cost per run and tokens per node.

**Sub-plan:** [`docs/superpowers/plans/phase-2-core-pipeline.md`](superpowers/plans/phase-2-core-pipeline.md) ← *to be written before starting*

**Brag moment after Phase 2:** "I have a working LangGraph pipeline with Pydantic AI extraction, RAG-powered scoring against my skill profile, and full Langfuse traces showing cost per run." This is already a top-tier portfolio signal. Most candidates have never run a real LangGraph pipeline with real traces.

---

## Phase 3 — Intelligence Layer

**Goal:** The system gets smart — HiTL approval flow works, evals measure whether scoring is accurate, parallel processing handles real volume.

**Deliverables:**
- [ ] HiTL state store — `HiTLStateStore` SQLite tracking pending interrupts with timestamps
- [ ] `hitl_node` — `interrupt()` pause with `RunnableConfig` thread_id injection, writes to state store
- [ ] Modal timeout checker — cron every 30 min, resumes timed-out threads via `Command(resume=...)`
- [ ] `tailor_node` — resume tailoring suggestions + cover note template for approved jobs
- [ ] Parallel job processing — `asyncio.gather` with semaphore, shared checkpointer
- [ ] Eval dataset — 30 labeled `(JD, expected_score, expected_skills, expected_retrieved_skills)` pairs
- [ ] Eval harness runner — score MAE + skill extraction recall + context recall, logged to Langfuse
- [ ] First eval run results in Langfuse
- [ ] **Aggregate gap analyzer** — `compass/analysis/gap_aggregator.py`: weekly digest that reads all vault `jobs/` notes with `match_score >= 3.5`, aggregates `skills_missing` across them weighted by score, cross-references against `_profile/skill-inventory.md`, and outputs a ranked priority list of skills to close
- [ ] **Master study plan** — `compass/analysis/study_planner.py`: takes the ranked gap list and generates a single `study-plans/master-gap-plan.md` in the vault with: skill priority order, why each skill appears (which roles need it), current level → target level, and concrete next steps per skill
- [ ] Gap aggregator exposed as MCP tool: `get_aggregate_gaps()` → ranked skill gap list usable on demand from Claude Code

**Definition of done:** The pipeline processes a batch of 10+ jobs in parallel. Approving a job triggers tailoring. Running `uv run python -m compass.evals.runner` prints a summary table. Running `uv run python -m compass.analysis.gap_aggregator` reads all vault job notes, prints a ranked skill gap table, and writes a master study plan to the vault.

**Sub-plan:** [`docs/superpowers/plans/phase-3-intelligence.md`](superpowers/plans/phase-3-intelligence.md) ← *to be written before starting*

**Note:** The amendments plan (`2026-05-16-architecture-amendments.md`) covers the architectural design for all Phase 3 pipeline components in detail. Phase 3's sub-plan translates those designs into implementation steps and adds the gap aggregator.

**Brag moment after Phase 3:** "I have a human-in-the-loop approval flow with an externally-enforced 4-hour timeout — LangGraph interrupt() checkpoints the state, and a Modal cron resumes timed-out threads via Command(resume=...). I can show you the eval results — score MAE and context recall tracked nightly in Langfuse. And I have an aggregate gap analyzer that reads across every job I've scored and tells me exactly which skills to study next, ranked by how many target roles need them and how far I am from proficient." This is the conversation that gets offers.

---

## Phase 4 — Portfolio Polish

**Goal:** The project looks like a real production system. Someone who has never seen it can understand what it does, clone it, run it, and be impressed.

**Deliverables:**
- [ ] MCP server — 6 tools (`search_jobs`, `get_skill_gaps`, `score_jd`, `get_study_plan`, `tailor_resume`, `add_application`) with typed input/output schemas
- [ ] Modal cron deployment — daily scrape + weekly digest running in the cloud
- [ ] Public Langfuse trace URL — one real trace from a real pipeline run, linked in README
- [ ] Eval results chart — precision-vs-cost across 3+ model configurations, in README
- [ ] README polished — live trace link, eval chart, "What I learned / what I'd do differently" filled in
- [ ] Resume updated — add Compass bullet with GitHub URL, Langfuse trace URL, key metrics
- [ ] Blog post or writeup — architecture walkthrough (optional but high-signal for FDE roles)

**Definition of done:** The README tells the story without explanation. A recruiter reads it and immediately understands: what the system does, how it's built, that it runs in production, and that the eval results prove it works.

**Sub-plan:** [`docs/superpowers/plans/phase-4-polish.md`](superpowers/plans/phase-4-polish.md) ← *to be written before starting*

**Brag moment after Phase 4:** This is the full story. You have a shipped, running system. You can show a live Langfuse trace. You can show the eval results chart. You can walk through the MCP server tools. You can deploy a change and watch it run in Modal. "I built the system I'm using to run my own job search" — and you can prove it's running.

---

## Phase 5 — Live & Learning (Ongoing)

**Goal:** Keep the system running and use it daily. Add depth as gaps close.

**Ongoing tasks:**
- Run the pipeline daily, review jobs in the vault
- Update `_profile/skill-inventory.md` as skills improve
- Add MLflow tracking to eval runs (alternative experiment-tracking story alongside Langfuse)
- Write a "design this system on a different observability stack (MLflow / W&B)" case study
- Pursue consulting or external-facing project to close the FDE customer-facing gap

**MLflow addition:**
Add `mlflow.start_run()` to the eval harness runner. Log: match score distribution, cost per run, tokens per node, context recall per model config. This gives an alternative experiment-tracking story alongside Langfuse — useful when interviewing for roles that prefer MLflow/W&B.

---

## Working Principles

**Ship ugly, polish later.** A working pipeline with one scraper and no tailoring is worth more than a perfectly designed unbuilt system. Each phase should produce something runnable before moving to the next.

**Tests first.** Every scraper, vault writer, and eval function gets a test before or alongside the implementation. Nodes get integration tests. This is not optional — the eval story requires you to be able to say "I test my AI systems."

**Langfuse from day one.** Don't add tracing after the pipeline works — wire it in during Phase 2 from the first LLM call. You want traces covering the entire development history, not just the polished version.

**Update STATUS.md and ROADMAP.md as you ship.** These docs are live. An agent reading them mid-project should know exactly where things stand.

**The vault is not a side project.** Use it daily during the job search. The more real data flows through it, the more credible the "I built the system I use" story becomes.

---

## Sub-plan Index

| Plan | Phase | Status |
|---|---|---|
| [`2026-05-16-architecture-amendments.md`](superpowers/plans/2026-05-16-architecture-amendments.md) | Cross-phase | ✅ Written + reviewed |
| [`phase-1-data-layer.md`](superpowers/plans/phase-1-data-layer.md) | 1 | ⬜ To be written |
| [`phase-2-core-pipeline.md`](superpowers/plans/phase-2-core-pipeline.md) | 2 | ⬜ To be written |
| [`phase-3-intelligence.md`](superpowers/plans/phase-3-intelligence.md) | 3 | ⬜ To be written |
| [`phase-4-polish.md`](superpowers/plans/phase-4-polish.md) | 4 | ⬜ To be written |

> Each sub-plan is written immediately before starting that phase — not upfront. Writing the plan too early means planning against a design that hasn't been validated by implementation yet.

---

## Skills Closed by Shipping This Project

| Skill | Gap level (today) | Closed by |
|---|---|---|
| LangGraph (stateful graph, HiTL, checkpointing) | P1 — blocking | Phase 2–3 |
| RAG pipeline (Chroma, embeddings, retrieval eval) | P1 — blocking | Phase 1–2 |
| Langfuse / observability | P1 — blocking | Phase 2 |
| Pydantic AI (structured extraction) | P1 — blocking | Phase 2 |
| Eval harness design (LLM-as-judge, labeled dataset) | P1 — blocking | Phase 3 |
| FastAPI + async Python | P1 — blocking | Phase 4 (MCP server) |
| Vector databases | P2 — next 3mo | Phase 1–2 |
| Modal deployment | P2 — next 3mo | Phase 4 |
| MCP server design | Already proficient | Phase 4 (deepens) |
| MLflow | P2 — critical for Databricks | Phase 5 |
