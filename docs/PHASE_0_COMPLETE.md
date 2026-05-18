# Phase 0 Complete — Retrospective & Handoff

> **Read this first if you're picking up Compass in a new chat.** Everything that shipped, every silent bug found, every deferred issue with its target phase. After reading this you should know exactly where to resume.

**Final tag:** `phase-0b-pipeline-mvp` · **Tests:** 72 passing · **Lint:** clean · **Date completed:** 2026-05-18

---

## What Compass is (one-paragraph recap)

Compass is an agentic career-coaching system. It scrapes ATS job boards, scores each posting against a candidate profile, identifies skill gaps, and generates a weekly study plan. The candidate profile + every JD + every skill grade + every gap-plan output lives in an Obsidian-readable vault at `~/Documents/compass-vault/`. Akash builds and uses it himself; it's both a daily tool and a public portfolio artifact for tier-2 agentic-AI hiring (Sierra Agent Engineer, Decagon MTS, Ramp ADP, etc.).

**Authoritative spec:** `docs/superpowers/specs/2026-05-17-compass-mvp-to-portfolio-ship-design.md`

---

## What Phase 0 built

| Phase | Tag | What shipped |
|---|---|---|
| **0.A — Foundation** | `phase-0a-foundation` | 3 ATS scrapers (Greenhouse, Lever, Ashby), vault reader + writer, schema-validated JobNote/SkillNote/CompanyNote, tax­onomy loader/normalizer, learning-vault bridge, smoke scripts |
| **0.B — Pipeline MVP** | `phase-0b-pipeline-mvp` | All 7 LangGraph nodes (intake/extract/score/reflect/hitl/tailor/vault_write), per-node OpenRouter model routing (Gemini Flash + Sonnet), batch-level URL dedup, Langfuse callback wiring, master gap plan auto-regeneration, pipeline-run forensic log, unknown-skills review queue |

**File surface:** ~1500 LoC production + ~1500 LoC tests across ~50 files. Repo at `~/Documents/compass`.

---

## The 16 silent bugs found across Phase 0

The pattern that surfaced over and over: **unit tests passed, smoke tests passed, code looked correct — but real data was wrong**. Every "we're ready" verdict in this session got rolled back by the next adversarial probe.

### Critical / Blocker class (would have shipped clearly-wrong data)

| # | Bug | Why it was silent | Fix |
|---|---|---|---|
| 1 | **Greenhouse scraper returned empty `content`** | API list endpoint omits `content` field by default; smoke test only checked job *count* not content length | Append `?content=true`; drop empty-content jobs loudly; regression test |
| 2 | **Lever scraper passed empty `descriptionPlain`** | ~14% of Spotify postings have empty plain text but populated HTML | Fall back to stripped HTML; drop both-empty; regression test |
| 3 | **Ashby scraper had no empty-content guard** | Same class as #1 and #2 | Same log+drop pattern; regression test |
| 4 | **extract LLM hallucinated skills from company name** | Anthropic sales JD got "Federated Learning", "Deep Learning" — schema-valid, completely fabricated | JD-substring validation: every extracted canonical (or synonym) must appear in JD text; regression test |
| 5 | **score LLM hallucinated matched/missing from candidate profile** when JD `required_skills=[]` | LLM listed every profile skill as matched, every other as missing — schema-valid, semantically meaningless | Tightened prompt + code post-filter `_constrain_to_jd_skills`; regression tests |
| 6 | **taxonomy parser misread 3-column tables** | Voice/Fine-Tuning sections lack a Synonyms column; parser blindly used cells[1] → `normalize("low")` returned `"DPO"` | Per-section header column-detection + demand-token allow-list filter; regression test |
| 7 | **taxonomy substring fallback false positives** | `"Pythonist"→Python`, `"Goblet"→Go`, `"Reactivity"→ReAct` via substring-in-key match | Removed substring fallback entirely; strict synonym match only; regression tests |
| 8 | **React vs ReAct case collision** | `_norm_key("React")` = `_norm_key("ReAct")` — JD mentioning React.js silently became agentic ReAct pattern | `_CASE_SENSITIVE_CANONICALS` set; case-mismatched inputs return None unless explicit synonym; regression test |

