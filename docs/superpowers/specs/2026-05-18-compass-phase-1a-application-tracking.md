# Compass Phase 1.A — Application Tracking + Role-Family Gate (Spec)

> Sub-spec of the master design doc (`2026-05-17-compass-mvp-to-portfolio-ship-design.md`). Read the master spec's Phase 1.A row and the Phase 0 handoff (`docs/PHASE_0_COMPLETE.md`) first — this spec is the contract for what 1.A actually ships.

**Status:** Draft · **Date:** 2026-05-18 · **Author:** Akash + Claude
**Parent spec:** `docs/superpowers/specs/2026-05-17-compass-mvp-to-portfolio-ship-design.md`
**Previous phase:** `phase-0b-pipeline-mvp` (tag) — 81 tests passing, lint clean.

---

## 1. Why this phase exists

Phase 0.B made Compass produce correct data on real ATS scrapes, but it left two interlocking problems that block daily use:

1. **The vault is biased toward easy wins.** The `SCORE_THRESHOLD ≥ 3.5` gate added in bug-fix #17 keeps sales/PM/designer noise out of the vault — but it also hides agentic-engineering roles Akash currently scores 2.0–3.4 on, which are precisely the *stretch roles whose gaps inform what to study next*. The master gap plan today is therefore a "what I'm already good at" reflection, not a "what the market wants me to learn" mirror.
2. **There is no application workflow.** Compass scores jobs and writes them to the vault. There is no way to mark "I applied," no status transitions, no next-action reminders, no dashboard view of "what should I do today." Akash cannot use it as a daily tool without leaving the vault to track applications elsewhere.

Phase 1.A fixes both. The result is the first version of Compass that Akash genuinely opens every morning.

---

## 2. Definition of done

A run of `uv run python -m compass.pipeline.graph` against the configured ATS boards produces a vault where:

- **Every JobNote is in-scope** for Akash's target role family (engineering work touching agentic AI / production AI systems). Sales / PM / design / CS / marketing / recruiting JDs never reach `extract_node`. False-positive rate ≤ 1 per 50 JDs after manual inspection.
- **Every in-scope JobNote is written**, regardless of `match_score`. The master gap plan reflects skills demanded by stretch roles (score 2.0+), not only roles Akash already matches.
- **Each JobNote has a non-empty `role_family`** frontmatter field (e.g. `agent-engineer`, `applied-ai`, `swe-backend`, `fde-eng`, `infra-llm`). The Dataview dashboard groups by it.
- **Each JobNote has the company's `tier`** copied from `_profile/target-companies.md` (no more `tier: unknown` on every Sierra / Decagon / Ramp note).
- **Greenhouse + Lever JobNotes have a populated `remote` field** parsed from the JD's `location` string.

And the human-facing side:

- **`add_application(job_id)` MCP tool** creates an `ApplicationNote` at `applications/YYYY-MM-DD-Company-Title.md`, sets the linked JobNote's `status` to `applied`, and stamps `applied_at`.
- **`update_application_status(app_id, status, next_action=, next_action_date=)` MCP tool** transitions an application through `applied → screen → onsite → offer/rejected/withdrawn` and writes the agent-log row.
- **`list_pending_actions()` MCP tool** returns all `ApplicationNote`s whose `next_action_date <= today`.
- **The dashboard at `compass-vault/dashboard.md`** has working Dataview queries for: "Apply now (top 5)", "In-flight applications by stage", "Today's next actions", "Top gaps this week (master plan)", and "Stretch roles I'm not ready for yet" (in-scope JDs with score < 3.5).

Tests pass (`uv run pytest -q`), ruff is clean, the post-implementation **adversarial verification step** (manually inspect 10 random JobNotes + create 3 real applications + edit a CompanyNote in Obsidian) passes.

---

## 3. Scope

### In scope

