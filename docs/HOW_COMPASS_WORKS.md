# How Compass Works

A plain-English walkthrough of what's actually in this project, how the pieces
fit together, and how data flows from a scraped job posting to a JobNote you
can apply against. Written 2026-05-19 after 14 commits past the
`phase-1b2-rag` tag.

---

## 1. What Compass is

An agentic career coach. You point it at ~50 company career boards, it
scrapes job postings, identifies which ones match your skill profile, scores
them against you with reasoning, tailors a paragraph for each, generates
cover letters on demand, regrades your skills against the live agent-eng
market, and tells you what to study next.

The whole thing runs locally on your machine. There's a daily-cron mode
(Modal) but it's not required — you can run it manually whenever.

**The interview story** is the headline: "I built the system I'm using to
run my own job search, and I built an agent inside it that grades my skills
against the live job market and tells me what to study next."

---

## 2. The three vaults (data lives in three places)

| Vault | Path | Owner | What's in it |
|---|---|---|---|
| **compass-vault** | `~/Documents/compass-vault/` | Compass writes here; you edit some files | JobNotes, SkillNotes, CompanyNotes, applications, master gap plan, dashboard, the `_profile/` files (resume, skill-inventory, preferences, target-companies) |
| **learning-vault** | `~/Documents/learning-vault/` | You own; Compass reads only via `learning-vault://` URIs | Decision logs, debug notes, courses, leetcode practice, daily notes — your second brain. Compass's skill_assessor cites these as evidence. |
| **compass repo** | `~/Documents/compass/` | Code only | Python source, tests, scripts, this doc |

The two vaults are intentionally separated. compass-vault is what the agent
writes (it can be wiped and rebuilt). learning-vault is what you write
(personal notes; the agent never modifies it). Skills get graded by reading
your learning-vault evidence URIs.

---

## 3. The data flow (one job, end to end)

```
                        ┌───────────────────────────────┐
                        │  YAML target companies        │
                        │  _profile/target-companies.   │
                        │  yaml — 49 entries with ATS   │
                        │  slugs                        │
                        └───────────────┬───────────────┘
                                        │
                       ┌────────────────┴────────────────┐
                       ↓                                  ↓
            ┌──────────────────────┐         ┌───────────────────┐
            │  scrape_greenhouse_   │         │  scrape_workday_  │
            │  many / lever / ashby │         │  many (4 banks +  │
            │  (37 boards)          │         │  Adobe)           │
            └──────────┬────────────┘         └─────────┬─────────┘
                       ↓                                ↓
                       └────────────────┬───────────────┘
                                        ↓
                       ┌────────────────────────────────┐
                       │  _scrape_all (graph.py)        │
                       │  - drop date_posted > 30d old  │
                       │  - sort each board by recency  │
                       │  - round-robin interleave      │
                       │  - cap to MAX_JOBS_PER_RUN=50  │
                       └────────────────┬───────────────┘
                                        ↓
                       ┌────────────────────────────────┐
                       │  _vault_url_set + dedup        │
                       │  Normalize URLs (case / scheme  │
                       │  / utm / trailing slash /      │
                       │  fragment) — same job via two   │
                       │  URL variants collapses to one │
                       └────────────────┬───────────────┘
                                        ↓
                       ┌─────────────────────────────────────────┐
                       │  PER-JOB graph (5 concurrent via         │
                       │  semaphore; LangGraph with               │
                       │  AsyncSqliteSaver checkpointer)          │
                       │                                          │
                       │  START → intake → intake_filter →        │
                       │                       │                  │
                       │            (out-of-scope)→ END           │
                       │            (in-scope) ↓                  │
                       │  extract → score → reflect → hitl →      │
                       │                       │                  │
                       │            (approved) → tailor →         │
                       │                          ↓               │
                       │            (rejected/auto) ─→ vault_write│
                       │                                ↓         │
                       │                              END          │
                       └────────────────┬─────────────────────────┘
                                        ↓
                       ┌────────────────────────────────┐
                       │  Post-batch:                    │
                       │  gap_aggregator.regenerate()    │
                       │  - sync SkillNote counters      │
                       │  - rebuild backlinks            │
                       │  - sync CompanyNote roles_seen  │
                       │  - rewrite master-gap-plan.md   │
                       │    (atomic via os.replace)      │
                       └────────────────────────────────┘
```

