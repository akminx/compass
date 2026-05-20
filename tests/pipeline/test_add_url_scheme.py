"""Regression tests for the URL scheme allowlist — added 2026-05-19 after the
adversarial review found that javascript:/ftp:/file:/data: URLs reached httpx
unchecked."""

from __future__ import annotations

import pytest

from compass.pipeline.add_url import fetch_rawjob_from_url


@pytest.mark.asyncio
async def test_javascript_scheme_rejected():
    """javascript: URLs must never be fetched — they can't possibly contain
    a JD body and they may indicate copy-paste from a malicious source."""
    assert await fetch_rawjob_from_url("javascript:alert(1)") is None


@pytest.mark.asyncio
async def test_file_scheme_rejected():
    """file:// would expose local filesystem to the fetch path. Block."""
    assert await fetch_rawjob_from_url("file:///etc/passwd") is None


@pytest.mark.asyncio
async def test_ftp_scheme_rejected():
    """ftp:// isn't where JDs live. Block."""
    assert await fetch_rawjob_from_url("ftp://example.com/job") is None


@pytest.mark.asyncio
async def test_data_scheme_rejected():
    """data: URLs encode payloads inline — not a JD source."""
    assert await fetch_rawjob_from_url("data:text/plain,fake-jd") is None


@pytest.mark.asyncio
async def test_url_with_no_hostname_rejected():
    """Empty / fragment-only URLs have no host to fetch from."""
    assert await fetch_rawjob_from_url("https://") is None
    assert await fetch_rawjob_from_url("https:///path") is None
    assert await fetch_rawjob_from_url("") is None


@pytest.mark.asyncio
async def test_http_and_https_allowed():
    """http and https are the only allowed schemes. Body-length check still
    applies; mocking the fetcher to return a long body confirms scheme passes."""
    from unittest.mock import AsyncMock, patch

    with patch(
        "compass.pipeline.add_url._fetch_generic",
        new=AsyncMock(return_value=("Title", "Real JD body. " * 100)),
    ):
        rj_https = await fetch_rawjob_from_url("https://example.com/job")
        rj_http = await fetch_rawjob_from_url("http://example.com/job")
    assert rj_https is not None
    assert rj_http is not None
