"""
Vault frontmatter schemas — Pydantic models for every note type.
Always validate against these before writing to the vault.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Tier values must stay in sync with `_profile/preferences.md::tier_weights`.
# `6-month` is the legacy name retained for backwards-compat with existing
# JobNotes; new code should prefer the 3-month-pivot tiers (apply-now,
# opportunistic, backend-prep, stretch, skip).
Tier = Literal[
    "apply-now",
    "opportunistic",
    "backend-prep",
    "6-month",
    "stretch",
    "skip",
    "unknown",
]
SkillLevel = Literal[0, 1, 2, 3, 4, 5]
SkillCategory = Literal[
    "language",
    "llm-api",
    "agent-framework",
    "mcp",
    "prompt",
    "rag",
    "vector-db",
    "evals",
    "observability",
    "durable-execution",
    "multi-agent",
    "hitl",
    "production",
    "cloud",
    "deployment",
    "browser-use",
    "voice",
    "fine-tuning",
]
Source = Literal["greenhouse", "lever", "ashby", "jobspy", "smoke", "manual"]
HitlDecision = Literal["approved", "rejected", "auto_rejected", "timed_out"]
InterviewDifficulty = Literal[
    "hackerrank",
    "case",
    "lc-easy",
    "lc-medium",
    "lc-medium-hard",
    "lc-hard",
    "takehome",
    "unknown",
]
CiscoAdjacency = Literal["none", "low", "medium", "high"]


class JobNote(BaseModel):
    company: str
    title: str
    url: str
    source: Source
    date_found: date
    status: str = "new"
    match_score: float
    score_reasoning: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    location: str | None = None
    remote: str | None = None
    seniority: str = "unknown"
    years_required: int | None = None
    role_family: str = ""
    tier: Tier = "unknown"
    interview_difficulty: InterviewDifficulty = "unknown"
    cisco_adjacency: CiscoAdjacency = "none"
    tags: list[str] = []
    skills_required: list[str] = []
    skills_nice_to_have: list[str] = []
    skills_matched: list[str] = []
    skills_missing: list[str] = []
    jd_summary: str = ""
    tailored_paragraph: str | None = None
    hitl_decision: HitlDecision | None = None
    hitl_at: datetime | None = None
    applied_at: datetime | None = None


class TierDemand(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    apply_now: int = Field(0, alias="apply-now")
    six_month: int = Field(0, alias="6-month")
    stretch: int = 0


class SkillNote(BaseModel):
    """Frontmatter schema for skills/ notes. Maintained by skill_assessor + gap_aggregator."""

    skill: str
    category: SkillCategory
    synonyms: list[str] = []
    my_level: SkillLevel = 0
    last_assessed: datetime | None = None
    grade_override: SkillLevel | None = None
    appears_in_jobs: int = 0
    tier_demand: TierDemand = Field(default_factory=TierDemand)
    gap_score: float = 0.0
    priority: str = "medium"
    evidence: list[str] = []
    study_resources: list[str] = []
    tags: list[str] = []


class CompanyNote(BaseModel):
    company: str
    tier: Tier = "unknown"
    roles_seen: int = 0
    hiring_signal: str = "unknown"
    geo: list[str] = []
    why_interesting: str = ""
    known_stack: list[str] = []
    interview_format_notes: str = ""
    interview_difficulty: InterviewDifficulty = "unknown"
    cisco_adjacency: CiscoAdjacency = "none"
    tags: list[str] = []


class ApplicationNote(BaseModel):
    company: str
    title: str
    job_ref: str
    applied_date: date
    resume_variant: str = "resume.md"
    status: str = "applied"
    contacts: list[str] = []
    next_action: str = ""
    next_action_date: date | None = None
    referral: bool = False
    tags: list[str] = []


class SkillAssessment(BaseModel):
    """Output of skill_assessor for one skill."""

    skill: str
    proposed_level: SkillLevel
    current_level: SkillLevel
    confidence: Literal["low", "medium", "high"]
    cited_evidence: list[str]
    reasoning: str
    dissenting_view: str
    requires_hitl: bool = False


class GapPlanEntry(BaseModel):
    """One row in the master gap plan."""

    skill: str
    your_level: SkillLevel
    appears_in_jobs: int
    tier_demand: TierDemand
    gap_score: float
    suggested_next_step: str
    cheap_win: bool = False
