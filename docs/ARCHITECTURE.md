# Compass Architecture

> Compass: Career Coach — Agentic job search, skill gap analysis, and interview preparation system

---

## What Compass Does

Compass is a personal agentic career coaching system built to:
1. **Discover** relevant job postings from ATS public APIs on a schedule
2. **Score** each posting against a structured candidate profile using LLM analysis
3. **Gap analysis** — identify which required skills the candidate lacks per role
4. **Study plans** — generate prioritized learning roadmaps for skill gaps
5. **Resume tailoring** — suggest specific edits to highlight relevant experience per role
6. **Track** applications, interviews, and outcomes in an Obsidian knowledge vault

It is explicitly NOT an auto-apply system. Every application is a human decision. Compass is a filter and preparation tool.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         COMPASS SYSTEM                          │
│                                                                 │
│  ┌──────────────┐    ┌───────────────────────────────────────┐  │
│  │   SCRAPERS   │    │           LANGGRAPH PIPELINE          │  │
│  │              │    │                                       │  │
│  │  Greenhouse  │───▶│  intake → search → score → reflect   │  │
│  │  Lever       │    │       → HiTL interrupt → tailor      │  │
│  │  Ashby       │    │       → vault write                  │  │
│  │  JobSpy      │    │                                       │  │
│  └──────────────┘    └──────────────┬────────────────────────┘  │
│                                     │                           │
│  ┌──────────────┐    ┌──────────────▼────────────────────────┐  │
│  │  MCP SERVER  │    │           OBSIDIAN VAULT              │  │
│  │              │◀──▶│                                       │  │
│  │  search_jobs │    │  _profile/   jobs/    skills/         │  │
│  │  score_jd    │    │  companies/  apps/    study-plans/    │  │
│  │  get_gaps    │    │  dashboard.md         _meta/          │  │
│  │  study_plan  │    │                                       │  │
│  └──────────────┘    └───────────────────────────────────────┘  │
│         ▲                                                       │
│         │            ┌───────────────────────────────────────┐  │
│  Claude Code /       │           LANGFUSE (self-hosted)      │  │
│  Cursor              │  Traces · Costs · Evals · Datasets    │  │
│                      └───────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Layer 1 — Data Ingestion (Scrapers)

**Purpose:** Fetch job postings from legitimate public sources on a schedule.

**Sources (in priority order):**
1. **Greenhouse public API** — `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs` — unauthenticated, no ToS issues, returns structured JSON
2. **Lever public API** — `GET https://api.lever.co/v0/postings/{company}?mode=json` — same
3. **Ashby public API** — `GET https://api.ashbyhq.com/posting-api/job-board/{board}` — covers many top AI startups (LangChain, PostHog, Linear, Notion)
4. **JobSpy** — aggregator covering LinkedIn, Indeed, Glassdoor, ZipRecruiter. Rate-limited on LinkedIn; use as supplemental not primary.

**Output:** A list of `RawJob` Pydantic objects:
```python
class RawJob(BaseModel):
    company: str
    title: str
    url: str
    source: str  # greenhouse | lever | ashby | jobspy
    location: str | None
    remote: bool | None
    salary_min: int | None
    salary_max: int | None
    description: str
    date_posted: date | None
```

**Scheduling:** Prefect flow or Modal cron, runs daily at 9am. Deduplicates against existing vault notes by URL hash.

---

## Layer 2 — LangGraph Pipeline

**Purpose:** Process raw jobs through a multi-step agentic workflow — from raw text to a structured, scored, vault-ready note.

### State Schema
```python
class CompassState(TypedDict):
    raw_jobs: list[RawJob]           # Input from scrapers
    current_job: RawJob | None       # Job being processed
    extracted_requirements: JobRequirements | None  # Pydantic structured extraction
    score: float | None              # 0.0–5.0 match score
    score_reasoning: str | None      # LLM reasoning
    skill_gaps: list[str] | None     # Skills in JD not in profile
    tailoring_notes: str | None      # Resume suggestions
    human_approved: bool | None      # Set by HiTL interrupt
    vault_written: bool              # Has this been persisted?
    errors: list[str]                # Accumulated errors
```

### Graph Nodes

**`intake_node`**
- Deduplicates against existing vault notes (check URL hash)
- Filters obviously irrelevant postings (wrong seniority, excluded companies)
- Queues valid jobs for processing

**`extract_node`**
- Uses Pydantic AI to extract structured requirements from JD text
- Returns `JobRequirements`: required_skills, nice_to_have_skills, years_experience, seniority, remote_policy
- Langfuse traces this call

**`score_node`** (fan-out — runs in parallel for all queued jobs)
- Compares `JobRequirements` against candidate profile from vault (`_profile/skill-inventory.md`)
- LLM scores match 0.0–5.0 with explicit reasoning
- Returns score + per-skill match breakdown
- Jobs below `SCORE_THRESHOLD` (default 3.5) are logged and dropped — not written to vault

**`reflection_node`** (only for jobs scoring 3.0–4.0)
- Re-examines borderline matches with a second LLM call using a stricter rubric
- Checks if the job was correctly scored or if surface-level keyword mismatch is causing underscore
- Can raise or lower score by up to 1.0 point with justification

