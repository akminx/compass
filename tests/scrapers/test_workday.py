"""Workday scraper unit tests — mocked HTTP responses, no network."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import httpx
import pytest

from compass.scrapers.workday import (
    _parse_posted_on,
    _parse_slug,
    _to_rawjob,
    scrape_workday,
)


class TestParseSlug:
    def test_well_formed(self):
        assert _parse_slug("wd5/citi/2") == ("wd5", "citi", "2")
        assert _parse_slug("wd1/wf/WellsFargoJobs") == ("wd1", "wf", "WellsFargoJobs")

    def test_missing_part_returns_none(self):
        assert _parse_slug("wd5/citi") is None
        assert _parse_slug("citi/2") is None

    def test_invalid_subdomain_returns_none(self):
        assert _parse_slug("wrong/citi/2") is None


class TestParsePostedOn:
    def test_today(self):
        assert _parse_posted_on("Posted Today") == date.today()

    def test_yesterday(self):
        assert _parse_posted_on("Posted Yesterday") == date.today() - timedelta(days=1)

    def test_n_days_ago(self):
        assert _parse_posted_on("Posted 5 Days Ago") == date.today() - timedelta(days=5)

    def test_30_plus_days_ago(self):
        assert _parse_posted_on("Posted 30+ Days Ago") == date.today() - timedelta(days=30)

    def test_n_months_ago(self):
        # Approximate: ~30 days per month
        assert _parse_posted_on("Posted 2 Months Ago") == date.today() - timedelta(days=60)

    def test_unparseable_returns_none(self):
        assert _parse_posted_on(None) is None
        assert _parse_posted_on("") is None
        assert _parse_posted_on("Posted Recently") is None


class TestToRawJob:
    def test_builds_rawjob_with_body(self):
        raw = {
            "title": "AI Engineer, LLM Suite",
            "locationsText": "Plano, TX",
            "postedOn": "Posted 3 Days Ago",
            "externalPath": "/job/123",
        }
        rj = _to_rawjob("JPMorgan", raw, "Build GenAI agents.", "https://x/apply")
        assert rj is not None
        assert rj.company == "JPMorgan"
        assert rj.title == "AI Engineer, LLM Suite"
        assert rj.url == "https://x/apply"
        assert rj.source == "workday"
        assert rj.location == "Plano, TX"
        assert rj.description == "Build GenAI agents."
        assert rj.date_posted == date.today() - timedelta(days=3)

    def test_drops_empty_body(self):
        """Workday detail endpoint sometimes rate-limits and we get no body.
        Don't ship empty descriptions downstream — extract LLM will hallucinate."""
        rj = _to_rawjob("Citi", {"title": "Engineer"}, "", None)
        assert rj is None

    def test_drops_missing_title(self):
        rj = _to_rawjob("Citi", {}, "body", None)
        assert rj is None


@pytest.mark.asyncio
async def test_scrape_workday_malformed_slug_returns_empty():
    jobs = await scrape_workday("not-a-slug")
    assert jobs == []


@pytest.mark.asyncio
async def test_scrape_workday_handles_http_error():
    """Network error MUST NOT raise — the pipeline keeps running."""

    async def boom(*a, **kw):
        raise httpx.ConnectError("simulated")

    with patch("httpx.AsyncClient.post", side_effect=boom):
        jobs = await scrape_workday("wd5/citi/2")
        assert jobs == []
