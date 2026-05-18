"""
hitl_node — Phase 0.B auto-approve based on SCORE_THRESHOLD.

This is INTENTIONALLY auto-approve for 0.B. Real LangGraph `interrupt()` +
`AsyncSqliteSaver` checkpointing + an MCP-tool-driven approval surface ship in
Phase 1.B per the spec. Auto-approve unblocks the end-to-end pipeline so we
can collect real eval data first.
"""
from __future__ import annotations

import logging

from compass.config import SCORE_THRESHOLD
from compass.pipeline.state import CompassState

logger = logging.getLogger(__name__)


async def hitl_node(state: CompassState) -> dict:
    """Auto-approve if score >= SCORE_THRESHOLD, else reject. No human interaction in 0.B."""
    score = state.get("score_result")
    if score is None:
        logger.info("hitl: no score_result, rejecting by default")
        return {"human_approved": False}

    approved = score.score >= SCORE_THRESHOLD
    job = state.get("current_job")
    job_id = job.url if job else "(unknown)"
    logger.info(
        "hitl: auto-%s job %s (score=%.2f, threshold=%.2f)",
        "approve" if approved else "reject", job_id, score.score, SCORE_THRESHOLD,
    )
    return {"human_approved": approved}
