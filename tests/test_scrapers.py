"""
Tests for the Greenhouse scraper.
Run: uv run pytest tests/test_scrapers.py -v
"""
import pytest
from compass.scrapers.greenhouse import scrape_greenhouse, scrape_greenhouse_many
from compass.pipeline.state import RawJob


@pytest.mark.asyncio
async def test_scrape_greenhouse_returns_jobs():
    """Greenhouse API is public — this is a real integration test."""
    jobs = await scrape_greenhouse("databricks")
    assert isinstance(jobs, list)
    assert len(jobs) > 0
    assert all(isinstance(j, RawJob) for j in jobs)


@pytest.mark.asyncio
async def test_scrape_greenhouse_job_has_required_fields():
    jobs = await scrape_greenhouse("databricks")
    for job in jobs[:3]:
        assert job.company == "Databricks"
        assert job.title
        assert job.url.startswith("https://")
        assert job.source == "greenhouse"
        assert job.description


@pytest.mark.asyncio
async def test_scrape_greenhouse_many():
    jobs = await scrape_greenhouse_many(["databricks", "langchain"])
    assert len(jobs) > 0
    companies = {j.company for j in jobs}
    assert len(companies) >= 1  # at least one company returned results


@pytest.mark.asyncio
async def test_scrape_greenhouse_invalid_board():
    """Invalid board tokens should return empty list, not raise."""
    jobs = await scrape_greenhouse("this-board-does-not-exist-xyz-123")
    assert jobs == []
