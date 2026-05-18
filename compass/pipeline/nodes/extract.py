"""
extract_node — Pydantic AI structured extraction of JobRequirements from JD text.

Skill normalization: every extracted skill is mapped to its canonical name via
compass.vault.taxonomy.normalize(). Unknown skills are dropped from the
requirements (so downstream gap_aggregator doesn't count noise) BUT recorded to
compass-vault/_meta/unknown-skills-log.md so the user can review weekly and
decide to graduate them to canonical, add as synonyms, or ignore.

Model: EXTRACT_MODEL (default google/gemini-2.5-flash). Routed via compass.llm.
"""

from __future__ import annotations

import logging
from datetime import datetime

from compass.config import VAULT_PATH
from compass.llm import make_agent
from compass.pipeline.state import CompassState, JobRequirements
from compass.vault.taxonomy import normalize

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You extract structured requirements from a job description.

Return a JobRequirements with:
- required_skills: technical skills the JD explicitly requires (frameworks, languages, tools).
- nice_to_have_skills: technical skills the JD lists as preferred/bonus.
- years_experience: minimum years stated, or null if not stated.
- seniority: one of junior | mid | senior | staff | unknown.
- remote_policy: one of remote | hybrid | onsite | unknown.
- summary: one short paragraph (~2 sentences) of what the role does.

Only include genuinely technical skills (not soft skills, not credentials, not industries).
"""


def _build_agent():
    return make_agent("extract", output_type=JobRequirements, system_prompt=_SYSTEM_PROMPT)


async def _extract(jd_text: str) -> JobRequirements:
    """The LLM call. Tests monkeypatch this wrapper rather than the underlying Agent."""
    agent = _build_agent()
    result = await agent.run(jd_text)
    return result.output


def _normalize_skill_list(skills: list[str], unknown_sink: list[str] | None = None) -> list[str]:
    """Map each raw skill to canonical; drop unknowns but record them for later review.

    Unknown skills are appended to `unknown_sink` (if provided) so the caller can
    persist them to the unknown-skills log for weekly review.
    """
    out: list[str] = []
    for raw in skills:
        canon = normalize(raw)
        if canon is None:
            logger.info("extract: unknown skill %r (not in canonical taxonomy)", raw)
            if unknown_sink is not None:
                unknown_sink.append(raw)
            continue
        if canon not in out:
            out.append(canon)
    return out


def _record_unknown_skills(skills: list[str], job_url: str) -> None:
    """Append seen unknown skills to compass-vault/_meta/unknown-skills-log.md.

    Format is a plain markdown log so the user can scan it weekly and decide
    whether to (a) graduate to canonical, (b) add as a synonym to an existing
    canonical, or (c) ignore.
    A separate helper script can aggregate frequencies — out of scope for 0.B.
    """
    if not skills:
        return
    log_path = VAULT_PATH / "_meta" / "unknown-skills-log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.write_text(
            "# Unknown Skills Log\n\n"
            "Skills seen in scraped JDs that don't match a canonical entry in "
            "`_meta/skill-taxonomy.md`. Review weekly; either add to canonical, "
            "add as a synonym to an existing canonical, or ignore.\n\n"
            "Format: `[ISO timestamp] skill_name (from job_url)`\n\n---\n\n",
            encoding="utf-8",
        )
    now = datetime.now().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as f:
        for skill in skills:
            f.write(f"[{now}] {skill}  (from {job_url})\n")


async def extract_node(state: CompassState) -> dict:
    """Extract JobRequirements from state.current_job.description."""
    job = state.get("current_job")
    if job is None:
        return {
            "extracted_requirements": None,
            "errors": [*state.get("errors", []), "extract_node: current_job is None"],
        }

    try:
        raw_req = await _extract(job.description)
    except Exception as e:
        logger.warning("extract_node: LLM call failed for %s — %s", job.url, e)
        return {
            "extracted_requirements": None,
            "errors": [*state.get("errors", []), f"extract_node: {e}"],
        }

    unknown: list[str] = []
    normalized = JobRequirements(
        required_skills=_normalize_skill_list(raw_req.required_skills, unknown),
        nice_to_have_skills=_normalize_skill_list(raw_req.nice_to_have_skills, unknown),
        years_experience=raw_req.years_experience,
        seniority=raw_req.seniority,
        remote_policy=raw_req.remote_policy,
        summary=raw_req.summary,
    )
    if unknown:
        _record_unknown_skills(unknown, job.url)
    return {"extracted_requirements": normalized}
