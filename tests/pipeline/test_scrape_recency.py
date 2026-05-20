"""Recency handling in _scrape_all: drop >30d-old postings, sort each board
by date_posted DESC, None-dated jobs sink to the bottom."""

from __future__ import annotations

from datetime import date, timedelta

from compass.pipeline.graph import MAX_POSTING_AGE_DAYS, _filter_and_sort_by_recency
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
    kept = _filter_and_sort_by_recency(jobs)
    names = [j.title for j in kept]
    assert "role-fresh" in names
    assert "role-borderline" in names  # exactly on the boundary is kept
    assert "role-stale" not in names


def test_undated_jobs_are_kept_and_sink_to_bottom():
    """ATSes that don't expose date_posted shouldn't have their jobs dropped —
    we can't distinguish stale from undated. But dated jobs are preferred."""
    jobs = [_job("undated", None), _job("recent", 1), _job("old", 14)]
    kept = _filter_and_sort_by_recency(jobs)
    assert len(kept) == 3
    # recent (1d ago) > old (14d ago) > undated
    assert kept[0].title == "role-recent"
    assert kept[1].title == "role-old"
    assert kept[2].title == "role-undated"


def test_freshest_first():
    jobs = [_job("oldish", 20), _job("today", 0), _job("yesterday", 1)]
    kept = _filter_and_sort_by_recency(jobs)
    assert [j.title for j in kept] == ["role-today", "role-yesterday", "role-oldish"]


def test_empty_list_returns_empty():
    assert _filter_and_sort_by_recency([]) == []