### The 8 pipeline nodes — what each does to a single job

1. **intake** — packages the RawJob into the LangGraph state. No I/O.
2. **intake_filter** — three gates BEFORE any LLM call:
   - **Reject rules from preferences.md**: `Senior` / `Staff` / `Principal` in
     title → drop. `5+ years` / `PhD required` in JD body → drop.
   - **`role_family.keyword_classify(title)`**: maps titles to families
     (`agent-engineer`, `applied-ai`, `infra-llm`, `swe-backend`, etc.)
     using IN/OUT keyword lists.
   - **Agent-body-signal gate**: AI-titled JDs (`agent-engineer` /
     `applied-ai` / `infra-llm`) MUST contain at least one strong signal
     ("LangGraph", "MCP", "multi-agent", "tool calling", etc.) — weak
     mentions of just "agent" aren't enough.
3. **extract** — Pydantic-AI LLM call (default Gemini Flash). Returns
   `JobRequirements{required_skills, nice_to_have_skills, years_experience,
   seniority, remote_policy, summary}`. Post-processing canonicalizes skill
   names against `_meta/skill-taxonomy.md` and drops skills the JD body
   doesn't actually mention (anti-hallucination guard).
4. **score** — Pydantic-AI LLM call (default Gemini Flash). Compares
   `JobRequirements` against your candidate profile (resume + RAG-retrieved
   skill-inventory chunks + YAML targeting context). Returns
   `JobScore{score 0-5, reasoning, matched_skills, missing_skills,
   tailoring_notes}`. Post-processing retries on truncated reasoning + drops
   matched/missing outside the JD's skill universe (anti-hallucination).
5. **reflect** — currently a no-op placeholder for future critique-revise.
6. **hitl** — calls `interrupt({kind: "approval_request", ...})` when score
   meets threshold. Resumes via MCP `approve_job` or Modal cron timeout.
   The `interrupt()` checkpoints state via `AsyncSqliteSaver`, so the
   pipeline can pause for hours and resume cleanly.
7. **tailor** — Sonnet LLM call. Only fires on approved jobs above
   threshold (cost gate). Returns a 3-5 sentence application paragraph
   anchored on specific projects from `_profile/role-clarifications.md`.
8. **vault_write** — persists JobNote to `compass-vault/jobs/`, upserts
   CompanyNote, adds auto-tags (`#tier/...`, `#fit/...`, `#role/...`,
   `#signal/agent-strong`, `#decision/...`). Idempotent on URL (uses
   normalize_url for dedup).

---

## 4. The components — what each module does

```
compass/
├── pipeline/
│   ├── graph.py            ← LangGraph orchestration; run_pipeline entry point
│   ├── state.py            ← CompassState TypedDict (what each node reads/writes)
│   ├── intake.py
│   ├── role_family.py      ← Title classifier (IN/OUT keywords + LLM fallback)
│   ├── add_url.py          ← Manual URL→RawJob for sites Compass can't auto-scrape
│   ├── cover_letter.py     ← On-demand cover letter draft (Sonnet)
│   └── nodes/
│       ├── intake_filter.py    ← reject rules + role_family + agent-signal gate
│       ├── extract.py
│       ├── score.py
│       ├── reflect.py
│       ├── hitl.py             ← interrupt() pause-for-approval
│       ├── tailor.py
│       └── vault_write.py
│
├── scrapers/
│   ├── greenhouse.py       ← Public Greenhouse API (boards-api.greenhouse.io)
│   ├── lever.py            ← Lever public API
│   ├── ashby.py            ← Ashby public API
│   ├── workday.py          ← Workday JSON endpoint (banks + Adobe — 5 tenants)
│   └── _remote_parser.py
│
├── vault/
│   ├── writer.py           ← write_job_note / write_company_note / write_application_note
│   ├── reader.py           ← read_resume / read_profile_section / load_reject_rules
│   ├── schemas.py          ← Pydantic models for every note type
│   ├── taxonomy.py         ← Skill canonicalization (sync against _meta/skill-taxonomy.md)
│   ├── target_companies.py ← YAML + markdown parsers; get_tier / get_company_meta
│   ├── learning_bridge.py  ← Resolves learning-vault:// URIs (path-jailed)
│   └── url_dedup.py        ← normalize_url for scheme/case/utm/etc.
│
├── rag/
│   ├── indexer.py          ← Builds Chroma index from _profile/skill-inventory.md
│   └── retriever.py        ← Top-k cosine retrieval for score_node context
│
├── analysis/
│   ├── gap_aggregator.py   ← Sync counters, rebuild backlinks, rewrite master plan
│   └── skill_assessor.py   ← Adversarial-grader assessing skills against evidence URIs
│
├── hitl/
│   ├── state_store.py      ← SQLite tracking pending HiTL approvals + atomic claim
│   ├── resume.py           ← Single source-of-truth for resuming a paused thread
│   └── timeout_checker.py  ← Modal-cron consumer for stale pending approvals
│
├── evals/
│   ├── dataset.py          ← EvalRecord schema + JSON dataset round-trip
│   ├── metrics.py          ← Pure-function MAE / RMSE / bias / recall / precision
│   ├── judge.py            ← LLM-as-judge (no hand labels needed)
│   └── runner.py           ← Two modes: --labels (rigorous) / --judge (cheap baseline)
│
├── applications/
│   └── lifecycle.py        ← Application status tracker
│
├── mcp_server/
│   └── server.py           ← FastMCP exposing the pipeline + analysis + vault as tools
│
├── llm.py                  ← make_agent() — pydantic-ai factory + OpenRouter routing
└── config.py               ← Env-var loading; per-node model selection
```

