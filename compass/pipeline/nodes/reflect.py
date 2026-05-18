"""
reflect_node — Phase 0.B no-op pass-through.

Future role (Phase 2): re-examine borderline scores (3.0–4.0) with a stricter
rubric. For Phase 0.B we don't have eval data showing where reflection would
help, so we wait. See spec section "Phase 0.B → 2.A" for the upgrade trigger.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from compass.pipeline.state import CompassState


async def reflect_node(state: CompassState) -> dict:
    """No-op for Phase 0.B. Returns {} (no state mutation)."""
    return {}