### Major class (degraded data quality, not catastrophic)

| # | Bug | Why it was silent | Fix |
|---|---|---|---|
| 9 | **gap_aggregator ignored `nice_to_have_skills`** | Only iterated `skills_required`; nice-to-haves never contributed to demand signal | Aggregate both at 1.0 + 0.5 weight, set-deduped per job |
| 10 | **skill_assessor used outdated pydantic-ai API** | `result_type=`/`result.data` were the old names — would throw on first real invocation | Routed through `compass.llm.make_agent`; use `output_type=`/`result.output` |
| 11 | **JobNote filename collisions on similar titles** | `Engineer/Backend` and `Engineer (Backend)` both sanitized to `Engineer_Backend.md` — silent overwrites | Append 8-char SHA-1 of URL to filename; different URLs guaranteed different files |
| 12 | **Skill counter drift** (`appears_in_jobs: 12` but real count 3) | `update_skill_note` accumulated on every overwrite — even URL-dedup rewrites incremented | Removed call from vault_write_node; `gap_aggregator._sync_skill_counters` rewrites counts from JobNote frontmatter at end of each run |
| 13 | **JobScore had no range constraint** | LLM returning 7.5 passed Pydantic; gap_aggregator's `score/5.0` computed 1.5 inflating gap scores | `Field(ge=0.0, le=5.0)` + clamp in aggregator |
| 14 | **score_factor 0.1 floor let 0.0-score jobs poison gap math** | Sales role scored 0.0 still contributed 10% weight to any hallucinated skills | Zero score_factor below 1.0 (rubric's "wrong field" zone) |
| 15 | **write_company_note clobbered human-edited fields every run** | `tier`, `geo`, `tags`, `hiring_signal`, etc. reset to defaults — destroyed Obsidian edits | Read existing values, preserve when incoming note has default |
| 16 | **score_node didn't deduplicate matched ∩ missing** | Gemini Flash occasionally put borderline skill in both lists; gap_aggregator counted as gap despite being matched | Post-filter resolves overlap in favor of matched_skills |

### Plus

- **5 hygiene fixes**: AI-tell docstrings, duplicate wrapper comments, `except Exception: logger.warning` losing tracebacks, hardcoded paths in `.env.example`, performative comments
- **2 prompt-design improvements**: extract injects canonical taxonomy directly; tailor uses bounded JD chars
- **Code-level seniority fallback** when LLM returns "unknown" but title says "Senior"/"Staff"/"Junior"

---

## What we know works (verified empirically on real data)

✅ **Scrapers return real JD content** across all 3 ATSes (Greenhouse, Lever, Ashby) — 1023+ jobs sampled, 0 silent-empty bugs
✅ **Extract** produces canonical-typed skills, drops hallucinations against JD text
✅ **Score** is constrained to JD universe; matched/missing overlap deduped
✅ **Tailor** fires only on `human_approved=True`; references real candidate projects (verified on Sierra/Decagon/Cresta/Ramp JobNotes — "Cisco MCP", "Minx", concrete numbers)
✅ **Vault writes** are idempotent on URL; filenames collision-free; human Obsidian edits preserved
✅ **gap_aggregator** weights correctly; counts are derived (no drift); creates missing skill notes; zeros below-rubric scores
✅ **skill_assessor agent** constructs without error (was broken before)
✅ **Master gap plan** reflects real JD-driven demand: "Eval harness" surfaces as top gap (matches the market report's flag)
✅ **HiTL auto-approve** uses explicit three-way check (`True`/`False`/`None`) ready for Phase 1.B real `interrupt()`
✅ **Pipeline-runs log** appends one row per invocation (forensic + portfolio)
✅ **Unknown-skills log** captures non-canonical extractions for weekly review

---

## Files you'll need to know

```
~/Documents/compass/                              # this repo
├── compass/
│   ├── analysis/
│   │   ├── gap_aggregator.py                     # ranks gaps, syncs skill counters
│   │   └── skill_assessor.py                     # adversarial-grader Pydantic AI agent
│   ├── llm.py                                    # per-node OpenRouter model resolver
│   ├── mcp_server/server.py                      # MCP tools for Claude Code/Cursor
│   ├── pipeline/
│   │   ├── graph.py                              # run_pipeline + LangGraph wiring + Langfuse
│   │   ├── state.py                              # CompassState, RawJob, JobRequirements, JobScore
│   │   └── nodes/                                # 7 node files
│   ├── scrapers/{greenhouse,lever,ashby}.py
│   └── vault/
│       ├── reader.py / writer.py                 # frontmatter-aware I/O
│       ├── schemas.py                            # JobNote / SkillNote / CompanyNote / etc.
│       ├── taxonomy.py                           # canonical skill registry + normalizer
│       └── learning_bridge.py                    # learning-vault:// URI resolver
├── tests/                                        # 72 tests across pipeline, scrapers, vault
├── scripts/
│   ├── seed_skills.py                            # initial 95-skill SkillNote seed
│   ├── test_scrape.py                            # smoke
│   └── test_vault_roundtrip.py                   # smoke
├── docs/
│   ├── PHASE_0_COMPLETE.md                       # THIS FILE
│   ├── ARCHITECTURE.md
│   ├── ROADMAP.md, STATUS.md, RUNBOOK.md
│   └── superpowers/
│       ├── specs/2026-05-17-compass-mvp-to-portfolio-ship-design.md  # AUTHORITATIVE
│       ├── plans/2026-05-17-compass-phase-0a-foundation.md
│       └── plans/2026-05-17-compass-phase-0b-pipeline-mvp.md
├── CLAUDE.md
└── .env / .env.example

~/Documents/compass-vault/                        # agent-owned product DB
├── _profile/                                     # candidate profile (human-edited)
│   ├── resume.md
│   ├── skill-inventory.md
│   ├── target-roles.md
│   ├── target-companies.md
│   ├── preferences.md
│   ├── role-clarifications.md
│   └── interview-prep.md
├── _meta/
│   ├── skill-taxonomy.md                         # canonical 95-skill registry
│   ├── unknown-skills-log.md                     # weekly review queue
│   ├── pipeline-runs.md                          # one row per pipeline invocation
│   └── agent-log.md                              # every vault mutation
├── jobs/                                         # one JobNote per scored JD
├── skills/                                       # 95 SkillNote files
├── companies/                                    # CompanyNote per scraped company
├── applications/                                 # human-maintained (Phase 1.A)
├── interviews/                                   # human-maintained
├── study-plans/master-gap-plan.md                # auto-regenerated
└── dashboard.md                                  # Dataview entrypoint

~/Documents/learning-vault/                       # human thinking surface
├── projects/{compass,minx}/                      # decisions, debug logs
├── interview-prep/                               # STAR stories, deep-dive scripts
├── leetcode/                                     # pattern journal + progress
└── roadmap/{NOW,HORIZON}.md
```

---

## How to use Compass right now (daily flow)

```bash
cd ~/Documents/compass

# Run pipeline once on a few apply-now boards
MAX_JOBS_PER_RUN=10 \
  GREENHOUSE_BOARDS=anthropic,hebbia,gleanwork,cresta \
  ASHBY_BOARDS=sierra,decagon,ramp \
  uv run python -m compass.pipeline.graph

# Or use the full configured set from .env
uv run python -m compass.pipeline.graph

# Open the gap plan
cat ~/Documents/compass-vault/study-plans/master-gap-plan.md

# Open the dashboard (Obsidian renders Dataview queries)
# In Obsidian: ~/Documents/compass-vault/dashboard.md
```

**Cost expectation:** ~$0.45/day for 50 jobs (Gemini Flash extract+score, Sonnet tailor on high-score). Cap pre-set at `MAX_CONCURRENT_JOBS=5`.

---

## What's deferred and to which phase

| Concern | Severity | Phase | Why deferred |
|---|---|---|---|
| Application lifecycle tracking (`add_application` workflow, status transitions, next-action reminders) | Required for daily use | **1.A** | Spec phase ordering |
| Dataview dashboard polish | Required for daily use | **1.A** | Same |
| Company `tier` lookup from `target-companies.md` (always "unknown" today) | Cosmetic in vault | **1.A** | TODO marker in vault_write_node |
| Role-family gate (skip pre-sales/PM JDs before scoring) | Cost optimization | **1.A** | Sales roles already score 0.0 correctly; just wastes LLM calls |
| Modal cron (daily scrape + weekly skill_assessor) | Required for "no babysitting" | **1.B** | Spec phase ordering |
| Real `interrupt()` + `AsyncSqliteSaver` checkpointing for HiTL | Portfolio claim | **1.B** | Auto-approve is intentional 0.B per spec |
| RAG via Chroma for profile retrieval (replaces string-injection) | Portfolio claim | **1.B** | String injection works for now; Chroma is the "right" approach for >100k profile |
| Langfuse callback API mismatch (graceful degradation in place; logs trace failures) | Observability | **1.B** | Dedicated observability phase |
| Concurrent-write race on `update_skill_note`/`write_company_note` (no file lock) | Hypothetical | **1.B** | Currently can't happen (we removed update_skill_note from pipeline); Modal cron concurrency is what would trigger it |
| `lru_cache` invalidation for long-lived MCP server | Hypothetical | **1.B** | Process restart resets cache; only matters for hours-long sessions |
| 30-JD labeled eval set + nightly regression eval | Portfolio claim | **2.A** | Need real scored JDs first (we now have ~28) |
| Public Langfuse trace URL in README | Portfolio claim | **2.B** | After Langfuse wiring in 1.B |
| README polish + architecture diagram + screenshots | Portfolio claim | **2.B** | After 1.A makes the system genuinely usable daily |
| Blog post on the skill_assessor loop | Portfolio claim | **2.C** | Differentiated story; requires assessor to actually run live (Phase 1.B cron) |
| Workday / Apple / Google / AWS / Microsoft scrapers | Coverage expansion | **3+** | Long-tail per spec |
| Getro / YC WAAS / HN Who-is-Hiring | Coverage expansion | **3+** | Long-tail per spec |
| CLI env vars don't override `.env` for ATS board lists (running with `LEVER_SLUGS=` still hits the .env defaults; produces noisy 404 logs) | Config UX | **1.B** | Low-impact; resolve when restructuring config for Modal Secrets in 1.B |
| Greenhouse / Lever scrapers don't populate `remote` field (Ashby does — fixed 2026-05-18) | Cosmetic | **1.A** | Greenhouse/Lever APIs encode remote in `location` string rather than a typed flag; needs string-pattern parsing |
| Taxonomy expansion for adjacent infra skills (PostgreSQL, Redis, Kafka, ClickHouse, Salesforce, HubSpot, Figma) | Coverage | **1.B** | Out of agentic-AI core; weekly review of unknown-skills-log surfaces these as candidates |

**Every item has a known fix and an assigned phase. Nothing in Phase 0 is broken-but-unflagged.**

## Post-retro fixes (2026-05-18 PM session)

Adversarial re-verification of Phase 0 surfaced 6 additional silent bugs that the original "ready" pass missed. All landed before this addendum:

| # | Bug | Fix |
|---|---|---|
| 17 | **`SCORE_THRESHOLD` not enforced on vault writes** — `.env` documented it as gating writes but only `hitl_node` used it. Vault filled with sub-3.5 sales/PM/designer noise. | `vault_write_node` short-circuits and logs to agent-log below threshold; regression test in `tests/pipeline/test_vault_write.py` |
| 18 | **"LLMs" / "Large Language Models" / "Machine Learning" / "Deep Learning" / "Reinforcement Learning" missing from taxonomy** — agentic-AI JDs lost their core skill signal and dropped to unknown-skills log. | Added 4 canonicals with synonym coverage to `_meta/skill-taxonomy.md`; regression test in `tests/vault/test_taxonomy.py::test_normalize_ml_foundations` |
| 19 | **Full JD body discarded** — only the LLM-generated summary survived to the JobNote, blocking human verification of agent extractions. | `write_job_note(note, full_description=...)` appends a `## Full JD` section; vault_write_node passes `job.description`; regression tests |
| 20 | **Ashby scraper read wrong field** — used `locationName` but live boards (Sierra, Posthog, Ramp) populate `location`. Every Ashby JobNote had `location: null`. Also: `isRemote` was discarded. | Fall back through `location → locationName`; capture `isRemote` into `RawJob.remote`; regression test |
| 21 | **`score_reasoning` occasionally truncated mid-clause** by Gemini Flash structured-output; passed Pydantic validation because any non-empty string was valid. | `_score_with_retry` enforces minimum length + terminal punctuation; retries once before accepting; regression tests for both retry and no-retry paths |
| 22 | **31 stale pre-fix JobNotes still in vault** with hallucinated matched/missing skills (URL-dedup prevented refresh). | One-shot cleanup script `scripts/cleanup_stale_jobnotes.py` — dry-run by default, `--apply` deletes. Mtime cutoff + JD-universe leak check identify the bad notes. Per CLAUDE.md, deletion is human-triggered. |
| 23 | **Langfuse callback API mismatch** (`host` kwarg invalid in newer `langfuse.langchain.CallbackHandler`). Already flagged in retro; degrades gracefully but no traces recorded. | Deferred to Phase 1.B observability work — already in deferred table above. |

**Tests:** 72 → 81 (9 new regression tests). **Lint:** clean.

**One-time cleanup the user runs:**
```bash
uv run python -m scripts.cleanup_stale_jobnotes              # dry-run
uv run python -m scripts.cleanup_stale_jobnotes --apply      # actually delete
# then:
uv run python -m compass.pipeline.graph                       # re-score with current code
```

## Known semantic limitation introduced in this pass (must be addressed first in Phase 1.A)

The bug #17 fix (enforcing `SCORE_THRESHOLD` on vault writes) cleaned up vault clutter but introduced a **gap-aggregator bias**: only roles you'd score ≥3.5 on contribute to the master gap plan. This is the **wrong filter** for the project's goal.

**What Akash actually wants** — and what the gap aggregator should reflect — is "the skills every agentic-engineering JD asks for, even the ones I'd score 2.0 on today, because those are the ones I should be studying toward." Filtering by match score hides exactly the stretch roles whose gaps are most informative for study planning.

The right filter is **role family** (agentic-eng vs sales/marketing/design), applied **before** scoring so non-relevant JDs never burn an LLM call. Sales/PM/designer JDs drop out at the gate; agentic-eng JDs all reach the vault regardless of current match score; the gap aggregator reads everything.

### Phase 1.A first-task ordering (do this before anything else)

1. **Implement role-family gate** in a new `compass/pipeline/nodes/intake_filter.py` (or extend `intake_node`). Classifies each `RawJob.title` + JD first 500 chars into IN-SCOPE vs OUT. Runs **before** `extract_node` so out-of-scope JDs never burn an LLM call. Suggested architecture: cheap Gemini Flash classifier (one tool call per JD, ~$0.0005) with a title-keyword pre-filter for obvious cases.
2. **Remove the `SCORE_THRESHOLD` gate from `vault_write_node`** (lines 50–66 of `compass/pipeline/nodes/vault_write.py`) — keep it only in `hitl_node` where it gates tailor-paragraph generation. Once role-family filtering removes the noise upstream, the threshold-on-write gate becomes harmful: it hides agentic-eng roles whose gaps you should be studying.
3. **Populate `role_family`** on the JobNote (currently `''` on every note — dead field) from the gate's classification. Phase 1.A's Dataview dashboard groups by it.
4. **Re-cleanup** the vault one more time after this change ships and re-run the pipeline so the master gap plan reflects all agentic-eng roles in the wild.

Skipping step 2 means continuing to ship a gap plan that's biased toward easy wins instead of stretch targets — directly contrary to what Akash said he wants the tool to do.

### Role-family scope definition (Akash, 2026-05-18)

**IN-SCOPE — keep these in the vault, contribute to gap plan, eligible for tailoring:**

The unifying criterion is **"engineering work that touches agentic AI or production AI systems"**. Specifically:

- Software engineering: Backend / Frontend / Fullstack / Product / Platform / Mobile / Infrastructure / Founding
- Applied AI / AI Engineer / ML Engineer / Machine Learning Engineer
- Agent Engineer / Agentic Engineer / Agent Platform Engineer / Agent Orchestration / Agent Reliability
- Forward Deployed Engineer / Deployed Engineer / AI Solutions Engineer **(when the JD body emphasizes technical implementation, not pre-sales)**
- Research Engineer **(applied — building shipping systems, not pure research labs)**
- Developer Experience / DevTools when the product is AI/agent infrastructure
- AI Infrastructure / LLM Platform / Inference / Eval Engineer
- Customer Engineer **(only when JD body shows real building, not sales support)**

**OUT — drop at the gate, never score, never tailor:**

- Sales: Account Executive, SDR, BDR, Account Manager, Enterprise Sales
- Pre-sales: Solutions Architect (pre-sales), Sales Engineer (most), "Solution Architect (Presales)"
- Customer Success: CSM, Customer Experience, Customer Support (even "Technical CSM" unless JD is heavy on building)
- Product: Product Manager, Group PM, "Agent PM" **(borderline — keep only if JD explicitly says coding/prototyping is core)**
- Conversational Designer / AI Designer / UX / Brand / Web Designer / Motion Graphics
- Marketing / Content / Growth / Demand Gen / Lifecycle
- Accounting / Finance / Operations / HR / People / Recruiting
- Legal / Compliance / Trust & Safety policy-side
- Internships (filter separately — most are out-of-scope for Akash's stage)

**Borderline rule — when in doubt, classify IN and let HiTL filter:**

The cost of one extra LLM extract+score (~$0.003) is far lower than the cost of silently filtering out a role Akash would have wanted to see. So the classifier should be biased toward inclusion, and the rejection prompt should require explicit evidence (job title in OUT list OR JD body shows zero engineering work) rather than the default.

**Verification after implementing:** run the pipeline on `sierra,decagon,ramp,langchain,posthog,linear,gleanwork,cresta,databricks,anthropic`. Manually scan the resulting JobNotes — every one should be a role Akash would conceivably want. Any false negatives (an agentic-eng role that got dropped) is a worse bug than a false positive (a borderline role that got scored).

---

## How to start Phase 1.A (next chat picks up here)

The Phase 1.A scope per spec: "Application tracking + dashboard — daily-usable for job decisions."

```
Phase 1.A scope per spec:
- `add_application(job_id)` MCP tool: creates an ApplicationNote linked to the JobNote
- Status transitions (applied → screen → onsite → offer/rejected) via MCP tools
- Next-action reminders surfaced in dashboard
- Dataview dashboard polish: "Apply now (top 5)", "In flight applications",
  "Today's actions", "Top gaps this week"
- Company tier lookup from `_profile/target-companies.md` (closes the
  vault_write TODO that's been "tier=unknown" since 0.B)
- Role-family gate before scoring (cost optimization)

Expected: 1 build session, ~250 LoC across ~8 files.
End state: Akash opens `compass-vault/dashboard.md` every morning to
decide applications.
```

### To resume in a new chat session, paste this brief:

```
You're picking up Compass after Phase 0.B shipped (tag phase-0b-pipeline-mvp).
Phase 0 retrospective + handoff is at:
  ~/Documents/compass/docs/PHASE_0_COMPLETE.md

Read that document first, then read the authoritative spec:
  ~/Documents/compass/docs/superpowers/specs/2026-05-17-compass-mvp-to-portfolio-ship-design.md

Phase 1.A scope: application tracking + dashboard polish. The spec phase
table is the source of truth.

Critical lesson from Phase 0: data-correctness bugs ship past unit tests
and smoke tests. After ANY claim that Phase 1.A is "ready", run
adversarial probing on real data BEFORE believing the claim. The
previous session found 16 silent bugs across 3+ audit passes — each one
required actually inspecting vault data, not just running tests.

Invoke superpowers:writing-plans for Phase 1.A implementation plan.
Use the Phase 0.B plan as a template:
  ~/Documents/compass/docs/superpowers/plans/2026-05-17-compass-phase-0b-pipeline-mvp.md

For execution, use superpowers:subagent-driven-development (worked well
for Phase 0.B — fresh subagent per task with two-stage review).

Run `cd ~/Documents/compass && uv run pytest -q` to confirm 72 tests pass
before starting any new work.
```

---

## Critical lesson learned (read this before declaring anything "ready" again)

**Tests check shape. Smoke tests check counts. Neither catches data-correctness bugs on real inputs.**

Throughout this session the pattern was:
1. "All tests pass + smoke tests succeed → we're ready"
2. User asks for adversarial probing
3. Adversarial probing finds bugs that produce wrong data without crashing
4. We fix them and add regression tests
5. We claim "ready" again
6. Loop, 3+ times

**The right test of "ready" is data inspection on real outputs.** Read 10 random JobNotes. Does the `match_score` feel right given the title? Does `skills_required` actually correspond to the JD's text? Are the matched skills plausible? Does the gap plan surface skills you'd expect a tier-2 agentic-AI hiring manager to want?

In Phase 1.A specifically, after the application-tracking feature lands:
- Manually create 3 applications via the new MCP tool
- Verify the status transitions actually update the JobNote
- Look at the dashboard Dataview queries — do they show the right rows?
- Edit a CompanyNote in Obsidian, re-run pipeline, verify edits preserved
- Apply to a real company and check the next-action reminder fires correctly

That's the only way to know it's actually ready.

---

## Vault data snapshot at end of Phase 0

| Metric | Value |
|---|---|
| JobNotes in vault | 28 (after cleaning stale pre-fix files) |
| SkillNotes | 95 (full canonical taxonomy) |
| CompanyNotes | ~12 |
| Pipeline runs logged | 14 |
| Master gap plan top-3 | Eval harness (0.65, 3 JDs), TypeScript (0.42, 4 JDs), RAG (0.20, 1 JD) |
| Unknown skills logged for review | ~30 entries (Salesforce, Figma, motion graphics, etc.) |

**These numbers will grow with each daily run.** The system is now genuinely usable as your morning job-search tool.

---

## Final session diff stats

- **45 new regression tests** (27 → 72)
- **~30 commits** between `phase-0a-foundation` and `phase-0b-pipeline-mvp`
- **16 silent bugs** found and fixed across 4 audit passes
- **5 hygiene improvements** for portfolio-grade code quality
- **0 known data-correctness issues** remaining at session end

`git log --oneline phase-0a-foundation..phase-0b-pipeline-mvp` will show the full history.

---

**Compass is ready for Phase 1.A.** Honestly this time — backed by adversarial verification, not just passing tests.
