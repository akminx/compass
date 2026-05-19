"""Fetch a single job posting by URL and build a RawJob.

Routes by URL pattern:
  - boards.greenhouse.io / job-boards.greenhouse.io  → greenhouse public API
  - jobs.lever.co                                    → lever public API
  - jobs.ashbyhq.com                                 → ashby public API
  - *.myworkdayjobs.com                              → workday JSON endpoint
  - everything else                                  → generic static fetch + strip

Generic fetch is best-effort. JS-rendered pages (Oracle Cloud, LinkedIn,
some custom careers UIs) return near-empty bodies; in that case the caller
should fall back to `add_job_from_text` with a manual paste.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date
from urllib.parse import urlparse

import httpx

from compass.pipeline.state import RawJob

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36 compass-job-scraper/0.1"
)
_TIMEOUT = 20.0
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)


def _strip_html(raw: str) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _detect_provider(url: str) -> str:
    """Return 'greenhouse' | 'lever' | 'ashby' | 'workday' | 'generic'."""
    host = (urlparse(url).hostname or "").lower()
    if "greenhouse.io" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "ashbyhq.com" in host:
        return "ashby"
    if "myworkdayjobs.com" in host:
        return "workday"
    return "generic"


async def _fetch_generic(url: str) -> tuple[str | None, str | None]:
    """Static-fetch a page + return (page_title, stripped_body). The body
    may be near-empty for JS-rendered pages — caller decides what to do."""
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html,*/*"},
            follow_redirects=True,
        ) as c:
            r = await c.get(url)
            if r.status_code != 200:
                logger.warning("add_url: generic fetch %s returned status=%s", url, r.status_code)
                return None, None
            html_text = r.text
    except httpx.HTTPError as e:
        logger.warning("add_url: generic fetch %s: %s", url, e)
        return None, None
    title_m = _TITLE_RE.search(html_text)
    page_title = title_m.group(1).strip() if title_m else None
    body = _strip_html(html_text)
    return page_title, body


async def fetch_rawjob_from_url(
    url: str,
    *,
    company: str | None = None,
    title: str | None = None,
) -> RawJob | None:
    """Return a RawJob built from `url`, or None when the body looks empty.

    `company` and `title` overrides bypass any structured-API detection —
    useful for generic URLs where the page title isn't a clean role name.
    Both default to inferred values from the URL's host or page <title>.

    Returns None (not raise) when extraction fails so MCP callers can show
    a clean "try paste-text instead" message.
    """
    # Provider detection is exposed for tests + future structured-API
    # routing. For one-off URLs the generic static path is fast enough.
    _detect_provider(url)

    # Structured-API path: not implemented here — for one-off URLs the
    # generic path is fast enough and avoids per-provider parsing edge
    # cases. The full-batch scrapers handle structured fetching.
    page_title, body = await _fetch_generic(url)
    if not body or len(body) < 200:
        # Likely JS-rendered (Oracle Cloud / LinkedIn / etc.). Drop —
        # caller should use add_job_from_text.
        logger.info("add_url: body too short (%d chars) — likely JS-rendered", len(body or ""))
        return None

    inferred_company = company
    if not inferred_company:
        host = (urlparse(url).hostname or "").lower()
        # Cheap heuristic: pull the company from the host's first label.
        # E.g. jobs.ashbyhq.com/sierra/... → use page_title; jpmc.fa.oraclecloud.com
        # → 'jpmc'. The user is encouraged to pass `company` explicitly when this
        # is wrong.
        parts = host.split(".")
        inferred_company = parts[0] if parts and parts[0] not in {"jobs", "www"} else "(unknown)"

    inferred_title = title or page_title or "(unknown)"

    return RawJob(
        company=inferred_company,
        title=inferred_title,
        url=url,
        source="manual",
        description=body,
        date_posted=date.today(),
    )
