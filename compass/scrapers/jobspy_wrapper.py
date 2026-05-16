"""
JobSpy wrapper — aggregates LinkedIn, Indeed, Glassdoor, ZipRecruiter.

Use as a supplemental source only. LinkedIn rate-limits aggressively.
Always design for graceful degradation: if LinkedIn returns 0 results, log and continue.

Usage:
    jobs = await scrape_jobspy(search_term="agentic AI engineer", location="Austin, TX")
"""
from compass.pipeline.state import RawJob


async def scrape_jobspy(
    search_term: str,
    location: str = "United States",
    results_wanted: int = 20,
) -> list[RawJob]:
    """Scrape jobs via JobSpy aggregator. Falls back gracefully on rate limits."""
    raise NotImplementedError("scrape_jobspy not yet implemented")
