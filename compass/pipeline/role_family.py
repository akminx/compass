"""Role-family classifier — two stages.

Stage 1 (top): pure-string title keyword filter. Zero LLM cost.
Returns (True, family) | (False, "out-of-scope") | (None, "") where None means
"borderline; ask the LLM".

Stage 2 (bottom): a Gemini-Flash structured-output classifier called only when
stage 1 returns None. Inclusion-biased prompt per the spec.

The scope definition is Akash's, dated 2026-05-18, in PHASE_0_COMPLETE.md.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

from compass.llm import make_agent

logger = logging.getLogger(__name__)

# Title → family. ORDER MATTERS: first match wins. Put more specific phrases first.
# NOTE: "fde-eng" / "forward deployed engineer" intentionally omitted — borderline
# per spec (FDE is out of scope for now; defer to LLM stage 2 rather than hard-coding
# IN or OUT so the LLM can inspect the JD body for engineering vs. pre-sales signal).
IN_TITLE_KEYWORDS: dict[str, list[str]] = {
    "agent-engineer": [
        "agent engineer",
        "ai agent engineer",
        "agentic engineer",
        "agentic ai engineer",
        "agent platform",
        "agent orchestration",
        "agent reliability",
        "software engineer, agents",
        "software engineer - agents",
        "software engineer - agentic",
        "software engineer, agentic",
        "ai native engineer",
        # MTS = Member of Technical Staff. Frontier-startup flat-hierarchy
        # signal, not literal seniority. Sierra / Decagon / Cognition / Cursor
        # / Mistral / xAI all use it for agent-eng ICs. The MTS title alone
        # routes to agent-engineer; if the JD body is research-flavored the
        # body-signal upgrader can move it elsewhere.
        "member of technical staff",
        "mts - agents",
        "mts, agents",
    ],
    "applied-ai": [
        "applied ai",
        "applied ml",
        "ai engineer",
        "ai/ml engineer",
        "ml engineer",
        "machine learning engineer",
        "genai engineer",
        # AI Enablement = Cognition (Devin/Windsurf), Cursor — FDE-lite path
        # explicitly named in target-roles.md as in-range.
        "ai enablement engineer",
    ],
    "infra-llm": [
        "llm platform",
        "ai infrastructure",
        "ai platform engineer",
        "inference engineer",
        "eval engineer",
        "evaluation engineer",
    ],
    "research-eng": ["research engineer", "applied research engineer"],
    "devtools-ai": [
        "developer experience engineer",
        "devtools engineer",
        "developer tools engineer",
    ],
    "swe-founding": ["founding engineer", "founding software engineer", "first engineer"],
    "swe-backend": [
        "backend engineer",
        "software engineer, backend",
        "platform engineer",
        "infrastructure engineer",
    ],
    "swe-frontend": ["frontend engineer", "software engineer, frontend"],
    "swe-fullstack": [
        "fullstack engineer",
        "full-stack engineer",
        "full stack engineer",
        "product engineer",
    ],
    "swe-mobile": ["mobile engineer", "ios engineer", "android engineer"],
}

# Multi-word and word-prefix OUT keywords matched as case-insensitive substrings on the lowercased title.
OUT_SUBSTRING_KEYWORDS: list[str] = [
    # sales
    "account executive",
    "sales development",
    "sales representative",
    "account manager",
    "enterprise sales",
    "sales engineer",
    # pre-sales / solutions
    "presales",
    "pre-sales",
    "solutions engineer",
    "solution engineer",
    # NOTE: "solutions architect" intentionally NOT in this list — that title
    # straddles pre-sales and hands-on infra depending on company; the LLM
    # body-check stage decides per-JD.
    # CS
    "customer success",
    "customer experience",
    "customer support",
    "technical csm",
    # PM / product ops
    "product manager",
    "product management",
    "group pm",
    "agent pm",
    "product operations",
    "operations specialist",
    "program manager",
    # management track (Akash isn't pursuing management — per role-clarifications)
    "engineering manager",
    "engineering lead",
    "director of engineering",
    "head of engineering",
    "vp of engineering",
    "vp engineering",
    # security (separate engineering discipline, not agentic-AI)
    "security engineer",
    "application security",
    "infrastructure security",
    # design (note: "designer" is distinctive enough for substring match)
    "designer",
    "motion graphics",
    "web designer",
    "conversation designer",
    "conversational designer",
    # marketing
    "marketing",
    "growth marketer",
    "demand gen",
    "lifecycle marketing",
    # devrel
    "developer advocate",
    "developer relations",
    "devrel",
    "technical evangelist",
    # ops / HR / finance / legal
    "recruiter",
    "people operations",
    "talent acquisition",
    "human resources",
    "accountant",
    "controller",
    "operations manager",
    "legal counsel",
    "trust and safety",
    "trust & safety",
    "compliance officer",
]

# Acronyms / short tokens matched on word boundaries. Standalone occurrence required.
OUT_WORD_KEYWORDS: list[str] = ["sdr", "bdr", "csm", "ux", "brand"]
_OUT_WORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in OUT_WORD_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

AGENT_SIGNAL = [
    "agent",
    "agents",
    "agentic",
    "agentic ai",
    "tool use",
    "tool-use",
    "tool calling",
    "function calling",
    "langgraph",
    "autogen",
    "mcp",
    "model context protocol",
    "react pattern",
]
LLM_SIGNAL = [
    "llm",
    "llms",
    "large language model",
    "large language models",
    "gpt-3",
    "gpt-4",
    "gpt-5",
    "claude",
    "gemini",
    "rag",
    "retrieval-augmented",
    "embedding",
    "embeddings",
    "vector database",
    "fine-tuning",
    "prompt engineering",
    "pydantic-ai",
    "openai api",
    "anthropic api",
]
ML_SIGNAL = [
    "machine learning",
    "deep learning",
    "neural network",
    "neural networks",
    "pytorch",
    "tensorflow",
    "sklearn",
    "scikit-learn",
    "huggingface",
]

GENERIC_FAMILIES = {
    "swe-backend",
    "swe-frontend",
    "swe-fullstack",
    "swe-founding",
    "swe-mobile",
    "other-eng",
}


def _build_signal_pattern(keywords: list[str]) -> re.Pattern[str]:
    """Compile one regex matching any keyword, with longest-first preference.

    Python's regex alternation is left-priority. Sorting keywords by length DESC
    ensures `"agentic ai"` wins over `"agentic"` wins over `"agent"` on the SAME
    span — preventing the substring-overlap triple-count that promoted plain
    backend roles whenever they mentioned the phrase "agentic AI" once.

    Word boundaries (`\\b`) also auto-fix the old keyword artifacts like
    `"mcp "` (trailing space required) — `\\bmcp\\b` now matches `MCP-based`
    and `MCP.` cleanly.
    """
    sorted_kws = sorted(set(keywords), key=len, reverse=True)
    parts = [re.escape(k) for k in sorted_kws]
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.IGNORECASE)


_AGENT_RE = _build_signal_pattern(AGENT_SIGNAL)
_LLM_RE = _build_signal_pattern(LLM_SIGNAL)
_ML_RE = _build_signal_pattern(ML_SIGNAL)


def _count_distinct_phrases(body: str, pattern: re.Pattern[str]) -> int:
    """Return the number of DISTINCT lowercased phrases the pattern matches.

    `re.findall` walks left-to-right and never re-matches a consumed span, so
    "agentic AI agentic AI" returns `["agentic AI", "agentic AI"]` → 1 distinct.
    Combined with the longest-first pattern build, "agentic AI" never double-
    counts via overlapping shorter substrings ("agent", "agentic").
    """
    if not body:
        return 0
    return len({m.lower() for m in pattern.findall(body)})


def upgrade_family(family: str, body: str) -> str:
    """Promote generic engineering families to agentic specializations when the
    JD body shows enough AI/agent keyword density. Promote-only.

    Threshold of 2 distinct AGENT phrases (or 3 LLM / 2 ML) ensures multiple
    independent signals are required — a JD with a single passing mention of
    "agentic AI" no longer over-promotes.
    """
    if family not in GENERIC_FAMILIES:
        return family
    body = body or ""
    if _count_distinct_phrases(body, _AGENT_RE) >= 2:
        return "agent-engineer"
    if _count_distinct_phrases(body, _LLM_RE) >= 3:
        return "applied-ai"
    if _count_distinct_phrases(body, _ML_RE) >= 2:
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
    lower = title.lower().strip()
    if _OUT_WORD_RE.search(title):
        return (False, "out-of-scope")
    for kw in OUT_SUBSTRING_KEYWORDS:
        if kw in lower:
            return (False, "out-of-scope")
    padded = f" {lower} "  # for IN matching of substring-style keywords
    for family, kws in IN_TITLE_KEYWORDS.items():
        for kw in kws:
            if kw in padded:
                return (True, family)
    return (None, "")


# ── Stage 2: LLM classifier ──────────────────────────────────────────────────

VALID_FAMILIES = (*IN_TITLE_KEYWORDS.keys(), "fde-eng", "other-eng", "out-of-scope")


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

BIAS TOWARD INCLUSION. The cost of one extra LLM extract+score is far lower than the cost of dropping a role Akash would want to see. Classify OUT only when:
  (a) the title is in the OUT list, AND
  (b) the JD body shows zero engineering work.

When uncertain, classify IN_SCOPE with role_family="other-eng".

Output ONE line in `reason` explaining the decision (≤140 chars)."""


async def llm_classify(title: str, jd_first_500: str) -> RoleFamilyClassification:
    """Call Gemini Flash to classify a borderline title. Caller should only invoke
    when keyword_classify returned (None, ""). Cost ~$0.0005/call."""
    jd_first_500 = jd_first_500[:500]
    agent = make_agent(
        "extract",
        output_type=RoleFamilyClassification,
        system_prompt=_SYSTEM_PROMPT,
    )
    user = f"TITLE: {title}\n\nJD (first 500 chars):\n{jd_first_500}"
    result = await agent.run(user)
    out: RoleFamilyClassification = result.output
    if out.role_family not in VALID_FAMILIES:
        logger.info("role_family: model returned unknown family %r; coerced", out.role_family)
        out = out.model_copy(
            update={"role_family": "other-eng" if out.in_scope else "out-of-scope"}
        )
    return out
