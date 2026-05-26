# Compass Phase 1.A — Application Tracking + Role-Family Gate (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire a role-family classifier into the pipeline so only in-scope engineering JDs reach the vault; remove the over-aggressive `SCORE_THRESHOLD` write gate so stretch-role gaps drive the master plan; populate `role_family` + company `tier` on every JobNote; ship `add_application` / `update_application_status` / `list_pending_actions` MCP tools backed by a real ApplicationNote lifecycle; rebuild the dashboard to render daily-actionable Dataview queries. End state: `uv run python -m compass.pipeline.graph` against the configured boards produces a vault that the candidate opens every morning to decide what to apply to and what to study.

**Architecture:** New `intake_filter_node` between `intake` and `extract` with a three-stage classifier: (1) title-keyword pre-filter, (2) zero-LLM body-signal *family upgrader* that promotes generic engineering titles to agentic families when the JD body shows enough AI/agent keywords, (3) Gemini-Flash structured-output classifier for borderline titles. Out-of-scope JDs short-circuit to `END`; in-scope JDs carry their (possibly upgraded) `role_family` through to `vault_write_node`. New `compass/vault/target_companies.py` parses `_profile/target-companies.md` and supplies tier on write — with a read-before-write check that preserves human-edited CompanyNote tiers. New `compass/applications/lifecycle.py` exposes the three application-lifecycle functions, surfaced as MCP tools. Both Greenhouse and Lever scrapers gain a `_remote_parser.py` helper. Dashboard rewritten with five Dataview blocks. All changes TDD with fixtures-only unit tests; one final live-LLM smoke at the end.

**Module-level discipline (applies to every new module):** any module that touches `VAULT_PATH` must reference it via `compass.config.VAULT_PATH` *inside the function body*, never as a module-level captured constant. The `temp_vault` pytest fixture monkeypatches `compass.config.VAULT_PATH`, which only affects code that re-reads the attribute each call. Module-level constants like `FOO = VAULT_PATH / "..."` freeze the value at import time and silently break the fixture, causing tests to write to the user's real vault.

**Tech Stack:** Python 3.12 · pydantic-ai 1.97 (Gemini Flash via OpenRouter) · LangGraph (single-node-at-a-time per invocation) · pytest + pytest-asyncio (no network in unit tests).

**Authoritative spec:** `docs/superpowers/specs/2026-05-18-compass-phase-1a-application-tracking.md`
**Parent spec:** `docs/superpowers/specs/2026-05-17-compass-mvp-to-portfolio-ship-design.md`
**Previous-phase handoff:** `docs/PHASE_0_COMPLETE.md`

**Carries these Phase 0.B deferred edges forward:**

1. `vault_write_node`'s `SCORE_THRESHOLD` short-circuit (lines 50–66) is removed in Task 5. `hitl_node`'s use of the same threshold is preserved so tailor (Sonnet, ~$0.05/call) only fires on score ≥ threshold.
2. The TODO at `compass/pipeline/nodes/vault_write.py:96` ("read company tier from target-companies.md instead of unknown") is closed in Task 4.
3. The TODO at `compass/mcp_server/server.py:214` (tailor_resume + add_application ship in 1.A) is closed in Task 9.
4. The deferred "Greenhouse / Lever scrapers don't populate `remote` field" item from `PHASE_0_COMPLETE.md` is closed in Task 8.

**Does NOT touch in this phase:** the 7-node skill_assessor / gap_aggregator logic, the LLM model resolver, the taxonomy normalizer, the extract/score/tailor node bodies, the Pydantic schemas (`role_family` and `ApplicationNote` already exist).

---

## File Structure

### New
- `compass/pipeline/role_family.py` — keyword pre-filter + Gemini classifier wrapper
- `compass/pipeline/nodes/intake_filter.py` — graph node calling role_family
- `compass/vault/target_companies.py` — parse `_profile/target-companies.md`
- `compass/scrapers/_remote_parser.py` — shared remote-policy substring parser
- `compass/applications/__init__.py`
- `compass/applications/lifecycle.py` — add_application / update_application_status / list_pending_actions

### Test scaffolding (new)
- `tests/pipeline/test_role_family.py`
- `tests/pipeline/test_intake_filter.py`
- `tests/vault/test_target_companies.py`
- `tests/scrapers/test_remote_parser.py`
- `tests/applications/__init__.py`
- `tests/applications/test_lifecycle.py`

### Modify
- `compass/pipeline/state.py` — add `role_family: str | None` and `in_scope: bool | None` to `CompassState`
- `compass/pipeline/graph.py` — insert `intake_filter` node + conditional edge to END
- `compass/pipeline/nodes/vault_write.py` — drop SCORE_THRESHOLD gate, read tier via target_companies, set role_family
- `compass/vault/writer.py` — add `write_application_note`; tier-merge logic stays in `write_company_note` (already correct)
- `compass/scrapers/greenhouse.py` — call `infer_remote_policy(location)`
- `compass/scrapers/lever.py` — call `infer_remote_policy(location)`
- `compass/mcp_server/server.py` — wire `add_application`, `update_application_status`, `list_pending_actions`, plus the existing-but-stubbed `tailor_resume`
- `compass-vault/dashboard.md` — rewrite with five Dataview queries
- `compass-vault/_meta/` — `filtered-jobs.md` (auto-created by intake_filter on first append)

### Untouched
- `compass/pipeline/nodes/{extract,score,reflect,hitl,tailor}.py`
- `compass/vault/schemas.py` (both `role_family: str = ""` on JobNote and `ApplicationNote` already present)
- `compass/analysis/*`
- `compass/llm.py`

### Decomposition rationale
The classifier is split across `role_family.py` (pure logic — keyword classify + LLM classify) and `intake_filter.py` (the graph node) so the LLM-call surface is monkey-patchable in tests and the keyword classify is testable with zero infrastructure. The application lifecycle lives under `compass/applications/` to keep MCP-server-facing CRUD out of `compass/vault/` (which is the durable I/O layer). `_remote_parser.py` is shared between two scrapers and has no dependencies — easy to test in isolation.

---

## Task 0: Pre-flight

**Files:** none

- [ ] **Step 1: Verify clean tree on phase-0b-pipeline-mvp tag**

```bash
cd ~/Documents/compass
git status   # expected: clean
git describe --tags --abbrev=0   # expected: phase-0b-pipeline-mvp
```

If working tree is dirty, STOP and ask the user before proceeding.

- [ ] **Step 2: Verify `.env` has `OPENROUTER_API_KEY` and `VAULT_PATH`**

```bash
test -f .env && grep -q '^OPENROUTER_API_KEY=sk-or-' .env && grep -q '^VAULT_PATH=' .env && echo "OK" || echo "MISSING"
```

Expected: `OK`. The final smoke step (Task 11) hits a live LLM and reads the user's real vault.

- [ ] **Step 3: Verify existing tests pass**

```bash
uv run pytest -q
```

Expected: 81 passed (the Phase 0.B baseline).

- [ ] **Step 4: Verify ruff is clean**

```bash
uv run ruff check compass tests && uv run ruff format --check compass tests
```

Expected: 0 errors.

- [ ] **Step 5: Confirm the in-scope / out-of-scope vocabulary**

Re-read `docs/PHASE_0_COMPLETE.md:241-272` (the "Role-family scope definition" the candidate signed off on 2026-05-18). The IN/OUT keyword lists in Task 1 must match that scope exactly. If anything is ambiguous, surface to the user BEFORE writing code.

---

## Task 1: Role-family keyword classifier (zero-LLM stage)

**Files:**
- Create: `compass/pipeline/role_family.py`
- Test: `tests/pipeline/test_role_family.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/pipeline/test_role_family.py
import pytest
from compass.pipeline.role_family import keyword_classify

class TestKeywordClassify:
    def test_obvious_in_scope_agent_engineer(self):
        in_scope, family = keyword_classify("Agent Engineer, APX")
        assert in_scope is True
        assert family == "agent-engineer"

    def test_obvious_in_scope_applied_ai(self):
        in_scope, family = keyword_classify("Applied AI Engineer")
        assert in_scope is True
        assert family == "applied-ai"

    def test_obvious_in_scope_backend(self):
        in_scope, family = keyword_classify("Software Engineer, Backend")
        assert in_scope is True
        assert family == "swe-backend"

    def test_obvious_in_scope_founding(self):
        in_scope, family = keyword_classify("Founding Engineer")
        assert in_scope is True
        assert family == "swe-founding"

    def test_obvious_out_scope_sales(self):
        assert keyword_classify("Account Executive, Enterprise") == (False, "out-of-scope")

    def test_obvious_out_scope_pm(self):
        assert keyword_classify("Product Manager, Agent Platform") == (False, "out-of-scope")

    def test_obvious_out_scope_designer(self):
        assert keyword_classify("Conversational Designer") == (False, "out-of-scope")

    def test_obvious_out_scope_recruiter(self):
        assert keyword_classify("Senior Technical Recruiter") == (False, "out-of-scope")

    def test_borderline_solutions_architect_is_none(self):
        # Could be pre-sales OR could be a real eng role. Defer to LLM.
        assert keyword_classify("Solutions Architect")[0] is None

    def test_borderline_fde_is_none(self):
        # FDE is borderline per spec; let LLM check JD body.
        assert keyword_classify("Forward Deployed Engineer")[0] is None

    def test_borderline_random_title(self):
        # No keyword either way — escalate.
        assert keyword_classify("Member of Technical Staff")[0] is None

    def test_out_keyword_beats_in_keyword(self):
        # "Sales Engineer" should be OUT, not IN (engineer keyword present).
        in_scope, family = keyword_classify("Sales Engineer")
        assert in_scope is False
        assert family == "out-of-scope"

    def test_case_insensitive(self):
        assert keyword_classify("ACCOUNT EXECUTIVE")[0] is False
        assert keyword_classify("agent engineer")[0] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/pipeline/test_role_family.py -v
```

Expected: ImportError / ModuleNotFoundError on `compass.pipeline.role_family`.

- [ ] **Step 3: Implement `keyword_classify`**

