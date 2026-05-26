# Compass — MVP to Portfolio-Grade Ship: Design Spec

> Date: 2026-05-17
> Status: Approved (user)
> Author: the candidate + Claude
> Related: `compass/CLAUDE.md`, `compass/docs/ARCHITECTURE.md`, `compass-vault/_profile/target-companies.md`

## Problem Statement

the candidate is targeting tier-2 agentic-AI startups and big-tech L3/L4 agentic roles in 2026. He has prior eng experience, strong MCP/a personal local-first OS project portfolio artifacts, and a calibrated skill inventory in `compass-vault/_profile/`. He needs:

1. A working tool that helps him find, score, and decide on jobs every morning — replacing manual LinkedIn browsing.
2. A portfolio artifact impressive enough to link from his resume.
3. A skill-tracking loop that closes the gap between "I have notes in learning-vault" and "my resume reflects what I've actually shipped."

**FDE-track roles are explicitly OUT OF SCOPE for this project's audience** — the candidate has insufficient YoE and will revisit later. The design optimizes for tier-2 product engineering and tier-3 big-tech L4 audiences.

> **Note on CLAUDE.md drift:** `compass/CLAUDE.md` was previously written with an FDE-focused portfolio audience. That framing is stale — this spec supersedes it. CLAUDE.md updated in the same commit to reflect the tier-2 product-engineering audience.

## Goals

A single agentic system, **Compass**, that:

1. Scrapes Greenhouse/Lever/Ashby job boards for tier-2 + apply-now companies
2. Scores each job against the candidate's profile + skill inventory
3. Tracks application lifecycle (applied → screen → onsite → offer/reject) with next-action reminders
4. Generates a master gap plan: which skills appear most in high-score jobs that the candidate currently lacks
5. Grades the candidate's skill levels from evidence URIs in his learning-vault, regenerating the gap plan as he ships things
6. Runs daily via Modal cron with traces logged to Langfuse
7. Reaches "genuinely impressive to any recruiter" via README polish, public Langfuse trace URL, 30-JD eval set, blog post

## Non-Goals

- Auto-apply or "blast applications" — every application is a deliberate human decision
- FDE-pattern customer engagement track — deferred to a future project
- Recorded demo (FDE-specific signal not needed for tier-2 audience)
- Workday / Apple / Google Cloud / AWS / Microsoft / Workable scrapers in MVP — deferred to Phase 3+
- Real-time job alerting beyond daily cron — daily cadence is the right rhythm for considered application
- LinkedIn / Indeed / Glassdoor scraping — ToS risk + recruiter spam noise outweighs marginal coverage
- Voice-stack roles — not targeting voice companies
- Eval harness with labeled set in MVP — needs real jobs to label first

## Approach

**Vertical-slice-first sequencing across four phases.** Each phase produces a shippable, demoable thing. the candidate can stop after any phase and have a coherent portfolio item.

| Phase | Goal | Sessions | End state |
|---|---|---|---|
| **0.A — Foundation** | Scrapers + vault I/O working independently | 1 | All three ATSes return RawJob[]; reader/writer round-trip a fake JobNote; smoke test of scrape-only |
| **0.B — Pipeline MVP** | Prove end-to-end architecture | 1 | Pipeline scrapes/scores/writes; gap plan regenerates; auto-approve for now |
| **1.A — Application tracking + dashboard** | Daily-usable for job decisions | 1 | `add_application` workflow + Dataview dashboard you open every morning |
| **1.B — Automation + HiTL + RAG** | Runs without babysitting; portfolio-claim parity | 1–2 | Modal cron + **real LangGraph `interrupt()` + `AsyncSqliteSaver` checkpointing** (MCP tool is the UI for approve/reject — backend is real interrupt/resume) + Chroma RAG for profile retrieval (replaces string-injection) + weekly skill_assessor cron |
| **2.A — Eval harness** | Numbers backing the claims | 1 | 30 hand-labeled JDs + precision/recall + LangFuse-logged regression eval (threshold set after first run) |
| **2.B — Portfolio polish** | Recruiter-grade | 1 | README polish + public Langfuse trace URL + architecture diagram + screenshots |
| **2.C — Blog post** | Differentiated story | 1 | "Building an agent that grades my skills against the live job market" — draft published |
| **3+ — Continuous additions** | Ongoing portfolio improvement | ad hoc | Workday/custom ATSes, Getro, YC WAAS, HN, Temporal, Stagehand, Guardrails |

