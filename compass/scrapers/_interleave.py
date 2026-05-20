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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from compass.pipeline.state import RawJob


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
