"""Regression: Workday's public `/wday/cxs/.../jobs` endpoint enforces a hard
limit of 20 per request. Anything larger returns HTTP 400. Pre-fix `_PAGE_SIZE`
was 50, which silently broke every Workday scrape — all 5 banks returned 0.

This test pins the constant so a future "let's reduce round-trips" tweak
doesn't reintroduce the bug. If Workday raises the cap, update the limit AND
this assertion together.
"""

from __future__ import annotations

from compass.scrapers import workday


def test_workday_page_size_within_api_limit():
    assert workday._PAGE_SIZE <= 20, (
        "Workday rejects limit > 20 with HTTP 400 — verified across "
        "Citi/WellsFargo/MorganStanley/BlackRock/Adobe on 2026-05-20. "
        "If Workday has since raised the cap, update both the constant "
        "and this assertion."
    )
