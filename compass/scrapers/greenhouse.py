"""
Greenhouse public API scraper.

Endpoint: GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs
No authentication required — fully public.
Returns normalized RawJob objects.

Usage:
    jobs = await scrape_greenhouse("databricks")
    jobs = await scrape_greenhouse_many(["databricks", "scale-ai", "langchain"])
"""
import httpx
from compass.pipeline.state import RawJob


GREENHOUSE_BASE = "https://boards-api.greenhouse.io/v1/boards"


async def scrape_greenhouse(board_token: str) -> list[RawJob]:
    """
    Scrape all open jobs from a Greenhouse board.

    Args:
        board_token: The board token from the company's Greenhouse URL.
                     e.g. for https://boards.greenhouse.io/databricks → "databricks"

    Returns:
        List of normalized RawJob objects.
    """
    raise NotImplementedError("scrape_greenhouse not yet implemented")


async def scrape_greenhouse_many(board_tokens: list[str]) -> list[RawJob]:
    """Scrape multiple Greenhouse boards concurrently."""
    raise NotImplementedError("scrape_greenhouse_many not yet implemented")
