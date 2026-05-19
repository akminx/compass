"""
score_node — score a job against the candidate profile.

Reads resume.md + skill-inventory.md from the vault and passes them as context
to the LLM. Returns a JobScore (0.0–5.0) with matched/missing/tailoring breakdown.

Model: SCORE_MODEL (default google/gemini-2.5-flash).
"""

from __future__ import annotations

import logging

from compass.config import SCORE_THRESHOLD
from compass.llm import make_agent
from compass.pipeline.state import CompassState, JobRequirements, JobScore
from compass.rag.retriever import retrieve as rag_retrieve
from compass.vault.reader import read_resume

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
    # Tests patch this function; the underlying pydantic-ai Agent is harder to stub.
    agent = _build_agent()
    result = await agent.run(_format_prompt(req, profile_text))
    return result.output


def _reasoning_complete(text: str) -> bool:
    """Gemini Flash occasionally streams a truncated reasoning string that ends
    mid-clause (e.g. "...entirely outside the candidate"). The structured-output
    schema doesn't catch this because any non-empty string is valid. Cheap check:
    require at least 20 chars and a terminal punctuation mark."""
    t = (text or "").strip()
    return len(t) >= 20 and t[-1] in '.!?"'


async def _score_with_retry(req: JobRequirements, profile_text: str) -> JobScore:
    result = await _score(req, profile_text)
    if _reasoning_complete(result.reasoning):
        return result
    logger.warning(
        "score_node: reasoning looks truncated (%d chars, tail=%r) — retrying once",
        len(result.reasoning or ""),
        (result.reasoning or "")[-40:],
    )
    retry = await _score(req, profile_text)
    if not _reasoning_complete(retry.reasoning):
        logger.warning("score_node: retry still produced incomplete reasoning — accepting anyway")
    return retry


async def _profile_text(req: JobRequirements) -> str:
    """Build candidate-profile context for the score prompt.

    Resume stays inline; the prior full skill-inventory inject is now top-k
    chunks retrieved against the JD's skills + summary.
    """
    query_parts = [*req.required_skills, *req.nice_to_have_skills]
    if req.summary:
        query_parts.append(req.summary)
    query = " ".join(query_parts).strip()

    chunks = await rag_retrieve(query, k=8) if query else []

    profile = f"## RESUME\n{read_resume()}"
    if chunks:
        ranked = "\n\n".join(c.document for c in chunks)
        profile += f"\n\n## RELEVANT SKILLS (top-{len(chunks)} by similarity)\n{ranked}"
    return profile


async def score_node(state: CompassState) -> dict:
    req = state.get("extracted_requirements")
    if req is None:
        return {
            "score_result": None,
            "errors": [*state.get("errors", []), "score_node: extracted_requirements is None"],
        }

    try:
        profile = await _profile_text(req)
        result = await _score_with_retry(req, profile)
    except Exception as e:
        logger.exception("score_node: LLM call failed")
        return {
            "score_result": None,
            "errors": [*state.get("errors", []), f"score_node: {type(e).__name__}: {e}"],
            "score_threshold": SCORE_THRESHOLD,
        }

    return {
        "score_result": _constrain_to_jd_skills(result, req),
        "score_threshold": SCORE_THRESHOLD,
    }


def _constrain_to_jd_skills(score: JobScore, req: JobRequirements) -> JobScore:
    """Defense in depth: drop matched/missing skills the JD didn't actually ask for,
    AND remove any skill that appears in BOTH matched and missing (matched wins).

    The score prompt forbids the LLM from inventing matched/missing skills
    outside the JD's required+nice_to_have lists. This filter enforces the
    same constraint at code-level. Gemini Flash also occasionally puts a
    borderline skill in both lists — without dedup, gap_aggregator would
    count the skill as a gap even though it's also "matched". We resolve
    overlaps in favor of matched (the LLM is more likely to over-flag gaps
    than over-claim matches).
    """
    jd_universe = set(req.required_skills) | set(req.nice_to_have_skills)
    matched_set = {s for s in score.matched_skills if s in jd_universe}
    missing_set = {s for s in score.missing_skills if s in jd_universe} - matched_set
    dropped = (set(score.matched_skills) | set(score.missing_skills)) - jd_universe
    if dropped:
        logger.info(
            "score_node: dropped %d skills not in JD universe (LLM ignored prompt constraint): %s",
            len(dropped),
            sorted(dropped),
        )
    return score.model_copy(
        update={
            "matched_skills": [s for s in score.matched_skills if s in matched_set],
            "missing_skills": [s for s in score.missing_skills if s in missing_set],
        }
    )