1. **Role-family gate** — new `intake_filter_node` between `intake` and `extract`. Cheap-first classifier:
   - Title-keyword pre-filter using the IN/OUT lists from `PHASE_0_COMPLETE.md:241-272` handles the obvious 70%+ of JDs at zero LLM cost.
   - Borderline JDs hit a Gemini-Flash classifier (one tool call, ~$0.0005) with a *biased-toward-inclusion* prompt: reject only on explicit evidence (title in OUT list OR JD body shows zero engineering work). Classifier returns `(in_scope: bool, role_family: str, reason: str)`.
   - Out-of-scope JDs short-circuit the graph (skip extract/score/tailor/vault_write) and are logged once to `_meta/filtered-jobs.md` (one append per JD with title + reason) for weekly review.
   - In-scope JDs continue with `role_family` set on state and threaded through to JobNote frontmatter.

2. **Remove `SCORE_THRESHOLD` gate from `vault_write_node`** — keep the threshold's use in `hitl_node` (tailor still only runs on score ≥ threshold to control Sonnet cost). The gap aggregator then aggregates over all in-scope JDs.

3. **`role_family` on JobNote** — already defined on the schema as `role_family: str = ""`. Populate it from `intake_filter_node` via state.

4. **Company tier lookup** — new `compass/vault/target_companies.py` parses `_profile/target-companies.md`'s "Tier `apply-now`" / "Tier `6-month`" / "Tier `stretch`" sections into a `{normalized_company_name: Tier}` map. Cached at module load with manual `refresh()` (no `lru_cache`). `vault_write_node` looks up `job.company` and passes the resolved tier to `write_company_note`. JobNote inherits the tier the company is currently at.

5. **`add_application` / `update_application_status` / `list_pending_actions` MCP tools** — new `compass/applications/lifecycle.py` module:
   - `add_application(job_id: str, resume_variant: str = "resume.md", referral: bool = False) -> ApplicationNote` — finds the JobNote by filename substring or URL, creates the ApplicationNote (already on the schema at `compass/vault/schemas.py:105`), updates the JobNote's `status = "applied"` + `applied_at = now()`, appends to agent-log.
   - `update_application_status(app_id, status, next_action="", next_action_date=None) -> ApplicationNote` — validates the status transition (refuses going backward unless `force=True`), writes back, appends to agent-log. Also updates the linked JobNote's `status` so the dashboard reflects current state.
   - `list_pending_actions(through_date: date | None = None) -> list[dict]` — globs `applications/*.md`, returns ones where `next_action_date <= through_date` (default today). Sorted ascending by `next_action_date`.
   - All three exposed as MCP tools in `compass/mcp_server/server.py` (today the file has a TODO comment at line 214 noting these ship in 1.A).

6. **`ApplicationNote` writer** — new `write_application_note(note: ApplicationNote) -> Path` in `compass/vault/writer.py`. Filename: `applications/YYYY-MM-DD-Company-Title-<8-char-job_ref-hash>.md`. The hash suffix prevents same-day collisions when Akash applies to two different postings at one company on the same day (different teams / URLs). Idempotency key: `(company, title, applied_date, job_ref)`. Re-running `add_application` on the same JobNote updates the existing file rather than duplicating.