**Total realistic sessions: 8–10** (Phase 0 split into 0.A + 0.B; Phase 1.B may need a second session for RAG + real HiTL). The original "1 session" estimates were optimistic.

## Architecture (revised, simplified)

**Two loops, one shared vault:**

```
Outer loop (daily, automatic):
  Career sites (Greenhouse, Lever, Ashby)
      ↓
  Score each job (Gemini 2.5 Flash) ← reads _profile/ from compass-vault
  Tailor (Sonnet 4.6) if above threshold
      ↓
  Write to compass-vault/jobs/  →  master-gap-plan.md regenerates


Inner loop (on demand, when the candidate ships something):
  the candidate writes a note in learning-vault (e.g. projects/compass/postmortem.md)
      ↓
  Adds learning-vault:// URI to evidence: in compass-vault/skills/<Skill>.md
      ↓
  skill_assessor (Sonnet 4.6) reads evidence, applies rubric, regrades my_level
      ↓
  Next outer-loop run sees higher level → gap plan reorders


Human-in-the-loop (daily morning ritual):
  Open compass-vault/dashboard.md  →  see today's high-score jobs
  Approve a few via MCP tool       →  applications/ note created
  Pick top gap                     →  learn it, write notes in learning-vault
  Add evidence URI                 →  next run grades you up
```

## Components

### Existing (already built or scaffolded)

- `compass/vault/taxonomy.py` — loads 95-skill canonical taxonomy, normalizes synonyms
- `compass/vault/learning_bridge.py` — resolves `learning-vault://path#anchor` URIs
- `compass/vault/schemas.py` — Pydantic schemas for JobNote, SkillNote, CompanyNote, ApplicationNote, SkillAssessment, GapPlanEntry
- `compass/analysis/gap_aggregator.py` — ranks gaps by `Σ (jobs × match_score × tier_weight)`, regenerates `study-plans/master-gap-plan.md`
- `compass/analysis/skill_assessor.py` — adversarial Pydantic AI grader with rubric, asymmetric promotion, HiTL escalation for 2+ level jumps
- `compass/mcp_server/server.py` — 11 tools exposing pipeline + vault + analysis
- `compass-vault/_meta/skill-taxonomy.md` — 95 canonical skills with synonyms + tier demand
- `compass-vault/_profile/{resume,skill-inventory,role-clarifications,preferences,target-roles,target-companies,interview-prep}.md`
- `compass-vault/skills/*.md` — 95 seeded skill notes, all with calibrated initial grades
- `compass-vault/dashboard.md` — Dataview-query stub
- `learning-vault/` — restructured with bridge protocol documented

### Phase 0.A — Foundation (1 session, ~280 LoC)

Scrapers + vault I/O work independently. No LLM calls yet. Ends with a `scripts/test_scrape.py` that returns 5 jobs from each ATS and a `scripts/test_vault_roundtrip.py` that writes + reads a fake JobNote.

| File | Action | Purpose |
|---|---|---|
| `compass/scrapers/greenhouse.py` | IMPLEMENT | Real `httpx` GET of `boards-api.greenhouse.io/v1/boards/{slug}/jobs` |
| `compass/scrapers/lever.py` | IMPLEMENT | Real GET of `api.lever.co/v0/postings/{slug}?mode=json` |
| `compass/scrapers/ashby.py` | IMPLEMENT | Real GET of `api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true` |
| `compass/vault/reader.py` | IMPLEMENT | `read_profile_section`, `read_skill_inventory`, `read_resume`, `job_url_exists`, `list_job_notes` |
| `compass/vault/writer.py` | IMPLEMENT | `write_job_note`, `update_skill_note`, `write_company_note`, **`append_agent_log(line)`** — frontmatter-aware, schema-validated |
| `compass/config.py` | EXTEND | `EXTRACT_MODEL`, `SCORE_MODEL`, `REFLECT_MODEL`, `TAILOR_MODEL`, `ASSESSOR_MODEL` env vars |
| `.env.example` | EXTEND | OpenRouter key + model overrides + initial board slugs |
| `scripts/test_scrape.py` | NEW | Smoke test: run each scraper, print first 5 jobs from each |
| `scripts/test_vault_roundtrip.py` | NEW | Smoke test: write a fake JobNote, read it back, validate schema |

### Phase 0.B — Pipeline MVP (1 session, ~360 LoC)

