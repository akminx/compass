"""
extract_node — extracts structured requirements from a job description.

Uses Pydantic AI to extract JobRequirements from raw JD text.
Langfuse traces this call — cost and tokens logged per extraction.

TODO: implement using pydantic_ai.Agent with result_type=JobRequirements
"""

from compass.pipeline.state import CompassState


async def extract_node(state: CompassState) -> dict:
    """Extract structured JobRequirements from the current job's description."""
    raise NotImplementedError("extract_node not yet implemented")
