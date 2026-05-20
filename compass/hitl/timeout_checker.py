"""Auto-cancel pending approvals older than HITL_TIMEOUT_HOURS.

Module entrypoint (CLI):  python -m compass.hitl.timeout_checker
Async API:                check_and_resume_timeouts(timeout_hours: int | None = None)

In Phase 1.B.1 this is human-run. In Phase 1.B.3 a Modal cron will import and
schedule it — see modal_app.py."""

from __future__ import annotations

import asyncio
import logging

from compass.hitl import HITL_TIMEOUT_FEEDBACK_PREFIX, state_store
from compass.hitl.resume import resume_pending

logger = logging.getLogger(__name__)


async def check_and_resume_timeouts(*, timeout_hours: int | None = None) -> int:
    """Resume every stale pending row with {"approved": False}. Returns the
    count successfully timed-out (i.e. exclude rows that errored)."""
    from compass.config import HITL_TIMEOUT_HOURS

    hrs = timeout_hours if timeout_hours is not None else HITL_TIMEOUT_HOURS
    stale = await state_store.list_timed_out(timeout_hours=hrs)
    if not stale:
        return 0

    logger.info("hitl: %d pending approval(s) past %dh timeout", len(stale), hrs)
    timed_out = 0
    for row in stale:
        tid = row["thread_id"]
        try:
            await resume_pending(
                tid,
                decision={
                    "approved": False,
                    "feedback": f"{HITL_TIMEOUT_FEEDBACK_PREFIX} {hrs}h timeout",
                },
                status_override="timed_out",
            )
            # Spec § DoD line 230: HiTL timeout must log to _meta/agent-log.md
            _log_to_agent_log(
                f"hitl-timeout: auto-cancelled {tid} ({row['company']} / {row['title']}, "
                f"score={row['score']:.2f}) after {hrs}h"
            )
            timed_out += 1
        except Exception as e:
            logger.exception("hitl: timeout resume failed for %s — marking as error", tid)
            try:
                await state_store.mark_resolved(tid, status="error", feedback=f"resume error: {e}")
                _log_to_agent_log(f"hitl-timeout-error: {tid} resume failed: {e}")
                # Mirror the error status into the vault note (best-effort).
                try:
                    from compass.hitl import vault_view

                    vault_view.update_pending_note_status(
                        tid, status="error", feedback=f"resume error: {e}"
                    )
                except Exception:
                    logger.exception("hitl: failed to update vault pending-note for %s", tid)
            except Exception:
                logger.exception("hitl: also failed to mark %s as error", tid)
    return timed_out


def _log_to_agent_log(line: str) -> None:
    """Append a timestamped row to compass-vault/_meta/agent-log.md.

    Late-binds via compass.vault.writer.append_agent_log so the temp_vault
    fixture works in tests.
    """
    from compass.vault.writer import append_agent_log

    try:
        append_agent_log(line)
    except Exception:
        logger.exception("hitl: failed to write to agent-log.md")


if __name__ == "__main__":
    n = asyncio.run(check_and_resume_timeouts())
    print(f"Timed out: {n}")