```python
# compass/pipeline/role_family.py
"""Role-family classifier — two stages.

Stage 1 (this file, top): pure-string title keyword filter. Zero LLM cost.
Returns (True, family) | (False, "out-of-scope") | (None, "") where None means
"borderline; ask the LLM".

Stage 2 (this file, bottom): a Gemini-Flash structured-output classifier called
only when stage 1 returns None. Inclusion-biased prompt per the spec.

The scope definition is the candidate's, dated 2026-05-18, in PHASE_0_COMPLETE.md.
"""
from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Title → family. ORDER MATTERS: first match wins. Put more specific phrases first.
IN_TITLE_KEYWORDS: dict[str, list[str]] = {
    "agent-engineer":   ["agent engineer", "agentic engineer", "agent platform", "agent orchestration", "agent reliability"],
    "applied-ai":       ["applied ai", "applied ml", "ai engineer", "ml engineer", "machine learning engineer"],
    "infra-llm":        ["llm platform", "ai infrastructure", "inference engineer", "eval engineer", "evaluation engineer"],
    "fde-eng":          ["forward deployed engineer", "deployed engineer", "ai solutions engineer"],
    "research-eng":     ["research engineer", "applied research engineer"],
    "devtools-ai":      ["developer experience engineer", "devtools engineer", "developer tools engineer"],
    "swe-founding":     ["founding engineer", "founding software engineer", "first engineer"],
    "swe-backend":      ["backend engineer", "software engineer, backend", "platform engineer", "infrastructure engineer"],
    "swe-frontend":     ["frontend engineer", "software engineer, frontend"],
    "swe-fullstack":    ["fullstack engineer", "full-stack engineer", "full stack engineer", "product engineer"],
    "swe-mobile":       ["mobile engineer", "ios engineer", "android engineer"],
}

# Order doesn't matter; any match = OUT.
OUT_TITLE_KEYWORDS: list[str] = [
    # sales
    "account executive", "sales development", "sales representative",
    "account manager", "enterprise sales", "sales engineer", "sdr ", " sdr,", "bdr ", " bdr,",
    # pre-sales / solutions (keyword-only; LLM rescues real-eng SA roles)
    "presales", "pre-sales",
    # CS
    "customer success", "customer experience", "customer support", "csm ", " csm,",
    "technical csm",
    # PM
    "product manager", "product management", "group pm", "agent pm",
    # design
    "designer", "ux ", " ux ", "brand ", "motion graphics", "web designer",
    "conversation designer", "conversational designer",
    # marketing
    "marketing", "growth marketer", "demand gen", "lifecycle marketing",
    # devrel / evangelism (out-of-scope per the candidate's targeting)
    "developer advocate", "developer relations", "devrel", "technical evangelist",
    # ops / HR / finance / legal
    "recruiter", "people operations", "talent acquisition", "human resources",
    "accountant", "controller", "operations manager", "legal counsel",
    "trust and safety", "trust & safety", "compliance officer",
]

# Body-signal upgrader — promotes generic engineering families to agentic
# specializations when the JD body shows strong AI/agent keyword density.
# Promote-only: never demotes, never changes in_scope. A plain swe-backend
# role with no AI signal stays swe-backend.
AGENT_SIGNAL = [
    "agent", "agentic", "tool use", "tool-use", "langgraph", "autogen",
    "mcp ", "model context protocol", "react pattern", "agentic ai",
    "function calling", "tool calling",
]
LLM_SIGNAL = [
    "llm", "large language model", "gpt-", "claude", "gemini",
    "rag ", "retrieval-augmented", "embedding", "vector database",
    "fine-tuning", "prompt engineering", "pydantic-ai", "openai api",
    "anthropic api",
]
ML_SIGNAL = [
    "machine learning", "deep learning", "neural network", "pytorch",
    "tensorflow", "sklearn", "scikit-learn", "huggingface",
]

GENERIC_FAMILIES = {
    "swe-backend", "swe-frontend", "swe-fullstack",
    "swe-founding", "swe-mobile", "other-eng",
}


def upgrade_family(family: str, body: str) -> str:
    """Promote generic engineering families to agentic specializations when the
    JD body shows enough AI/agent keyword density. Promote-only.

    Threshold of >=2 distinct keywords prevents single-mention false positives
    ("we partner with AI teams" alone wouldn't upgrade anything).
    """
    if family not in GENERIC_FAMILIES:
        return family
    b = (body or "").lower()
    agent_hits = sum(1 for k in AGENT_SIGNAL if k in b)
    if agent_hits >= 2:
        return "agent-engineer"
    llm_hits = sum(1 for k in LLM_SIGNAL if k in b)
    if llm_hits >= 3:
        return "applied-ai"
    ml_hits = sum(1 for k in ML_SIGNAL if k in b)
    if ml_hits >= 2:
        return "applied-ai"
    return family


def keyword_classify(title: str) -> tuple[bool | None, str]:
    """Classify a job title from string-substrings alone.

    Returns:
        (True, family)        — confident IN; LLM not consulted.
        (False, "out-of-scope") — confident OUT; LLM not consulted.
        (None, "")            — borderline; caller should escalate to LLM.

    OUT keywords beat IN keywords: "Sales Engineer" → OUT despite "engineer".
    """
    t = f" {title.lower().strip()} "  # pad so " sdr " etc. match cleanly
    for kw in OUT_TITLE_KEYWORDS:
        if kw in t:
            return (False, "out-of-scope")
    for family, kws in IN_TITLE_KEYWORDS.items():
        for kw in kws:
            if kw in t:
                return (True, family)
    return (None, "")


# ── Stage 2: LLM classifier ──────────────────────────────────────────────────

VALID_FAMILIES = tuple(IN_TITLE_KEYWORDS.keys()) + ("other-eng", "out-of-scope")


class RoleFamilyClassification(BaseModel):
    """Structured output for the borderline-title LLM classifier."""

    in_scope: bool
    role_family: str = Field(description="One of: " + ", ".join(VALID_FAMILIES))
    reason: str = Field(max_length=200)


_SYSTEM_PROMPT = """You are classifying a job posting for an agentic-AI engineer's job search.

IN_SCOPE means: engineering work that touches agentic AI or production AI systems. Specifically:
- Software engineering: Backend / Frontend / Fullstack / Product / Platform / Mobile / Infrastructure / Founding
- Applied AI / AI Engineer / ML Engineer
- Agent Engineer / Agentic Engineer / Agent Platform / Orchestration / Reliability
- Forward Deployed Engineer / Deployed Engineer / AI Solutions Engineer — ONLY if the JD body emphasizes technical implementation, not pre-sales
- Research Engineer — applied, building shipping systems
- Developer Experience / DevTools when the product is AI/agent infrastructure
- AI Infrastructure / LLM Platform / Inference / Eval Engineer
- Customer Engineer — ONLY when JD body shows real building, not sales support

OUT means:
- Sales, pre-sales, customer success / experience / support
- Product Manager (unless JD explicitly says coding/prototyping is core — rare)
- Designer, UX, brand, motion graphics, conversation designer
- Marketing / growth / demand gen / lifecycle
- Accounting / finance / operations / HR / recruiting / legal / compliance / policy-side T&S

BIAS TOWARD INCLUSION. The cost of one extra LLM extract+score is far lower than the cost of dropping a role the candidate would want to see. Classify OUT only when:
  (a) the title is in the OUT list, AND
  (b) the JD body shows zero engineering work.

When uncertain, classify IN_SCOPE with role_family="other-eng".

Output ONE line in `reason` explaining the decision (≤140 chars)."""


async def llm_classify(title: str, jd_first_500: str) -> RoleFamilyClassification:
    """Call Gemini Flash to classify a borderline title. Caller should only invoke
    when keyword_classify returned (None, ""). Cost ~$0.0005/call."""
    from compass.llm import make_agent

    agent = make_agent(
        "extract",  # reuse Gemini Flash configured for extract; cheap + structured-output-friendly
        output_type=RoleFamilyClassification,
        system_prompt=_SYSTEM_PROMPT,
    )
    user = f"TITLE: {title}\n\nJD (first 500 chars):\n{jd_first_500}"
    result = await agent.run(user)
    out: RoleFamilyClassification = result.output
    # Normalize: the model may return an out-of-list family. Clamp.
    if out.role_family not in VALID_FAMILIES:
        logger.info("role_family: model returned unknown family %r; coerced to other-eng", out.role_family)
        out = out.model_copy(update={"role_family": "other-eng" if out.in_scope else "out-of-scope"})
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/pipeline/test_role_family.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Add LLM-classifier test with monkeypatched agent**

```python
# Append to tests/pipeline/test_role_family.py
import asyncio
from unittest.mock import AsyncMock

class TestLLMClassify:
    def test_llm_classify_in_scope(self, monkeypatch):
        from compass.pipeline import role_family

        fake = AsyncMock()
        fake.run = AsyncMock(return_value=type("R", (), {
            "output": role_family.RoleFamilyClassification(
                in_scope=True, role_family="agent-engineer", reason="real eng work in body"
            )
        })())
        monkeypatch.setattr(role_family, "make_agent", lambda *a, **kw: fake)

        out = asyncio.run(role_family.llm_classify("Solutions Architect", "Build agent pipelines, write Python..."))
        assert out.in_scope is True
        assert out.role_family == "agent-engineer"

    def test_llm_unknown_family_coerced_in_scope(self, monkeypatch):
        from compass.pipeline import role_family

        fake = AsyncMock()
        fake.run = AsyncMock(return_value=type("R", (), {
            "output": role_family.RoleFamilyClassification(
                in_scope=True, role_family="bogus-family", reason="x"
            )
        })())
        monkeypatch.setattr(role_family, "make_agent", lambda *a, **kw: fake)

        out = asyncio.run(role_family.llm_classify("MTS", "writes systems code..."))
        assert out.role_family == "other-eng"
```

- [ ] **Step 6: Add body-signal upgrader tests**

```python
# Append to tests/pipeline/test_role_family.py
class TestUpgradeFamily:
    def test_specialized_family_unchanged(self):
        from compass.pipeline.role_family import upgrade_family
        # Already agent-engineer — never demoted, never changed
        assert upgrade_family("agent-engineer", "we sell hammers") == "agent-engineer"
        assert upgrade_family("applied-ai", "non-AI body") == "applied-ai"
        assert upgrade_family("fde-eng", "any body") == "fde-eng"

    def test_swe_backend_no_signal_stays_swe_backend(self):
        from compass.pipeline.role_family import upgrade_family
        body = "Build REST APIs in Go. Postgres. Kafka. SLOs. On-call."
        assert upgrade_family("swe-backend", body) == "swe-backend"

    def test_swe_backend_weak_signal_stays(self):
        # One AI mention only — below threshold
        from compass.pipeline.role_family import upgrade_family
        body = "We also have an LLM team but you'll work on payments infra."
        assert upgrade_family("swe-backend", body) == "swe-backend"

    def test_swe_backend_strong_agent_signal_promoted(self):
        from compass.pipeline.role_family import upgrade_family
        body = ("You'll build agent workflows in LangGraph with tool calling and "
                "MCP servers. Strong agentic AI background required.")
        assert upgrade_family("swe-backend", body) == "agent-engineer"

    def test_swe_fullstack_strong_llm_signal_promoted(self):
        from compass.pipeline.role_family import upgrade_family
        body = ("Build features powered by Claude and GPT-4. RAG pipeline with "
                "embedding retrieval. Prompt engineering for the assistant UX.")
        assert upgrade_family("swe-fullstack", body) == "applied-ai"

    def test_other_eng_strong_ml_signal_promoted(self):
        from compass.pipeline.role_family import upgrade_family
        body = "Train deep learning models in PyTorch. HuggingFace, neural networks."
        assert upgrade_family("other-eng", body) == "applied-ai"

    def test_empty_body_no_promotion(self):
        from compass.pipeline.role_family import upgrade_family
        assert upgrade_family("swe-backend", "") == "swe-backend"
        assert upgrade_family("swe-backend", None) == "swe-backend"
