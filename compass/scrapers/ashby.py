"""
Ashby public API scraper.

Endpoint: GET https://api.ashbyhq.com/posting-api/job-board/{boardName}?includeCompensation=true
No authentication required.
Covers: LangChain, PostHog, Linear, Ramp, Vercel, Plaid, and many AI-native companies.

Usage:
    jobs = await scrape_ashby("langchain")
    jobs = await scrape_ashby_many(["langchain", "posthog", "linear"])
"""
import httpx
from compass.pipeline.state import RawJob

ASHBY_BASE = "https://api.ashbyhq.com/posting-api/job-board"


async def scrape_ashby(board_name: str) -> list[RawJob]:
    """Scrape open jobs from an Ashby job board."""
    raise NotImplementedError("scrape_ashby not yet implemented")


async def scrape_ashby_many(board_names: list[str]) -> list[RawJob]:
    """Scrape multiple Ashby boards concurrently."""
    raise NotImplementedError("scrape_ashby_many not yet implemented")
