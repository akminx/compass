"""Tests for compass.scrapers.greenhouse."""
import pytest
from compass.scrapers.greenhouse import scrape_greenhouse, GREENHOUSE_BASE

SAMPLE_RESPONSE = {
    "jobs": [
        {
            "id": 1234567,
            "title": "Senior Agent Engineer",
            "absolute_url": "https://job-boards.greenhouse.io/sample/jobs/1234567",
            "location": {"name": "San Francisco, CA"},
            "updated_at": "2026-05-15T10:00:00-07:00",
            "content": "<p>Build AI agents</p><p>Required: Python, LangGraph</p>",
        },
        {
            "id": 7654321,
            "title": "Agent Engineer",
            "absolute_url": "https://job-boards.greenhouse.io/sample/jobs/7654321",
            "location": {"name": "Remote"},
            "updated_at": "2026-05-10T09:00:00-07:00",
            "content": "<p>Junior role</p>",
        },
    ],
    "meta": {"total": 2},
}


async def test_scrape_greenhouse_returns_rawjob_list(httpx_mock):
    httpx_mock.add_response(
        url=f"{GREENHOUSE_BASE}/sample/jobs",
        json=SAMPLE_RESPONSE,
    )
    jobs = await scrape_greenhouse("sample")
    assert len(jobs) == 2
    first = jobs[0]
    assert first.company == "sample"
    assert first.title == "Senior Agent Engineer"
    assert first.url == "https://job-boards.greenhouse.io/sample/jobs/1234567"
    assert first.source == "greenhouse"
    assert first.location == "San Francisco, CA"
    assert "LangGraph" in first.description  # HTML stripped to plain text
    assert first.date_posted is not None


async def test_scrape_greenhouse_handles_missing_location(httpx_mock):
    httpx_mock.add_response(
        url=f"{GREENHOUSE_BASE}/sample/jobs",
        json={"jobs": [{
            "id": 1,
            "title": "X",
            "absolute_url": "https://example.com/x",
            "location": None,
            "updated_at": "2026-05-15T10:00:00-07:00",
            "content": "<p>y</p>",
        }]},
    )
    jobs = await scrape_greenhouse("sample")
    assert jobs[0].location is None


async def test_scrape_greenhouse_empty_board(httpx_mock):
    httpx_mock.add_response(
        url=f"{GREENHOUSE_BASE}/sample/jobs",
        json={"jobs": []},
    )
    jobs = await scrape_greenhouse("sample")
    assert jobs == []


async def test_scrape_greenhouse_http_error_returns_empty(httpx_mock):
    """A 404 board should log and return [], not raise — pipeline must keep running."""
    httpx_mock.add_response(
        url=f"{GREENHOUSE_BASE}/nonexistent/jobs",
        status_code=404,
    )
    jobs = await scrape_greenhouse("nonexistent")
    assert jobs == []
