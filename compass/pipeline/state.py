"""
Compass pipeline state schema.
All nodes receive the full state and return partial updates — only return keys you changed.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, TypedDict

from pydantic import BaseModel

Source = Literal["greenhouse", "lever", "ashby", "jobspy", "smoke", "manual"]
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
    score: float  # 0.0 – 5.0
    reasoning: str
    matched_skills: list[str]
    missing_skills: list[str]
    tailoring_notes: str


class CompassState(TypedDict):
    """Full pipeline state passed between all LangGraph nodes."""
    raw_jobs: list[RawJob]

    current_job: RawJob | None
    extracted_requirements: JobRequirements | None
    score_result: JobScore | None

    human_approved: bool | None
    human_feedback: str | None

    vault_written: bool
    jobs_processed: int
    jobs_written: int

    errors: list[str]
