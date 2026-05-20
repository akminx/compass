# Compass — Complete Project Overview

> A plain-language walkthrough of what Compass is, how it works, what we've built phase by phase, and why each design decision was made. Read this when you want to see the whole project in one place.

**Current tag:** `phase-1b2-rag` · **Tests:** 259 passing · **Branch lineage:** `phase-0a-foundation` → `phase-0b-pipeline-mvp` → `phase-1a-application-tracking` → `phase-1b1-hitl` → `phase-1b2-rag`

---

## 1. What is Compass?

### The problem

Job search at the senior-engineer level is two simultaneous problems:

1. **Application work** — find roles you fit, decide which ones to apply to, tailor your story for each
2. **Skill-gap work** — figure out what the JD market is actually asking for that you don't yet have, and study toward those gaps

Most job-search tools solve only the first problem. They surface roles. They don't help you decide what to study to be a stronger candidate next quarter.

### The solution

Compass is a tool that does both at once. It:

- Scrapes job boards (Greenhouse, Lever, Ashby)
- Drops the noise (sales, PM, design roles)
- Scores each engineering role against your profile (0.0 - 5.0)
- Identifies skills the JDs want that you don't yet have, ranked by demand
- Pauses the high-scoring ones so you (the human) can approve before any LLM-generated tailoring is wasted
- Writes everything to an Obsidian markdown vault so you can read/edit it like a regular notes app
- Has an **agent inside it that grades your own skills against evidence you provide**, then re-prioritizes the gap plan based on which skills moved

It's a research-and-preparation tool, not an auto-apply bot. The human is in the loop for every application decision.

### The three "sides" of the system

Compass has three storage layers, each with a different owner:

```
┌─────────────────────┐      ┌──────────────────────┐      ┌──────────────────────┐
│  THE PIPELINE       │      │  PRODUCT VAULT       │      │  LEARNING VAULT      │
│  (the code)         │─────▶│  agent-written       │◀─────│  human-written       │
│                     │      │  markdown            │      │  markdown            │
│  scrapes JDs        │      │                      │      │                      │
│  scores them        │      │  jobs/*.md           │      │  projects/*/*.md     │
│  writes results     │      │  skills/*.md         │      │  canon/*.md          │
│  runs gap analysis  │      │  applications/*.md   │      │  daily/*.md          │
│                     │      │  companies/*.md      │      │  roadmap/*.md        │
└─────────────────────┘      │  dashboard.md        │      └──────────────────────┘
                             └──────────────────────┘
                              ~/Documents/compass-vault   ~/Documents/learning-vault
```

**Why three?** Separation of concerns. The agent owns what it writes (jobs, skills, scores) and never touches your personal notes. Your learning vault is private; the agent only *reads* it (via `learning-vault://` URIs) to find evidence that you've actually done the work you claim.

This is the system's "unique angle": the agent doesn't take your word for what you know. It grades your skills against the evidence in your learning vault, using a deliberately skeptical hiring-manager persona.

---

## 2. The Big Picture: How a Job Flows Through Compass

A single job posting goes through 8 steps. Each step has a Python module in `compass/pipeline/nodes/`. The whole thing is a LangGraph state machine — meaning each step writes to a shared `state` dictionary, and the graph routes between steps based on what's in that state.

```
                  ┌──────────────────────────────────────────────────────┐
                  │                                                      │
   raw JD ───▶ intake ──▶ intake_filter ─out-of-scope──▶ filtered-jobs.md
                              │                                          
                              │ in-scope                                  
                              ▼                                          
                          extract  ──▶  score  ──▶  reflect              
                                                       │                  
                                                       ▼                  
                                                     hitl                
                                              ┌────────┼─────────┐       
                                       below-thresh   above-thresh        
                                              │      (PAUSE here)         
                                              │      ┌─────────────────┐  
                                              │      │ human approves  │  
                                              │      │ via MCP tool    │  
                                              │      └─────────────────┘  
                                              │              │            
                                              ▼              ▼            
                                       vault_write  ◀──── tailor          
                                              │                            
                                              ▼                            
                                          JobNote.md                      
```

Let me walk through each step.

### Step 1: `intake_node`

Just packages the raw job data into the shared state. No LLM call. No skill needed. This is the entry point.

### Step 2: `intake_filter_node`

The first cost-control gate. Decides if this JD is even worth showing to the LLM. Three stages in order:

1. **Title keyword filter** — if the title contains `"account executive"`, `"product manager"`, `"sales engineer"`, etc., it's out-of-scope. Cheap, no LLM call.
2. **Body-signal upgrader** — if the title is something generic like "Software Engineer" but the JD body mentions "agent", "MCP", "LangGraph" enough times, promote the role to `agent-engineer`.
3. **LLM fallback** — for genuinely borderline titles (e.g. "Solutions Architect"), call Gemini Flash once to read the first 500 chars of the JD and decide.

Out-of-scope JDs get logged to `_meta/filtered-jobs.md` and short-circuit to END. They never reach the score step.

**Why this matters:** without intake_filter, every JD costs ~$0.003 for extract + ~$0.003 for score, even the sales JDs. With it, ~70% of JDs drop here for free.

### Step 3: `extract_node`

Calls Gemini 2.5 Flash with a structured-output schema (Pydantic AI). The LLM reads the JD and produces:

- `required_skills: list[str]` — canonical skill names from the JD
- `nice_to_have_skills: list[str]`
- `seniority: "junior" | "mid" | "senior" | "staff" | "unknown"`
- `years_experience: int | None`
- `remote_policy: "remote" | "hybrid" | "onsite" | "unknown"`
- `summary: str` — a 2-3 sentence summary of the role

The extracted skills are normalized through the canonical taxonomy (`compass/vault/taxonomy.py`) — so JD-mentions like "Pydantic" and "pydantic-ai" both map to `Pydantic AI`.

**Defense in depth:** the schema doesn't catch the LLM inventing skills that aren't in the JD. So there's a substring-validation step: every extracted canonical (or synonym) must appear in the JD text. Phase 0 caught a case where the LLM read an Anthropic sales JD and invented "Federated Learning" — schema-valid, completely fabricated. The validation step now drops these silently.

### Step 4: `score_node`

The other expensive LLM call. Gemini 2.5 Flash again, structured output. It receives:

- The job requirements from step 3
- The candidate's profile context — resume + relevant skill-inventory chunks (retrieved via RAG, see Phase 1.B.2 below)

And returns:

- `score: float` (0.0 - 5.0)
- `reasoning: str` (2-3 sentences explaining)
- `matched_skills: list[str]` — skills from the JD the candidate has
- `missing_skills: list[str]` — skills from the JD the candidate doesn't have
- `tailoring_notes: str` (only if score ≥ 3.0)

**Defense in depth:** the LLM is constrained twice — once via prompt ("matched/missing MUST be subset of JD's required + nice-to-have"), once via post-LLM filter (`_constrain_to_jd_skills`). Phase 0 caught the LLM listing every profile skill as "matched" when the JD had empty required_skills.

### Step 5: `reflect_node`

A no-op pass-through for now. Reserved for Phase 2.A where we'll have a second LLM read borderline scores and dissent.

### Step 6: `hitl_node` — Human-in-the-Loop gate

The interesting one. Three branches:

- `score < SCORE_THRESHOLD` (default 3.5) → **auto-reject** with no LLM call. Sets `human_approved=False`. The JD still gets written to the vault (so the gap aggregator sees it), but the expensive Sonnet tailoring step is skipped.
- `score >= SCORE_THRESHOLD` → **`interrupt()`**. LangGraph pauses the graph mid-execution, saves a checkpoint to a SQLite DB, and returns control to the caller. The thread sits idle until a human approves via MCP tool.
- On resume → the LLM's `interrupt()` call returns the human's decision (`{"approved": True/False, "feedback": str}`) and the graph continues to either tailor or vault_write.

**Why pause instead of always running tailor?** Tailor uses Sonnet (~$0.05/call). Cheap for one job, expensive at 50/day if most of them are mid-fit. Pausing lets the human bulk-approve only the apply-now candidates.

### Step 7: `tailor_node`

Only runs if the human approved. Uses Sonnet 4.6 to write a custom paragraph for that JD, referencing the candidate's real projects. The output is recruiter-grade prose, not LLM slop. Example from a real run:

> "Position yourself as the ideal founder-mindset candidate who has already built and deployed real-world AI agents at scale. Lead with your production MCP server portfolio where you created natural language interfaces..."

### Step 8: `vault_write_node`

Writes the final JobNote markdown file to `~/Documents/compass-vault/jobs/YYYY-MM-DD-Company-Role-<hash>.md`. Updates the company's CompanyNote (`companies/Company.md`). Populates the audit trail (`hitl_decision: approved | rejected | auto_rejected | timed_out`, `hitl_at: <timestamp>`).