**`hitl_node`** (Human-in-the-Loop)
- Uses LangGraph `interrupt()` to pause the graph
- Writes a draft note to vault for human review
- Waits up to `HITL_TIMEOUT_HOURS` (default 4) for human approval
- If no response: resumes with `cancelled` status and logs reason
- If approved: resumes to `tailor_node`

**`tailor_node`** (only for approved jobs)
- Generates specific resume tailoring suggestions: which bullets to emphasize, which skills to mention, what framing fits this role
- Generates a one-paragraph cover note template
- Produces a study plan if skill gaps exist

**`vault_write_node`**
- Writes the complete job note to `jobs/YYYY-MM-DD-Company-Title.md` with full frontmatter
- Updates the relevant `skills/SkillName.md` notes (increments `appears_in_jobs` counter)
- Creates or updates `companies/CompanyName.md`
- Appends to `_meta/agent-log.md`

### Graph Edges
```
START → intake_node
intake_node → extract_node (for each valid job)
extract_node → score_node
score_node → reflection_node (if 3.0 ≤ score < 4.0)
score_node → vault_write_node (if score < 3.0, write as "low-match" and exit)
score_node → hitl_node (if score ≥ 4.0)
reflection_node → hitl_node (if revised score ≥ 3.5)
reflection_node → vault_write_node (if revised score < 3.5)
hitl_node → tailor_node (if approved)
hitl_node → vault_write_node (if rejected or timed out)
tailor_node → vault_write_node
vault_write_node → END
```

---

## Layer 3 — Obsidian Vault

**Purpose:** Durable, human-readable storage for everything. The vault is the source of truth for the candidate's profile, all discovered jobs, and all generated artifacts.

**Path:** `~/Documents/compass-vault/`

**Full schema:**
```
compass-vault/
├── _raw/                    # Staging — drop anything here for agent to process
│   ├── jd-captures/         # Pasted JD text before processing
│   ├── company-research/    # Unstructured notes and links
│   └── interview-notes/     # Raw notes from calls
│
├── _meta/
│   ├── taxonomy.md          # Controlled tag vocabulary — THE LAW
│   ├── agent-log.md         # Running log of all agent actions
│   └── templates/           # Frontmatter templates
│       ├── job.md
│       ├── skill.md
│       ├── company.md
│       └── interview.md
│
├── _profile/                # YOU — agent reads this constantly
│   ├── resume.md            # Clean current resume
│   ├── skill-inventory.md   # Honest skill levels — what gap analysis runs against
│   ├── interview-prep.md    # Deep technical talking points per role
│   ├── role-clarifications.md  # Source of truth for what you actually built
│   ├── target-roles.md      # Role taxonomy, companies, interview formats
│   ├── skills-competency-map.md  # What to learn, why, how
│   ├── target-companies.md  # Company tiers and reasoning
│   └── preferences.md       # Location, remote, comp floor, deal-breakers
│
├── jobs/                    # One note per role — agent-generated
│   └── YYYY-MM-DD-Company-Title.md
│
├── companies/               # One note per company — agent-maintained
│   └── CompanyName.md
│
├── skills/                  # Atomic skill notes
│   └── SkillName.md
│
├── applications/            # Applied roles — human-maintained
│   └── YYYY-MM-DD-Company-Title.md
│
├── interviews/              # Prep + post-mortems — human-maintained
│   └── YYYY-MM-DD-Company.md
│
├── study-plans/             # Agent-generated learning roadmaps
│   └── YYYY-MM-DD-topic.md
│
└── dashboard.md             # Dataview queries — control panel
```

---

## Layer 4 — MCP Server

**Purpose:** Exposes the vault and pipeline as tools so Claude Code and Cursor can drive Compass interactively.

**Run:** `uv run python -m compass.mcp_server.server`

**Tools:**
| Tool | Input | Output | Description |
|---|---|---|---|
| `search_jobs` | `query: str, limit: int` | `list[JobNote]` | Semantic search over vault job notes |
| `get_skill_gaps` | `job_id: str` | `list[SkillGap]` | JD skills vs. skill-inventory.md |
| `score_jd` | `jd_text: str` | `JobScore` | Score raw JD against candidate profile |
| `get_study_plan` | `skills: list[str]` | `StudyPlan` | Learning roadmap for skill list |
| `tailor_resume` | `job_id: str` | `TailoringNote` | Resume suggestions for a specific role |
| `add_application` | `job_id: str` | `None` | Write application note to vault |
| `get_profile` | `section: str` | `str` | Read a section of the candidate profile |

---

## Layer 5 — Observability (Langfuse)

**Purpose:** Full tracing, cost tracking, and eval scoring for every pipeline run.

**Self-hosted setup:**
```bash
git clone https://github.com/langfuse/langfuse
cd langfuse && docker compose up -d
# UI at http://localhost:3000
```

**What gets traced:**
- Every LLM call (model, prompt, completion, tokens, cost, latency)
- Every node in the LangGraph graph
- Every eval run result
- Cost per complete pipeline run

