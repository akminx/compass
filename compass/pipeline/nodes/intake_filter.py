"""intake_filter_node — role-family gate.

Runs BEFORE extract so out-of-scope JDs never burn an LLM extract+score call.

Pipeline cost optimization: this saves ~$0.003 per dropped JD (skipping
extract+score+tailor) for the ~30–50% of postings on most boards that are
sales / PM / design / CS. With MAX_JOBS_PER_RUN=50, that's ~$0.10/day saved.

More importantly: it fixes the gap-aggregator bias introduced by Phase 0.B's
SCORE_THRESHOLD write-gate. Now ALL in-scope JDs reach the vault regardless
of current match score, so stretch-role gaps (the ones Akash should be
studying toward) actually drive the master gap plan.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

import compass.config as cfg
from compass.pipeline.role_family import keyword_classify, llm_classify, upgrade_family

if TYPE_CHECKING:
    from compass.pipeline.state import CompassState

logger = logging.getLogger(__name__)


def _log_filtered(company: str, title: str, reason: str) -> None:
    # IMPORTANT: read VAULT_PATH at call time. Module-level constants would
    # break the temp_vault test fixture (which monkeypatches cfg.VAULT_PATH).
    log_path = cfg.VAULT_PATH / "_meta" / "filtered-jobs.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = f"- [{datetime.now().isoformat(timespec='seconds')}] {company} {title!r} — {reason}\n"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)


async def intake_filter_node(state: CompassState) -> dict:
    job = state.get("current_job")
    if job is None:
        return {
            "in_scope": False,
            "role_family": "out-of-scope",
            "errors": [*state.get("errors", []), "intake_filter_node: current_job is None"],
        }

    body = job.description or ""

    decided, family = keyword_classify(job.title)
    if decided is True:
        upgraded = upgrade_family(family, body)
        return {"in_scope": True, "role_family": upgraded}
    if decided is False:
        _log_filtered(job.company, job.title, f"title keyword → {family}")
        logger.info("intake_filter: dropped %s — %s (keyword)", job.company, job.title)
        return {"in_scope": False, "role_family": family}

    # Borderline — escalate to LLM
    try:
        result = await llm_classify(job.title, body[:500])
    except Exception as e:
        logger.warning(
            "intake_filter: LLM classify failed for %r — %s; defaulting to IN", job.title, e
        )
        return {"in_scope": True, "role_family": upgrade_family("other-eng", body)}

    if not result.in_scope:
        _log_filtered(job.company, job.title, f"llm → {result.reason}")
        logger.info(
            "intake_filter: dropped %s — %s (llm: %s)", job.company, job.title, result.reason
        )
        return {"in_scope": False, "role_family": result.role_family}

    upgraded = upgrade_family(result.role_family, body)
    return {"in_scope": True, "role_family": upgraded}