All nodes implemented as the simplest version that works end-to-end. Ends with `MAX_JOBS_PER_RUN=5 uv run python -m compass.pipeline.graph` producing 5 scored jobs in vault + regenerated `master-gap-plan.md`.

| File | Action | Purpose |
|---|---|---|
| `compass/llm.py` | NEW | `get_model(node)` helper; OpenRouter base URL; per-node model routing |
| `compass/pipeline/nodes/intake.py` | IMPLEMENT | **Dedup against vault by URL** (assigns intake the dedup duty; removes contradiction with external dedup) |
| `compass/pipeline/nodes/extract.py` | IMPLEMENT | Pydantic AI Agent → `JobRequirements` (Gemini Flash) |
| `compass/pipeline/nodes/score.py` | IMPLEMENT | Pydantic AI Agent → `JobScore` w/ profile context (Gemini Flash) |
| `compass/pipeline/nodes/reflect.py` | IMPLEMENT | No-op pass-through for MVP (revisit in Phase 2 once eval data shows false negatives) |
| `compass/pipeline/nodes/hitl.py` | IMPLEMENT | Auto-approve if score ≥ SCORE_THRESHOLD (real `interrupt()` + checkpointing ships in Phase 1.B) |
| `compass/pipeline/nodes/tailor.py` | IMPLEMENT | One-paragraph tailoring (Sonnet 4.6) |
| `compass/pipeline/nodes/vault_write.py` | IMPLEMENT | Write JobNote + update CompanyNote + increment matched SkillNote counters + append to `_meta/agent-log.md` |
| `compass/pipeline/graph.py` | RESTRUCTURE | `run_pipeline` iterates jobs externally, invokes graph per-job, calls `gap_aggregator.regenerate()` at end |

### Phase 1.A — Application tracking + dashboard

- `compass/pipeline/application.py` — NEW module for application lifecycle
- `compass/mcp_server/server.py` — wire `add_application`, `update_application_status`, `pending_approvals` tools
- `compass-vault/dashboard.md` — refine Dataview queries: "Apply now (top 5)", "In flight applications", "Today's actions", "Top gaps this week"

### Phase 1.B — Automation + skill loop

- `compass/pipeline/graph.py` — switch to compiling graph with `AsyncSqliteSaver` checkpointer; replace auto-approve hitl_node with real `interrupt()`; add resume entrypoint
- `compass/hitl/state_store.py` + `compass/hitl/timeout_checker.py` — SQLite-backed pending-approval queue (resumes timed-out threads via `Command(resume={"approved": False})`)
- `compass/mcp_server/server.py` — `pending_approvals()` and `approve(thread_id, decision)` tools that wrap LangGraph resume
- `compass/rag/indexer.py` + `compass/rag/retriever.py` — Chroma index of `_profile/skill-inventory.md` chunks; `score_node` retrieves top-k relevant chunks instead of injecting full inventory (closes RAG portfolio claim)
- `modal_app.py` (root) — `@app.function(schedule=Cron("0 9 * * *"), timezone="America/Chicago")` daily scrape + `@app.function(schedule=Cron("0 2 * * 0"), timezone="America/Chicago")` weekly skill_assessor. **Both pin to a local TZ** — Modal cron defaults to UTC otherwise.
- Modal Secrets configured for `OPENROUTER_API_KEY`, `LANGFUSE_*` (NOT injected via env file in cloud)

### Phase 2.A — Eval harness

- `compass/evals/dataset.json` — 30 hand-labeled JDs with ground-truth scores + skill lists
- `compass/evals/runner.py` — score MAE, skill extraction recall, cost per run; LangFuse logging
- `scripts/label_jd.py` — interactive CLI for adding labeled examples

### Phase 2.B — Portfolio polish

- Public Langfuse trace URL embedded in README
- Architecture diagram (mermaid) + screenshot of master-gap-plan output
- "What I learned / what I'd do differently" README section

### Phase 2.C — Blog post

- `learning-vault/projects/compass/postmortem.md` — long-form internal version
- Public version published to personal blog / Substack: "Building an agent that grades my skills against the live job market"

## Data Flow Example (one job through the pipeline)

