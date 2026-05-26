"""
Greenhouse public API scraper.

Endpoint: GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs
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

GREENHOUSE_BASE = "https://boards-api.greenhouse.io/v1/boards"
_REQUEST_TIMEOUT = 20.0
_USER_AGENT = "compass-job-scraper/0.1"


from compass.scrapers._html import strip_html as _strip_html


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _to_rawjob(board_token: str, raw: dict) -> RawJob | None:
    try:
        description = _strip_html(raw.get("content", ""))
        if not description:
            # Empty content means the API contract changed (e.g. content=true
            # dropped). Sending an empty JD downstream causes the extract LLM
            # to hallucinate skills from the title alone — drop loudly instead.
            logger.warning(
                "greenhouse %s: empty content for %r — dropping (API may have changed)",
                board_token,
                raw.get("title", "?"),
            )
            return None
        location_str = (raw.get("location") or {}).get("name") if raw.get("location") else None
        return RawJob(
            company=board_token,
            title=raw["title"],
            url=raw["absolute_url"],
            source="greenhouse",
            location=location_str,
            remote=infer_remote_policy(location_str),
            salary_min=None,
            salary_max=None,
            description=description,
            date_posted=_parse_date(raw.get("updated_at")),
        )
    except (KeyError, TypeError) as e:
        logger.warning("greenhouse: malformed job entry skipped: %s", e)
        return None


async def scrape_greenhouse(board_token: str) -> list[RawJob]:
    """Scrape all open jobs from a Greenhouse board.

    Returns [] on any HTTP error — never raises. Pipeline must keep running
    when one ATS source is unavailable.
    """
    # `?content=true` is REQUIRED — without it the API returns job metadata only
    # (no `content` field), and downstream LLM nodes silently hallucinate skills
    # from the title alone.
    url = f"{GREENHOUSE_BASE}/{board_token}/jobs?content=true"
    try:
        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("greenhouse %s: %s", board_token, e)
        return []
    jobs = [
        j for j in (_to_rawjob(board_token, raw) for raw in data.get("jobs", [])) if j is not None
    ]
    return jobs


async def scrape_greenhouse_many(board_tokens: list[str]) -> list[RawJob]:
    """Scrape multiple Greenhouse boards concurrently. Pre-filters at the
    scraper layer (title-reject, jd-reject, non-US location) BEFORE the
    per-board round-robin, so high-volume boards don't burn round-robin
    slots on title-doomed jobs. Returns a per-board interleaved flat list."""
    from compass.scrapers._interleave import round_robin_by_board
    from compass.scrapers._pre_filter import pre_filter_many

    if not board_tokens:
        return []
    results = await asyncio.gather(
        *[scrape_greenhouse(t) for t in board_tokens], return_exceptions=True
    )
    per_board: list[list[RawJob]] = []
    for r in results:
        if isinstance(r, list):
            per_board.append(r)
        else:
            logger.warning("greenhouse_many: unexpected exception: %s", r)
    return round_robin_by_board(pre_filter_many(per_board))
