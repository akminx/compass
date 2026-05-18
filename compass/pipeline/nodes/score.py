"""
score_node — score a job against the candidate profile.

Reads resume.md + skill-inventory.md from the vault and passes them as context
to the LLM. Returns a JobScore (0.0–5.0) with matched/missing/tailoring breakdown.

Model: SCORE_MODEL (default google/gemini-2.5-flash).
"""

from __future__ import annotations

import logging

from compass.llm import make_agent
from compass.pipeline.state import CompassState, JobRequirements, JobScore
from compass.vault.reader import read_resume, read_skill_inventory

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You score a job description against a candidate's profile.

Score 0.0–5.0:
- 5.0 = perfect match, candidate has every required skill at production level
- 4.0 = strong match, candidate has ~80% of required skills with real evidence
- 3.0 = decent match, candidate has core skills but missing some required ones
- 2.0 = stretch, candidate has adjacent skills but lacks several required ones
- 1.0 = poor match, fundamental skill gaps
- 0.0 = wrong field entirely

Be honest. Score conservatively when evidence is conceptual rather than shipped.

Return a JobScore with:
- score: float 0.0–5.0
- reasoning: 2–3 sentences justifying the score
- matched_skills: skills from the JD's required+nice-to-have list that the candidate has (level >= 2)
- missing_skills: skills from the JD's required+nice-to-have list that the candidate lacks (level < 2)
- tailoring_notes: ONE sentence suggesting how to frame the application (skip if score < 3.0)

HARD CONSTRAINTS on matched_skills and missing_skills:
1. Every skill in matched_skills MUST appear in the JD's required or nice_to_have list. Do NOT list skills from the candidate's profile that the JD did not ask for.
2. Every skill in missing_skills MUST appear in the JD's required or nice_to_have list. Do NOT list every skill in the canonical taxonomy that the candidate lacks.
3. The union (matched_skills ∪ missing_skills) MUST be a subset of the JD's required ∪ nice_to_have lists.
4. If the JD has no required or nice_to_have skills, matched_skills and missing_skills MUST both be empty lists.

Use the EXACT skill names from the JD's required/nice_to_have lists (don't paraphrase).
"""


def _build_agent():
    return make_agent("score", output_type=JobScore, system_prompt=_SYSTEM_PROMPT)


def _format_prompt(req: JobRequirements, profile_text: str) -> str:
    return (
        f"# CANDIDATE PROFILE\n{profile_text}\n\n"
        f"# JOB REQUIREMENTS\n"
        f"required: {', '.join(req.required_skills) or '(none)'}\n"
        f"nice-to-have: {', '.join(req.nice_to_have_skills) or '(none)'}\n"
        f"years_experience: {req.years_experience}\n"
        f"seniority: {req.seniority}\n"
        f"remote_policy: {req.remote_policy}\n"
        f"summary: {req.summary}\n"
    )


async def _score(req: JobRequirements, profile_text: str) -> JobScore:
    """The LLM call. Tests monkeypatch this wrapper rather than the underlying Agent."""
    agent = _build_agent()
    result = await agent.run(_format_prompt(req, profile_text))
    return result.output


def _profile_text() -> str:
    return f"## RESUME\n{read_resume()}\n\n## SKILL INVENTORY\n{read_skill_inventory()}"


async def score_node(state: CompassState) -> dict:
    req = state.get("extracted_requirements")
    if req is None:
        return {
            "score_result": None,
            "errors": [*state.get("errors", []), "score_node: extracted_requirements is None"],
        }

    try:
        result = await _score(req, _profile_text())
    except Exception as e:
        logger.warning("score_node: LLM call failed — %s", e)
        return {
            "score_result": None,
            "errors": [*state.get("errors", []), f"score_node: {e}"],
        }

    return {"score_result": _constrain_to_jd_skills(result, req)}


def _constrain_to_jd_skills(score: JobScore, req: JobRequirements) -> JobScore:
    """Defense in depth: drop matched/missing skills the JD didn't actually ask for.

    The score prompt forbids the LLM from inventing matched/missing skills
    outside the JD's required+nice_to_have lists. This is the post-hoc filter
    that enforces the same constraint at code-level — so a prompt-following
    failure can't pollute the gap_aggregator with skills the JD never required.
    """
    jd_universe = set(req.required_skills) | set(req.nice_to_have_skills)
    filtered_matched = [s for s in score.matched_skills if s in jd_universe]
    filtered_missing = [s for s in score.missing_skills if s in jd_universe]
    dropped = (set(score.matched_skills) | set(score.missing_skills)) - jd_universe
    if dropped:
        logger.info(
            "score_node: dropped %d skills not in JD universe (LLM ignored prompt constraint): %s",
            len(dropped),
            sorted(dropped),
        )
    return score.model_copy(
        update={"matched_skills": filtered_matched, "missing_skills": filtered_missing}
    )
