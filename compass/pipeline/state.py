"""
Compass pipeline state schema.
All nodes receive the full state and return partial updates — only return keys you changed.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, TypedDict

from pydantic import BaseModel, Field

Source = Literal["greenhouse", "lever", "ashby", "workday", "jobspy", "smoke", "manual"]
Seniority = Literal["junior", "mid", "senior", "staff", "unknown"]
RemotePolicy = Literal["remote", "hybrid", "onsite", "unknown"]


class RawJob(BaseModel):
    """Normalized job posting from any ATS source."""

    company: str
    title: str
    url: str
    source: Source
    location: str | None = None
    remote: bool | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    description: str
    date_posted: date | None = None


class JobRequirements(BaseModel):
    """Structured extraction from a job description."""

    required_skills: list[str]
    nice_to_have_skills: list[str]
    years_experience: int | None = None
    seniority: Seniority
    remote_policy: RemotePolicy
    summary: str


class JobScore(BaseModel):
    """LLM-generated match score for a job against the candidate profile."""

    score: float = Field(ge=0.0, le=5.0)  # constrained; out-of-range = retry
    reasoning: str
    matched_skills: list[str]
    missing_skills: list[str]
    tailoring_notes: str
    # JD-quote grounding for matched/missing skills. Key = skill name (exact form
    # used in matched_skills / missing_skills), value = verbatim 5–15 word JD
    # phrase that justifies the classification. Optional and defaults to empty
    # for backwards-compat with pre-existing serialized JobScore records on disk.
    evidence: dict[str, str] = Field(default_factory=dict)


class CompassState(TypedDict):
    """Full pipeline state passed between all LangGraph nodes."""

    raw_jobs: list[RawJob]

    current_job: RawJob | None
    extracted_requirements: JobRequirements | None
    score_result: JobScore | None

    in_scope: bool | None
    role_family: str | None
    # Count of distinct agent-related terms hit in the JD body by intake_filter.
    # 0 means the body has no agentic signal (and the role was likely dropped
    # for that reason if the title was agent-oriented). 1+ means real signal.
    # Used by vault_write_node to emit a `#signal/agent-strong|mention` tag.
    agent_signal_count: int | None

    human_approved: bool | None
    human_feedback: str | None
    tailored_paragraph: str | None

    vault_written: bool
    # Absolute path of the JobNote written for this job, when one was written.
    # Set by `vault_write_node` so callers (MCP server, tests, audit log) can
    # reference the real file rather than re-deriving the path.
    vault_note_path: str | None
    jobs_processed: int
    jobs_written: int

    errors: list[str]

    thread_id: str | None

    score_threshold: float | None
