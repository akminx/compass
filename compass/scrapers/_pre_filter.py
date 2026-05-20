"""Pre-filter at the scraper layer: apply intake_filter's *free* predicates
(title-reject, jd-reject, non-US location) BEFORE the per-board round-robin +
global cap.

Why this exists
---------------
The per-job graph runs intake_filter after the global cap is applied. So when
a high-volume board's first few postings are senior+ titles, the round-robin
"uses" those board-turns on jobs that get dropped before extract. Combined
with a typical ~50% senior-density on enterprise boards, most of the cap can
get spent on title-doomed jobs.

Doing the same checks at the scraper level — *before* round-robin — means
the round-robin sees only post-filter jobs. Each board contributes its
freshest *eligible* job, not its freshest *any* job. Empirically multiplies
signal density per LLM-dollar.

Defense-in-depth: intake_filter still runs the same checks on each job that
makes it through. Manually-added jobs (`add_job_from_url`, `add_job_from_text`)
bypass _scrape_all so the intake_filter checks remain the canonical gate.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

import compass.config as cfg
from compass.pipeline.location_filter import is_us_compatible
from compass.vault.reader import load_reject_rules

if TYPE_CHECKING:
    from compass.pipeline.state import RawJob

logger = logging.getLogger(__name__)


def _check_one(job: RawJob, rules: dict[str, list[str]]) -> str | None:
    """Apply the three free predicates to one job. Returns drop-reason string,
    or None if the job is kept.
    """
    title_lc = (job.title or "").lower()
    body_lc = (job.description or "").lower()

    for needle in rules["title"]:
        if needle and needle in title_lc:
            return f"title rejects: {needle!r}"
    for needle in rules["jd"]:
        if needle and needle in body_lc:
            return f"jd rejects: {needle!r}"
    keep, reason = is_us_compatible(job.location)
    if not keep:
        return reason
    return None


def pre_filter_board(
    jobs: list[RawJob], rules: dict[str, list[str]] | None = None
) -> tuple[list[RawJob], list[tuple[RawJob, str]]]:
    """Apply title + jd + location predicates to one board's job list.

    Returns (kept, dropped_with_reasons). Caller passes `rules` to avoid
    re-parsing preferences.md once per board; if omitted, rules are loaded
    once.
    """
    if rules is None:
        rules = load_reject_rules()
    kept: list[RawJob] = []
    dropped: list[tuple[RawJob, str]] = []
    for j in jobs:
        reason = _check_one(j, rules)
        if reason is None:
            kept.append(j)
        else:
            dropped.append((j, reason))
    return kept, dropped


def log_drops(dropped: list[tuple[RawJob, str]]) -> None:
    """Append pre-filter drops to `_meta/filtered-jobs.md` so the same audit
    trail covers both pre-filter and intake_filter drops. Same format as
    `compass.pipeline.nodes.intake_filter._log_filtered`."""
    if not dropped:
        return
    log_path = cfg.VAULT_PATH / "_meta" / "filtered-jobs.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as f:
        for job, reason in dropped:
            f.write(f"- [{ts}] {job.company} {job.title!r} — {reason}\n")
    logger.info("pre-filter: dropped %d job(s) at scraper layer", len(dropped))


def pre_filter_many(per_board: list[list[RawJob]]) -> list[list[RawJob]]:
    """Apply pre_filter_board to each board's list, logging drops once. The
    rules dict is parsed once and shared.

    Returns the filtered per-board lists in the same order as input.
    """
    rules = load_reject_rules()
    out: list[list[RawJob]] = []
    all_dropped: list[tuple[RawJob, str]] = []
    for board_jobs in per_board:
        kept, dropped = pre_filter_board(board_jobs, rules)
        out.append(kept)
        all_dropped.extend(dropped)
    log_drops(all_dropped)
    return out