---

## 5. The MCP tools (what Claude Code can invoke)

The MCP server in `compass/mcp_server/server.py` exposes 12 tools:

| Tool | Use case |
|---|---|
| `score_jd(jd_text)` | Score a pasted JD without writing to vault — cheap sanity check |
| `add_job_from_url(url)` | Auto-fetch + score + write a JobNote (greenhouse/lever/ashby/workday/generic HTML) |
| `add_job_from_text(company, title, url, jd_text)` | For JS-rendered sites Compass can't scrape (JPM Oracle Cloud, LinkedIn) |
| `generate_cover_letter(jobnote_filename)` | Sonnet-quality 250-400 word cover letter draft for a specific JobNote |
| `run_evals(mode, limit)` | Run the eval harness — measures extract recall + score MAE |
| `search_jobs(query, limit)` | Substring search over JobNote bodies + frontmatter |
| `get_skill_gaps(job_id)` | Matched + missing skills for one JobNote |
| `get_profile(section)` | Read a `_profile/` file (path-jailed) |
| `read_learning_artifact(uri)` | Resolve a `learning-vault://` URI (path-jailed) |
| `assess_skills(scope)` | Regrade skills via adversarial grader against evidence URIs |
| `regenerate_gap_plan()` | Rebuild `study-plans/master-gap-plan.md` |
| `get_master_gap_plan()` | Read current top gaps |
| `suggest_evidence(skill, search_terms)` | Surface candidate learning-vault files to cite |
| `list_canonical_skills()` | Enumerate the taxonomy |
| `add_application(...)` | Mark a JobNote as applied; create applications/ note |

---

## 6. The skill-assessor meta-loop (the differentiated bit)

This is the loop that makes Compass interesting as a portfolio artifact:

