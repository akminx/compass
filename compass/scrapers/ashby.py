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

# Parses compensation summaries like "$180K – $230K", "$120,000 - $160,000"
_COMP_RANGE_RE = re.compile(
    r"\$([\d,]+)(?:[Kk])?\s*[–\-—to]+\s*\$?([\d,]+)(?:[Kk])?",
)


def _parse_money(token: str, is_k: bool) -> int | None:
    try:
        n = int(token.replace(",", ""))
    except ValueError:
        return None
    return n * 1000 if is_k else n


def _parse_compensation(summary: str | None) -> tuple[int | None, int | None]:
    if not summary:
        return None, None
    m = _COMP_RANGE_RE.search(summary)
    if m:
        is_k = "K" in summary or "k" in summary
        return _parse_money(m.group(1), is_k), _parse_money(m.group(2), is_k)
    return None, None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _to_rawjob(slug: str, raw: dict) -> RawJob | None:
    try:
        comp = (
            (raw.get("compensation") or {}).get("compensationTierSummary")
            if raw.get("shouldDisplayCompensationOnJobBoard")
            else None
        )
        salary_min, salary_max = _parse_compensation(comp)
        return RawJob(
            company=slug,
            title=raw["title"],
            url=raw["jobUrl"],
            source="ashby",
            location=raw.get("locationName") or None,
            remote=None,
            salary_min=salary_min,
            salary_max=salary_max,
            description=raw.get("descriptionPlain", ""),
            date_posted=_parse_date(raw.get("publishedAt")),
        )
    except (KeyError, TypeError) as e:
        logger.warning("ashby: malformed job skipped: %s", e)
        return None


async def scrape_ashby(slug: str) -> list[RawJob]:
    url = f"{ASHBY_BASE}/{slug}?includeCompensation=true"
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("ashby %s: %s", slug, e)
        return []
    return [j for j in (_to_rawjob(slug, raw) for raw in data.get("jobs", [])) if j is not None]


async def scrape_ashby_many(slugs: list[str]) -> list[RawJob]:
    if not slugs:
        return []
    results = await asyncio.gather(*[scrape_ashby(s) for s in slugs], return_exceptions=True)
    out: list[RawJob] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
    return out
