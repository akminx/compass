"""hitl_node — Phase 1.B.1 real human-in-the-loop via LangGraph interrupt().

Behaviour:
  * score < SCORE_THRESHOLD or score missing -> auto-reject, no interrupt fires
  * score >= SCORE_THRESHOLD -> interrupt() with the approval payload; the
    orchestrator catches the interrupt and registers the thread in
    compass.hitl.state_store. A human resumes via Command(resume={...}).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langgraph.types import interrupt

from compass.config import SCORE_THRESHOLD

if TYPE_CHECKING:
    from compass.pipeline.state import CompassState

logger = logging.getLogger(__name__)


async def hitl_node(state: CompassState) -> dict:
    score = state.get("score_result")
    job = state.get("current_job")

    if score is None or score.score < SCORE_THRESHOLD:
        logger.info(
            "hitl: auto-reject %s (score=%s, threshold=%.2f)",
            job.url if job else "(unknown)",
            getattr(score, "score", None),
            SCORE_THRESHOLD,
        )
        return {"human_approved": False}

    payload = {
        "kind": "approval_request",
        "job_url": job.url if job else "",
        "company": job.company if job else "",
        "title": job.title if job else "",
        "score": score.score,
        "score_reasoning": score.reasoning,
        "matched_skills": list(score.matched_skills),
        "missing_skills": list(score.missing_skills),
    }
    logger.info(
        "hitl: interrupting for approval — %s (score=%.2f)", payload["job_url"], score.score
    )
    decision = interrupt(payload)

    if not isinstance(decision, dict):
        logger.warning("hitl: malformed resume value %r — defaulting to reject", decision)
        return {"human_approved": False}
    return {
        "human_approved": bool(decision.get("approved", False)),
        "human_feedback": decision.get("feedback"),
    }