7. **Greenhouse + Lever `remote` field parsing** — new `compass/scrapers/_remote_parser.py` with one function `infer_remote_policy(location: str | None) -> bool | None` matching common substrings (`remote`, `wfh`, `anywhere`, `usa-remote`, `remote-us`, `hybrid`, etc.). Both scrapers call it before constructing `RawJob`. Returns `None` for ambiguous strings (so we don't lie). Ashby already populates `remote` directly (fixed in bug #20) — no change there.

8. **Dashboard polish** — rewrite `compass-vault/dashboard.md` with the five required Dataview queries (top 5 apply-now, in-flight by stage, today's actions, top gaps, stretch roles). Verified manually in Obsidian.

### Out of scope (deferred to later phases — see master spec)

- Real `interrupt()` + `AsyncSqliteSaver` checkpointing for HiTL → **Phase 1.B**
- Modal cron for daily scrape + weekly assessor → **Phase 1.B**
- Chroma RAG retrieval for profile chunks → **Phase 1.B**
- Langfuse callback API fix (handler kwargs mismatch) → **Phase 1.B**
- Taxonomy expansion (PostgreSQL, Redis, Kafka, Salesforce, etc.) → **Phase 1.B**
- 30-JD labeled eval set → **Phase 2.A**
- Public Langfuse trace URL in README → **Phase 2.B**

### Explicitly NOT changing in 1.A

- The 7-node LangGraph topology stays the same except for inserting `intake_filter` between `intake` and `extract`.
- `extract_node`, `score_node`, `tailor_node` logic — unchanged.
- Vault frontmatter schemas — `JobNote.role_family` already exists; `ApplicationNote` already exists. No schema migration.
- The skill_assessor pipeline / gap_aggregator math.

---

## 4. Architecture

### 4.1 Graph topology change

```
Before (Phase 0.B):
    START → intake → extract → score → reflect → hitl
                                                   ├─(approved)→ tailor → vault_write → END
                                                   └─(rejected)─────────→ vault_write → END

After (Phase 1.A):
    START → intake → intake_filter
                          ├─(in_scope=False)──────────────────────────→ END   (logged to _meta/filtered-jobs.md)
                          └─(in_scope=True) → extract → score → reflect → hitl
                                                                            ├─(approved)→ tailor → vault_write → END
                                                                            └─(rejected)─────────→ vault_write → END
```

The new edge after `intake_filter` is a conditional that routes to `END` for out-of-scope JDs. `vault_write_node` is NOT called for out-of-scope JDs because there's no value in vaulting Sales Director postings; the filtered-jobs log preserves auditability.

### 4.2 Role-family classifier (three-stage)

Three stages, cheapest first:
- **Stage 1** — title keyword pre-filter (zero LLM cost): returns `(True, family)` / `(False, "out-of-scope")` / `(None, "")` for borderline.
- **Stage 1.5** — body-signal family upgrader (zero LLM cost): when stage 1 returns IN with a *generic* family (`swe-backend`, `swe-frontend`, `swe-fullstack`, `swe-founding`, `other-eng`), scan the JD body for agentic / LLM / ML keyword density. If signal crosses a threshold, **promote** the family (e.g. `swe-backend` → `agent-engineer`). Promote-only — never demotes and never changes `in_scope`. Generic engineering roles with no AI signal keep their original family and still reach the vault.
- **Stage 2** — Gemini-Flash structured-output classifier (~$0.0005 / call): runs only when stage 1 returned `None`. Inclusion-biased prompt: reject only on explicit evidence (title in OUT list OR body shows zero engineering work). After the LLM returns IN, stage 1.5 runs again on the LLM's family for the same upgrade chance.

**Stage 1 — Title keyword pre-filter (zero LLM cost):**

```python
# compass/pipeline/role_family.py
IN_TITLE_KEYWORDS = {
    "agent-engineer":   ["agent engineer", "agentic engineer", "agent platform", "agent orchestration", "agent reliability"],
    "applied-ai":       ["applied ai", "applied ml", "machine learning engineer", "ml engineer", "ai engineer"],
    "swe-backend":      ["backend engineer", "software engineer, backend", "platform engineer", "infrastructure engineer"],
    "swe-frontend":     ["frontend engineer", "software engineer, frontend"],
    "swe-fullstack":    ["fullstack engineer", "full-stack engineer", "full stack engineer", "product engineer"],
    "swe-mobile":       ["mobile engineer", "ios engineer", "android engineer"],
    "swe-founding":     ["founding engineer", "first engineer", "founding software engineer"],
    "infra-llm":        ["llm platform", "ai infrastructure", "inference", "eval engineer", "evaluation engineer"],
    "fde-eng":          ["forward deployed", "deployed engineer", "ai solutions engineer"],
    "research-eng":     ["research engineer", "applied research engineer"],
    "devtools-ai":      ["developer experience", "devtools", "developer tools engineer"],
}

OUT_TITLE_KEYWORDS = [
    # sales
    "account executive", "sales development", "sales representative", "sdr", "bdr",
    "account manager", "enterprise sales", "sales engineer",
    # pre-sales / solutions
    "solutions architect", "solution architect", "presales", "pre-sales",
    # CS
    "customer success", "customer experience", "customer support", "csm",
    # PM
    "product manager", "product management", "group pm", " pm,", "agent pm",
    # design
    "designer", "ux ", " ux,", "brand", "motion graphics", "web designer",
    "conversation designer", "conversational designer",
    # marketing
    "marketing", "content marketing", "growth marketer", "demand gen", "lifecycle marketing",
    # ops / HR / finance / legal
    "recruiter", "people operations", "talent acquisition", "human resources",
    "accountant", "finance", "controller", "operations manager", "compliance",
    "legal counsel", "trust and safety", "trust & safety",
]

def keyword_classify(title: str) -> tuple[bool | None, str]:
    """Return (in_scope_or_None, role_family). None means 'borderline — escalate'."""
```

Returns `(True, family)` if title matches any IN keyword AND no OUT keyword, `(False, "out-of-scope")` if any OUT keyword matches, `(None, "")` otherwise.

**Stage 1.5 — Body-signal family upgrader (zero LLM cost):**

When stage 1 returns IN with a generic family, scan the JD body for agentic / LLM / ML keyword sets. Promote on threshold crossing. Single-mention false-positives ("we work alongside AI") are filtered by requiring multiple distinct keywords.

```python
AGENT_SIGNAL = ["agent", "agentic", "tool use", "tool-use", "langgraph", "autogen",
                "mcp ", "model context protocol", "react pattern", "agentic ai",
                "function calling", "tool calling"]
LLM_SIGNAL   = ["llm", "large language model", "gpt-", "claude", "gemini",
                "rag ", "retrieval-augmented", "embedding", "vector database",
                "fine-tuning", "prompt engineering", "pydantic-ai", "openai api",
                "anthropic api"]
ML_SIGNAL    = ["machine learning", "deep learning", "neural network", "pytorch",
                "tensorflow", "sklearn", "scikit-learn", "huggingface"]

GENERIC_FAMILIES = {"swe-backend", "swe-frontend", "swe-fullstack",
                    "swe-founding", "swe-mobile", "other-eng"}

def upgrade_family(family: str, body: str) -> str:
    if family not in GENERIC_FAMILIES:
        return family
    b = body.lower()
    agent_hits = sum(1 for k in AGENT_SIGNAL if k in b)
    llm_hits   = sum(1 for k in LLM_SIGNAL   if k in b)
    ml_hits    = sum(1 for k in ML_SIGNAL    if k in b)
    if agent_hits >= 2:
        return "agent-engineer"
    if llm_hits >= 3:
        return "applied-ai"
    if ml_hits >= 2:
        return "applied-ai"
    return family
```

A `swe-backend` posting at a non-AI fintech with zero AI keywords stays `swe-backend`, still in_scope, still scored, still vaulted. Only mis-labeled generic titles (e.g. `"Software Engineer, Platform"` at Sierra) get pulled into the correct agentic family for dashboard grouping.

**Stage 2 — Gemini-Flash classifier (borderline only):**

Pydantic AI agent with structured output:

```python
class RoleFamilyClassification(BaseModel):
    in_scope: bool
    role_family: str   # one of the IN_TITLE_KEYWORDS keys, or "other-eng" / "out-of-scope"
    reason: str        # one sentence, <140 chars
```

Prompt template injects the IN-SCOPE / OUT list from the spec, the JD title, and first 500 chars of the JD. **Inclusion-biased rule** in the prompt: "If the JD title is borderline AND the body contains any engineering work (writing code, building systems, ML/AI implementation), classify IN_SCOPE. Reject only when the body shows zero engineering work." Cost: ~$0.0005/JD. Runs only on titles that fail stage 1.

### 4.3 Company-tier lookup

`compass/vault/target_companies.py` exposes:

```python
def get_tier(company: str) -> Tier:
    """Return the tier for a company from target-companies.md, or 'unknown' if not listed."""

def refresh() -> None:
    """Re-parse target-companies.md. Call from MCP server / tests if you edit the file mid-process."""
```

Parsing is naive on purpose: walk the markdown headings, look for `Tier \`apply-now\`` / `Tier \`6-month\`` / `Tier \`stretch\``, then read company names from the first column of any `| Company |` table that follows. Company-name normalization: lowercase, strip non-alphanumerics. `Sierra` ↔ `sierra`; `Glean` ↔ `glean`. Single match wins; if a company appears in multiple tiers (it shouldn't), highest tier wins (`apply-now > 6-month > stretch > skip > unknown`).

`vault_write_node` calls `get_tier(job.company)` and uses the result as follows:

- **JobNote.tier** is always set to the resolved tier (a JobNote is a per-posting snapshot; if you edit `target-companies.md` later, only future JobNotes pick up the new tier — old ones keep their snapshot value, which is correct).
- **CompanyNote.tier** is set only when the CompanyNote does not already exist with a non-default tier. The existing writer logic at `compass/vault/writer.py:130-132` only preserves human edits when the *incoming* tier is `"unknown"`, but with Phase 1.A the incoming tier is rarely `unknown` — it's whatever target-companies says. That would silently clobber a human edit in Obsidian (Phase 0 bug #15 resurfacing under a new code path). **Fix:** `vault_write_node` reads the existing CompanyNote (if any) FIRST. If it has a non-default tier set by a human, do not pass a competing tier on write. If it doesn't exist or has `tier=unknown`, pass the resolved tier so creation / first-write gets the correct value.

This means: target-companies.md is the source of truth on first encounter; CompanyNote edits in Obsidian override target-companies thereafter. Akash can edit either side without one stomping the other.

### 4.4 Application lifecycle

```python
# compass/applications/lifecycle.py
VALID_TRANSITIONS = {
    "applied":    {"screen", "rejected", "withdrawn", "ghosted"},
    "screen":     {"onsite", "rejected", "withdrawn", "ghosted"},
    "onsite":     {"offer", "rejected", "withdrawn", "ghosted"},
    "offer":      {"accepted", "declined", "withdrawn"},
    "rejected":   set(),  # terminal
    "withdrawn":  set(),
    "ghosted":    {"rejected"},  # ghosting → eventual rejection
    "accepted":   set(),
    "declined":   set(),
}

def add_application(job_id: str, resume_variant: str = "resume.md", referral: bool = False, vault_path: Path = VAULT_PATH) -> ApplicationNote
def update_application_status(app_id: str, status: str, next_action: str = "", next_action_date: date | None = None, force: bool = False, vault_path: Path = VAULT_PATH) -> ApplicationNote
def list_pending_actions(through_date: date | None = None, vault_path: Path = VAULT_PATH) -> list[dict]
```

`job_id` is matched against `applications/*.md` filenames substring-style AND against the JobNote frontmatter `url` (so MCP callers can pass either form). Ambiguous matches raise.

### 4.4.1 Module-level `VAULT_PATH` discipline (carryover for new modules)

Every new module that needs `VAULT_PATH` (intake_filter, target_companies, lifecycle, application writer) **must** reference it via `compass.config.VAULT_PATH` inside the function body, NOT capture it as a module-level constant. The existing `temp_vault` pytest fixture monkeypatches `compass.config.VAULT_PATH`, which only takes effect for code that re-reads the attribute on each call. Module-level constants like `FOO = VAULT_PATH / "..."` freeze the path at import time and silently break the fixture — tests would write to the user's real `~/Documents/compass-vault/`. The Phase 0.B nodes (see `compass/pipeline/nodes/vault_write.py`) already follow this pattern.

### 4.5 Filtered-jobs log

`_meta/filtered-jobs.md` — append-only markdown. One entry per filtered JD:

```markdown
- [2026-05-19 09:14:23] sierra "Account Executive, Enterprise" — title contains "account executive"
- [2026-05-19 09:14:25] anthropic "Product Manager, Claude.ai" — title contains "product manager"
```

Purpose: when Akash thinks the gate dropped a role it shouldn't have, he greps this file. False-negative debugging requires this log to exist.

---

## 5. Verification (the lesson-learned step from Phase 0)

**Tests alone don't catch data-correctness bugs in this pipeline.** Phase 1.A is not "done" until the following adversarial pass is performed on real outputs:

1. Run the pipeline against the full apply-now board set:
   ```
   uv run python -m compass.pipeline.graph
   ```
2. Manually inspect 10 random JobNotes — every one should be a role Akash would conceivably want. Any false negative (an agentic-eng role that was dropped) is logged as a bug and the classifier prompt is tightened.
3. Spot-check 10 entries in `_meta/filtered-jobs.md` — every dropped JD should be obviously out of scope.
4. Create 3 real applications via `add_application` MCP tool, transition them through `applied → screen → onsite` via `update_application_status`. Verify the linked JobNotes' status updates in Obsidian.
5. Edit a CompanyNote's `tier` in Obsidian (e.g. force `cresta` to `apply-now`), re-run the pipeline, verify the edit is preserved AND that new JobNotes for that company inherit the edited tier.
6. Open `dashboard.md` in Obsidian — every Dataview query renders ≥ 1 row from real data; no `(empty)` panels.

Only after all 6 pass do we cut the `phase-1a-application-tracking` tag.

---

## 6. Risk register

| Risk | Mitigation |
|---|---|
| Classifier false-negatives (drops a role Akash wanted) | Inclusion-biased prompt; `_meta/filtered-jobs.md` review queue; manual inspection step in verification |
| Classifier cost balloons (Gemini Flash on every JD) | Stage-1 keyword filter catches ~70%; only borderline titles hit LLM; estimated < $0.05 per daily run |
| `target-companies.md` parser breaks on Akash editing the file freeform | Parser is defensive (silently skips malformed tables); `_profile/target-companies.md` is human-edited but follows a stable section structure — parser tests include a fixture with deliberately-malformed rows |
| ApplicationNote idempotency collides on re-applying to a different posting at the same company | Filename includes `applied_date`; if same `(company, title, applied_date)` re-runs, update in place; different dates create different files |
| Removing the `SCORE_THRESHOLD` write gate floods the vault with low-score in-scope roles | Acceptable — that's the point. The gap aggregator weights by `score_factor` so 0.0-score roles still contribute 0 to gap math; non-zero scores contribute proportionally. Dashboard groups by tier + role_family so the human can scan quickly. |
| Lever / Greenhouse `remote` parser over-matches (e.g. "remote AL" → True when it means Alabama) | Substring rules are conservative ("remote-us", "remote, us", "anywhere"); ambiguous returns `None`. Test fixture covers known confusables. |
| Status transition rules block a legitimate edit | `force=True` parameter bypasses validation; agent-log captures forced transitions |

---

## 7. File-surface estimate

- **New code:** ~6 files, ~400 LoC (`role_family.py`, `target_companies.py`, `applications/lifecycle.py`, `applications/__init__.py`, `intake_filter.py`, `_remote_parser.py`)
- **New tests:** ~5 files, ~350 LoC
- **Modified:** `graph.py`, `vault_write.py`, `writer.py`, `mcp_server/server.py`, both scrapers, `dashboard.md`

Roughly half the size of Phase 0.B. One implementation session is realistic.

---

## 8. Open questions (answered before plan)

| Question | Decision |
|---|---|
| Where should `role_family` classification live — in `intake_node` or a new node? | **New node** (`intake_filter_node`). Keeps `intake_node` as the pure sanity gate; new node owns the cost of the LLM call and the routing decision. Easier to test in isolation. |
| Should out-of-scope JDs still be written to the vault (with `status: out-of-scope`)? | **No.** Vault is for in-scope roles only. Filtered-jobs log preserves auditability. Vault clutter is what Phase 1.A is trying to *remove*. |
| Should the tier lookup happen in `intake_filter` or `vault_write`? | **`vault_write`.** Tier doesn't affect scoring (the tier weights live in `gap_aggregator`, not `score_node`). Cleaner to keep tier as a write-time decoration. |
| Do we add `pending_approvals` MCP tool now? | **No.** That tool wraps LangGraph `interrupt()` which doesn't ship until 1.B. Adding a stub in 1.A would lie about what works. |
| Should `add_application` accept a free-text JD paste (not just a vault job_id)? | **No, defer.** Adds a "create JobNote on the fly" code path that's another surface for bugs. If Akash wants to apply to a JD that wasn't scraped, he runs `score_jd` first, copies the result into a JobNote manually, then `add_application` on it. Revisit if friction is high. |

---

**This spec is the contract.** Implementation plan at `docs/superpowers/plans/2026-05-18-compass-phase-1a-application-tracking.md` decomposes it into bite-sized TDD tasks.
