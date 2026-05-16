"""
Compass pipeline state schema.
All nodes receive the full state and return partial updates — only return keys you changed.
"""
from typing import TypedDict, Optional
from pydantic import BaseModel
from datetime import date


class RawJob(BaseModel):
    """Normalized job posting from any ATS source."""
    company: str
    title: str
    url: str
    source: str  # greenhouse | lever | ashby | jobspy
    location: Optional[str] = None
    remote: Optional[bool] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    description: str
    date_posted: Optional[date] = None


class JobRequirements(BaseModel):
    """Structured extraction from a job description."""
    required_skills: list[str]
    nice_to_have_skills: list[str]
    years_experience: Optional[int] = None
    seniority: str  # junior | mid | senior | staff | unknown
    remote_policy: str  # remote | hybrid | onsite | unknown
    summary: str  # one paragraph


class JobScore(BaseModel):
    """LLM-generated match score for a job against the candidate profile."""
    score: float  # 0.0 – 5.0
    reasoning: str
    matched_skills: list[str]
    missing_skills: list[str]
    tailoring_notes: str


class CompassState(TypedDict):
    """Full pipeline state passed between all LangGraph nodes."""
    # Input
    raw_jobs: list[RawJob]

    # Per-job processing (one job at a time)
    current_job: Optional[RawJob]
    extracted_requirements: Optional[JobRequirements]
    score_result: Optional[JobScore]

    # Human-in-the-loop
    human_approved: Optional[bool]
    human_feedback: Optional[str]

    # Output tracking
    vault_written: bool
    jobs_processed: int
    jobs_written: int

    # Error accumulation
    errors: list[str]