```

- [ ] **Step 7: Run and verify**

```bash
uv run pytest tests/pipeline/test_role_family.py -v
```

Expected: 22 passed (15 prior + 7 new).

- [ ] **Step 8: Commit**

```bash
git add compass/pipeline/role_family.py tests/pipeline/test_role_family.py
git commit -m "feat(pipeline): role-family classifier — keyword pre-filter + LLM fallback"
```

---

## Task 2: `intake_filter_node` (graph node + state plumbing)

**Files:**
- Modify: `compass/pipeline/state.py` (add `role_family`, `in_scope`)
- Create: `compass/pipeline/nodes/intake_filter.py`
- Test: `tests/pipeline/test_intake_filter.py`

- [ ] **Step 1: Extend `CompassState`**

```python
# compass/pipeline/state.py — add to TypedDict
class CompassState(TypedDict):
    raw_jobs: list[RawJob]
    current_job: RawJob | None
    extracted_requirements: JobRequirements | None
    score_result: JobScore | None

    in_scope: bool | None      # NEW: set by intake_filter; None pre-filter
    role_family: str | None    # NEW: set by intake_filter; None pre-filter

    human_approved: bool | None
    human_feedback: str | None
    tailored_paragraph: str | None

    vault_written: bool
    jobs_processed: int
    jobs_written: int

    errors: list[str]
```

Also update `_initial_state` in `compass/pipeline/graph.py` to include `"in_scope": None, "role_family": None`.

- [ ] **Step 2: Write the failing test**

```python
# tests/pipeline/test_intake_filter.py
import asyncio
from datetime import date
from unittest.mock import AsyncMock

from compass.pipeline.state import CompassState, RawJob


def _state(title: str, description: str = "We build agents.") -> CompassState:
    job = RawJob(
        company="Acme", title=title, url=f"https://x/{title}",
        source="manual", description=description, date_posted=date.today(),
    )
    return {
        "raw_jobs": [], "current_job": job,
        "extracted_requirements": None, "score_result": None,
        "in_scope": None, "role_family": None,
        "human_approved": None, "human_feedback": None, "tailored_paragraph": None,
        "vault_written": False, "jobs_processed": 0, "jobs_written": 0, "errors": [],
    }


