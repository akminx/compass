"""Tests for compass.scrapers.lever."""
import pytest
from compass.scrapers.lever import scrape_lever, LEVER_BASE

SAMPLE_RESPONSE = [
    {
        "id": "abc-123",
        "text": "Software Engineer, AI",
        "hostedUrl": "https://jobs.lever.co/sample/abc-123",
        "categories": {"location": "Remote", "commitment": "Full-time", "team": "Engineering"},
        "createdAt": 1715600000000,
        "descriptionPlain": "Build agentic systems with Python and LangGraph.",
    },
    {
        "id": "def-456",
        "text": "ML Engineer",
        "hostedUrl": "https://jobs.lever.co/sample/def-456",
        "categories": {"location": "SF, CA", "commitment": "Full-time", "team": "Research"},
        "createdAt": 1715500000000,
        "descriptionPlain": "Train models.",
    },
]


async def test_scrape_lever_returns_rawjob_list(httpx_mock):
    httpx_mock.add_response(
        url=f"{LEVER_BASE}/sample?mode=json",
        json=SAMPLE_RESPONSE,
    )
    jobs = await scrape_lever("sample")
    assert len(jobs) == 2
    first = jobs[0]
    assert first.company == "sample"
    assert first.title == "Software Engineer, AI"
    assert first.url == "https://jobs.lever.co/sample/abc-123"
    assert first.source == "lever"
    assert first.location == "Remote"
    assert "LangGraph" in first.description
    assert first.date_posted is not None


async def test_scrape_lever_handles_missing_categories(httpx_mock):
    httpx_mock.add_response(
        url=f"{LEVER_BASE}/sample?mode=json",
        json=[{
            "id": "x",
            "text": "Y",
            "hostedUrl": "https://example.com/x",
            "categories": {},
            "createdAt": 1715600000000,
            "descriptionPlain": "z",
        }],
    )
    jobs = await scrape_lever("sample")
    assert jobs[0].location is None


async def test_scrape_lever_http_error_returns_empty(httpx_mock):
    httpx_mock.add_response(
        url=f"{LEVER_BASE}/nonexistent?mode=json",
        status_code=404,
    )
    jobs = await scrape_lever("nonexistent")
    assert jobs == []
