"""
tailor_node — Sonnet-quality one-paragraph tailoring suggestion.

Only fires when state['human_approved'] is True. Sets state['tailored_paragraph']
(separate from score.tailoring_notes which is score_node's short pitch).
Sonnet (or TAILOR_MODEL override) for writing quality.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel

from compass.llm import make_agent
from compass.vault.reader import read_profile_section, read_resume

if TYPE_CHECKING:
    from compass.pipeline.state import CompassState

logger = logging.getLogger(__name__)


class TailoringResult(BaseModel):
    """Structured output: a single tailoring paragraph."""

    paragraph: str


_SYSTEM_PROMPT = """You write tailoring suggestions for job applications.

Output ONE concrete paragraph (3–5 sentences) suggesting how the candidate
should frame their application for this specific role. Reference concrete
projects/work from the candidate's profile that match the role's requirements.

Avoid generic advice. Be specific. Mention real projects and concrete numbers
when the profile provides them.
"""

# Sonnet handles long context fine, but trimming keeps tailor calls predictable in cost.
# 6000 chars ≈ ~1500 tokens of JD body — enough signal for one paragraph of tailoring.
_MAX_JD_CHARS_FOR_TAILOR = 6000


def _build_agent():
    return make_agent("tailor", output_type=TailoringResult, system_prompt=_SYSTEM_PROMPT)


async def _tailor(
    job_summary: str, profile_text: str, missing: list[str], matched: list[str]
) -> str:
    """The LLM call. Tests monkeypatch this wrapper rather than the underlying Agent."""
    agent = _build_agent()
    prompt = (
        f"CANDIDATE PROFILE\n{profile_text}\n\n"
        f"JOB SUMMARY\n{job_summary}\n\n"
        f"Skills matched: {', '.join(matched) or '(none)'}\n"
        f"Skills missing: {', '.join(missing) or '(none)'}\n"
    )
    result = await agent.run(prompt)
    return result.output.paragraph


async def tailor_node(state: CompassState) -> dict:
    if not state.get("human_approved"):
        return {}

    score = state.get("score_result")
    job = state.get("current_job")
    if score is None or job is None:
        return {}

    profile = f"{read_resume()}\n\n{read_profile_section('role-clarifications')}"

    try:
        paragraph = await _tailor(
            job.description[:_MAX_JD_CHARS_FOR_TAILOR],
            profile,
            score.missing_skills,
            score.matched_skills,
        )
    except Exception as e:
        logger.warning("tailor_node: LLM call failed for %s — %s", job.url, e)
        return {"errors": [*state.get("errors", []), f"tailor_node: {e}"]}

    return {"tailored_paragraph": paragraph}