After all jobs in the batch finish, `gap_aggregator.regenerate()` reads every JobNote and produces `study-plans/master-gap-plan.md` — the ranked list of "skills the JD market wants that you don't have, ordered by demand × score × tier-weight."

---

## 3. Phase 0: Building the Foundation

### Phase 0.A — Foundation (`phase-0a-foundation`)

The bones. No LLM calls yet.

- 3 ATS scrapers (Greenhouse, Lever, Ashby) — using each ATS's public unauthenticated API
- Vault reader/writer with Pydantic schemas
- Canonical skill taxonomy (95 skills, with synonyms)
- `learning-vault://` URI bridge

### Phase 0.B — Pipeline MVP (`phase-0b-pipeline-mvp`)

The LangGraph pipeline. All 7 nodes implemented. Per-node OpenRouter model routing (Gemini Flash for cheap extract/score, Sonnet for tailor). Batch-level URL dedup. Gap aggregator. Master gap plan auto-regeneration.

### What Phase 0 taught us — the 16 silent bugs

This phase is where the project's testing discipline took shape. **Every "ready" claim got rolled back by the next adversarial probe.** Sample bugs:

| # | What broke | Lesson |
|---|---|---|
| 1 | Greenhouse scraper returned empty `content` field | API list endpoint omits content by default — append `?content=true` |
| 4 | LLM invented "Federated Learning" from an Anthropic sales JD | Validate every extracted skill appears in JD text |
| 6 | Taxonomy parser misread 3-column tables (Voice section had no Synonyms column) | Per-section header column detection |
| 7 | Substring fallback false positives: `"Pythonist" → Python`, `"Goblet" → Go` | Drop the substring fallback; strict synonym match only |
| 8 | `React` vs `ReAct` case collision — JDs mentioning React.js silently became the agentic ReAct pattern | Case-sensitive canonicals set |
| 11 | Filename collisions on similar titles (`Engineer/Backend` and `Engineer (Backend)` both became `Engineer_Backend.md` — silent overwrite) | Append 8-char SHA-1 of URL to filename |
| 12 | Skill counter drift — `appears_in_jobs` accumulated on every overwrite, inflated by URL-dedup reruns | Remove counter increments from pipeline; derive from JobNotes at gap-plan time |

**The pattern:** tests pass, smoke tests pass, code looks correct — but real data is wrong. Schema-valid, semantically meaningless. Only adversarial probing on real outputs catches this class of bug.

This pattern became the project's most expensive lesson and is repeated through every subsequent phase.

---

## 4. Phase 1.A: Making It Daily-Usable

### What shipped (`phase-1a-application-tracking`)

Two big themes:

