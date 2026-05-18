"""
intake_node — deduplicates raw jobs against existing vault notes.

Responsibilities:
- Check each RawJob URL against existing vault job notes (by URL hash)
- Filter obviously irrelevant jobs (wrong seniority, excluded companies)
- Filter jobs that score below threshold based on title alone (fast pre-filter)
- Return the deduplicated list in state

TODO: implement
"""

from compass.pipeline.state import CompassState


async def intake_node(state: CompassState) -> dict:
    """Deduplicate and pre-filter raw jobs before expensive LLM calls."""
    raise NotImplementedError("intake_node not yet implemented")