```
1. Greenhouse scraper returns RawJob{company: "AgentCo", title: "Agent Engineer", ...}
2. run_pipeline.dedup() checks compass-vault/jobs/ for URL match → not found
3. graph.ainvoke(state={current_job: RawJob, ...})
4.   intake_node       → no-op, returns {}
5.   extract_node      → Gemini Flash → JobRequirements{required_skills: ["LangGraph", "MCP", ...]}
6.   score_node        → Gemini Flash → JobScore{score: 4.2, matched: ["MCP", ...], missing: ["LangGraph"]}
7.   reflect_node      → no-op (score above threshold, no reflection needed)
8.   hitl_node         → auto-approve since 4.2 ≥ 3.5
9.   tailor_node       → Sonnet → "Lead with your production MCP work and the candidate's local-first OS 4-server pattern..."
10.  vault_write_node  → writes compass-vault/jobs/2026-05-18-AgentCo-Agent-Engineer.md
                       → updates compass-vault/companies/AgentCo.md
                       → increments compass-vault/skills/LangGraph.md appears_in_jobs
11. After batch: gap_aggregator.regenerate() → master-gap-plan.md shows LangGraph rank #1
```

## Error Handling

- **Every node returns `{success, data, error}` style result via state** — never raises.
- **Scraper failures** (one ATS down): log to `_meta/agent-log.md`, continue with other sources.
- **LLM call failures** (rate limit, bad JSON): retry once with exponential backoff, then mark `errors:` on state and skip downstream nodes for that job.
- **Vault write failures**: log to `_meta/agent-log.md` with full error, don't crash pipeline.
- **Taxonomy normalization misses** (unknown skill): log to `_meta/agent-log.md` for human review, drop from `skills_required` but don't fail.

## Testing Strategy

- **MVP**: Real-run smoke test only. `MAX_JOBS_PER_RUN=5 uv run python -m compass.pipeline.graph` against 2 Greenhouse boards (`acme`, `exampleco`) + 1 Ashby (`democorp`). Verify 5 jobs in vault + non-empty master-gap-plan.
- **Phase 1+**: Pytest unit tests for scrapers (mock httpx) + vault writer (in-memory) + skill_assessor (mock LLM). Integration test for end-to-end pipeline on a frozen sample JD.
- **Phase 2**: Eval harness IS the regression test. Nightly Modal cron runs eval against labeled set, alerts if MAE > 0.5.

## Model Routing

| Node | Model | Why |
|---|---|---|
| extract | `google/gemini-2.5-flash` | See rationale below |
| score | `google/gemini-2.5-flash` | Comparison reasoning, sufficient |
| reflect | `anthropic/claude-sonnet-4.6` | Borderline jobs only; needs heavier reasoning + dissent |
| tailor | `anthropic/claude-sonnet-4.6` | Writing quality + nuance |
| skill_assessor | `anthropic/claude-sonnet-4.6` | Adversarial grader needs strong dissent reasoning |

**Why Gemini Flash over Claude Haiku for extract/score?** Two reasons: (1) Gemini 2.5 Flash benchmarks at or above Haiku 4.5 on structured extraction tasks at ~1/3 the price ($0.15/M in vs $1/M in). (2) Multi-provider routing through OpenRouter lets us A/B Sonnet-vs-Flash on score quality during eval phase (2.A) and surface real numbers rather than guessing. If eval shows Flash leaving precision on the table, swap to Haiku via a single env var change — `EXTRACT_MODEL` and `SCORE_MODEL` are pulled from `config.py`. Trade-off accepted: more complex Langfuse cost attribution because of two providers.

Routed via OpenRouter (`https://openrouter.ai/api/v1`). Estimated cost at 50 jobs/day: ~$0.45/day = $14/month.

## Definition of Done (Phase 2 complete)

Every criterion below is verifiable (testable, observable, or has a concrete artifact). "Genuinely impressive" was replaced with checklists.

**Pipeline correctness**
- `MAX_JOBS_PER_RUN=50 uv run python -m compass.pipeline.graph` completes without unhandled exceptions
- At least 80% of jobs that reach `extract_node` produce valid `JobRequirements` (Pydantic validates)
- 100% of jobs with `score ≥ SCORE_THRESHOLD` have a written `JobNote` in `compass-vault/jobs/`
- `master-gap-plan.md` regenerates on every run; top-10 reflects current job market

**Automation**
- Modal cron fires daily at 9 AM Central; first three consecutive runs succeed without manual intervention
- Weekly `skill_assessor` cron fires Sundays 2 AM Central; updates `_profile/skill-inventory.md` if grades change
- HiTL timeout enforced: pending approvals auto-cancel after 4 hours and log to `_meta/agent-log.md`

