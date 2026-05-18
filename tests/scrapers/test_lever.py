"""Tests for compass.scrapers.lever."""

from compass.scrapers.lever import LEVER_BASE, scrape_lever

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
        json=[
            {
                "id": "x",
                "text": "Y",
                "hostedUrl": "https://example.com/x",
                "categories": {},
                "createdAt": 1715600000000,
                "descriptionPlain": "z",
            }
        ],
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


async def test_scrape_lever_falls_back_to_html_when_plain_empty(httpx_mock):
    """Regression: Spotify (and other Lever boards) sometimes leave
    descriptionPlain empty while populating HTML description. The scraper must
    fall back to stripped HTML, not silently pass an empty JD downstream."""
    httpx_mock.add_response(
        url=f"{LEVER_BASE}/spotify?mode=json",
        json=[
            {
                "id": "x",
                "text": "Backend Engineer",
                "hostedUrl": "https://jobs.lever.co/spotify/x",
                "categories": {"location": "Remote"},
                "createdAt": 1715600000000,
                "descriptionPlain": "",  # empty
                "description": "<p>Build distributed services in <b>Python</b>.</p>",
            }
        ],
    )
    jobs = await scrape_lever("spotify")
    assert len(jobs) == 1
    assert "Python" in jobs[0].description
    assert "<p>" not in jobs[0].description  # HTML was stripped


async def test_scrape_lever_drops_when_both_descriptions_empty(httpx_mock):
    """If both descriptionPlain AND description are empty, drop the posting
    rather than hallucinate skills from the title downstream."""
    httpx_mock.add_response(
        url=f"{LEVER_BASE}/sample?mode=json",
        json=[
            {
                "id": "x",
                "text": "Engineer",
                "hostedUrl": "https://jobs.lever.co/sample/x",
                "categories": {},
                "createdAt": 1715600000000,
                "descriptionPlain": "",
                "description": "",
            }
        ],
    )
    jobs = await scrape_lever("sample")
    assert jobs == []