class TestIntakeFilter:
    def test_obvious_in_skips_llm(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        mock_llm = AsyncMock()
        monkeypatch.setattr(mod, "llm_classify", mock_llm)
        out = asyncio.run(mod.intake_filter_node(_state("Agent Engineer")))
        assert out["in_scope"] is True
        assert out["role_family"] == "agent-engineer"
        mock_llm.assert_not_called()

    def test_obvious_out_skips_llm_and_logs(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        mock_llm = AsyncMock()
        monkeypatch.setattr(mod, "llm_classify", mock_llm)
        out = asyncio.run(mod.intake_filter_node(_state("Account Executive")))
        assert out["in_scope"] is False
        assert out["role_family"] == "out-of-scope"
        mock_llm.assert_not_called()

        # filtered-jobs.md was appended
        log = temp_vault / "_meta" / "filtered-jobs.md"
        assert log.exists()
        assert "Account Executive" in log.read_text()

    def test_borderline_invokes_llm(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod
        from compass.pipeline.role_family import RoleFamilyClassification

        async def fake_llm(title, body):
            return RoleFamilyClassification(in_scope=True, role_family="fde-eng", reason="real eng")
        monkeypatch.setattr(mod, "llm_classify", fake_llm)

        out = asyncio.run(mod.intake_filter_node(_state("Forward Deployed Engineer")))
        assert out["in_scope"] is True
        assert out["role_family"] == "fde-eng"

    def test_generic_swe_promoted_by_body_signal(self, monkeypatch, temp_vault):
        """Title is swe-backend but body screams agent engineering — should promote."""
        from compass.pipeline.nodes import intake_filter as mod

        body = ("Build agentic workflows in LangGraph. Tool calling, MCP servers, "
                "agent reliability. Strong agentic AI experience required.")
        mock_llm = AsyncMock()
        monkeypatch.setattr(mod, "llm_classify", mock_llm)

        out = asyncio.run(mod.intake_filter_node(_state("Software Engineer, Backend", body)))
        assert out["in_scope"] is True
        assert out["role_family"] == "agent-engineer"  # promoted from swe-backend
        mock_llm.assert_not_called()                   # zero-LLM upgrade

    def test_generic_swe_stays_when_no_ai_signal(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        body = "Build REST APIs. Postgres. Kafka. On-call rotations."
        out = asyncio.run(mod.intake_filter_node(_state("Backend Engineer", body)))
        assert out["role_family"] == "swe-backend"
        assert out["in_scope"] is True

    def test_llm_in_scope_also_runs_upgrade(self, monkeypatch, temp_vault):
        """LLM returned a generic family but body has strong agent signal — upgrade."""
        from compass.pipeline.nodes import intake_filter as mod
        from compass.pipeline.role_family import RoleFamilyClassification

        async def fake_llm(title, body):
            return RoleFamilyClassification(in_scope=True, role_family="other-eng", reason="generic")
        monkeypatch.setattr(mod, "llm_classify", fake_llm)

        body = "agentic AI workflows, agent reliability, tool calling everywhere"
        out = asyncio.run(mod.intake_filter_node(_state("Member of Technical Staff", body)))
        assert out["role_family"] == "agent-engineer"

    def test_borderline_out_logs(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod
        from compass.pipeline.role_family import RoleFamilyClassification

        async def fake_llm(title, body):
            return RoleFamilyClassification(in_scope=False, role_family="out-of-scope", reason="JD is presales")
        monkeypatch.setattr(mod, "llm_classify", fake_llm)

        out = asyncio.run(mod.intake_filter_node(_state("Solutions Architect")))
        assert out["in_scope"] is False
        assert "Solutions Architect" in (temp_vault / "_meta" / "filtered-jobs.md").read_text()

    def test_missing_current_job_errors(self, temp_vault):
        from compass.pipeline.nodes.intake_filter import intake_filter_node
        s = _state("X")
        s["current_job"] = None
        out = asyncio.run(intake_filter_node(s))
        assert out["in_scope"] is False
        assert "current_job is None" in out["errors"][-1]
```

- [ ] **Step 3: Run tests — they should fail (module not yet created)**

```bash
uv run pytest tests/pipeline/test_intake_filter.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 4: Implement `intake_filter_node`**

```python
# compass/pipeline/nodes/intake_filter.py
"""intake_filter_node — role-family gate.

Runs BEFORE extract so out-of-scope JDs never burn an LLM extract+score call.

Pipeline cost optimization: this saves ~$0.003 per dropped JD (skipping
extract+score+tailor) for the ~30–50% of postings on most boards that are
sales / PM / design / CS. With MAX_JOBS_PER_RUN=50, that's ~$0.10/day saved.

More importantly: it fixes the gap-aggregator bias introduced by Phase 0.B's
SCORE_THRESHOLD write-gate. Now ALL in-scope JDs reach the vault regardless
of current match score, so stretch-role gaps (the ones the candidate should be
studying toward) actually drive the master gap plan.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

import compass.config as cfg  # read VAULT_PATH at call time, NOT at import
from compass.pipeline.role_family import keyword_classify, llm_classify, upgrade_family

if TYPE_CHECKING:
    from compass.pipeline.state import CompassState

logger = logging.getLogger(__name__)


def _log_filtered(company: str, title: str, reason: str) -> None:
    # IMPORTANT: read VAULT_PATH at call time. Module-level constants would
    # break the temp_vault test fixture (which monkeypatches cfg.VAULT_PATH).
    log_path = cfg.VAULT_PATH / "_meta" / "filtered-jobs.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"- [{datetime.now().isoformat(timespec='seconds')}] "
        f"{company} {title!r} — {reason}\n"
    )
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)


async def intake_filter_node(state: CompassState) -> dict:
    job = state.get("current_job")
    if job is None:
        return {
            "in_scope": False,
            "role_family": "out-of-scope",
            "errors": [*state.get("errors", []), "intake_filter_node: current_job is None"],
        }

    body = job.description or ""

    decided, family = keyword_classify(job.title)
    if decided is True:
        upgraded = upgrade_family(family, body)
        return {"in_scope": True, "role_family": upgraded}
    if decided is False:
        _log_filtered(job.company, job.title, f"title keyword → {family}")
        logger.info("intake_filter: dropped %s — %s (keyword)", job.company, job.title)
        return {"in_scope": False, "role_family": family}

    # Borderline — escalate to LLM
    try:
        result = await llm_classify(job.title, body[:500])
    except Exception as e:
        logger.warning("intake_filter: LLM classify failed for %r — %s; defaulting to IN", job.title, e)
        return {"in_scope": True, "role_family": upgrade_family("other-eng", body)}

    if not result.in_scope:
        _log_filtered(job.company, job.title, f"llm → {result.reason}")
        logger.info("intake_filter: dropped %s — %s (llm: %s)", job.company, job.title, result.reason)
        return {"in_scope": False, "role_family": result.role_family}

    upgraded = upgrade_family(result.role_family, body)
    return {"in_scope": True, "role_family": upgraded}
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
uv run pytest tests/pipeline/test_intake_filter.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add compass/pipeline/state.py compass/pipeline/nodes/intake_filter.py tests/pipeline/test_intake_filter.py
git commit -m "feat(pipeline): intake_filter_node — drops out-of-scope JDs before extract"
```

---

## Task 3: Wire `intake_filter` into the graph

**Files:**
- Modify: `compass/pipeline/graph.py`
- Test: `tests/pipeline/test_routing.py` (extend existing)

- [ ] **Step 1: Add a failing test for the new routing**

Assert via final state, not by spying on internal node calls — LangGraph captures node references at `build_graph()` time so post-build monkeypatching is fragile.

```python
# Append to tests/pipeline/test_routing.py
import asyncio
from datetime import date

from compass.pipeline.state import RawJob


class TestIntakeFilterRouting:
    def test_out_of_scope_yields_in_scope_false_and_no_write(self, temp_vault):
        from compass.pipeline import graph as g

        job = RawJob(
            company="Acme", title="Account Executive", url="https://x/ae",
            source="manual", description="Sell things.", date_posted=date.today(),
        )
        graph = g.build_graph()
        out = asyncio.run(graph.ainvoke(g._initial_state(job)))
        assert out["in_scope"] is False
        assert out["vault_written"] is False
        assert out.get("extracted_requirements") is None
        assert out.get("score_result") is None
```

- [ ] **Step 2: Run test — expect failure (graph hasn't been changed yet)**

```bash
uv run pytest tests/pipeline/test_routing.py::TestIntakeFilterRouting -v
```

Expected: FAIL (extract still runs).

- [ ] **Step 3: Modify `build_graph` + add the routing predicate**

In `compass/pipeline/graph.py`:

```python
# Add at module top
from compass.pipeline.nodes.intake_filter import intake_filter_node


def _route_after_filter(state: CompassState) -> str:
    """Out-of-scope JDs short-circuit to END. In-scope continue to extract."""
    return "extract" if state.get("in_scope") is True else "end"


def build_graph():
    builder = StateGraph(CompassState)
    builder.add_node("intake", intake_node)
    builder.add_node("intake_filter", intake_filter_node)   # NEW
    builder.add_node("extract", extract_node)
    builder.add_node("score", score_node)
    builder.add_node("reflect", reflect_node)
    builder.add_node("hitl", hitl_node)
    builder.add_node("tailor", tailor_node)
    builder.add_node("vault_write", vault_write_node)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "intake_filter")              # NEW
    builder.add_conditional_edges(                            # NEW
        "intake_filter",
        _route_after_filter,
        {"extract": "extract", "end": END},
    )
    builder.add_edge("extract", "score")
    builder.add_edge("score", "reflect")
    builder.add_edge("reflect", "hitl")
    builder.add_conditional_edges(
        "hitl",
        _route_after_hitl,
        {"tailor": "tailor", "vault_write": "vault_write"},
    )
    builder.add_edge("tailor", "vault_write")
    builder.add_edge("vault_write", END)

    return builder.compile()
```

(The `_initial_state` update for the two new state keys was made in Task 2 step 1; nothing to change here.)

- [ ] **Step 4: Run all routing tests**

```bash
uv run pytest tests/pipeline/test_routing.py -v
```

Expected: all pass (existing routing tests still pass; new test passes).

- [ ] **Step 5: Run the integration test to confirm no regression**

```bash
uv run pytest tests/pipeline/ -v
```

Expected: 0 failures.

- [ ] **Step 6: Commit**

```bash
git add compass/pipeline/graph.py tests/pipeline/test_routing.py
git commit -m "feat(pipeline): wire intake_filter between intake and extract"
```

---

## Task 4: Company-tier lookup from `target-companies.md`

**Files:**
- Create: `compass/vault/target_companies.py`
- Test: `tests/vault/test_target_companies.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/vault/test_target_companies.py
from pathlib import Path
import pytest


TIERED_MD = """---
type: profile
---
# Target Companies

## Tier `apply-now`

### Top-tier
| Company | Title | Geo |
|---|---|---|
| AgentCo | Agent Engineer | SF |
| BotCo | MTS | SF |
| Ramp | Engineer | NYC |

### Big tech
| Company | Notes |
|---|---|
| NVIDIA Agentic AI | Austin |
| Apple Apple Intelligence | Austin |

## Tier `6-month`

| Company | Title |
|---|---|
| OpenAI | Member of Technical Staff |
| Cursor | Frontend |

## Tier `stretch`

| Company | Why |
|---|---|
| Anthropic | dream role |
"""


@pytest.fixture
def tiered_vault(tmp_path, monkeypatch):
    vault = tmp_path / "v"
    (vault / "_profile").mkdir(parents=True)
    (vault / "_profile" / "target-companies.md").write_text(TIERED_MD)
    import compass.config as cfg
    monkeypatch.setattr(cfg, "VAULT_PATH", vault)
    # Bust the cached parser
    import compass.vault.target_companies as tc
    tc.refresh()
    return vault


def test_get_tier_apply_now(tiered_vault):
    from compass.vault.target_companies import get_tier
    assert get_tier("AgentCo") == "apply-now"
    assert get_tier("Ramp") == "apply-now"
    assert get_tier("Apple Apple Intelligence") == "apply-now"

def test_get_tier_six_month(tiered_vault):
    from compass.vault.target_companies import get_tier
    assert get_tier("OpenAI") == "6-month"
    assert get_tier("Cursor") == "6-month"

def test_get_tier_stretch(tiered_vault):
    from compass.vault.target_companies import get_tier
    assert get_tier("Anthropic") == "stretch"

def test_get_tier_unknown_company(tiered_vault):
    from compass.vault.target_companies import get_tier
    assert get_tier("Random Inc") == "unknown"

def test_case_insensitive_normalization(tiered_vault):
    from compass.vault.target_companies import get_tier
    assert get_tier("agentco") == "apply-now"
    assert get_tier("AGENTCO") == "apply-now"
    assert get_tier("sier ra") == "apply-now"   # whitespace tolerated

def test_missing_file_returns_unknown(tmp_path, monkeypatch):
    import compass.config as cfg
    import compass.vault.target_companies as tc
    monkeypatch.setattr(cfg, "VAULT_PATH", tmp_path)
    tc.refresh()
    assert tc.get_tier("AgentCo") == "unknown"

def test_refresh_picks_up_edits(tiered_vault):
    from compass.vault.target_companies import get_tier, refresh
    new = TIERED_MD.replace("| Anthropic | dream role |", "| Anthropic | nope |\n| NewCo | x |")
    (tiered_vault / "_profile" / "target-companies.md").write_text(new + "\n## Tier `apply-now`\n\n| Company | Notes |\n|---|---|\n| NewCo | added |\n")
    refresh()
    assert get_tier("NewCo") == "apply-now"


def test_multiple_adjacent_tables_one_tier(tmp_path, monkeypatch):
    """Parser must handle two tables back-to-back under one tier heading
    (the real target-companies.md has 'Top-tier startups' and 'Big tech' under
    apply-now). Test both with-blank-line-between and no-blank-line variants."""
    md = """## Tier `apply-now`

### Startups
| Company | Geo |
|---|---|
| AgentCo | SF |
### Big tech
| Company | Notes |
|---|---|
| NVIDIA | Austin |
"""
    vault = tmp_path / "v"
    (vault / "_profile").mkdir(parents=True)
    (vault / "_profile" / "target-companies.md").write_text(md)
    import compass.config as cfg
    import compass.vault.target_companies as tc
    monkeypatch.setattr(cfg, "VAULT_PATH", vault)
    tc.refresh()
    assert tc.get_tier("AgentCo") == "apply-now"
    assert tc.get_tier("NVIDIA") == "apply-now"


def test_company_header_row_skipped(tmp_path, monkeypatch):
    """Defensive: a literal '| Company |' header must NOT be parsed as a company."""
    md = """## Tier `apply-now`

| Company | Notes |
|---|---|
| AgentCo | SF |
"""
    vault = tmp_path / "v"
    (vault / "_profile").mkdir(parents=True)
    (vault / "_profile" / "target-companies.md").write_text(md)
    import compass.config as cfg
    import compass.vault.target_companies as tc
    monkeypatch.setattr(cfg, "VAULT_PATH", vault)
    tc.refresh()
    assert tc.get_tier("Company") == "unknown"
    assert tc.get_tier("AgentCo") == "apply-now"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/vault/test_target_companies.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `target_companies.py`**

```python
# compass/vault/target_companies.py
"""Parse _profile/target-companies.md into a company→tier map.

The file is human-edited but follows a stable section structure:
  ## Tier `apply-now`
  | Company | ... |
  |---|---|
  | AgentCo | ... |
  | ...
  ## Tier `6-month`
  ...

Parser walks the file once at module import (and on refresh()) and builds a
dict keyed by normalized company name. Naive lookup; no fuzzy matching.

This is the source of truth for JobNote.tier and CompanyNote.tier during
pipeline runs. Human edits to a CompanyNote's tier are still preserved by
write_company_note (which we don't touch here).
"""
from __future__ import annotations

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

Tier = Literal["apply-now", "6-month", "stretch", "skip", "unknown"]
TIER_ORDER: list[Tier] = ["apply-now", "6-month", "stretch", "skip"]

_TIER_HEADING = re.compile(r"^##\s*Tier\s*`([^`]+)`", re.IGNORECASE)
_TABLE_DIVIDER = re.compile(r"^\|\s*-+\s*\|")
_TABLE_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|")  # captures first column

_company_to_tier: dict[str, Tier] = {}


def _normalize(name: str) -> str:
    return re.sub(r"\s+", "", name.strip().lower())


def _parse() -> dict[str, Tier]:
    from compass.config import VAULT_PATH

    path = VAULT_PATH / "_profile" / "target-companies.md"
    out: dict[str, Tier] = {}
    if not path.exists():
        return out

    current_tier: Tier | None = None
    in_table = False
    table_seen_divider = False

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        m = _TIER_HEADING.match(line)
        if m:
            tier_str = m.group(1).strip().lower()
            current_tier = tier_str if tier_str in TIER_ORDER else None  # type: ignore[assignment]
            in_table = False
            table_seen_divider = False
            continue

        if current_tier is None:
            continue

        if _TABLE_DIVIDER.match(line):
            table_seen_divider = True
            in_table = True
            continue

        if in_table and table_seen_divider:
            if not line.startswith("|"):
                in_table = False
                table_seen_divider = False
                continue
            mrow = _TABLE_ROW.match(line)
            if mrow:
                company = mrow.group(1).strip()
                # Skip header-like rows that slipped past (defensive)
                if not company or company.lower() == "company":
                    continue
                key = _normalize(company)
                # If company appears in multiple tiers, higher tier wins
                existing = out.get(key)
                if existing is None or TIER_ORDER.index(current_tier) < TIER_ORDER.index(existing):
                    out[key] = current_tier
        else:
            in_table = False
            table_seen_divider = False

    return out


def refresh() -> None:
    """Re-parse target-companies.md. Call from tests or after manual edits."""
    global _company_to_tier
    _company_to_tier = _parse()
    logger.info("target_companies: parsed %d entries", len(_company_to_tier))


def get_tier(company: str) -> Tier:
    if not _company_to_tier:
        refresh()
    return _company_to_tier.get(_normalize(company), "unknown")


# Parse at import for callers that don't trigger refresh()
refresh()
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/vault/test_target_companies.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add compass/vault/target_companies.py tests/vault/test_target_companies.py
git commit -m "feat(vault): parse target-companies.md into tier lookup"
```

---

## Task 5: Drop `SCORE_THRESHOLD` write gate; populate `role_family` and `tier` in `vault_write`

**Files:**
- Modify: `compass/pipeline/nodes/vault_write.py`
- Test: extend `tests/pipeline/test_vault_write.py`

- [ ] **Step 1: DELETE the two obsolete threshold tests by name**

The current Phase 0.B tests at `tests/pipeline/test_vault_write.py:108-128` codify the bug we're now fixing. They MUST be removed (not "replaced" — deleted):

```bash
# Open tests/pipeline/test_vault_write.py and delete these two functions
# in their entirety (including the docstring + body):
#   - async def test_vault_write_node_skips_below_threshold(...)
#   - async def test_vault_write_node_writes_at_or_above_threshold(...)
```

After deletion, also remove the `monkeypatch.setattr(vw, "SCORE_THRESHOLD", 0.0)` line from `test_vault_write_node_persists_full_jd_body` — the symbol no longer exists in the node module after Task 5 step 4.

Verify:
```bash
grep -n SCORE_THRESHOLD tests/pipeline/test_vault_write.py
# Expected: no matches.
```

- [ ] **Step 2: Add new tests for Phase 1.A vault_write behavior**

The existing `_state(...)` helper at `tests/pipeline/test_vault_write.py:10` is the canonical state builder — reuse it. Append these tests:

```python
# Append to tests/pipeline/test_vault_write.py

async def test_low_score_in_scope_still_writes(temp_vault):
    """Phase 1.A: gap_aggregator needs stretch-role data → write all in-scope JDs
    regardless of match_score. Pre-1.A this returned vault_written=False."""
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _state(["Python"], ["Python"], score=1.5)
    state["in_scope"] = True
    state["role_family"] = "swe-backend"
    result = await vault_write_node(state)

    assert result["vault_written"] is True
    assert len(list((temp_vault / "jobs").glob("*AgentCo*.md"))) == 1


async def test_role_family_threaded_to_jobnote(temp_vault):
    """role_family from state lands in JobNote frontmatter."""
    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _state(["LangGraph"], ["LangGraph"], score=4.0)
    state["in_scope"] = True
    state["role_family"] = "agent-engineer"
    await vault_write_node(state)

    path = next((temp_vault / "jobs").glob("*AgentCo*.md"))
    assert frontmatter.load(path).metadata["role_family"] == "agent-engineer"


async def test_tier_resolved_from_target_companies(temp_vault):
    """target-companies.md says AgentCo=apply-now → JobNote.tier == 'apply-now'."""
    (temp_vault / "_profile" / "target-companies.md").write_text(
        "## Tier `apply-now`\n\n| Company | Geo |\n|---|---|\n| AgentCo | SF |\n"
    )
    import compass.vault.target_companies as tc
    tc.refresh()

    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _state(["MCP"], ["MCP"], score=4.5)
    state["in_scope"] = True
    state["role_family"] = "agent-engineer"
    await vault_write_node(state)

    path = next((temp_vault / "jobs").glob("*AgentCo*.md"))
    assert frontmatter.load(path).metadata["tier"] == "apply-now"


async def test_unknown_company_tier_remains_unknown(temp_vault):
    """No target-companies.md entry → JobNote.tier == 'unknown'."""
    import compass.vault.target_companies as tc
    tc.refresh()  # ensure stale map is cleared

    from compass.pipeline.nodes.vault_write import vault_write_node

    state = _state(["MCP"], ["MCP"], score=4.5)
    state["in_scope"] = True
    state["role_family"] = "agent-engineer"
    state["current_job"] = state["current_job"].model_copy(update={"company": "RandomCo"})
    await vault_write_node(state)

    path = next((temp_vault / "jobs").glob("*RandomCo*.md"))
    assert frontmatter.load(path).metadata["tier"] == "unknown"


async def test_human_edited_company_tier_preserved(temp_vault):
    """Bug #15 regression: if the candidate edits a CompanyNote's tier in Obsidian to
    override what target-companies.md says, vault_write must NOT clobber that
    edit on the next pipeline run."""
    # 1. Seed CompanyNote on disk with tier=stretch (simulating a human edit)
    from compass.vault.schemas import CompanyNote
    from compass.vault.writer import write_company_note
    write_company_note(CompanyNote(company="AgentCo", tier="stretch", roles_seen=3))

    # 2. Seed target-companies.md saying AgentCo is apply-now (conflicts with edit)
    (temp_vault / "_profile" / "target-companies.md").write_text(
        "## Tier `apply-now`\n\n| Company | Notes |\n|---|---|\n| AgentCo | x |\n"
    )
    import compass.vault.target_companies as tc
    tc.refresh()

    # 3. Run vault_write_node with a AgentCo job
    from compass.pipeline.nodes.vault_write import vault_write_node
    state = _state(["MCP"], ["MCP"], score=4.5)
    state["in_scope"] = True
    state["role_family"] = "agent-engineer"
    await vault_write_node(state)

    # 4. CompanyNote.tier must still be 'stretch' (human edit preserved)
    md = frontmatter.load(temp_vault / "companies" / "AgentCo.md").metadata
    assert md["tier"] == "stretch", "human-edited CompanyNote tier was clobbered"

    # 5. But the new JobNote snapshots the resolved tier (apply-now) at write time
    job_path = next((temp_vault / "jobs").glob("*AgentCo*.md"))
    assert frontmatter.load(job_path).metadata["tier"] == "apply-now"
```

- [ ] **Step 3: Run — expect failures**

```bash
uv run pytest tests/pipeline/test_vault_write.py -v
```

Expected: failures (threshold gate still in place; role_family/tier not yet read).

- [ ] **Step 4: Modify `vault_write_node`**

Replace lines 50–66 (threshold gate) and the tier=unknown hardcode (line 99). Final node body:

```python
async def vault_write_node(state: CompassState) -> dict:
    job = state.get("current_job")
    score = state.get("score_result")
    req = state.get("extracted_requirements")

    if job is None or score is None or req is None:
        missing = [
            n for n, v in [
                ("current_job", job), ("score_result", score), ("extracted_requirements", req),
            ] if v is None
        ]
        return {
            "vault_written": False,
            "errors": [*state.get("errors", []), f"vault_write_node: missing {missing}"],
        }

    # NOTE: SCORE_THRESHOLD is intentionally NOT applied here in Phase 1.A.
    # The threshold still gates tailor (Sonnet cost control) inside hitl_node.
    # Removing it here lets stretch-role gaps drive the master gap plan —
    # see docs/superpowers/specs/2026-05-18-compass-phase-1a-application-tracking.md §2.

    from compass.vault.target_companies import get_tier

    # JobNote.tier is a per-posting snapshot — always use the currently-resolved
    # tier so a later edit to target-companies.md doesn't retroactively change
    # what the snapshot said when the job was first seen.
    company_tier = get_tier(job.company)

    # CompanyNote.tier — read-before-write to preserve human edits in Obsidian.
    # If an existing CompanyNote has a non-default tier, pass "unknown" on
    # write_company_note so its merge logic preserves the existing tier.
    # (writer.py:130-132 only preserves when incoming.tier == "unknown".)
    # Bug #15 (Phase 0) regression guard.
    import compass.config as _cfg
    import frontmatter as _fm

    company_tier_for_write = company_tier
    companies_dir = _cfg.VAULT_PATH / "companies"
    if companies_dir.exists():
        for existing in companies_dir.glob("*.md"):
            try:
                existing_md = _fm.load(existing).metadata
            except Exception:
                continue
            if existing_md.get("company") == job.company:
                if existing_md.get("tier", "unknown") not in ("unknown", ""):
                    company_tier_for_write = "unknown"
                break

    note = JobNote(
        company=job.company,
        title=job.title,
        url=job.url,
        source=job.source,
        date_found=job.date_posted or date.today(),
        match_score=score.score,
        score_reasoning=score.reasoning,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        location=job.location,
        remote=("remote" if job.remote else None),
        seniority=req.seniority,
        years_required=req.years_experience,
        role_family=state.get("role_family") or "",
        tier=company_tier,
        skills_required=req.required_skills,
        skills_nice_to_have=req.nice_to_have_skills,
        skills_matched=score.matched_skills,
        skills_missing=score.missing_skills,
        jd_summary=req.summary,
        tailored_paragraph=state.get("tailored_paragraph"),
    )
    write_job_note(note, full_description=job.description)

    write_company_note(CompanyNote(company=job.company, tier=company_tier_for_write, roles_seen=1))

    return {
        "vault_written": True,
        "jobs_written": state.get("jobs_written", 0) + 1,
    }
```

Also: remove the `from compass.config import SCORE_THRESHOLD` import and the `append_agent_log` import if it's only used for the skip branch.

- [ ] **Step 5: Run — expect pass**

```bash
uv run pytest tests/pipeline/test_vault_write.py -v
```

Expected: all pass.

- [ ] **Step 6: Run full test suite — confirm no regression**

```bash
uv run pytest -q
```

Expected: all green; new test count >= 81 + Phase-1A new tests.

- [ ] **Step 7: Commit**

```bash
git add compass/pipeline/nodes/vault_write.py tests/pipeline/test_vault_write.py
git commit -m "fix(pipeline): drop score-threshold write gate; populate role_family + tier on JobNote"
```

---

## Task 6: `write_application_note` writer

**Files:**
- Modify: `compass/vault/writer.py` — add `write_application_note`
- Test: extend `tests/vault/` or add `tests/vault/test_application_writer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/vault/test_application_writer.py
from datetime import date
from compass.vault.schemas import ApplicationNote


def test_write_application_note_creates_file(temp_vault):
    from compass.vault.writer import write_application_note
    note = ApplicationNote(
        company="AgentCo", title="Agent Engineer", job_ref="https://x/agentco",
        applied_date=date(2026, 5, 18),
    )
    path = write_application_note(note)
    assert path.exists()
    assert path.name.startswith("2026-05-18-AgentCo-Agent_Engineer-")
    assert path.name.endswith(".md")
    # 8-char hash suffix present
    stem = path.stem  # "2026-05-18-AgentCo-Agent_Engineer-<hash>"
    suffix = stem.rsplit("-", 1)[-1]
    assert len(suffix) == 8


def test_write_application_idempotent_same_jobref_same_day(temp_vault):
    """Same (company, title, applied_date, job_ref) → same file, updated."""
    from compass.vault.writer import write_application_note
    note = ApplicationNote(company="AgentCo", title="Agent Engineer",
                           job_ref="https://x/agentco-team-a", applied_date=date(2026, 5, 18))
    p1 = write_application_note(note)
    note2 = note.model_copy(update={"next_action": "follow up", "next_action_date": date(2026, 5, 25)})
    p2 = write_application_note(note2)
    assert p1 == p2
    import frontmatter
    md = frontmatter.load(p2)
    assert md["next_action"] == "follow up"


def test_write_application_same_company_title_same_day_different_jobref(temp_vault):
    """Two different postings at the same company on the same day produce
    distinct files (different job_ref → different filename hash)."""
    from compass.vault.writer import write_application_note
    n1 = ApplicationNote(company="AgentCo", title="Agent Engineer",
                         job_ref="https://x/agentco-team-a", applied_date=date(2026, 5, 18))
    n2 = ApplicationNote(company="AgentCo", title="Agent Engineer",
                         job_ref="https://x/agentco-team-b", applied_date=date(2026, 5, 18))
    assert write_application_note(n1) != write_application_note(n2)


def test_write_application_separate_files_per_date(temp_vault):
    """Re-applying to the same posting on a different date is allowed."""
    from compass.vault.writer import write_application_note
    n1 = ApplicationNote(company="AgentCo", title="Agent Engineer",
                         job_ref="https://x/agentco", applied_date=date(2026, 1, 1))
    n2 = ApplicationNote(company="AgentCo", title="Agent Engineer",
                         job_ref="https://x/agentco", applied_date=date(2026, 5, 18))
    assert write_application_note(n1) != write_application_note(n2)
```

- [ ] **Step 2: Run — expect failure**

```bash
uv run pytest tests/vault/test_application_writer.py -v
```

Expected: ImportError on `write_application_note`.

- [ ] **Step 3: Implement**

Add to `compass/vault/writer.py` (`hashlib` is already imported at top):

```python
from compass.vault.schemas import ApplicationNote  # add to existing imports


def _application_filename(note: ApplicationNote) -> str:
    """Filename includes a short hash of job_ref so applying to two different
    postings at one company on the same day produces two separate files.
    Mirrors the JobNote-filename strategy from bug #11 in Phase 0."""
    job_ref_hash = hashlib.sha1(note.job_ref.encode("utf-8")).hexdigest()[:8]
    return (
        f"{note.applied_date.isoformat()}"
        f"-{_safe_segment(note.company)}"
        f"-{_safe_segment(note.title)}"
        f"-{job_ref_hash}.md"
    )


def write_application_note(note: ApplicationNote) -> Path:
    """Write or update an application note. Idempotent on (company, title, applied_date).

    Re-running with the same identity overwrites the file; downstream callers
    use this to record status transitions without duplicating notes.
    """
    apps_dir = VAULT_PATH / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    path = apps_dir / _application_filename(note)

    body = f"# {note.company} — {note.title}\n\n"
    body += f"Applied: {note.applied_date.isoformat()}\n"
    body += f"Status: {note.status}\n"
    if note.next_action:
        body += f"\n**Next action:** {note.next_action}"
        if note.next_action_date:
            body += f" (by {note.next_action_date.isoformat()})"
        body += "\n"
    post = frontmatter.Post(content=body)
    post.metadata = _to_metadata(note)
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    append_agent_log(
        f"vault_write application {note.company} {note.title} "
        f"applied={note.applied_date} status={note.status}"
    )
    return path
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/vault/test_application_writer.py -v
```

- [ ] **Step 5: Commit**

```bash
git add compass/vault/writer.py tests/vault/test_application_writer.py
git commit -m "feat(vault): write_application_note — idempotent on (company,title,applied_date)"
```

---

## Task 7: Application lifecycle module

**Files:**
- Create: `compass/applications/__init__.py`
- Create: `compass/applications/lifecycle.py`
- Test: `tests/applications/__init__.py` + `tests/applications/test_lifecycle.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/applications/test_lifecycle.py
import pytest
from datetime import date
from pathlib import Path


def _seed_jobnote(vault: Path, company="AgentCo", title="Agent Engineer", url="https://x/s") -> Path:
    """Write a minimal JobNote frontmatter that the lifecycle can find."""
    from compass.vault.schemas import JobNote
    from compass.vault.writer import write_job_note
    note = JobNote(
        company=company, title=title, url=url, source="manual",
        date_found=date(2026, 5, 10), match_score=4.5,
    )
    return write_job_note(note)


class TestAddApplication:
    def test_creates_application_note(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application
        app = add_application(job_id="AgentCo-Agent_Engineer")
        assert app.company == "AgentCo"
        assert app.status == "applied"
        # Application file exists
        assert any((temp_vault / "applications").glob("*AgentCo*"))

    def test_marks_jobnote_status_applied(self, temp_vault):
        job_path = _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application
        add_application(job_id="AgentCo-Agent_Engineer")
        import frontmatter
        md = frontmatter.load(job_path)
        assert md["status"] == "applied"
        assert md["applied_at"] is not None

    def test_unknown_job_raises(self, temp_vault):
        from compass.applications.lifecycle import add_application
        with pytest.raises(LookupError):
            add_application(job_id="not-a-real-job")

    def test_ambiguous_job_raises(self, temp_vault):
        _seed_jobnote(temp_vault, company="AgentCo", title="Agent Engineer", url="x1")
        _seed_jobnote(temp_vault, company="AgentCo", title="Agent Engineer II", url="x2")
        from compass.applications.lifecycle import add_application
        with pytest.raises(LookupError, match="ambiguous"):
            add_application(job_id="AgentCo-Agent")


class TestUpdateStatus:
    def test_valid_transition(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application, update_application_status
        app = add_application(job_id="AgentCo")
        updated = update_application_status(
            app_id=f"{app.applied_date.isoformat()}-AgentCo", status="screen",
            next_action="prep recruiter screen", next_action_date=date(2026, 5, 22),
        )
        assert updated.status == "screen"
        assert updated.next_action == "prep recruiter screen"

    def test_invalid_transition_raises(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application, update_application_status
        app = add_application(job_id="AgentCo")
        with pytest.raises(ValueError, match="invalid transition"):
            update_application_status(app_id=f"{app.applied_date.isoformat()}-AgentCo", status="offer")

    def test_force_bypasses_validation(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application, update_application_status
        app = add_application(job_id="AgentCo")
        updated = update_application_status(
            app_id=f"{app.applied_date.isoformat()}-AgentCo", status="offer", force=True,
        )
        assert updated.status == "offer"


class TestListPending:
    def test_returns_due_actions(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application, update_application_status, list_pending_actions
        app = add_application(job_id="AgentCo")
        update_application_status(
            app_id=f"{app.applied_date.isoformat()}-AgentCo", status="screen",
            next_action="follow up", next_action_date=date(2026, 5, 18),
        )
        pending = list_pending_actions(through_date=date(2026, 5, 18))
        assert len(pending) == 1
        assert pending[0]["company"] == "AgentCo"

    def test_filters_out_future_actions(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application, update_application_status, list_pending_actions
        app = add_application(job_id="AgentCo")
        update_application_status(
            app_id=f"{app.applied_date.isoformat()}-AgentCo", status="screen",
            next_action_date=date(2026, 12, 1),
        )
        pending = list_pending_actions(through_date=date(2026, 5, 18))
        assert pending == []


class TestNextActionSentinel:
    """update_application_status uses a sentinel to distinguish 'don't change'
    from 'clear this field'. Verify both branches and the preservation case."""

    def test_omitted_args_preserve_existing(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application, update_application_status

        app = add_application(job_id="AgentCo")
        update_application_status(
            app_id=f"{app.applied_date.isoformat()}-AgentCo", status="screen",
            next_action="prep call", next_action_date=date(2026, 5, 25),
        )
        # Transition again without specifying next_action* — must preserve them
        update_application_status(
            app_id=f"{app.applied_date.isoformat()}-AgentCo", status="onsite",
        )
        import frontmatter
        path = next((temp_vault / "applications").glob("*AgentCo*.md"))
        md = frontmatter.load(path).metadata
        assert md["next_action"] == "prep call"
        assert md["next_action_date"] == "2026-05-25"  # frontmatter stores ISO string

    def test_explicit_none_clears(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application, update_application_status

        app = add_application(job_id="AgentCo")
        update_application_status(
            app_id=f"{app.applied_date.isoformat()}-AgentCo", status="screen",
            next_action="prep call", next_action_date=date(2026, 5, 25),
        )
        # Clear both with explicit None
        update_application_status(
            app_id=f"{app.applied_date.isoformat()}-AgentCo", status="onsite",
            next_action=None, next_action_date=None,
        )
        import frontmatter
        path = next((temp_vault / "applications").glob("*AgentCo*.md"))
        md = frontmatter.load(path).metadata
        assert md["next_action"] == ""
        assert md["next_action_date"] is None
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/applications/ -v
```

- [ ] **Step 3: Implement `compass/applications/lifecycle.py`**

```python
# compass/applications/__init__.py
# empty

# compass/applications/lifecycle.py
"""Application lifecycle — wraps ApplicationNote CRUD and JobNote status updates.

Exposed via MCP server. Single-writer assumption: only the human (via MCP)
mutates applications. The pipeline writes JobNotes; it never creates
ApplicationNotes. Status transitions are validated (see VALID_TRANSITIONS).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import frontmatter

import compass.config as cfg  # read VAULT_PATH at call time, not at import
from compass.vault.schemas import ApplicationNote
from compass.vault.writer import append_agent_log, write_application_note

logger = logging.getLogger(__name__)

# Sentinel for "caller didn't pass this argument" vs "caller passed None to clear it"
_UNSET: object = object()


VALID_TRANSITIONS: dict[str, set[str]] = {
    "applied":   {"screen", "rejected", "withdrawn", "ghosted"},
    "screen":    {"onsite", "rejected", "withdrawn", "ghosted"},
    "onsite":    {"offer", "rejected", "withdrawn", "ghosted"},
    "offer":     {"accepted", "declined", "withdrawn"},
    "rejected":  set(),
    "withdrawn": set(),
    "ghosted":   {"rejected"},
    "accepted":  set(),
    "declined":  set(),
}


def find_jobnote(job_id: str) -> Path:
    """Public: resolve a job_id (filename substring or url) to a JobNote path.
    Used by add_application AND by the MCP tailor_resume tool."""
    jobs_dir = cfg.VAULT_PATH / "jobs"
    if not jobs_dir.exists():
        raise LookupError(f"no jobs/ directory in vault at {cfg.VAULT_PATH}")
    matches: list[Path] = []
    for p in jobs_dir.glob("*.md"):
        if job_id in p.name:
            matches.append(p)
            continue
        try:
            md = frontmatter.load(p).metadata
        except Exception:
            continue
        if md.get("url") == job_id:
            matches.append(p)
    if not matches:
        raise LookupError(f"no JobNote matched job_id={job_id!r}")
    if len(matches) > 1:
        names = ", ".join(p.name for p in matches)
        raise LookupError(f"ambiguous job_id={job_id!r} — matches {names}")
    return matches[0]


def _find_application(app_id: str) -> Path:
    apps_dir = cfg.VAULT_PATH / "applications"
    matches = [p for p in apps_dir.glob("*.md") if app_id in p.name]
    if not matches:
        raise LookupError(f"no ApplicationNote matched app_id={app_id!r}")
    if len(matches) > 1:
        raise LookupError(f"ambiguous app_id={app_id!r}")
    return matches[0]


def _update_jobnote_status(jobnote_path: Path, status: str) -> None:
    md = frontmatter.load(jobnote_path)
    md["status"] = status
    if status == "applied":
        md["applied_at"] = datetime.now().isoformat()
    jobnote_path.write_text(frontmatter.dumps(md) + "\n", encoding="utf-8")


def add_application(
    job_id: str,
    *,
    resume_variant: str = "resume.md",
    referral: bool = False,
) -> ApplicationNote:
    """Create an ApplicationNote linked to a JobNote and mark the JobNote applied."""
    job_path = find_jobnote(job_id)
    job_md = frontmatter.load(job_path).metadata

    note = ApplicationNote(
        company=job_md["company"],
        title=job_md["title"],
        job_ref=job_md.get("url", str(job_path)),
        applied_date=date.today(),
        resume_variant=resume_variant,
        status="applied",
        referral=referral,
    )
    write_application_note(note)
    _update_jobnote_status(job_path, "applied")
    append_agent_log(f"application added {note.company} {note.title}")
    return note


def update_application_status(
    app_id: str,
    status: str,
    *,
    next_action: object = _UNSET,
    next_action_date: object = _UNSET,
    force: bool = False,
) -> ApplicationNote:
    """Transition an application's status.

    next_action / next_action_date semantics:
        omitted (sentinel) → existing value preserved
        passed as None      → existing value cleared
        passed as a value   → existing value replaced
    """
    path = _find_application(app_id)
    md = frontmatter.load(path).metadata
    current = md.get("status", "applied")

    if not force:
        allowed = VALID_TRANSITIONS.get(current, set())
        if status not in allowed:
            raise ValueError(
                f"invalid transition {current!r} → {status!r} "
                f"(allowed: {sorted(allowed) or '(terminal)'})"
            )

    note = ApplicationNote(**{**md, "status": status})
    if next_action is not _UNSET:
        note = note.model_copy(update={"next_action": next_action or ""})
    if next_action_date is not _UNSET:
        note = note.model_copy(update={"next_action_date": next_action_date})
    write_application_note(note)

    # Mirror status on the JobNote so dashboard queries reflect current state
    job_id = note.job_ref
    try:
        job_path = find_jobnote(job_id)
        _update_jobnote_status(job_path, status)
    except LookupError:
        logger.warning("update_status: could not find linked JobNote for %r", job_id)

    append_agent_log(f"application status {note.company} {note.title} {current}→{status}")
    return note


def list_pending_actions(through_date: date | None = None) -> list[dict]:
    cutoff = through_date or date.today()
    out: list[dict] = []
    apps_dir = cfg.VAULT_PATH / "applications"
    if not apps_dir.exists():
        return out
    for p in apps_dir.glob("*.md"):
        md = frontmatter.load(p).metadata
        nad = md.get("next_action_date")
        if nad is None:
            continue
        # frontmatter may return str or date
        if isinstance(nad, str):
            try:
                nad = date.fromisoformat(nad)
            except ValueError:
                continue
        if nad <= cutoff:
            out.append({"file": p.name, **md})
    out.sort(key=lambda r: r["next_action_date"])
    return out
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/applications/ -v
```

Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add compass/applications/ tests/applications/
git commit -m "feat(applications): lifecycle CRUD — add_application, update_status, list_pending"
```

---

## Task 8: Greenhouse + Lever `remote` field parsing

**Files:**
- Create: `compass/scrapers/_remote_parser.py`
- Modify: `compass/scrapers/greenhouse.py`, `compass/scrapers/lever.py`
- Test: `tests/scrapers/test_remote_parser.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/scrapers/test_remote_parser.py
import pytest
from compass.scrapers._remote_parser import infer_remote_policy


@pytest.mark.parametrize("loc,expected", [
    ("Remote", True),
    ("Remote - US", True),
    ("Remote, US", True),
    ("US Remote", True),
    ("Anywhere", True),
    ("Work from home", True),
    ("WFH", True),
    ("Hybrid", None),
    ("Hybrid - SF", None),
    ("San Francisco", False),
    ("New York, NY", False),
    ("San Francisco, CA or Remote", True),
    (None, None),
    ("", None),
    ("Remote AL", None),  # ambiguous: Alabama; conservative None
    ("Remote (United States)", True),
])
def test_infer_remote_policy(loc, expected):
    assert infer_remote_policy(loc) is expected
```

- [ ] **Step 2: Run — expect failure**

- [ ] **Step 3: Implement**

```python
# compass/scrapers/_remote_parser.py
"""Substring-based remote-policy parser for ATS location strings.

Greenhouse + Lever encode remote in the human-readable location field rather
than a typed flag (Ashby has its own `isRemote` boolean — handled separately).

Conservative on purpose: ambiguous strings return None ("don't know") rather
than guessing. We'd rather have JobNote.remote=None than a wrong True/False.
"""
from __future__ import annotations

import re

_TRUE_TOKENS = [
    "remote - us", "remote, us", "us remote", "remote (united states)",
    "anywhere", "work from home", "wfh", "fully remote", "100% remote",
    "remote-us", "us-remote", "or remote", "remote position",
]
_TRUE_STANDALONE = re.compile(r"\bremote\b", re.IGNORECASE)
_FALSE_TOKENS = [
    "san francisco", "new york", "nyc", "los angeles", "seattle", "boston",
    "austin", "chicago", "atlanta", "london", "paris", "berlin", "toronto",
    "palo alto", "mountain view", "menlo park", "cambridge",
]
_AMBIGUOUS = ["hybrid"]
_AMBIGUOUS_REMOTE_GEO = re.compile(r"^remote\s+[a-z]{2}\b", re.IGNORECASE)  # "Remote AL" = Alabama


def infer_remote_policy(location: str | None) -> bool | None:
    if location is None:
        return None
    s = location.strip()
    if not s:
        return None
    lower = s.lower()

    if any(a in lower for a in _AMBIGUOUS):
        return None

    if _AMBIGUOUS_REMOTE_GEO.match(s):
        return None

    if any(t in lower for t in _TRUE_TOKENS):
        return True

    # Standalone "remote" (with optional surrounding whitespace/punctuation)
    if _TRUE_STANDALONE.search(lower):
        # If a known city ALSO appears AND no "or remote" disjunction, be cautious
        if any(f in lower for f in _FALSE_TOKENS):
            if "or remote" in lower or "remote or" in lower:
                return True
            return None
        return True

    if any(f in lower for f in _FALSE_TOKENS):
        return False

    return None
```

- [ ] **Step 4: Wire into Greenhouse scraper**

`compass/scrapers/greenhouse.py:63-74` is the `RawJob(...)` construction. Two changes:

1. Extract the location string into a local variable so it can be reused (currently inlined as a long expression on line 68):

```python
# Replace lines 63-74 with:
        location_str = (raw.get("location") or {}).get("name") if raw.get("location") else None
        return RawJob(
            company=board_token,
            title=raw["title"],
            url=raw["absolute_url"],
            source="greenhouse",
            location=location_str,
            remote=infer_remote_policy(location_str),
            salary_min=None,
            salary_max=None,
            description=description,
            date_posted=_parse_date(raw.get("updated_at")),
        )
```

2. Add the import at module top: `from compass.scrapers._remote_parser import infer_remote_policy`.

- [ ] **Step 5: Wire into Lever scraper**

`compass/scrapers/lever.py:75-84` is the `RawJob(...)` construction. The location is already in a `categories` local (line 74). Change line 80 region:

```python
# Replace lines 75-84 with:
        location_str = categories.get("location") or None
        return RawJob(
            company=company,
            title=raw["text"],
            url=raw["hostedUrl"],
            source="lever",
            location=location_str,
            remote=infer_remote_policy(location_str),
            salary_min=None,
            salary_max=None,
            description=description,
            # ... preserve any trailing fields from the original
        )
```

Add the import at module top: `from compass.scrapers._remote_parser import infer_remote_policy`.

- [ ] **Step 6: Add wiring regression tests**

```python
# Append to tests/scrapers/test_remote_parser.py
def test_greenhouse_scraper_calls_remote_parser(monkeypatch):
    """End-to-end: a Greenhouse location 'Remote - US' must produce remote=True."""
    from compass.scrapers import greenhouse

    # The internal _job_from_raw helper is where RawJob is built.
    raw = {
        "id": 1, "title": "Backend Engineer",
        "absolute_url": "https://x/1",
        "content": "Build APIs in Python.",
        "location": {"name": "Remote - US"},
        "updated_at": "2026-05-18T00:00:00Z",
    }
    # Find and call the parsing function; name varies — adjust if Greenhouse
    # uses a different private name. As of phase-0b-pipeline-mvp the helper
    # was `_job_from_raw`. Update if the executor finds a different name.
    job = greenhouse._job_from_raw(raw, board_token="x")
    assert job is not None
    assert job.remote is True


def test_lever_scraper_calls_remote_parser():
    from compass.scrapers import lever

    raw = {
        "id": 1, "text": "Frontend Engineer",
        "hostedUrl": "https://x/1",
        "descriptionPlain": "Build UI in React.",
        "categories": {"location": "San Francisco"},
    }
    job = lever._job_from_raw(raw, company="x")  # adjust name if different
    assert job is not None
    assert job.remote is False
```

**Note for executor:** the test helper names (`_job_from_raw`) are best-guess. Inspect the scraper module and use the actual private function name that constructs `RawJob`. If no such helper exists (the construction is inline in a loop), instead write a fixture-based test that monkey-patches `httpx.AsyncClient.get` to return crafted JSON and assert `remote` on the resulting `RawJob`s. Either approach satisfies the regression intent.

- [ ] **Step 7: Run — expect pass**

```bash
uv run pytest tests/scrapers/ -v
```

- [ ] **Step 8: Commit**

```bash
git add compass/scrapers/_remote_parser.py compass/scrapers/greenhouse.py compass/scrapers/lever.py tests/scrapers/test_remote_parser.py
git commit -m "feat(scrapers): parse remote policy from Greenhouse/Lever location strings"
```

---

## Task 9: MCP server — wire `add_application`, `update_application_status`, `list_pending_actions`, `tailor_resume`

**Files:**
- Modify: `compass/mcp_server/server.py`
- Test: extend `tests/test_mcp_server.py`

- [ ] **Step 1: Write failing test for MCP tool wiring**

```python
# Append to tests/test_mcp_server.py
from datetime import date


def _seed_agentco_jobnote(vault):
    from compass.vault.schemas import JobNote
    from compass.vault.writer import write_job_note
    write_job_note(JobNote(
        company="AgentCo", title="Agent Engineer",
        url="https://x/agentco-agent", source="manual",
        date_found=date(2026, 5, 10), match_score=4.5,
    ))


def test_mcp_add_application_creates_note(temp_vault):
    """The MCP tool wraps lifecycle.add_application — exercising it end-to-end
    via the MCP registration confirms wiring."""
    from compass.mcp_server.server import add_application

    _seed_agentco_jobnote(temp_vault)
    result = add_application(job_id="AgentCo-Agent_Engineer")

    assert "error" not in result
    assert result["company"] == "AgentCo"
    assert result["status"] == "applied"
    assert any((temp_vault / "applications").glob("*AgentCo*.md"))


def test_mcp_add_application_unknown_job_returns_error(temp_vault):
    from compass.mcp_server.server import add_application

    result = add_application(job_id="not-a-real-job")
    assert "error" in result
    assert "no JobNote matched" in result["error"]


def test_mcp_update_application_status_valid_transition(temp_vault):
    from compass.mcp_server.server import add_application, update_application_status

    _seed_agentco_jobnote(temp_vault)
    app = add_application(job_id="AgentCo")
    today_iso = date.today().isoformat()

    result = update_application_status(
        app_id=f"{today_iso}-AgentCo",
        status="screen",
        next_action="prep recruiter call",
        next_action_date="2026-05-25",
    )
    assert "error" not in result
    assert result["status"] == "screen"
    assert result["next_action"] == "prep recruiter call"


def test_mcp_update_application_status_invalid_transition(temp_vault):
    from compass.mcp_server.server import add_application, update_application_status

    _seed_agentco_jobnote(temp_vault)
    add_application(job_id="AgentCo")
    today_iso = date.today().isoformat()

    # applied → offer is invalid; must go via screen → onsite first
    result = update_application_status(app_id=f"{today_iso}-AgentCo", status="offer")
    assert "error" in result
    assert "invalid transition" in result["error"]


def test_mcp_list_pending_actions_returns_due_rows(temp_vault):
    from compass.mcp_server.server import (
        add_application, update_application_status, list_pending_actions,
    )

    _seed_agentco_jobnote(temp_vault)
    add_application(job_id="AgentCo")
    today_iso = date.today().isoformat()
    update_application_status(
        app_id=f"{today_iso}-AgentCo",
        status="screen",
        next_action="follow up",
        next_action_date=today_iso,
    )

    pending = list_pending_actions(through_date=today_iso)
    assert len(pending) == 1
    assert pending[0]["company"] == "AgentCo"


def test_mcp_list_pending_filters_future_dates(temp_vault):
    from compass.mcp_server.server import (
        add_application, update_application_status, list_pending_actions,
    )

    _seed_agentco_jobnote(temp_vault)
    add_application(job_id="AgentCo")
    today_iso = date.today().isoformat()
    update_application_status(
        app_id=f"{today_iso}-AgentCo", status="screen",
        next_action_date="2099-01-01",
    )

    pending = list_pending_actions(through_date=today_iso)
    assert pending == []


async def test_mcp_tailor_resume_reads_existing_paragraph(temp_vault):
    """tailor_resume returns the already-computed tailored_paragraph from the
    JobNote frontmatter. It does NOT re-run the LLM."""
    from compass.vault.schemas import JobNote
    from compass.vault.writer import write_job_note
    from compass.mcp_server.server import tailor_resume

    write_job_note(JobNote(
        company="AgentCo", title="Agent Engineer", url="https://x/agentco-agent",
        source="manual", date_found=date(2026, 5, 10), match_score=4.5,
        tailored_paragraph="Lead with MCP project in a prior role.",
    ))
    result = await tailor_resume(job_id="AgentCo-Agent_Engineer")
    assert "error" not in result
    assert result["tailored_paragraph"] == "Lead with MCP project in a prior role."
```

- [ ] **Step 2: Implement — replace the TODO comment block at server.py:214**

```python
@mcp.tool()
def add_application(job_id: str, resume_variant: str = "resume.md", referral: bool = False) -> dict:
    """Create an ApplicationNote linked to a JobNote. Marks the JobNote as applied.

    job_id: substring of the JobNote filename (e.g. 'AgentCo-Agent_Engineer') or
            the JobNote's url field. Raises if zero or >1 match.
    """
    from compass.applications.lifecycle import add_application as _add
    try:
        note = _add(job_id, resume_variant=resume_variant, referral=referral)
    except LookupError as e:
        return {"error": str(e)}
    return note.model_dump(mode="json")


@mcp.tool()
def update_application_status(
    app_id: str,
    status: str,
    next_action: str | None = None,
    next_action_date: str | None = None,
    clear_next_action: bool = False,
    clear_next_action_date: bool = False,
    force: bool = False,
) -> dict:
    """Transition an application's status. Refuses invalid transitions unless force=True.

    Next-action fields use explicit clear flags because MCP can't transmit a
    Python sentinel. To CLEAR an existing next_action or next_action_date,
    pass clear_next_action=True or clear_next_action_date=True. Passing the
    bare arg with no value (None) preserves the existing field.
    """
    from datetime import date as _date
    from compass.applications.lifecycle import _UNSET
    from compass.applications.lifecycle import update_application_status as _upd

    if clear_next_action:
        na: object = None
    elif next_action is not None:
        na = next_action
    else:
        na = _UNSET

    if clear_next_action_date:
        nad: object = None
    elif next_action_date is not None:
        try:
            nad = _date.fromisoformat(next_action_date)
        except ValueError as e:
            return {"error": f"invalid next_action_date: {e}"}
    else:
        nad = _UNSET

    try:
        note = _upd(app_id, status, next_action=na, next_action_date=nad, force=force)
    except (LookupError, ValueError) as e:
        return {"error": str(e)}
    return note.model_dump(mode="json")


@mcp.tool()
def list_pending_actions(through_date: str | None = None) -> list[dict]:
    """Return ApplicationNotes whose next_action_date <= through_date (default: today)."""
    from datetime import date as _date
    from compass.applications.lifecycle import list_pending_actions as _pending
    cutoff = _date.fromisoformat(through_date) if through_date else None
    return _pending(cutoff)


@mcp.tool()
async def tailor_resume(job_id: str) -> dict:
    """Return tailoring suggestions for a specific JobNote. Reads existing
    tailored_paragraph if present, otherwise runs tailor_node on demand."""
    from pathlib import Path
    from compass.applications.lifecycle import find_jobnote  # public
    import frontmatter

    try:
        path: Path = find_jobnote(job_id)
    except LookupError as e:
        return {"error": str(e)}
    md = frontmatter.load(path).metadata
    return {
        "company": md["company"], "title": md["title"],
        "tailored_paragraph": md.get("tailored_paragraph") or "(not yet tailored — re-run pipeline with score >= threshold)",
        "skills_matched": md.get("skills_matched", []),
        "skills_missing": md.get("skills_missing", []),
    }
```

Delete the TODO comment block at lines 213–218.

- [ ] **Step 3: Run — expect pass**

```bash
uv run pytest tests/test_mcp_server.py -v
```

- [ ] **Step 4: Commit**

```bash
git add compass/mcp_server/server.py tests/test_mcp_server.py
git commit -m "feat(mcp): expose application lifecycle tools (add/update/list/tailor)"
```

---

## Task 10: Dashboard rewrite

**Files:**
- Modify: `~/Documents/compass-vault/dashboard.md`

This task is human-verified (Obsidian Dataview renders aren't automatable from pytest). The plan executor writes the file; the candidate verifies in Obsidian.

- [ ] **Step 1: Read the existing dashboard.md**

```bash
cat ~/Documents/compass-vault/dashboard.md
```

- [ ] **Step 2: Replace with the Phase 1.A dashboard**

```markdown
# Compass Dashboard

> Open in Obsidian with Dataview enabled. All queries are Dataview-DQL.

## ⭐ Apply now — top 5 unactioned

```dataview
TABLE WITHOUT ID
  file.link AS Role,
  company AS Company,
  role_family AS Family,
  match_score AS Score,
  location AS Loc
FROM "jobs"
WHERE tier = "apply-now" AND (status = "new" OR !status)
SORT match_score DESC
LIMIT 5
```

## 🟢 In-flight applications (by stage)

```dataview
TABLE WITHOUT ID
  file.link AS App,
  company AS Company,
  title AS Role,
  status AS Stage,
  next_action AS "Next Action",
  next_action_date AS Due
FROM "applications"
WHERE status != "rejected" AND status != "withdrawn" AND status != "accepted" AND status != "declined"
SORT next_action_date ASC
```

## 🔔 Today's next actions

```dataview
TABLE WITHOUT ID
  file.link AS App,
  company AS Company,
  next_action AS Action,
  next_action_date AS Due
FROM "applications"
WHERE next_action_date AND next_action_date <= date(today)
SORT next_action_date ASC
```

## 🎯 Top gaps this week

→ [[study-plans/master-gap-plan]]

```dataview
TABLE WITHOUT ID
  file.link AS Skill,
  my_level AS "Lvl",
  appears_in_jobs AS "JDs",
  gap_score AS Gap
FROM "skills"
WHERE gap_score > 0.1
SORT gap_score DESC
LIMIT 10
```

## 🌱 Stretch roles (in-scope, not ready yet)

```dataview
TABLE WITHOUT ID
  file.link AS Role,
  company AS Company,
  match_score AS Score,
  skills_missing AS Missing
FROM "jobs"
WHERE role_family != "" AND role_family != "out-of-scope"
  AND match_score < 3.5 AND match_score > 0
  AND (status = "new" OR !status)
SORT match_score DESC
LIMIT 10
```

## 📊 Pipeline activity (last 7 days)

```dataview
TABLE WITHOUT ID
  file.link AS Role,
  company AS Company,
  role_family AS Family,
  match_score AS Score,
  date_found AS Found
FROM "jobs"
WHERE date_found >= date(today) - dur(7 days)
SORT match_score DESC
```

## Observability

- Langfuse: http://localhost:3000 (Phase 1.B will wire traces)
- Master gap plan: [[study-plans/master-gap-plan]]
- Filtered-out JDs: [[_meta/filtered-jobs]]
- Unknown skills queue: [[_meta/unknown-skills-log]]
```

- [ ] **Step 3: Open in Obsidian; visually confirm every panel renders ≥ 1 row from real data**

This is the eyeball step. If any panel shows `(empty)` after a recent pipeline run, the query is wrong (or the data isn't there). Fix the query, not the data.

- [ ] **Step 4: Commit**

```bash
# The dashboard.md lives in compass-vault, not the repo — commit it in the vault repo if the candidate versions the vault, otherwise just note it.
git add ~/Documents/compass-vault/dashboard.md 2>/dev/null || echo "(vault is not git-tracked; dashboard rewrite is a non-repo change)"
```

If the vault is not versioned, this task lives outside repo commits.

---

## Task 11: Live-LLM smoke + adversarial verification

**Files:** none (verification only)

- [ ] **Step 1: Confirm green tests + lint**

```bash
uv run pytest -q
uv run ruff check compass tests && uv run ruff format --check compass tests
```

Expected: all green.

- [ ] **Step 2: Run the pipeline on the apply-now board set**

```bash
MAX_JOBS_PER_RUN=20 \
  GREENHOUSE_BOARDS=anthropic,docco,searchco,voiceco \
  ASHBY_BOARDS=agentco,botco,ramp \
  uv run python -m compass.pipeline.graph
```

- [ ] **Step 3: Inspect 10 random JobNotes**

```bash
ls ~/Documents/compass-vault/jobs/ | shuf -n 10 | while read f; do
  echo "=== $f ==="
  head -25 ~/Documents/compass-vault/jobs/$f
done
```

Every one should be a role the candidate would conceivably want. For each: is `role_family` plausible? Is `tier` correct? Is `skills_matched` real?

- [ ] **Step 4: Spot-check `_meta/filtered-jobs.md`**

```bash
tail -20 ~/Documents/compass-vault/_meta/filtered-jobs.md
```

Every dropped row should be obviously out of scope. If you see an agentic-eng role in here, the classifier is wrong — surface to the candidate.

- [ ] **Step 5: Manual application workflow**

In Claude Code:
```
Use the compass MCP add_application tool to apply to <a JobNote that appeared in the run>.
Then transition it through screen → onsite using update_application_status.
Verify the linked JobNote's status updates in Obsidian.
```

- [ ] **Step 6: Edit a CompanyNote in Obsidian + re-run pipeline**

Pick any CompanyNote with tier=`unknown`. Edit the frontmatter to `tier: apply-now`. Save. Re-run pipeline. Open the CompanyNote — tier should still be `apply-now` (the merge logic preserves human edits). New JobNotes for that company should also inherit `tier: apply-now` (the target_companies lookup hits first, but the CompanyNote merge logic preserves user edits — they don't conflict because the lookup reads the same canonical source).

- [ ] **Step 7: Open `dashboard.md` in Obsidian**

Every Dataview block renders ≥ 1 row. No `(empty)` panels.

- [ ] **Step 8: Cut the phase tag**

Only if all 6 verification steps pass:

```bash
git tag -a phase-1a-application-tracking -m "Phase 1.A complete — role-family gate, application lifecycle, dashboard"
git status   # expected: clean
```

Update `docs/STATUS.md` and `docs/ROADMAP.md` reflecting Phase 1.A done. Write `docs/PHASE_1A_COMPLETE.md` using `PHASE_0_COMPLETE.md` as template — include any silent bugs found during verification.

---

## Critical lesson from Phase 0 (apply here too)

**Tests check shape. Smoke tests check counts. Neither catches data-correctness bugs on real inputs.** Phase 0.B found 23 silent bugs across 4 audit passes. The right test of "ready" is data inspection on real outputs.

In Phase 1.A specifically, after the role-family gate lands:

- Read 10 random JobNotes — does every one feel in-scope?
- Read 10 random entries in `_meta/filtered-jobs.md` — are any of them false-negatives (agentic-eng roles wrongly dropped)?
- Apply to 3 real companies via MCP, transition through statuses, verify mirroring on JobNotes.
- Edit a CompanyNote in Obsidian, re-run, verify edits preserved.
- Open dashboard — every panel renders ≥ 1 row.

If any of those fail, **the phase is not done**, even if pytest is green.

---

## Risk table (carried forward from spec — kept here for the executor)

| Risk | Mitigation |
|---|---|
| Classifier false-negative drops a real role | Inclusion-biased prompt; `_meta/filtered-jobs.md` review queue; Task 11 manual inspection |
| Classifier cost runs hot | Stage-1 keyword filter catches majority; only borderline titles hit LLM |
| `target-companies.md` parser breaks on unusual table format | Parser is defensive (skips malformed rows); test fixture covers edge cases |
| Removing SCORE_THRESHOLD floods vault with low-score JDs | Acceptable — gap aggregator's `score_factor` zeros 0.0-score contribs and weights real scores proportionally. Role-family gate has already removed sales/PM/design noise upstream. |
| `infer_remote_policy` over-matches | Conservative on ambiguous; returns None rather than guessing |

---

**End of Phase 1.A plan.** ~11 tasks · ~6 new files · ~400 LoC production · ~350 LoC tests · estimated 1 build session.
