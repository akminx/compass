"""URL normalization for deduplication.

The pipeline dedups jobs by URL — but raw URLs vary in case, scheme, trailing
slashes, and tracking params. Two scrapers (or the same scraper across runs)
can produce different strings for the same job:

  https://jobs.ashbyhq.com/acme/abc
  https://jobs.ashbyhq.com/acme/abc/
  https://jobs.ashbyhq.com/acme/abc?utm_source=google
  http://JOBS.ASHBYHQ.COM/acme/abc

Without normalization the dedup at `_vault_url_set()` and the URL-match in
`write_job_note()` treat all of these as distinct, leading to duplicate
JobNotes for the same role.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that are tracking-only and don't change which job a URL points
# to. Strip them before dedup so the same JD via Google + LinkedIn refer counts
# once. Conservative list — anything not here is preserved.
_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "msclkid",
        "ref",
        "ref_src",
        "referer",
        "referrer",
        "src",
        "source",
        "campaign",
    }
)


def normalize_url(url: str) -> str:
    """Return a canonical form of `url` for dedup purposes.

    Normalization rules:
      - Lowercase the scheme + host (URL components below the path are
        case-insensitive per RFC 3986).
      - Strip default ports (`:80` for http, `:443` for https).
      - Strip trailing slash from the path (treat /abc and /abc/ as same).
      - Remove known tracking query params (utm_*, gclid, etc.).
      - Sort remaining query params alphabetically.
      - Drop the URL fragment (#section anchors are client-side only).
      - HTTP and HTTPS variants of the same URL collapse to https.

    NOT normalized:
      - User-info, port (non-default).
      - Path case (servers may treat /Foo and /foo differently).
      - Non-tracking query params.

    Returns the original `url` unchanged if parsing fails — dedup degrades
    gracefully to per-string matching for that one URL rather than crashing
    the pipeline.
    """
    if not url:
        return url
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    scheme = parts.scheme.lower() or "https"
    # http and https collapse — same job, both schemes, one canonical.
    if scheme == "http":
        scheme = "https"
    host = (parts.hostname or "").lower()
    # Reconstruct netloc — drop user-info (rare in JD URLs, no signal) and
    # drop default ports.
    if parts.port and not (
        (scheme == "https" and parts.port == 443) or (scheme == "http" and parts.port == 80)
    ):
        netloc = f"{host}:{parts.port}"
    else:
        netloc = host
    path = parts.path.rstrip("/")
    # Strip tracking params, sort the rest.
    kept = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    )
    query = urlencode(kept)
    # Drop fragment — anchors are client-side, not a different resource.
    return urlunsplit((scheme, netloc, path, query, ""))