```
        ┌─────────────────────────────────────────┐
        │  You add a new evidence URI to a        │
        │  SkillNote (e.g. point LangGraph at     │
        │  compass/pipeline/graph.py via the      │
        │  decision-log note)                     │
        └──────────────────┬──────────────────────┘
                           ↓
        ┌─────────────────────────────────────────┐
        │  Run `assess_skills(scope=["LangGraph"])│
        │  via MCP or as a Modal cron             │
        └──────────────────┬──────────────────────┘
                           ↓
        ┌─────────────────────────────────────────┐
        │  skill_assessor:                         │
        │  - resolve_many(evidence_uris) → reads   │
        │    each learning-vault:// URI (path-     │
        │    jailed; raises on traversal attempt)  │
        │  - construct adversarial-grader prompt   │
        │    with 5-level rubric + dissenting-view │
        │    requirement                           │
        │  - Pydantic-AI Agent returns             │
        │    SkillAssessment{proposed_level,       │
        │    cited_evidence, reasoning,             │
        │    dissenting_view, confidence,           │
        │    requires_hitl}                         │
        └──────────────────┬──────────────────────┘
                           ↓
        ┌─────────────────────────────────────────┐
        │  Promotion rules:                        │
        │  - single-level change → auto-apply      │
        │  - 2+ level change → requires_hitl=True; │
        │    user reviews via MCP before applying  │
        │  - grade_override set → ignore assessor  │
        └──────────────────┬──────────────────────┘
                           ↓
        ┌─────────────────────────────────────────┐
        │  Updates:                                │
        │  - SkillNote.my_level                    │
        │  - SkillNote body: ## Latest assessment  │
        │    notes section appended/updated        │
        │  - _profile/skill-inventory.md table     │
        │    regenerated                           │
        │  - _meta/agent-log.md gets a one-line    │
        │    audit entry                           │
        └──────────────────┬──────────────────────┘
                           ↓
        ┌─────────────────────────────────────────┐
        │  Next pipeline run's score_node sees     │
        │  the new level via RAG retrieval — so    │
        │  JD scoring AUTOMATICALLY reflects your  │
        │  evolving skill graph as you ship work   │
        └─────────────────────────────────────────┘
```

This is the part the spec calls the "differentiated angle" — Compass doesn't
just find jobs, it grades you against the live market and tells you what to
study next, with documented evidence chains from your `learning-vault/`.

---

## 7. The vault layout (what gets written where)

```
compass-vault/
├── jobs/                      ← JobNotes (one per JD)
│   └── YYYY-MM-DD-{company}-{title}-{8charhash}.md
├── companies/                 ← CompanyNotes (one per company; human-editable fields preserved)
│   └── {company}.md
├── skills/                    ← SkillNotes (95 seeded from taxonomy)
│   └── {skill}.md
├── applications/              ← One per submitted application
│   └── YYYY-MM-DD-{company}-{title}-{hash}.md
├── cover-letters/             ← Generated cover letters
│   └── YYYY-MM-DD-{company}-{title}-{hash}.md
├── study-plans/
│   ├── master-gap-plan.md         ← Auto-regenerated; atomic write (os.replace)
│   └── *.archive-pre-pivot-*.md   ← Old plans (preserved on wipe)
├── _profile/                  ← YOU edit these — Compass reads them
│   ├── resume.md
│   ├── skill-inventory.md
│   ├── preferences.md
│   ├── target-companies.md        ← Human-readable narrative
│   ├── target-companies.yaml      ← Machine-readable; drives the scraper
│   ├── target-roles.md
│   ├── role-clarifications.md
│   └── interview-prep.md
├── _meta/                     ← Compass-managed metadata
│   ├── skill-taxonomy.md          ← Canonical skill list + synonyms + categories
│   ├── agent-log.md               ← Append-only audit trail of every vault write
│   ├── pipeline-runs.md           ← Per-run forensic summary row
│   ├── filtered-jobs.md           ← Audit log of every dropped JD with reason
│   ├── unknown-skills-log.md      ← Skills the LLM emitted but taxonomy doesn't know
│   └── *.archive-pre-pivot-*.md
├── dashboard.md               ← Dataview-powered: 5 panels (apply-now / velocity / etc.)
└── jobs.archive-pre-pivot-*/  ← Old JobNotes (preserved on wipe)
```

---

## 8. How a single full pipeline run looks (timeline)

For a manual `uv run python -m compass.pipeline.graph` invocation:

```
0:00.0  start_wall captured
0:00.1  _scrape_all begins — 4 scrapers run concurrently
0:01.5    greenhouse_many returns ~150 JDs from 17 boards
0:02.0    ashby_many returns ~200 JDs from 24 boards
0:03.0    lever_many returns 0 (no lever targets in YAML)
0:05.0    workday_many returns ~80 JDs from 5 banks (slower; 2 fetches per JD)
0:05.5  _filter_and_sort_by_recency drops ~40% as >30 days old → 270 jobs
0:05.6  round-robin interleave + cap to MAX_JOBS_PER_RUN=50 → 50 jobs
0:05.7  _vault_url_set normalizes URLs from existing JobNotes; dedup → 48 fresh
0:05.8  AsyncSqliteSaver checkpoint DB opens; build_graph compiles
0:06.0  asyncio.gather over 48 _process_one calls, bounded by semaphore=5
        Each _process_one:
          intake → intake_filter (reject rules + role_family + agent gate)
            ~50% drop here at zero LLM cost
          extract (Flash) → score (Flash) → reflect (no-op) → hitl
            hitl auto-rejects below SCORE_THRESHOLD=3.5
            hitl interrupts for human approval on score >= threshold
            non-interrupt path: vault_write
          interrupt-path: state_store.add_pending; main loop continues
