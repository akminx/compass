"""
intake_node — Phase 0.B sanity gate.

Dedup happens BATCH-LEVEL in `run_pipeline` (build URL set once via
list_job_notes, filter raw_jobs before graph iteration). This node just
confirms `current_job` is set; future filtering logic (e.g., seniority
pre-filter, excluded-company list) can land here without restructuring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from compass.pipeline.state import CompassState


async def intake_node(state: CompassState) -> dict:
    if state.get("current_job") is None:
        return {"errors": [*state.get("errors", []), "intake_node: current_job is None"]}
    return {}
