"""Recency handling at the _scrape_all level: stale (>30d) postings are
dropped, but input ORDER is preserved — the per-board recency sort moved
into `round_robin_by_board` to fix the high-volume-board starvation bug.
See tests/test_scraper_interleave.py for the sort + interleave behaviour."""

from __future__ import annotations

from datetime import date, timedelta

from compass.pipeline.graph import MAX_POSTING_AGE_DAYS, _drop_stale_postings
from compass.pipeline.state import RawJob


def _job(name: str, days_ago: int | None) -> RawJob:
    return RawJob(
        company="Acme",
        title=f"role-{name}",
        url=f"https://x/{name}",
        source="manual",
        description="t",
        date_posted=(date.today() - timedelta(days=days_ago)) if days_ago is not None else None,
    )


def test_drops_jobs_older_than_cutoff():
    cutoff = MAX_POSTING_AGE_DAYS
    jobs = [_job("fresh", 1), _job("borderline", cutoff), _job("stale", cutoff + 1)]
    kept = _drop_stale_postings(jobs)
    names = [j.title for j in kept]
    assert "role-fresh" in names
    assert "role-borderline" in names  # exactly on the boundary is kept
    assert "role-stale" not in names


def test_undated_jobs_are_kept():
    """ATSes that don't expose date_posted shouldn't have their jobs dropped —
    we can't distinguish stale from undated."""
    jobs = [_job("undated", None), _job("recent", 1), _job("old", 14)]
    kept = _drop_stale_postings(jobs)
    assert len(kept) == 3
    assert {j.title for j in kept} == {"role-undated", "role-recent", "role-old"}


def test_preserves_input_order():
    """Sorting was deliberately moved out — the per-board round-robin in
    `round_robin_by_board` must not be un-interleaved by a downstream sort."""
    jobs = [_job("oldish", 20), _job("today", 0), _job("yesterday", 1)]
    kept = _drop_stale_postings(jobs)
    assert [j.title for j in kept] == ["role-oldish", "role-today", "role-yesterday"]


def test_empty_list_returns_empty():
    assert _drop_stale_postings([]) == []
