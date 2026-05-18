"""
Greenhouse public API scraper.

Endpoint: GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs
No authentication required.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import date, datetime

import httpx

from compass.pipeline.state import RawJob

logger = logging.getLogger(__name__)

GREENHOUSE_BASE = "https://boards-api.greenhouse.io/v1/boards"
_REQUEST_TIMEOUT = 20.0
_USER_AGENT = "compass-job-scraper/0.1"


_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(raw: str) -> str:
    """Cheap HTML-to-text. Good enough for JD bodies — strips `<script>` / `<style>`
    blocks before tag removal so their content doesn't leak into the description."""
    text = _SCRIPT_STYLE_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


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
        return RawJob(
            company=board_token,
            title=raw["title"],
            url=raw["absolute_url"],
            source="greenhouse",
            location=(raw.get("location") or {}).get("name") if raw.get("location") else None,
            remote=None,
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
    """Scrape multiple Greenhouse boards concurrently."""
    if not board_tokens:
        return []
    results = await asyncio.gather(
        *[scrape_greenhouse(t) for t in board_tokens], return_exceptions=True
    )
    out: list[RawJob] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
        else:
            logger.warning("greenhouse_many: unexpected exception: %s", r)
    return out
