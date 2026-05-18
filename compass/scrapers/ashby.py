"""
Ashby public API scraper.

Endpoint: GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true
No authentication required. Covers Sierra, Decagon, Cognition, Ramp, OpenAI, Cursor, and many more.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime

import httpx

from compass.pipeline.state import RawJob

logger = logging.getLogger(__name__)

ASHBY_BASE = "https://api.ashbyhq.com/posting-api/job-board"
_REQUEST_TIMEOUT = 20.0
_USER_AGENT = "compass-job-scraper/0.1"

# Parses compensation summaries like "$180K – $230K", "$120,000 - $160,000", "$120K - $160".
# Captures the K-suffix per-group so mixed forms parse correctly.
_COMP_RANGE_RE = re.compile(
    r"\$([\d,]+)([Kk])?\s*[–\-—]+\s*\$?([\d,]+)([Kk])?",
)


def _parse_money(token: str, k_suffix: str | None) -> int | None:
    try:
        n = int(token.replace(",", ""))
    except ValueError:
        return None
    return n * 1000 if k_suffix else n


def _parse_compensation(summary: str | None) -> tuple[int | None, int | None]:
    if not summary:
        return None, None
    m = _COMP_RANGE_RE.search(summary)
    if m is None:
        return None, None
    low_token, low_k, high_token, high_k = m.group(1), m.group(2), m.group(3), m.group(4)
    # If only one side has a K suffix (e.g. "$120K - 160"), assume both are K-denominated —
    # that's the common Ashby convention.
    if low_k and not high_k:
        high_k = low_k
    elif high_k and not low_k:
        low_k = high_k
    return _parse_money(low_token, low_k), _parse_money(high_token, high_k)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _to_rawjob(slug: str, raw: dict) -> RawJob | None:
    try:
        description = (raw.get("descriptionPlain") or "").strip()
        if not description:
            logger.warning(
                "ashby %s: empty description for %r — dropping (posting may use external HTML)",
                slug,
                raw.get("title", "?"),
            )
            return None
        comp = (
            (raw.get("compensation") or {}).get("compensationTierSummary")
            if raw.get("shouldDisplayCompensationOnJobBoard")
            else None
        )
        salary_min, salary_max = _parse_compensation(comp)
        # Most boards use `location`; a few legacy responses use `locationName`.
        # Empty string means "field present but null" — coerce to None.
        location = (raw.get("location") or raw.get("locationName") or "").strip() or None
        return RawJob(
            company=slug,
            title=raw["title"],
            url=raw["jobUrl"],
            source="ashby",
            location=location,
            remote=bool(raw.get("isRemote")) if "isRemote" in raw else None,
            salary_min=salary_min,
            salary_max=salary_max,
            description=description,
            date_posted=_parse_date(raw.get("publishedAt")),
        )
    except (KeyError, TypeError) as e:
        logger.warning("ashby: malformed job skipped: %s", e)
        return None


async def scrape_ashby(slug: str) -> list[RawJob]:
    """Scrape all open jobs from an Ashby job-board.

    Returns [] on any HTTP error — never raises. Pipeline must keep running
    when one ATS source is unavailable.
    """
    url = f"{ASHBY_BASE}/{slug}?includeCompensation=true"
    try:
        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("ashby %s: %s", slug, e)
        return []
    return [j for j in (_to_rawjob(slug, raw) for raw in data.get("jobs", [])) if j is not None]


async def scrape_ashby_many(slugs: list[str]) -> list[RawJob]:
    """Scrape multiple Ashby boards concurrently. Per-slug errors are logged, not raised."""
    if not slugs:
        return []
    results = await asyncio.gather(*[scrape_ashby(s) for s in slugs], return_exceptions=True)
    out: list[RawJob] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
        else:
            logger.warning("ashby_many: unexpected exception: %s", r)
    return out