**Eval setup:**
- Dataset: 30-50 labeled (JD, profile) pairs with ground-truth match scores
- LLM-as-judge: Claude scores system output against rubric nightly
- Metrics tracked: precision@threshold, cost per run, tokens per node
- Results logged to Langfuse, charted in dashboard

---

## Layer 6 — Eval Harness

**Purpose:** Measure whether the scoring and extraction pipeline actually works. Run nightly.

**Dataset format** (`compass/evals/dataset.json`):
```json
[
  {
    "id": "eval-001",
    "jd_text": "...",
    "expected_score": 4.2,
    "expected_skills": ["LangGraph", "Pydantic", "RAG"],
    "notes": "Strong match — all required skills present"
  }
]
```

**Metrics:**
- Score MAE (mean absolute error vs. human labels)
- Skill extraction recall (did we find all the skills a human identified?)
- Cost per eval run
- Tokens per node (track for optimization)

---

## Layer 7 — Scheduling (Modal / Prefect)

**Daily job scan** (Modal cron):
```python
@app.function(schedule=modal.Cron("0 9 * * *"))
async def daily_scan():
    jobs = await scrape_all_ats()
    await run_pipeline(jobs)
```

**Weekly digest** (Modal cron):
```python
@app.function(schedule=modal.Cron("0 8 * * 1"))  # Mondays
async def weekly_digest():
    generate_weekly_summary_note()
```

---

## Technology Choices & Rationale

| Choice | Rationale |
|---|---|
| LangGraph | Production standard for stateful agents. Time-travel debugging, HiTL interrupts, native LangSmith/Langfuse integration. Portfolio signal. |
| Pydantic AI | Typed LLM I/O — structured extraction with validation. No silent schema failures. |
| Langfuse (self-hosted) | Full observability without data leaving local machine. Public trace URL for portfolio. Apache-2.0 license. |
| Obsidian vault | Human-readable, git-trackable, queryable with Dataview. Karpathy wiki pattern. Not locked into any app. |
| MCP server | Exposes entire system to Claude Code/Cursor. First-class portfolio artifact — demonstrates MCP server design skills. |
| Modal | Serverless Python, easy cron scheduling, no infrastructure to manage. Demonstrates production deployment. |
| uv | Fast, lockfile-based, consistent with a personal local-first OS project. |
| ATS public APIs | No ToS violations, reliable, structured JSON. Greenhouse/Lever/Ashby cover most quality AI companies. |
| SQLite (if needed) | If vault + JSON isn't sufficient for deduplication state, add SQLite with the same migration pattern as a personal local-first OS project. |

---

## Layer 8 — Skill Assessment Loop (NEW)

The piece that makes Compass an actual career coach instead of a job aggregator.

**Components:**
- `compass/vault/taxonomy.py` — loads `_meta/skill-taxonomy.md` (canonical skills + synonyms + tier demand). Every JD-extracted skill normalizes through this.
- `compass/vault/learning_bridge.py` — resolves `learning-vault://path/to/file.md#anchor` URIs into evidence artifacts (snippet, kind, last_modified).
- `compass/analysis/gap_aggregator.py` — combines all scored jobs into a ranked gap list. Formula: `gap_score = Σ (jobs_requiring × match_score × tier_weight)`. Tier weights from `_profile/preferences.md`. Writes `study-plans/master-gap-plan.md`.
- `compass/analysis/skill_assessor.py` — adversarial-grader Pydantic AI agent. Reads `evidence:` URIs from each `skills/*.md`, applies the rubric in `_meta/skill-taxonomy.md`, regrades `my_level`. Asymmetric promotion (jumping 2+ levels requires HiTL). Respects `grade_override:` for human-locked grades.

**The loop:**
1. Daily scrape + pipeline writes jobs + updates skill `appears_in_jobs` counts.
2. `gap_aggregator.regenerate()` writes top-10 gaps to `study-plans/master-gap-plan.md`.
3. Human reads `master-gap-plan.md`, picks something to learn, writes notes in `learning-vault/`.
4. Human adds the new learning-vault file path to `evidence:` in the relevant `compass-vault/skills/<Skill>.md`.
5. Nightly `assess_skills` cron (or manual MCP call) reads the new evidence, regrades, updates `_profile/skill-inventory.md`.
6. Next pipeline run sees the higher `my_level` → that skill no longer counts toward the gap → study plan reorders.

**Why this matters for the portfolio:**
"I built an agent that grades my own skills against the live JD market and tells me what to study next" is a meta-loop story that pattern-matches what tier-2 agent-eng employers explicitly value. Worth a blog post (flagged in the job-market report as the highest-leverage missing artifact).

---

## What Compass Is NOT

- **Not an auto-apply bot.** Every application is a conscious human decision. The HiTL interrupt enforces this.
- **Not a LinkedIn scraper.** Greenhouse/Lever/Ashby APIs are legitimate. JobSpy/LinkedIn is a fallback with known rate limits and ToS risk — document this clearly.
- **Not a resume fabricator.** Tailoring suggestions highlight true experience. The system cannot add skills you don't have.
- **Not a replacement for preparation.** The study plans and interview prep are inputs to your learning — the actual learning is on you.