0:30.0  ~24 jobs reach vault_write (other 24 dropped at intake_filter)
0:30.5  ~6 jobs paused for HiTL (score >= 3.5); thread_ids logged
0:30.6  asyncio.gather completes
0:30.7  gap_aggregator.regenerate() syncs counters, rebuilds backlinks,
        writes master-gap-plan.md (atomic via os.replace)
0:31.0  pipeline-runs.md gets a one-line summary row
0:31.1  process exits
```

For each HiTL-paused job, the user later runs `approve_job(thread_id)` or
the Modal cron `check_and_resume_timeouts` fires after the 4-hour window
and auto-rejects. Resume goes through `claim_pending` to prevent
double-resume races, then continues from the checkpoint past `hitl_node`
into `tailor` (if approved) and `vault_write`.

---

## 9. Cost expectations (approximate, OpenRouter pricing)

| Cost item | Per-unit | Typical batch |
|---|---|---|
| extract (Gemini Flash) | ~$0.0003/JD | $0.015 / 50-JD batch |
| score (Gemini Flash) | ~$0.0005/JD | $0.025 / 50-JD batch |
| tailor (Sonnet) | ~$0.05/JD | $0.30 / 6-approved batch |
| cover_letter (Sonnet, on demand) | ~$0.08/letter | $0.08 / app |
| assess_skills (Sonnet, on demand) | ~$0.02/skill | $0.40 / full re-grade |
| eval --judge (Flash) | ~$0.002/JD | $0.04 / 20-record run |

**A typical day's run** (manual refresh + tailoring 5 approved jobs +
cover-letters for the 3 you apply to + 1 eval run) costs roughly $0.50.
At 7 runs/week that's $3.50/week. Modal compute is free at this scale.

---

## 10. What's NOT in the pipeline (deferred / out of scope)

- **Modal cron deploy** — daily scrape + weekly skill-assessor.
  Not deployed. Manual runs work fine for the 2-month sprint.
- **Cisco-internal manual tracker** — AI Hub / Outshift / Webex AI /
  ThousandEyes AI. Need to come from a manager referral, not the
  ATS scrape.
- **Banks/consulting beyond the 5 Workday tenants** — JPM Oracle Cloud,
  Capital One Workday (non-discoverable site), etc. Use `add_job_from_url`
  per specific role.
- **Auto-apply** — explicit non-goal. Compass is research + preparation.
- **LinkedIn integration** — explicit non-goal (ToS + rate-limit pain).

---

## 11. The honest summary

What Compass does well:
- Scrapes 41 verified ATS boards in one command
- Filters out senior/staff/principal + non-agentic JDs cheaply (no LLM)
- Scores remaining JDs against your profile with reasoning + matched/
  missing skills
- Pauses for human approval on strong-fit jobs; auto-rejects weak-fit
- Tailors a paragraph + cover letter per approved JD
- Regrades your skills against documented evidence as you ship work
- Surfaces gaps with weighted ranking (tier × frequency × match score)
- Surfaces realistic apply-now roles with easy-loop filter for the
  8-week sprint
- Audit-trails every decision in `_meta/`

What it doesn't do (yet):
- Run on a daily cron (Modal undeployed)
- See Oracle Cloud / iCIMS / SmartRecruiters job boards (~30% of the
  apply-now market) without manual paste
- Auto-update applications/ from interview emails
- Suggest specific cover-letter A/B variants
- Track interview prep progress against per-skill study plans

The architecture is intentionally separable. Each scraper is independent;
each pipeline node is testable in isolation; the vault is the
serialization boundary between code and user. If you wanted to swap the
LLM provider tomorrow it's an env-var change. If you wanted to add a new
ATS, it's one scraper file matching the existing interface.
