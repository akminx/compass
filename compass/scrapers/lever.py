"""
Lever public API scraper.

Endpoint: GET https://api.lever.co/v0/postings/{company}?mode=json
No authentication required.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

import httpx

from compass.pipeline.state import RawJob
from compass.scrapers._remote_parser import infer_remote_policy

logger = logging.getLogger(__name__)

LEVER_BASE = "https://api.lever.co/v0/postings"
_REQUEST_TIMEOUT = 20.0
_USER_AGENT = "compass-job-scraper/0.1"

from compass.scrapers._html import strip_html as _strip_html


def _ms_to_date(ms: int | None) -> date | None:
    """Convert a Lever createdAt (ms since epoch) to a date. Returns None for
    null, zero, or out-of-range values."""
    if ms is None or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000).date()
    except (TypeError, ValueError, OSError):
        return None


def _resolve_description(raw: dict) -> str:
    """Prefer plain text; fall back to stripped HTML.

    Some Lever boards (observed: Spotify) leave `descriptionPlain` empty on a
    subset of postings while still populating the HTML `description`. Without
    the fallback, those postings reach the LLM with empty content and the
    extract node hallucinates skills from the title alone.
    """
    plain = (raw.get("descriptionPlain") or "").strip()
    if plain:
        return plain
    html_body = raw.get("description") or ""
    return _strip_html(html_body)


def _to_rawjob(company: str, raw: dict) -> RawJob | None:
    try:
        description = _resolve_description(raw)
        if not description:
            logger.warning(
                "lever %s: empty description for %r — dropping (API may have changed)",
                company,
                raw.get("text", "?"),
            )
            return None
        categories = raw.get("categories") or {}
        location_str = categories.get("location") or None
        return RawJob(
            company=company,
            title=raw["text"],
            url=raw["hostedUrl"],
            source="lever",
            location=location_str,
            remote=infer_remote_policy(location_str),
            salary_min=None,
            salary_max=None,
            description=description,
            date_posted=_ms_to_date(raw.get("createdAt")),
        )
    except (KeyError, TypeError) as e:
        logger.warning("lever: malformed posting skipped: %s", e)
        return None


async def scrape_lever(company: str) -> list[RawJob]:
    """Scrape all open postings from a Lever company."""
    url = f"{LEVER_BASE}/{company}?mode=json"
    try:
        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("lever %s: %s", company, e)
        return []
    if not isinstance(data, list):
        logger.warning("lever %s: unexpected payload type %s", company, type(data).__name__)
        return []
    return [j for j in (_to_rawjob(company, raw) for raw in data) if j is not None]


async def scrape_lever_many(companies: list[str]) -> list[RawJob]:
    """Scrape multiple Lever companies concurrently. Pre-filters at the
    scraper layer before per-board round-robin."""
    from compass.scrapers._interleave import round_robin_by_board
    from compass.scrapers._pre_filter import pre_filter_many

    if not companies:
        return []
    results = await asyncio.gather(*[scrape_lever(c) for c in companies], return_exceptions=True)
    per_board: list[list[RawJob]] = []
    for r in results:
        if isinstance(r, list):
            per_board.append(r)
        else:
            logger.warning("lever_many: unexpected exception: %s", r)
    return round_robin_by_board(pre_filter_many(per_board))