**Skill loop**
- `skill_assessor` grades reflect linked `learning-vault://` evidence URIs (verifiable: link 1 URI, run assessor, see grade change in log)
- `grade_override:` honored: setting a value disables auto-assessment for that skill

**Application tracking**
- `add_application(job_id)` creates a valid `ApplicationNote` linked back to the source `JobNote`
- `update_application_status(application, new_status)` produces a valid transition
- Dashboard "In flight applications" Dataview query returns expected rows after 3 test applications

**Eval harness**
- `compass/evals/dataset.json` contains ≥ 30 hand-labeled JDs (`expected_score` + `expected_skills`)
- `uv run python -m compass.evals.runner` produces a results table to stdout with: score MAE, skill recall, cost-per-run, p50 latency
- Results logged to a named Langfuse dataset; baseline numbers documented in `docs/EVAL_BASELINE.md` (alert threshold set as `baseline + 2σ`)

**Portfolio artifacts**
- README contains: ≥ 1 mermaid architecture diagram, ≥ 2 screenshots (master-gap-plan, dashboard), 1 public Langfuse trace URL (responds 200), "What I learned" section with ≥ 3 substantive entries, eval results table
- Public Langfuse trace URL has at least 5 traced pipeline runs and is reachable without auth
- Blog post draft at `learning-vault/projects/compass/postmortem.md` is ≥ 1200 words and covers: the skill_assessor loop, the gap_aggregator weighting formula, the calibrated initial inventory story, what didn't work
- Compass repo link is added to `compass-vault/_profile/resume.md` Projects section

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| ATS APIs change unexpectedly | Low | Public ATS APIs are remarkably stable. Use `httpx` with response validation; log + alert on schema mismatch. |
| OpenRouter Gemini rate limits | Medium | Cap `MAX_CONCURRENT_JOBS=5`; add jittered retry with backoff. |
| Pydantic AI structured extraction fails on unusual JD format | Medium | Retry once with stricter prompt; on second failure, mark job `errors` and skip — never crash batch. |
| Skill assessor over-grades from weak evidence | Medium | Adversarial-grader prompt + asymmetric promotion (jumping 2+ levels requires HiTL). Already designed in. |
| Eval set becomes stale as JD market shifts | High over 6 months | Eval harness logs per-month accuracy; flag drift; refresh labels quarterly. |
| the candidate gets caught up in scope-creep on Phase 3+ instead of applying to jobs | High | Phase 2.C marks "applying" as the next priority; roadmap NOW.md should enforce. |
| **Secrets leak to public repo** (Compass repo is going public) | Medium | `.gitignore` includes `.env`, `.compass/`, `*.db`; pre-commit hook scans for `sk-or-`, `sk-ant-`, `pk-lf-`, `sk-lf-`; Modal Secrets used for cloud (no env file in deployment); README `.env.example` contains only placeholders. Audit `git log -p` before first `git push origin main`. |
| **Modal cron fires at wrong wall-clock time** (TZ default = UTC) | Medium | Pin `timezone="America/Chicago"` on every `Cron()` schedule. Verify first three fires by checking `_meta/agent-log.md` timestamps match expected wall-clock. |
| **Langfuse self-hosted goes down** mid-pipeline | Low | Callback handler swallows trace failures by default; pipeline keeps running. Add a healthcheck on Langfuse before each batch; if down, log warning and continue (don't block scoring). |
| **Pydantic AI / model provider auth fails silently** | Low | On first LLM call of each batch, do a 1-token canary call; if it fails, abort batch with loud error rather than burning Modal compute. |

## Open Questions (resolved before implementation)

- ✅ Model choice: Gemini Flash for extract/score, Sonnet for reflect/tailor/assessor
- ✅ FDE track: dropped from scope
- ✅ ATS coverage in MVP: Greenhouse + Lever + Ashby only; Wave 2 in Phase 3+
- ✅ HiTL approach: auto-approve for MVP, MCP-tool-driven approvals for Phase 1.B (not real LangGraph interrupt)
- ✅ Eval harness: deferred to Phase 2.A so we have real jobs to label

## References

- `compass-vault/_profile/target-companies.md` — tier mapping
- `compass-vault/_profile/preferences.md` — comp/geo/tier weights
- Job-market report: `~/Downloads/agentic-ai-job-market-2026.md`
- Roadmap v2: `~/Downloads/agentic-ai-roadmap-v2.md`
- ATS coverage research: in-conversation result of 2026-05-17 background research task
