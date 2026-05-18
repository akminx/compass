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
from compass.vault.taxonomy import all_canonicals, normalize

logger = logging.getLogger(__name__)


def _build_system_prompt() -> str:
    """Inject the canonical taxonomy into the prompt at call time.

    The LLM must pick from this exact list — that closes the "agent frameworks"
    → dropped-as-unknown failure mode where JDs use generic phrasing that
    doesn't match canonical names character-for-character.
    """
    canonicals = ", ".join(all_canonicals())
    return f"""You extract structured requirements from a job description.

Return a JobRequirements with these fields (no extras, no comments):
- required_skills: list of technical skills the JD explicitly requires.
- nice_to_have_skills: list of technical skills the JD lists as preferred / bonus.
- years_experience: integer minimum years stated (e.g. "3+ years" → 3), or null if not stated.
- seniority: exactly one of: junior | mid | senior | staff | unknown.
- remote_policy: exactly one of: remote | hybrid | onsite | unknown.
- summary: ONE short paragraph (1-2 sentences max) describing the role.

CRITICAL — skill names:
You MUST output every skill using the EXACT canonical name from this list (case-sensitive):

{canonicals}

Map JD phrasing to the closest canonical. Examples:
- "agent frameworks" or "agent orchestration" → LangChain, LangGraph (whichever is mentioned, or both if generic)
- "Python 3.x" or "py" → Python
- "TypeScript / Node.js" → TypeScript
- "vector database" without specifying which → Chroma (or pgvector if SQL-adjacent)
- "tool calling" or "function calling" → Function calling
- "structured outputs" or "JSON mode" → Structured outputs
- "human in the loop" → HiTL
- "observability" without specifying → Langfuse
- "evals" or "evaluation" → Eval harness

If a JD-mentioned skill has NO good canonical match (e.g. Salesforce, Figma, motion graphics), OMIT it entirely from required_skills and nice_to_have_skills. Do not invent canonical names not in the list above.

RULES:
- Skills must be GENUINELY TECHNICAL. Do NOT include soft skills, credentials, degrees, industries.
- Return [] when a section has no canonical matches. Do not omit fields.
- For "5+ years" → years_experience=5. For "Bachelor's required" → years_experience=null.
"""

# Gemini 2.5 Flash structured-output reliability degrades beyond ~10k input chars.
# Trimming preserves the top of the JD (where requirements typically live) while
# keeping calls predictable in cost and validation success rate.
_MAX_JD_CHARS_FOR_EXTRACT = 8000

# Pydantic-AI default is 1 retry. Gemini Flash JSON-shape failures are usually
# transient on the second try; 3 retries pushes practical success >95% without
# meaningful cost (only failures retry).
_EXTRACT_RETRIES = 3


def _build_agent():
    return make_agent(
        "extract",
        output_type=JobRequirements,
        system_prompt=_build_system_prompt(),
        output_retries=_EXTRACT_RETRIES,
    )


async def _extract(jd_text: str) -> JobRequirements:
    """The LLM call. Tests monkeypatch this wrapper rather than the underlying Agent."""
    agent = _build_agent()
    result = await agent.run(jd_text[:_MAX_JD_CHARS_FOR_EXTRACT])
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
