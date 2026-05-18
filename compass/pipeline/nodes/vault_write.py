"""
vault_write_node — persist a scored job to the compass vault.

Writes three things:
1. JobNote -> jobs/YYYY-MM-DD-Company-Title.md (idempotent on URL via write_job_note)
2. Increments appears_in_jobs on each skill the JD requires (via update_skill_note)
3. Upserts companies/Company.md (via write_company_note)

All skills passed downstream are already canonical (extract_node normalized them).
This node never normalizes — if a non-canonical skill appears here, that's an
upstream bug.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from compass.config import SCORE_THRESHOLD
from compass.vault.schemas import CompanyNote, JobNote
from compass.vault.writer import append_agent_log, write_company_note, write_job_note

if TYPE_CHECKING:
    from compass.pipeline.state import CompassState

logger = logging.getLogger(__name__)


async def vault_write_node(state: CompassState) -> dict:
    job = state.get("current_job")
    score = state.get("score_result")
    req = state.get("extracted_requirements")

    if job is None or score is None or req is None:
        missing = [
            n
            for n, v in [
                ("current_job", job),
                ("score_result", score),
                ("extracted_requirements", req),
            ]
            if v is None
        ]
        return {
            "vault_written": False,
            "errors": [*state.get("errors", []), f"vault_write_node: missing {missing}"],
        }

    # Threshold gate: .env documents SCORE_THRESHOLD as "only write jobs scoring
    # above this to vault". Without this check the vault fills with sales / PM /
    # designer roles that score 0.0–3.0 and clutter the daily dashboard. The
    # pipeline-runs log still records that we processed them.
    if score.score < SCORE_THRESHOLD:
        append_agent_log(
            f"vault_write skipped (below threshold {SCORE_THRESHOLD}) "
            f"{job.company} {job.title} score={score.score}"
        )
        logger.info(
            "vault_write: skipping %s — %s (score=%.1f < threshold=%.1f)",
            job.company,
            job.title,
            score.score,
            SCORE_THRESHOLD,
        )
        return {"vault_written": False}

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
        skills_required=req.required_skills,
        skills_nice_to_have=req.nice_to_have_skills,
        skills_matched=score.matched_skills,
        skills_missing=score.missing_skills,
        jd_summary=req.summary,
        tailored_paragraph=state.get("tailored_paragraph"),
    )
    write_job_note(note, full_description=job.description)

    # Skill counters are derived data — gap_aggregator._sync_skill_counters()
    # recomputes them from JobNote frontmatter at end of each run. We do NOT
    # call update_skill_note here because that accumulated incorrectly on
    # job overwrites (every pipeline rerun used to inflate the counter).

    # TODO(Phase 1.A): read company tier from target-companies.md instead of "unknown".
    # `write_company_note` is idempotent, so roles_seen=1 currently never increments;
    # Phase 1.A application-tracking will rewire this to read-merge-write properly.
    write_company_note(CompanyNote(company=job.company, tier="unknown", roles_seen=1))

    return {
        "vault_written": True,
        "jobs_written": state.get("jobs_written", 0) + 1,
    }