**1. Role-family gating + removing the score-write gate.** Phase 0.B had `SCORE_THRESHOLD=3.5` as a vault-write gate — only jobs scoring above that got written. This was the wrong filter. the candidate wants the gap plan to include skills from stretch roles (jobs he'd score 2.0 on), because *those gaps are the most informative for study planning*. Filtering on match score hid exactly the right signal.

The fix:
- **Role-family gate at intake** (the `intake_filter_node` above) drops out-of-scope JDs cheaply
- **All in-scope JDs reach the vault** regardless of score
- The expensive Sonnet tailor step is still gated on score (so cost stays bounded)

**2. Application lifecycle.** MCP tools so you can mark a job applied and track status transitions: `add_application(job_id)`, `update_application_status(app_id, status, next_action, next_action_date)`, `list_pending_actions()`.

### The bugs Phase 1.A caught (20 of them)

Same pattern as Phase 0. A few highlights:

- **Bug #1**: parallel writes to `companies/Sierra.md` (5 concurrent jobs reading `roles_seen=0`, incrementing to 1, last writer wins) — fixed by deriving `roles_seen` at gap-plan time, never incrementing
- **Bug #2**: invalid manual `tier` value in Obsidian (user typing `tier: applynow` instead of `apply-now`) crashed the next pipeline run — fixed by tolerating invalid Literal values
- **Bug #B**: body-signal upgrader triple-counted `"agent" ⊂ "agentic" ⊂ "agentic ai"` — fixed by longest-first word-bounded matching
- **Bug #F**: `add_application` silently overwrote in-flight ApplicationNotes — fixed with `force=True` default-off

---

## 5. Phase 1.B.1: Real Human-in-the-Loop

### What shipped (`phase-1b1-hitl`)

Phase 0/1.A's `hitl_node` was a placeholder — it auto-approved everything above threshold. Phase 1.B.1 made it real:

- **`langgraph.types.interrupt()`** — when a high-scoring job hits `hitl_node`, the graph pauses. Mid-execution. The Python coroutine returns, but the graph state is checkpointed.
- **`AsyncSqliteSaver`** — the checkpoint goes to `~/.compass/checkpoints.db`. Survives process restarts.
- **`compass/hitl/state_store.py`** — a separate SQLite table tracking which threads are paused, with company/title/score for display. Powers the `pending_approvals()` MCP tool.
- **`compass/hitl/resume.py`** — re-opens the checkpointer, recompiles the graph, drives `graph.ainvoke(Command(resume={"approved": True, "feedback": "LGTM"}))`. The single entry point for both human approves AND timeout auto-cancels.
- **`compass/hitl/timeout_checker.py`** — auto-cancels pending approvals older than `HITL_TIMEOUT_HOURS` (default 4). Phase 1.B.3 will wire this into a Modal cron.
- **MCP tools** — `pending_approvals()` and `approve(thread_id, approved, feedback)` so the human can see and resolve from Claude Code.
- **Audit trail** — `JobNote.hitl_decision` is now a Literal of `approved | rejected | auto_rejected | timed_out`, populated from state by `vault_write_node`. `JobNote.hitl_at` is the timestamp.

### Why this is load-bearing for the portfolio claim

The spec says "real LangGraph `interrupt()` + `AsyncSqliteSaver` checkpointing." This is one of the headline differentiators when interviewing for tier-2 agentic-engineering roles. Phase 1.B.1 delivers it as actual working code, not a slideware claim.

### The bugs adversarial review caught (8 more)

The plan went through **6 adversarial review iterations** before execution. Found defects included:

- **C1 (silent data divergence)**: state_store said "approved" but JobNote said "auto_rejected" for the same thread — because the resume process used the default `SCORE_THRESHOLD=3.5` while the original run used `1.5`, so `hitl_node` short-circuited on resume without consuming the `interrupt()` value. Two-part fix: derive resume status from the FINAL graph state, AND make the threshold check sticky by capturing it in state at score time.
- **C2 (run-log column drift)**: pre-1.B.1 `pipeline-runs.md` header was 5-col, new code wrote 6-col rows. Dataview rendered misaligned. Self-healing migration added.
- **C3 (counter drift on resume paths)**: `gap_aggregator.regenerate()` was only called at end of `run_pipeline()`. Resume paths bypassed it. Cognition CompanyNote showed `roles_seen: 3` while 9 cognition JobNotes existed on disk. Fixed by calling regen at end of `resume_pending`.
- **I2 (thread_id collision)**: `_thread_id_for()` hashed `(url, batch_started_at)` — two cross-process pipelines starting at the same microsecond would collide. Added `os.getpid()` to the hash.

The plan-review pattern: each adversarial pass rolled back the previous "ready" verdict. Six iterations was the diminishing-returns line.

---

## 6. Phase 1.B.2: RAG + Cleanup (current)

### What shipped (`phase-1b2-rag`)

Two themes:

**1. RAG via Chroma.** Previously `score_node._profile_text()` injected the entire `_profile/skill-inventory.md` (~2,500 tokens) into every score prompt. Phase 1.B.2 replaces that with semantic retrieval:

- `compass/rag/indexer.py` parses `skill-inventory.md` into one chunk per `## SkillName` section, embeds each via `sentence-transformers all-MiniLM-L6-v2`, stores in a Chroma collection pinned to **cosine** distance
- `compass/rag/retriever.py` exposes `retrieve(query, k=8) -> list[RetrievedChunk]` with lazy index init
- `score_node` builds a query string from the JD's `required_skills + nice_to_have + summary` and retrieves the 8 most relevant skill-inventory chunks; injects those instead of the full file
- Token savings: ~2,500 → ~750 per scored JD
- Real-data verification: the same Sierra JobNote that scored 3.0 pre-RAG scored 3.0 post-RAG — no quality regression, just smaller context

**2. Phase 1.B.1 carryover fixes.**

- **msgpack deprecation**: every paused thread logged `Deserializing unregistered type compass.pipeline.state.RawJob from checkpoint. This will be blocked in a future version.` LangGraph 1.2 has a `JsonPlusSerializer(allowed_msgpack_modules=[(module, classname), ...])` constructor that suppresses the warning. Took **5 plan-review iterations** to find the right API form — the obvious-looking `with_msgpack_allowlist` method is a no-op when the default `allowed_msgpack_modules=True`.
- **checkpoint DB bloat**: every paused thread accumulates ~10 checkpoint blobs in `~/.compass/checkpoints.db`, never deleted. New `_purge_thread_checkpoints(thread_id)` in `resume.py` runs after `mark_resolved`. Bounded growth.

### Why RAG instead of just dumping the inventory

The spec made RAG a portfolio-claim requirement. But the engineering rationale is real:

- **Cost**: 2,500-token context costs ~3x what a 750-token one does at Gemini Flash rates. Over 50 jobs/day, that's real money.
- **Focus**: full inventory inject includes irrelevant chunks ("Voice — skip"). Retrieved chunks are the skills actually closest to the JD's vocabulary.
- **Demonstrable**: "I built RAG over my profile and reduced score-prompt tokens 70%" is a concrete interview talking point.

### Why Chroma + all-MiniLM-L6-v2

- **Chroma**: simplest persistent vector DB with a real Python API. PersistentClient writes to a SQLite file. No service to run. Cosine distance pinned at collection-create.
- **all-MiniLM-L6-v2**: 90MB model, downloaded once to `~/.cache/torch/`. Fast enough to embed 20 chunks in <100ms on a laptop. Cosine similarity in [0, 1] is meaningful out of the box.
- **Alternative considered**: `nomic-embed-text` (better quality) — deferred to Phase 2.B as a one-line config change.

### The bugs adversarial review caught (8 more)

**6 plan iterations + 2 code-quality iterations.** Highlights:

- **C1 (the silent metric bug)**: existing `~/.compass/chroma/` collections from before the cosine pin would keep the L2 default. `get_or_create_collection(metadata={"hnsw:space": "cosine"})` does NOT update the metric on an existing collection. The retriever's `1.0 - dist/2.0` formula then produces negative similarities. Fix: inspect existing collection's metadata, drop+recreate if not cosine.
- **`Assessor-current grades` heading pollution**: the assessor writes a `## Assessor-current grades` section to `skill-inventory.md` containing every skill name. If embedded into the index, it would dominate retrieval for any query. Excluded via `_EXCLUDED_HEADINGS`.
- **`_kebab` parenthetical stripping**: heading `## Fine-Tuning (awareness only — explicit anti-claim)` would otherwise become the unreadable ID `fine-tuning-awareness-only-explicit-anti-claim-per-role-clarifications`. Regex strips parentheticals + em-dash commentary before kebab-casing while preserving internal hyphens (`Fine-Tuning` stays `fine-tuning`, not `fine`).
- **AI-slop cleanup** (8 patterns): plan-meta narrative in production docstrings, defensive `try/except: pass`, speculative `_load_model` / `_get_client` helpers, `await ... await ...` on one line, etc.

### Post-tag findings (deferred to Phase 2.A)

Adversarial post-smoke review surfaced four LLM-behavior bug classes — documented in [`KNOWN_DATA_QUALITY_ISSUES.md`](KNOWN_DATA_QUALITY_ISSUES.md):

- **B1**: `extract_node` under-extracts `skills_required` on best-fit roles. Sierra Agent Architecture JD scored 3.0 because `skills_required: []` left no signal for matched_skills.
- **B2**: `extract_node` mis-reads OR-lists ("languages such as Python, TypeScript, Go") as AND-lists.
- **B3**: `score_node` occasionally marks candidate-strong skills as missing (Python listed missing despite candidate's Python=3).
- **B4 (FIXED)**: `intake_filter` title-keyword list was leaky. 5 false-negatives migrated post-fix.

These are LLM-prompt-tuning bugs that need the Phase 2.A eval harness (30 labeled JDs + score-MAE measurement) to fix correctly. Whack-a-mole prompt tweaking without measurement is worse than waiting.

---

## 7. The Skill Assessor Loop (the "unique angle")

### What it does

The candidate marks each skill in `skills/SkillName.md` with `evidence: [learning-vault://...]` URIs pointing to artifacts in the learning vault. The skill assessor agent (`compass/analysis/skill_assessor.py`) reads those URIs, applies a deliberately skeptical hiring-manager rubric, and proposes new grades.

### The rubric

```
Level 0  No exposure.
Level 1  Tutorial-level: course notes, "hello world", or a read paper.
Level 2  Applied in a personal project. Repo or vault note showing real use.
Level 3  Shipped. Deployed, evals exist, OR used by people other than candidate.
Level 4  Production-grade. Shipped WITH observability + cost tracking + recovered from a real failure.
Level 5  Authority. Taught it, merged upstream PR, or fixed a non-trivial bug in the library itself.
```

The agent demands artifact citations. Conceptual evidence caps at L1. Jumps of 2+ levels require HITL.

### Real first run (2026-05-19)

After wiring 4 skills to actual evidence URIs:

| Skill | Current | Proposed | Reasoning |
|---|---|---|---|
| MCP | 4 | **2** (requires_hitl=True) | "Empty or template documents in projects/minx/. Minimal content." 2-level downgrade triggers human review. |
| LangGraph | 1 | 1 | "Template files for Compass project, no LangGraph implementation artifacts visible. Decision log empty." |
| Eval_harness | 0 | 0 | "Hamel reading material status=queued, read_count=0. No applied work." |
| HiTL | 1 | 1 | "Decision log template without actual HiTL decisions or artifacts." |

**This is the value working as intended.** The grader correctly refused to credit the candidate's actual MCP/LangGraph/HiTL work — because the *learning vault* doesn't yet document it. The work itself lives in the compass codebase. Filling `learning-vault/projects/compass/decisions.md` with the real architectural decisions from Phases 0-1.B.2 will raise the grades on next run.

This is the loop: study/build → write it down → cite the writeup as evidence → agent regrades → gap plan reprioritizes. It closes the feedback loop between "what the market wants" and "what I can credibly claim."

---

## 8. Key Design Decisions (and why)

### Why a markdown vault instead of a database?

**Decision**: store all agent output as `.md` files with YAML frontmatter.

**Why**: Obsidian renders it natively. Dataview queries give you SQL-like power over markdown. The user can edit fields by hand in Obsidian and the next pipeline run respects those edits (e.g. tightening a CompanyNote.tier). No separate UI to build. Version-controllable. Diff-able.

**Trade-off**: schema enforcement happens at write time via Pydantic, but a user editing the file in Obsidian can introduce invalid values. Phase 1.A bug #d40f36e was a literal example — `tier: applynow` (typo) crashed the next run. Fixed by tolerating invalid Literal values on read.

### Why MCP for HITL (and not a web UI)?

**Decision**: the human approves paused jobs via MCP tools called from Claude Code, not via a separate web app.

**Why**: the candidate already lives in Claude Code daily. Building a Flask UI to surface 5 pending approvals would be over-engineered. MCP tools (`pending_approvals()`, `approve(tid, True, "LGTM")`) are zero-friction from his existing workflow.

**Trade-off**: the dashboard doesn't surface pending approvals (Dataview can't read SQLite). Phase 2.B may add a thin web view if this becomes a daily-flow friction point.

### Why three vaults (pipeline / compass-vault / learning-vault)?

**Decision**: agent-written content goes to `~/Documents/compass-vault/`. Personal notes stay in `~/Documents/learning-vault/`. The pipeline code only writes to compass-vault.

**Why**: separation of concerns. The agent can rewrite anything in compass-vault freely — it's the system's output. The learning-vault is the candidate's brain — the agent never touches it; it only resolves `learning-vault://` URIs to read evidence.

**Trade-off**: cross-vault evidence requires the URI protocol (`compass/vault/learning_bridge.py`). Slight indirection. But preserves the cognitive model: "the agent doesn't read my journal."

### Why LangGraph (and not custom state management)?

**Decision**: use LangGraph for the pipeline state machine.

**Why**: `interrupt()` + `AsyncSqliteSaver` checkpointing is what makes real HITL work. Building this from scratch — durable pause-resume across process restarts with a SQLite checkpointer — would be a multi-week side project. LangGraph 1.2 gives it for free.

**Trade-off**: LangGraph has its own conventions (state schema as TypedDict, edges defined declaratively). Required Phase 1.B.1 to be careful about the "compile graph inside async with checkpointer" invariant. The framework's once-only warning sets and msgpack allowlist API have required 5+ adversarial review iterations to use correctly.

### Why subagent-driven development?

**Decision**: most implementation work goes through fresh implementer subagents with combined spec+quality reviewers between tasks.

**Why**: it caught 8+ real bugs across Phase 1.B.1, several of which were genuine silent-data-correctness defects the human reviewer wouldn't have spotted. Fresh subagent per task means no context pollution. The reviewer cycle creates a forcing function — implementer can't ship questionable code because a different agent will read it.

**Trade-off**: more LLM invocations per task (implementer + 2 reviewers minimum). Higher token cost. But far cheaper than debugging silent bugs in production.

### Why so much adversarial review?

**Decision**: every plan goes through 3-6 adversarial review iterations before execution. Every implementation gets a spec+quality review. Live smoke verification is mandatory before tagging.

**Why**: Phase 0 caught 16 silent bugs. Phase 1.A caught 20 more. Phase 1.B.1 caught 8 more. The pattern is consistent: tests pass + smoke tests pass + code looks correct → but real data is wrong. The only thing that catches this is *adversarial inspection of real outputs*.

The portfolio cost of shipping a silently-broken Compass to recruiters is enormous. The cost of one more review pass is ~30 minutes. Math is obvious.

**Trade-off**: process overhead. But it's now the project's defining methodology and (frankly) its strongest interview talking point — "I built a system that caught its own data-correctness bugs through structured adversarial review, where most agentic systems ship with the bugs."

---

## 9. The State of the System Right Now

### What works end-to-end

- **Daily pipeline**: `uv run python -m compass.pipeline.graph` against the configured ATS boards → scrapes, filters, scores, writes. Real cost per 20 jobs: ~$0.05.
- **HITL flow**: above-threshold jobs pause; `pending_approvals()` MCP tool lists them; `approve(tid, True, "LGTM")` resumes into tailor + vault_write. Audit trail intact.
- **Timeout cancel**: `uv run python -m compass.hitl.timeout_checker` resumes stale pending approvals as `timed_out`, writes to agent-log per spec.
- **RAG**: `uv run python -m compass.rag.indexer --force` builds the Chroma index. `score_node` uses retrieved chunks instead of full inventory.
- **Gap plan**: regenerates after every pipeline run AND after every resume. Out-of-scope JobNotes excluded.
- **Skill assessor**: `assess_skills(scope=[...])` MCP tool grades skills against evidence URIs. Adversarial grader catches under-documented claims.

### What's stubbed but not yet exercised in production

- **Modal cron**: `timeout_checker.py` is callable but no schedule wires it. → Phase 1.B.3.
- **Langfuse traces**: callback API mismatch (`host` kwarg) — every run logs the error, pipeline continues. → Phase 1.B.3.
- **Eval harness**: 30 labeled JDs + nightly score-MAE regression. Not built. → Phase 2.A.
- **Application lifecycle**: tools work but `~/Documents/compass-vault/applications/` is empty — nobody has applied via the tool yet.

### What's deferred and why

[`docs/KNOWN_DATA_QUALITY_ISSUES.md`](KNOWN_DATA_QUALITY_ISSUES.md) lists 8 known bug classes (B1-B8) with severity, evidence, and Phase 2.A fix surface for each. The headline ones:

- **B1**: extract under-extracts skills_required on best-fit JDs
- **B7**: gap_aggregator includes auto_rejected/timed_out/null at full weight
- **B8**: tailor_node has no programmatic constraint against hallucination

Each needs a regression test against labeled JDs (Phase 2.A) before tuning, otherwise we whack-a-mole.

---

## 10. What's Next

### Phase 1.B.3 — automation + observability (next sub-phase)

- **Modal cron** for daily scrape (9 AM Central) + weekly skill_assessor (Sunday 2 AM Central). The `timeout_checker` becomes a Modal-scheduled job.
- **Langfuse callback fix**. Then a public trace URL goes in the README. Portfolio claim.
- **Modal Secrets**: secrets out of `.env`, into Modal's secret manager. Compass repo can be public.
- **URL dedup for filtered-jobs**. Currently the same sales JDs hit `intake_filter` every run. Trivial cache.
- **I4 race fix**: `claim_pending` atomic transition prevents double-resume races once Modal cron and human MCP can fire simultaneously.

### Phase 2.A — eval harness

- 30 hand-labeled JDs in `compass/evals/dataset.json`
- Nightly: extract recall, score MAE vs ground truth, cost-per-run, p50 latency
- LangFuse-logged with regression alert if MAE > baseline + 2σ
- **Then** tune extract/score prompts to fix B1-B3. Measure each change.

### Phase 2.B — portfolio polish

- README: architecture diagram (mermaid), screenshots, public Langfuse trace URL, "what I learned" section, eval results table
- Public Langfuse trace URL reachable without auth
- Repo link in resume Projects section

### Phase 2.C — blog post

"Building an agent that grades my skills against the live job market." The skill_assessor loop is the differentiated story.

### Phase 3+ — coverage expansion

Workday, Apple, Google, AWS, Microsoft scrapers. YC WAAS, HN Who's Hiring. Long-tail.

---

## 11. Glossary

| Term | Meaning |
|---|---|
| **Agentic AI** | software that orchestrates LLM calls + tools to accomplish multi-step tasks (e.g. agent that searches the web, summarizes findings, drafts a response). Compass itself is agentic. |
| **ATS** | Applicant Tracking System (Greenhouse, Lever, Ashby). Standard interface job postings flow through. Compass scrapes each ATS's public unauthenticated API. |
| **CompassState** | the TypedDict shared between all LangGraph nodes. One JD's-worth of pipeline state. |
| **Canonical taxonomy** | the 95-skill registry at `_meta/skill-taxonomy.md`. Maps synonyms ("pydantic-ai", "Pydantic AI") to one canonical name. |
| **Chroma** | the persistent vector DB used for RAG. Stores `skill-inventory.md` chunks + their embeddings. |
| **`interrupt()`** | LangGraph function that pauses graph execution mid-node. The graph state is checkpointed; control returns to the caller. The same node re-runs on resume with the human's value substituted. |
| **JobNote** | one markdown file per scored JD at `compass-vault/jobs/`. Frontmatter has `match_score`, `hitl_decision`, `skills_matched`, etc. |
| **MCP** | Model Context Protocol. Anthropic's standard for exposing tools to LLM clients (Claude Code, Cursor). Compass's MCP server exposes 16 tools — `pending_approvals`, `approve`, `add_application`, etc. |
| **Modal** | the serverless platform where Phase 1.B.3 will host the daily cron. Free tier covers Compass's expected usage. |
| **Pydantic AI** | the library that gives LLMs typed structured output. Define a Pydantic model; the LLM is constrained to return data that validates against it. Used for extract + score nodes. |
| **RAG** | Retrieval-Augmented Generation. Instead of dumping all candidate-profile data into every LLM prompt, retrieve the relevant chunks via vector similarity. |
| **Role family** | the classification an in-scope JD falls into: `agent-engineer`, `applied-ai`, `swe-backend`, `fde-eng`, `research-eng`, or `out-of-scope`. Stored on JobNote frontmatter. |
| **score_threshold** | currently 3.5. Jobs scoring ≥ this pause for human approval. Below auto-reject. Captured into pipeline state at score time so pause-resume across env changes stays consistent. |
| **`learning-vault://` URI** | the protocol the skill_assessor uses to read evidence files from `~/Documents/learning-vault/`. Read-only; the agent never writes there. |

---

## 12. Files You'll Touch Most

If you want to understand any one piece deeply, these are the entry points:

- **The whole pipeline**: [compass/pipeline/graph.py](../compass/pipeline/graph.py) — `run_pipeline()` is the top-level function. Every node hangs off the graph defined here.
- **A specific node**: `compass/pipeline/nodes/{intake,intake_filter,extract,score,reflect,hitl,tailor,vault_write}.py`
- **HITL infrastructure**: `compass/hitl/{state_store,resume,timeout_checker}.py`
- **RAG**: `compass/rag/{indexer,retriever}.py`
- **MCP tools**: [compass/mcp_server/server.py](../compass/mcp_server/server.py)
- **Skill assessor**: [compass/analysis/skill_assessor.py](../compass/analysis/skill_assessor.py)
- **Gap aggregator**: [compass/analysis/gap_aggregator.py](../compass/analysis/gap_aggregator.py)
- **Vault schemas**: [compass/vault/schemas.py](../compass/vault/schemas.py) — what every JobNote/SkillNote/CompanyNote/ApplicationNote frontmatter must look like
- **Config**: [compass/config.py](../compass/config.py) — every env var and default path lives here

And the corresponding test files in `tests/` mirror the same structure. 259 tests at current tag.

---

## 13. The Big Picture (one paragraph)

You're building an agentic career coach that scrapes job boards, drops noise, scores in-scope JDs against your profile via Gemini Flash, pauses high-scoring jobs for your approval through real LangGraph `interrupt()`, generates Sonnet-tailored paragraphs for approved ones, derives a master gap plan from every scored JD via weighted demand math, and houses an adversarial skill grader that reads evidence from your personal learning vault and proposes grade changes when you've shipped new work. All output is markdown in an Obsidian vault. Cost ~$0.05 per 20-job batch. 259 tests passing. Six phases left to complete: automation cron, observability, eval harness, polish, blog post, coverage expansion.

You're roughly halfway through the planned 8-10 sessions. The hardest architectural calls are made. What remains is operational discipline + measurement.
