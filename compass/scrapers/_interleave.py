"""Per-board round-robin interleave so a single high-volume board can't
starve quieter boards when the global MAX_JOBS_PER_RUN cap fires.

Pre-fix behaviour: `scrape_*_many` concatenated per-board lists in YAML order,
then `_scrape_all` sorted the whole pile by `date_posted DESC`. A single
high-volume board posting hundreds of fresh JDs in a day could dominate the
top of the queue and starve every quieter board out of the global cap.

Post-fix: each board's results are sorted by `date_posted DESC` independently,
then round-robined so round N picks each board's Nth-freshest. The cap then
trims uniformly across boards rather than from the tail of one board.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from compass.pipeline.state import RawJob

logger = logging.getLogger(__name__)


def _date_key(job: RawJob) -> tuple[bool, float]:
    """Sort key for RawJob: (date_unknown, -date_ordinal). Sorting ascending
    yields date_posted DESC with None-dated jobs at the bottom."""
    d = job.date_posted
    if d is None:
        return (True, 0.0)
    return (False, -float(d.toordinal()))


def round_robin_by_board(per_board: list[list[RawJob]]) -> list[RawJob]:
    """Sort each board's list by recency DESC, then interleave round-robin.

    Round N takes the Nth-freshest job from each board (when present). Empty
    boards are skipped silently. Original input lists are not mutated."""
    sorted_lists = [sorted(board, key=_date_key) for board in per_board if board]
    if not sorted_lists:
        return []
    iters = [iter(b) for b in sorted_lists]
    out: list[RawJob] = []
    while iters:
        next_iters = []
        for it in iters:
            try:
                out.append(next(it))
                next_iters.append(it)
            except StopIteration:
                pass
        iters = next_iters
    return out


async def gather_filter_interleave(
    scrape_fn: Callable[[str], Awaitable[list[RawJob]]],
    items: list[str],
    source_name: str,
) -> list[RawJob]:
    """Shared `scrape_*_many` driver. Per-source scrapers (greenhouse, lever,
    ashby, workday) previously duplicated this 5-step orchestration verbatim:

        1. early-exit on empty input
        2. asyncio.gather(*[scrape_fn(item) for item in items]) with
           return_exceptions so one bad board doesn't kill the batch
        3. log + drop any non-list result (an exception bubbled up)
        4. pre-filter at the scraper layer so high-volume boards don't burn
           round-robin slots on title-doomed jobs
        5. per-board round-robin interleave

    `source_name` is only used for the warning log on per-item failure.
    """
    from compass.scrapers._pre_filter import pre_filter_many

    if not items:
        return []
    results = await asyncio.gather(*[scrape_fn(i) for i in items], return_exceptions=True)
    per_board: list[list[RawJob]] = []
    for item, r in zip(items, results, strict=True):
        if isinstance(r, list):
            per_board.append(r)
        else:
            logger.warning("%s_many: unexpected exception for %r: %s", source_name, item, r)
    return round_robin_by_board(pre_filter_many(per_board))
