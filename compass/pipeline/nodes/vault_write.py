"""
vault_write_node — persist a scored job to the compass vault.

Writes two things:
1. JobNote -> jobs/YYYY-MM-DD-Company-Title-<hash>.md (idempotent on URL via write_job_note)
2. Upserts companies/Company.md (via write_company_note, preserving human-edited tier)

Skill counters are NOT touched here — gap_aggregator._sync_skill_counters() recomputes
them from JobNote frontmatter at end of each run, which avoids double-counting on reruns.

All skills passed downstream are already canonical (extract_node normalized them).
This node never normalizes — if a non-canonical skill appears here, that's an
upstream bug.

Phase 1.A note: the SCORE_THRESHOLD write gate has been intentionally removed.
Stretch-role data (low-scoring JDs) is needed by gap_aggregator to surface the
full market skill picture. The threshold still gates tailor (Sonnet cost control)
inside hitl_node — only the vault-write gate is gone.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

from compass.vault.schemas import CompanyNote, JobNote
from compass.vault.writer import write_company_note, write_job_note

if TYPE_CHECKING:
    from compass.pipeline.state import CompassState

logger = logging.getLogger(__name__)


def _derive_hitl_decision(state: CompassState) -> tuple[str | None, datetime | None]:
    """Map state -> (hitl_decision, hitl_at). Returns (None, None) if hitl never ran."""
    from compass.config import SCORE_THRESHOLD
    from compass.hitl import HITL_TIMEOUT_FEEDBACK_PREFIX

    approved = state.get("human_approved")
    if approved is None:
        # hitl never reached (e.g. extract/score errored). Leave fields null.
        return (None, None)

    feedback = (state.get("human_feedback") or "").lower()
    score = state.get("score_result")
    score_value = score.score if score is not None else 0.0

    # Prefer state-captured threshold (sticky); fall back to config for old checkpoints.
    threshold = state.get("score_threshold")
    if threshold is None:
        threshold = SCORE_THRESHOLD

    if approved is True:
        decision = "approved"
    elif feedback.startswith(HITL_TIMEOUT_FEEDBACK_PREFIX):
        decision = "timed_out"
    elif score_value < threshold:
        decision = "auto_rejected"
    else:
        decision = "rejected"
    return (decision, datetime.now())


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

    # SCORE_THRESHOLD is intentionally NOT applied here in Phase 1.A. The threshold
    # still gates tailor (Sonnet cost control) inside hitl_node. Removing it here
    # lets stretch-role gaps drive the master gap plan — see spec § 2.

    from compass.vault.target_companies import get_tier

    # JobNote.tier is a per-posting snapshot — always use the currently-resolved
    # tier so a later edit to target-companies.md doesn't retroactively change
    # what the snapshot said when the job was first seen.
    company_tier = get_tier(job.company)

    # CompanyNote.tier — read-before-write to preserve human edits in Obsidian.
    # If an existing CompanyNote has a non-default tier, pass "unknown" on
    # write_company_note so its merge logic preserves the existing tier.
    # (writer.py only preserves when incoming.tier == "unknown".)
    # Bug #15 (Phase 0) regression guard.
    import frontmatter as _fm

    import compass.config as _cfg

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

    hitl_decision, hitl_at = _derive_hitl_decision(state)
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
        hitl_decision=hitl_decision,
        hitl_at=hitl_at,
    )
    write_job_note(note, full_description=job.description)

    # Skill counters are derived data — gap_aggregator._sync_skill_counters()
    # recomputes them from JobNote frontmatter at end of each run. We do NOT
    # call update_skill_note here because that accumulated incorrectly on
    # job overwrites (every pipeline rerun used to inflate the counter).

    # roles_seen is intentionally 0 — gap_aggregator._sync_company_counters
    # derives it from len(JobNotes for company) at end of run. See writer.py:117.
    write_company_note(CompanyNote(company=job.company, tier=company_tier_for_write, roles_seen=0))

    return {
        "vault_written": True,
        "jobs_written": state.get("jobs_written", 0) + 1,
    }
