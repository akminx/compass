"""Tests for compass.scrapers._interleave.round_robin_by_board — the per-board
round-robin that prevents one high-volume board from starving the others
out of MAX_JOBS_PER_RUN."""

from __future__ import annotations

from datetime import date

import pytest

from compass.pipeline.state import RawJob
from compass.scrapers._interleave import round_robin_by_board


def _job(company: str, n: int, d: date | None = date(2026, 5, 20)) -> RawJob:
    return RawJob(
        company=company,
        title=f"{company} job {n}",
        url=f"https://{company}.example.com/{n}",
        source="manual",
        description="...",
        date_posted=d,
    )


def test_empty_returns_empty():
    assert round_robin_by_board([]) == []
    assert round_robin_by_board([[], [], []]) == []


def test_single_board_preserves_after_sort():
    jobs = [
        _job("a", 1, date(2026, 5, 18)),
        _job("a", 2, date(2026, 5, 20)),
        _job("a", 3, date(2026, 5, 19)),
    ]
    out = round_robin_by_board([jobs])
    # Single board: just date-sorted DESC
    assert [j.title for j in out] == ["a job 2", "a job 3", "a job 1"]


def test_two_boards_alternate():
    a = [_job("a", 1), _job("a", 2), _job("a", 3)]
    b = [_job("b", 1), _job("b", 2)]
    out = round_robin_by_board([a, b])
    assert [j.company for j in out] == ["a", "b", "a", "b", "a"]


def test_starvation_fix_high_volume_board_does_not_dominate_first_n():
    """Regression: pre-fix, Databricks (322 fresh) dominated the head of the
    flat list and the 50-cap starved Anthropic + others. This test asserts
    that the first slice contains a job from each board, even when one board
    has 100x the volume of the others."""
    big = [_job("databricks", n) for n in range(322)]
    small = [_job("anthropic", n) for n in range(5)]
    smaller = [_job("agentco", n) for n in range(2)]

    out = round_robin_by_board([big, small, smaller])

    # First 3 slots: one job from each board (round 1)
    first_three_companies = {j.company for j in out[:3]}
    assert first_three_companies == {"databricks", "anthropic", "agentco"}

    # After 2 rounds, agentco is exhausted; rounds 3-5 alternate databricks + anthropic
    # After 5 rounds, anthropic is exhausted; the rest is databricks tail
    # Total: 322 + 5 + 2 = 329 jobs
    assert len(out) == 329

    # Top 10 should contain at least 1 job per non-empty board
    top10_companies = {j.company for j in out[:10]}
    assert {"databricks", "anthropic", "agentco"} <= top10_companies


def test_within_board_freshest_first():
    """Each board's freshest job comes out before its older jobs."""
    board = [
        _job("a", 1, date(2026, 4, 1)),   # oldest
        _job("a", 2, date(2026, 5, 20)),  # freshest
        _job("a", 3, date(2026, 5, 1)),   # middle
    ]
    out = round_robin_by_board([board])
    assert [j.title for j in out] == ["a job 2", "a job 3", "a job 1"]


def test_none_dated_jobs_sink_to_bottom_within_board():
    board = [
        _job("a", 1, None),
        _job("a", 2, date(2026, 5, 20)),
        _job("a", 3, date(2026, 5, 18)),
    ]
    out = round_robin_by_board([board])
    # None-dated drops to the end of this board's slice
    assert [j.title for j in out] == ["a job 2", "a job 3", "a job 1"]


def test_does_not_mutate_input():
    board = [_job("a", 2, date(2026, 5, 18)), _job("a", 1, date(2026, 5, 20))]
    original = list(board)
    round_robin_by_board([board])
    assert board == original


@pytest.mark.asyncio
async def test_scrape_greenhouse_many_interleaves():
    """End-to-end at the scraper level: with mocked per-board returns, the
    flattened output is interleaved per-board, not concatenated."""
    from unittest.mock import patch

    from compass.scrapers import greenhouse

    async def fake_one(token):
        # databricks returns 5 jobs, anthropic returns 2
        return [_job(token, n) for n in range(5 if token == "databricks" else 2)]

    with patch.object(greenhouse, "scrape_greenhouse", side_effect=fake_one):
        out = await greenhouse.scrape_greenhouse_many(["databricks", "anthropic"])

    # Interleaved: d, a, d, a, d, d, d  (not d,d,d,d,d,a,a)
    companies = [j.company for j in out]
    assert companies[:4] == ["databricks", "anthropic", "databricks", "anthropic"]
    assert len(out) == 7
