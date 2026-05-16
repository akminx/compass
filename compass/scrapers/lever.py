"""
Lever public API scraper.

Endpoint: GET https://api.lever.co/v0/postings/{company}?mode=json
No authentication required — fully public.

Usage:
    jobs = await scrape_lever("databricks")
    jobs = await scrape_lever_many(["databricks", "anthropic"])
"""
import httpx
from compass.pipeline.state import RawJob

LEVER_BASE = "https://api.lever.co/v0/postings"


async def scrape_lever(company: str) -> list[RawJob]:
    """Scrape open jobs from a Lever company board."""
    raise NotImplementedError("scrape_lever not yet implemented")


async def scrape_lever_many(companies: list[str]) -> list[RawJob]:
    """Scrape multiple Lever boards concurrently."""
    raise NotImplementedError("scrape_lever_many not yet implemented")
