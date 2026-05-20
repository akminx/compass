"""
Workday public JSON-endpoint scraper.

Endpoint: POST https://{tenant}.{subdomain}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs

Workday's careers UI is a JavaScript SPA, but every tenant exposes an
unauthenticated JSON endpoint behind it that serves the same paginated list.
No auth, no cookies, no anti-bot — the SPA hits this same URL.

The slug format the rest of Compass uses is `{subdomain}/{tenant}/{site}` —
e.g. `wd5/citi/2`, `wd1/wf/WellsFargoJobs`. The YAML's `ats.slug` for a
Workday-provider entry must be in this `wdN/tenant/site` form. The slug is
parsed and joined back into the full URL at request time.

Tenant/site discovery is per-company manual work — public careers pages all
embed the URL in their initial JS bundle. There's no programmatic way to
enumerate them. The verified set as of 2026-05-19:
  wf/WellsFargoJobs/wd1            Wells Fargo
  citi/2/wd5                       Citi
  adobe/external_experienced/wd5   Adobe
  ms/External/wd5                  Morgan Stanley
  blackrock/BlackRock_Professional/wd1  BlackRock
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import date

import httpx

from compass.pipeline.state import RawJob
from compass.scrapers._remote_parser import infer_remote_policy

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 25.0
_USER_AGENT = "compass-job-scraper/0.1"
# Workday paginates at 20 by default; ask for 50 per request to reduce round-trips.
_PAGE_SIZE = 50
# Cap iterations so a runaway pagination loop (or a board that returns
# `total` lower than the actual count and never converges) can't burn
# unbounded requests. 10 pages × 50 = 500 jobs per board, more than enough.
_MAX_PAGES = 10

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(raw: str) -> str:
    """Same approach as greenhouse/lever: strip script/style blocks then tags."""
    text = _SCRIPT_STYLE_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_slug(slug: str) -> tuple[str, str, str] | None:
    """Parse `subdomain/tenant/site` (e.g. `wd5/citi/2`) into a 3-tuple.

    Returns None for malformed slugs so the orchestrator can log + skip
    without raising. The subdomain (wd1/wd3/wd5/wd12/...) is per-tenant —
    don't try to auto-detect; the YAML carries it.
    """
    parts = [p for p in slug.split("/") if p]
    if len(parts) != 3:
        return None
    subdomain, tenant, site = parts
    if not subdomain.startswith("wd"):
        return None
    return subdomain, tenant, site


def _parse_posted_on(value: str | None) -> date | None:
    """Workday's `postedOn` is a free-text relative phrase like
    'Posted Yesterday', 'Posted 5 Days Ago', 'Posted 30+ Days Ago'. The JSON
    endpoint does NOT include an ISO timestamp — `postedOn` is the only signal
    we have. Convert to an approximate date so the recency sort in graph.py
    can still rank.
    """
    if not value:
        return None
    today = date.today()
    v = value.lower()
    if "today" in v:
        return today
    if "yesterday" in v:
        from datetime import timedelta

        return today - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*day", v)
    if m:
        from datetime import timedelta

        return today - timedelta(days=int(m.group(1)))
    m = re.search(r"(\d+)\+?\s*month", v)
    if m:
        from datetime import timedelta

        return today - timedelta(days=int(m.group(1)) * 30)
    return None


async def _fetch_job_detail(
    client: httpx.AsyncClient, base: str, ext_path: str
) -> tuple[str | None, str | None]:
    """Fetch the full JD body + apply URL for one job. Returns (body, apply_url).

    Workday's list endpoint returns short summaries; the actual JD lives at
    /jobs/{external_path}. That endpoint is also unauthenticated JSON.
    """
    url = f"{base}{ext_path}"
    try:
        r = await client.get(url)
        if r.status_code != 200:
            return None, None
        data = r.json()
        body_html = (data.get("jobPostingInfo") or {}).get("jobDescription") or ""
        apply_url = (data.get("jobPostingInfo") or {}).get("externalUrl")
        return _strip_html(body_html), apply_url
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("workday detail %s: %s", url, e)
        return None, None


def _to_rawjob(
    company_label: str,
    raw: dict,
    body: str | None,
    apply_url: str | None,
    base_url: str = "",
) -> RawJob | None:
    """Build a RawJob from a Workday list-page entry + (optional) detail body.

    `base_url` is the Workday tenant origin (e.g. `https://citi.wd5.myworkdayjobs.com`)
    used to absolutize relative `externalPath` values when the detail endpoint
    didn't return an `externalUrl`. Without this, the `RawJob.url` would be a
    bare path like `/job/abc` that `normalize_url` then mangles into the
    invalid string `https:///job/abc`, breaking dedup and apply-link clicks.
    """
    try:
        title = raw.get("title")
        if not title:
            return None
        if not body:
            # Without a body the score node will hallucinate from title alone.
            # Workday rate-limits detail fetches more aggressively than list
            # fetches, so we sometimes get list-only entries. Drop them.
            return None
        # Resolve the canonical URL: prefer the detail endpoint's `externalUrl`;
        # fall back to absolutizing `externalPath` against the tenant origin.
        url = apply_url
        if not url:
            ext_path = raw.get("externalPath") or ""
            if ext_path and base_url and ext_path.startswith("/"):
                url = f"{base_url}{ext_path}"
            elif ext_path.startswith("http"):
                url = ext_path
        if not url:
            # No usable URL at all — skip rather than write a broken vault row.
            logger.warning(
                "workday: no usable URL for %r at %s (skipping)",
                title,
                company_label,
            )
            return None
        location_str = raw.get("locationsText") or None
        return RawJob(
            company=company_label,
            title=title,
            url=url,
            source="workday",  # type: ignore[arg-type]
            location=location_str,
            remote=infer_remote_policy(location_str),
            salary_min=None,
            salary_max=None,
            description=body,
            date_posted=_parse_posted_on(raw.get("postedOn")),
        )
    except (KeyError, TypeError) as e:
        logger.warning("workday: malformed entry skipped: %s", e)
        return None


async def scrape_workday(slug: str, company_label: str | None = None) -> list[RawJob]:
    """Scrape all open jobs from a Workday tenant/site.

    `slug` is `subdomain/tenant/site` (e.g. `wd5/citi/2`). `company_label`
    overrides the displayed company name — useful when the tenant token is
    cryptic (e.g. `ms` → Morgan Stanley, `wf` → Wells Fargo).

    Returns [] on HTTP error — never raises.
    """
    parsed = _parse_slug(slug)
    if parsed is None:
        logger.warning("workday: malformed slug %r (expected subdomain/tenant/site)", slug)
        return []
    subdomain, tenant, site = parsed
    base = f"https://{tenant}.{subdomain}.myworkdayjobs.com"
    list_url = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    label = company_label or tenant

    jobs: list[RawJob] = []
    offset = 0
    async with httpx.AsyncClient(
        timeout=_REQUEST_TIMEOUT, headers={"User-Agent": _USER_AGENT}
    ) as client:
        for _ in range(_MAX_PAGES):
            try:
                resp = await client.post(
                    list_url,
                    json={
                        "limit": _PAGE_SIZE,
                        "offset": offset,
                        "searchText": "",
                        "appliedFacets": {},
                    },
                )
                if resp.status_code != 200:
                    logger.warning("workday %s: status=%s", label, resp.status_code)
                    break
                data = resp.json()
            except (httpx.HTTPError, ValueError) as e:
                logger.warning("workday %s: %s", label, e)
                break

            postings = data.get("jobPostings") or []
            if not postings:
                break

            # Fetch detail bodies in parallel (modest concurrency to be a
            # good citizen — Workday will rate-limit aggressive scrapers).
            detail_results = await asyncio.gather(
                *[_fetch_job_detail(client, base, p.get("externalPath", "")) for p in postings],
                return_exceptions=True,
            )

            for raw, detail in zip(postings, detail_results, strict=True):
                if isinstance(detail, BaseException):
                    continue
                body, apply_url = detail
                rj = _to_rawjob(label, raw, body, apply_url, base_url=base)
                if rj is not None:
                    jobs.append(rj)

            offset += _PAGE_SIZE
            total = data.get("total")
            if total is not None and offset >= total:
                break

    return jobs


async def scrape_workday_many(slugs: list[str]) -> list[RawJob]:
    """Scrape multiple Workday tenants concurrently. Each slug is the full
    `subdomain/tenant/site` form."""
    if not slugs:
        return []
    results = await asyncio.gather(*[scrape_workday(s) for s in slugs], return_exceptions=True)
    out: list[RawJob] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
        else:
            logger.warning("workday_many: unexpected exception: %s", r)
    return out
