# Phase 1.A Complete — Retrospective & Handoff

> **Read this first if you're picking up Compass in a new chat.** Everything that shipped in 1.A, every issue caught by the two-stage review loop, what's deferred to 1.B, and how to resume.

**Final tag:** `phase-1a-application-tracking` · **Tests:** 178 passing · **Lint:** clean · **Date completed:** 2026-05-18

---

## One-paragraph recap

Phase 1.A made Compass daily-usable. Before this phase, the vault was both polluted with out-of-scope JDs (sales / PM / design / CS reaching extract+score+vault_write at full LLM cost) and *biased toward easy wins* (the SCORE_THRESHOLD≥3.5 write gate hid every stretch role from the master gap plan — exactly the roles whose gaps you'd want to study toward). Phase 1.A fixes both with a three-stage role-family classifier (keyword pre-filter → zero-LLM body-signal upgrader → Gemini Flash for borderline titles), removes the threshold write gate, populates `role_family` + company `tier` on every JobNote, ships the application-lifecycle MCP tools (`add_application`, `update_application_status`, `list_pending_actions`, `tailor_resume`), and rebuilds the Obsidian dashboard around what to do today vs. what to study this week.

**Authoritative spec:** `docs/superpowers/specs/2026-05-18-compass-phase-1a-application-tracking.md`
**Implementation plan:** `docs/superpowers/plans/2026-05-18-compass-phase-1a-application-tracking.md`

---

## What shipped (10 commits, ~2,800 LoC across 36 files)

| # | Tag | What | Tests added |
|---|---|---|---|
| 1 | `522d8a0` → `6c403fd` | **Role-family classifier** — `keyword_classify` + `upgrade_family` (body-signal promotion) + `llm_classify` (Gemini Flash borderline) | 25 |
| 2 | `225ec03` | **`intake_filter_node`** — graph node + state plumbing (`in_scope`, `role_family`) | 9 |
| 3 | `90d722f` | **Graph topology rewire** — `intake → intake_filter → (END | extract)` conditional edge | 3 |
| 4 | `f380e4d` | **`target_companies` tier parser** — reads `_profile/target-companies.md` | 10 |
| 5 | `c298722` | **`vault_write_node` overhaul** — drops SCORE_THRESHOLD gate; populates `role_family` + `tier` on JobNote; read-before-write for CompanyNote.tier (bug #15 regression guard) | 5 |
| 6 | `50e1157` | **`write_application_note`** — idempotent on `(company, title, applied_date, job_ref)`; 8-char URL hash in filename | 4 |
| 7 | `bd89f0b` | **`compass/applications/lifecycle.py`** — `add_application`, `update_application_status`, `list_pending_actions`, public `find_jobnote`; `_UNSET` sentinel for omit/clear/replace semantics | 11 |
| 8 | `1c480da` | **`infer_remote_policy`** — substring parser for Greenhouse + Lever `location` strings | 20 |
| 9 | `3011433` | **MCP tools** — wires the lifecycle into `mcp_server/server.py` as `@mcp.tool()` callables; uses `clear_next_action` boolean flags since MCP can't transmit Python sentinels | 8 |
| 10 | (vault file) | **`dashboard.md` rewrite** — 5 Dataview panels: top 5 apply-now, in-flight by stage, today's actions, top gaps, stretch roles | — |

**Net test count:** 85 (Phase 0.B baseline) → 178 (+93 across all 1.A files).

**Subagent-driven execution:** each task ran with a fresh implementer subagent, followed by spec-compliance + code-quality reviews, fix-cycle as needed, then merge. Three tasks (1, 2, 4, 5, 7) needed at least one round of fixes from review feedback; the rest landed clean on first pass.

---

## Bugs caught and fixed by the two-stage review loop

Phase 0 found 23 silent data-correctness bugs across 4 audit passes — Phase 1.A's reviewer dispatches caught analogous issues *before* commits landed. The pattern that surfaced:

| # | Bug | Where surfaced | Fix |
|---|---|---|---|
| 1 | `keyword_classify` substring trick failed for acronyms — `" sdr,"` never matched real titles (false negative); `" ux "` matched `"auxiliary ux"` (false positive) | Quality review, Task 1 | Split into `OUT_SUBSTRING_KEYWORDS` + `OUT_WORD_KEYWORDS` (regex `\b` word boundaries) |
| 2 | `llm_classify` didn't truncate `jd_first_500` — prompt-injection vector + cost runaway | Quality review, Task 1 | Add `jd_first_500 = jd_first_500[:500]` at top |
| 3 | `TestLLMClassify` used `asyncio.run()` inside sync tests despite `asyncio_mode = "auto"` in pyproject | Quality review, Task 1 | Convert to `async def test_*` |
| 4 | `run_pipeline` aggregate dict missing the new state keys (`in_scope`, `role_family`) — would `KeyError` on access | Quality review, Task 2 | Add both keys to the aggregate literal |
| 5 | Routing test ran the full graph including real `extract_node` (LLM-touching) — non-hermetic | Quality review, Task 3 | Replace with direct unit tests of `_route_after_filter` predicate |
| 6 | Module docstring on `graph.py` still described Phase 0.B topology | Quality review, Task 3 | Update to reflect new `intake_filter` flow |
| 7 | `target_companies._normalize` stripped only whitespace; spec says strip non-alphanumerics — `"Hebbia/Glean"`-style names wouldn't roundtrip | Quality review, Task 4 | `re.sub(r"[^a-z0-9]", "", ...)` |
| 8 | `target_companies.get_tier` re-parsed on every call when companies dict was empty `{}` (truthiness gotcha) | Quality review, Task 4 | Sentinel `_company_to_tier: dict | None = None` with `is None` guard |
| 9 | `vault_write.py` module docstring claimed `update_skill_note` is called — stale from Phase 0 (gap_aggregator owns this now) | Quality review, Task 5 | Update docstring; clarify skill counters are derived |
| 10 | `_state(...)` test helper didn't include `in_scope` / `role_family` keys, masking potential future regressions | Quality review, Task 5 | Add both with defaults |
| 11 | `list_pending_actions` returned raw `date` objects in the dict — FastMCP can't JSON-serialize them | Quality review, Task 9 | Serialize through `ApplicationNote.model_dump(mode="json")`; added JSON-serializability regression test |
| 12 | `list_pending_actions` sort key relied on YAML parser converting ISO dates — fragile | Quality review, Task 7 | Use coerced `nad` as separate sort key, not the dict value |
| 13 | `test_llm_failure_defaults_to_in` asserted only `in_scope`, skipped `role_family` despite docstring | Quality review, Task 2 | Add `role_family == "other-eng"` assertion |

Plus the **FDE-eng keyword reconciliation** in Task 1 (the original plan had `"forward deployed engineer"` in both the IN keyword list AND a test asserting it returns `None`) — implementer correctly removed FDE from the keyword list so the LLM stage decides.

**Critical-lesson outcome:** every review cycle either approved immediately or surfaced a real issue that would have shipped data-quality bugs. None of the issues required more than one fix cycle to resolve. The fresh-subagent-per-task pattern preserved context and kept feedback focused.

---

## What we know works (verified empirically on real data)

Live pipeline run on 2026-05-18T15:48 against `anthropic,hebbia,gleanwork,cresta` (Greenhouse) + `sierra,decagon,ramp` (Ashby), `MAX_JOBS_PER_RUN=20`:

```
Processed: 20 | Written: 3 | Errors: 0   (16.3s, ~$0.05 OpenRouter cost)
```

✅ **Role-family gate filters correctly.** 17 of 20 dropped at intake_filter; all 17 are legitimately out-of-scope (sales, PM, brand, compliance, GTM partnerships, sales director with AI body-language). Sample from `_meta/filtered-jobs.md`:
- title-keyword drops: "Account Executive", "Sales Engineer", "Product Manager Agent Data Platform", "Brand Designer", "AI Compliance Officer"
- LLM rescues: "Sales Director" → *"implies sales, not building"*; "Amazon GTM Partnership" → *"GTM partnerships role, not engineering"*

✅ **Body-signal upgrader promotes generic SWE titles to agentic families.** The 3 written JobNotes:
- `sierra-Software_Engineer_Platform` (2024-08-28) → keyword `swe-backend`, no upgrade
- `sierra-Software_Engineer_Agent` (2025-02-13) → keyword start + body promotion → `agent-engineer`
- `sierra-Software_Engineer_Product` (2026-03-27) → keyword `swe-fullstack` + body promotion → `applied-ai`

✅ **SCORE_THRESHOLD write gate is removed.** The 0.0-score Sierra Product job was written to the vault — Phase 0.B would have dropped it. The master gap plan now considers it.

✅ **CompanyNote.tier resolves from target-companies.md.** `companies/sierra.md` correctly has `tier: apply-now`.

✅ **Master gap plan reflects stretch-role demand.** TypeScript (#3) and Go (#5) both show `apply-now: 2` — exactly the kind of stretch-role gap signal Phase 1.A was built to surface.

✅ **`_meta/filtered-jobs.md` is auto-appending** with the right format (timestamp + company + quoted-title + reason).

✅ **Pipeline-runs log** records the new run cleanly: `2026-05-18T15:48:26 | 20 | 3 | 0 | 16.3s`.

✅ **All 178 unit tests pass.** Ruff clean. No regressions in Phase 0.B test coverage.

---

## What's deferred (and to which phase)

Carryover from the Phase 1.A spec's "Out of scope" section plus issues surfaced during the live run:

| Concern | Severity | Phase | Why deferred |
|---|---|---|---|
| Real `interrupt()` + `AsyncSqliteSaver` checkpointing for HiTL | Portfolio claim | **1.B** | Auto-approve still in place; works fine for daily use |
| Modal cron (daily scrape + weekly skill_assessor) | Required for "no babysitting" | **1.B** | Spec phase ordering |
| RAG via Chroma for profile retrieval (replaces string-injection in `score_node`) | Portfolio claim | **1.B** | String injection works for the current profile size |
| **Langfuse callback API mismatch** — every run logs `LangchainCallbackHandler.__init__() got an unexpected keyword argument 'host'`. Pipeline degrades gracefully, no traces recorded. | Observability | **1.B** | Bug #23 carryover from Phase 0; dedicated 1.B observability work |
| Taxonomy expansion (PostgreSQL, Redis, Kafka, ClickHouse, etc.) | Coverage | **1.B** | Weekly review of unknown-skills-log will surface candidates |
| **Hebbia Greenhouse board 404s** — they moved off Greenhouse. Logged warning, no impact on the run. | Coverage | **1.B** | Update ATS-board config when restructuring for Modal Secrets |
| CLI env vars don't override `.env` for ATS board lists | Config UX | **1.B** | Low impact; resolve when restructuring config for Modal |
| 30-JD labeled eval set + score-MAE / skill-recall harness | Portfolio claim | **2.A** | We now have ~24 scored JDs to draw from |
| Public Langfuse trace URL in README | Portfolio claim | **2.B** | After 1.B Langfuse fix lands |
| README polish + architecture diagram + screenshots | Portfolio claim | **2.B** | After daily use validates the system end-to-end |
| Blog post on the skill_assessor loop | Portfolio claim | **2.C** | Requires assessor running live via Modal cron (1.B) |
| Workday / Apple / Google / AWS / Microsoft scrapers | Coverage | **3+** | Long-tail per master spec |
| Cleanup of pre-Phase-1A stale JobNotes (entries with `role_family=''` from earlier today's runs before tasks merged) | Cosmetic | now (human-run) | One-shot: `uv run python -m scripts.cleanup_stale_jobnotes --apply` |

---

## Files added or significantly changed

```
~/Documents/compass/
├── compass/
│   ├── applications/                         # NEW package
│   │   ├── __init__.py
│   │   └── lifecycle.py                      # add_application / update_status / list_pending / find_jobnote
│   ├── pipeline/
│   │   ├── role_family.py                    # NEW — keyword classifier + body-signal upgrader + LLM fallback
│   │   ├── state.py                          # +in_scope, +role_family on CompassState
│   │   ├── graph.py                          # intake_filter wired in; _route_after_filter predicate; aggregate dict updated
│   │   └── nodes/
│   │       ├── intake_filter.py              # NEW
│   │       └── vault_write.py                # SCORE_THRESHOLD gate removed; role_family + tier populated; CompanyNote read-before-write
│   ├── vault/
│   │   ├── target_companies.py               # NEW — parses _profile/target-companies.md → tier map
│   │   └── writer.py                         # +write_application_note + _application_filename
│   ├── scrapers/
│   │   ├── _remote_parser.py                 # NEW — infer_remote_policy
│   │   ├── greenhouse.py                     # remote=infer_remote_policy(location_str)
│   │   └── lever.py                          # same
│   └── mcp_server/server.py                  # +add_application, +update_application_status, +list_pending_actions, +tailor_resume
├── tests/                                    # 93 new tests across all the modules above
└── docs/
    ├── PHASE_1A_COMPLETE.md                  # THIS FILE
    └── superpowers/
        ├── specs/2026-05-18-compass-phase-1a-application-tracking.md
        └── plans/2026-05-18-compass-phase-1a-application-tracking.md

~/Documents/compass-vault/                    # agent-owned product vault
├── dashboard.md                              # rewritten — 5 Dataview panels (apply-now / in-flight / today's actions / top gaps / stretch)
├── _meta/
│   └── filtered-jobs.md                      # NEW auto-appending log (intake_filter writes here)
└── jobs/                                     # 3 new Sierra JobNotes with proper role_family + tier
```

---

## How to use Compass right now (daily flow, post-1.A)

```bash
cd ~/Documents/compass

# Morning: scrape, score, write, regenerate gap plan
MAX_JOBS_PER_RUN=20 \
  GREENHOUSE_BOARDS=anthropic,gleanwork,cresta \
  ASHBY_BOARDS=sierra,decagon,ramp \
  uv run python -m compass.pipeline.graph

# Open the dashboard in Obsidian
# ~/Documents/compass-vault/dashboard.md  →  5 Dataview panels render
#   • Apply now — top 5 unactioned
#   • In-flight applications (by stage)
#   • Today's next actions
#   • Top gaps this week
#   • Stretch roles (in-scope, score < 3.5)

# Pick a role to apply to. In Claude Code / Cursor (via compass MCP server):
#   add_application(job_id="Sierra-Software_Engineer_Agent")
#   → JobNote.status becomes "applied"
#   → ApplicationNote created at applications/2026-05-18-sierra-Software_Engineer_Agent-<hash>.md

# After the recruiter screen:
#   update_application_status(
#     app_id="2026-05-18-sierra",
#     status="screen",
#     next_action="prep onsite case study",
#     next_action_date="2026-05-25"
#   )

# Daily standup query:
#   list_pending_actions()  →  every app with next_action_date ≤ today
```

**Cost expectation:** ~$0.05/run for 20 jobs (down from Phase 0.B's ~$0.45 because the role-family gate now drops ~70% of postings before extract/score). Most days you'd run once.

---

## How to start Phase 1.B (next chat picks up here)

Phase 1.B scope per master spec: **automation + skill loop**. Three independent sub-projects:

1. **HiTL realization** — real `interrupt()` + `AsyncSqliteSaver` checkpointing + external timeout via `compass/hitl/timeout_checker.py` Modal cron + MCP `pending_approvals` / `approve` tools.
2. **RAG retrieval** — `compass/rag/indexer.py` + `compass/rag/retriever.py` build a Chroma index of `_profile/skill-inventory.md` chunks; `score_node` retrieves top-k instead of injecting full inventory.
3. **Modal cron + Langfuse fix + Modal Secrets** — `modal_app.py` defines `@app.function(schedule=Cron("0 9 * * *"), timezone="America/Chicago")` for daily scrape and weekly assessor. Fix the `CallbackHandler(host=...)` API mismatch so traces actually land in Langfuse.

### Resume-in-new-chat brief

```
You're picking up Compass after Phase 1.A shipped (tag phase-1a-application-tracking).
Phase 1.A retrospective + handoff is at:
  ~/Documents/compass/docs/PHASE_1A_COMPLETE.md

Read that doc first, then the authoritative master spec:
  ~/Documents/compass/docs/superpowers/specs/2026-05-17-compass-mvp-to-portfolio-ship-design.md

Phase 1.B scope: automation + skill loop. The spec phase table is the source of truth.
Phase 1.B is the LARGEST phase by file surface — strongly consider breaking it into
sub-phases 1.B.1 (HiTL), 1.B.2 (RAG), 1.B.3 (Modal cron + Langfuse) and writing
separate plans for each.

Critical lessons from Phases 0 and 1.A:
1. Tests check shape; data-correctness bugs need real-data inspection.
   After ANY claim that 1.B is ready, run adversarial probing on real outputs
   BEFORE believing the claim.
2. The two-stage review loop (spec compliance → code quality) catches ~1 issue
   per task on average. Don't skip reviews even on "mechanical" tasks.
3. Module-level `from compass.config import VAULT_PATH` freezes at import time
   and silently breaks the temp_vault test fixture. Use late-binding via
   `import compass.config as cfg; cfg.VAULT_PATH` inside function bodies for
   every new module.

Run `cd ~/Documents/compass && uv run pytest -q` to confirm 178 tests pass
before starting any new work.

Invoke superpowers:writing-plans for Phase 1.B.1 (HiTL) first. Use 1.A's plan
as the structural template:
  ~/Documents/compass/docs/superpowers/plans/2026-05-18-compass-phase-1a-application-tracking.md

For execution, use superpowers:subagent-driven-development. The pattern that
worked in 1.A:
  - One implementer subagent per task with full task text + scene-setting context
  - One combined spec+quality reviewer per task (sonnet model is plenty)
  - Fix-cycle → re-review → mark complete → next task
  - Pause before Tasks that hit production (real LLM calls, real vault writes)
```

---

## Vault snapshot at end of Phase 1.A

| Metric | Value | Δ since Phase 0.B |
|---|---|---|
| JobNotes in vault | 21 | +3 (this run only; some pre-Phase-1A entries persist) |
| SkillNotes | 99 | +4 (LLMs, Large Language Models, Machine Learning, Deep Learning from Phase 0.B retro) |
| CompanyNotes | ~9 | (unchanged) |
| Pipeline runs logged | 18 | +5 |
| Filtered-jobs log entries | ~17 | NEW (didn't exist before 1.A) |
| Master gap plan top-3 | LangGraph · LLMs · TypeScript | Stretch-role weighting working |
| Total commits Phase 0.B → 1.A | 13 | — |
| Test count | 178 | +93 |
| LoC delta | +2,785 / −195 | — |

---

## Critical lesson (carry forward to Phase 1.B)

**Tests check shape. Smoke tests check counts. Two-stage subagent review catches code-quality issues. None of these catch data-correctness bugs on real inputs.**

Phase 1.A's automated verification step (Task 11) ran the pipeline against real ATS boards and confirmed the gate filters real roles correctly, the body-signal upgrader promotes real titles, and the threshold removal lets stretch roles through. That's the verification that mattered. The 178 passing tests gave us *correctness in the small*; the 20-job real-data run gave us *correctness in production*.

For Phase 1.B specifically — when the HiTL flow lands with real `interrupt()`, you cannot verify it without invoking the actual graph with a real LLM in the loop and confirming the checkpoint state survives a process restart. Don't trust the tag until you've checkpoint-resumed at least one paused thread end-to-end.

---

**Phase 1.A is functionally complete and automatically verified. The human-driven verification steps (create 3 real applications, edit a CompanyNote, render the dashboard in Obsidian) are recommended before considering 1.A truly done — but the pipeline runs cleanly on real data today, and the system is genuinely usable as your morning job-search tool.**
