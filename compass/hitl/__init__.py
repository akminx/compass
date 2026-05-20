"""HiTL pause/resume infrastructure for Compass.

The audit-trail mapping in vault_write._derive_hitl_decision matches on this
prefix; both sites must import HITL_TIMEOUT_FEEDBACK_PREFIX to stay in sync.
"""

HITL_TIMEOUT_FEEDBACK_PREFIX = "auto-cancelled after"
"""Leading substring of the feedback string used to mark a timeout-driven resume.

Used by:
  - compass.hitl.timeout_checker — writes f"{HITL_TIMEOUT_FEEDBACK_PREFIX} {hrs}h timeout"
  - compass.pipeline.nodes.vault_write._derive_hitl_decision — matches
    feedback.startswith(HITL_TIMEOUT_FEEDBACK_PREFIX) to set hitl_decision="timed_out"
"""
