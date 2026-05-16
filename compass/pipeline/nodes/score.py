"""
score_node — scores a job against the candidate profile.

Reads skill-inventory.md and resume.md from the vault.
LLM scores match 0.0–5.0 with explicit reasoning and per-skill breakdown.
Jobs below SCORE_THRESHOLD are logged and dropped.
Langfuse traces this call.

TODO: implement
"""
from compass.pipeline.state import CompassState


async def score_node(state: CompassState) -> dict:
    """Score the current job against the candidate profile in the vault."""
    raise NotImplementedError("score_node not yet implemented")
