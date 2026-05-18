"""Tests for compass.scrapers.ashby."""
import pytest
from compass.scrapers.ashby import scrape_ashby, ASHBY_BASE

SAMPLE_RESPONSE = {
    "jobs": [
        {
            "id": "uuid-aaa",
            "title": "Agent Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/sample/uuid-aaa",
            "locationName": "New York, NY",
            "publishedAt": "2026-05-12T15:00:00.000Z",
            "descriptionPlain": "Build customer agents with LangGraph, Python, and MCP.",
            "compensation": {"compensationTierSummary": "$180K – $230K"},
            "employmentType": "FullTime",
            "shouldDisplayCompensationOnJobBoard": True,
        },
        {
            "id": "uuid-bbb",
            "title": "Senior Agent Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/sample/uuid-bbb",
            "locationName": "Remote",
            "publishedAt": "2026-05-10T15:00:00.000Z",
            "descriptionPlain": "Senior role.",
            "compensation": None,
            "employmentType": "FullTime",
            "shouldDisplayCompensationOnJobBoard": False,
        },
    ],
}


async def test_scrape_ashby_returns_rawjob_list(httpx_mock):
    httpx_mock.add_response(
        url=f"{ASHBY_BASE}/sample?includeCompensation=true",
        json=SAMPLE_RESPONSE,
    )
    jobs = await scrape_ashby("sample")
    assert len(jobs) == 2
    first = jobs[0]
    assert first.company == "sample"
    assert first.title == "Agent Engineer"
    assert first.url == "https://jobs.ashbyhq.com/sample/uuid-aaa"
    assert first.source == "ashby"
    assert first.location == "New York, NY"
    assert "LangGraph" in first.description
    assert first.date_posted is not None


async def test_scrape_ashby_parses_compensation_range(httpx_mock):
    httpx_mock.add_response(
        url=f"{ASHBY_BASE}/sample?includeCompensation=true",
        json=SAMPLE_RESPONSE,
    )
    jobs = await scrape_ashby("sample")
    assert jobs[0].salary_min == 180000
    assert jobs[0].salary_max == 230000
    # Second job has compensation=None → salary fields should be None.
    assert jobs[1].salary_min is None
    assert jobs[1].salary_max is None


async def test_scrape_ashby_http_error_returns_empty(httpx_mock):
    httpx_mock.add_response(
        url=f"{ASHBY_BASE}/nonexistent?includeCompensation=true",
        status_code=404,
    )
    jobs = await scrape_ashby("nonexistent")
    assert jobs == []
