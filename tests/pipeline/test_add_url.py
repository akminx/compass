"""add_job_from_url unit tests — provider detection + generic fetch fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from compass.pipeline.add_url import _detect_provider, fetch_rawjob_from_url


def test_detect_provider_greenhouse():
    assert _detect_provider("https://boards.greenhouse.io/databricks/jobs/123") == "greenhouse"
    assert _detect_provider("https://job-boards.greenhouse.io/anthropic/jobs/x") == "greenhouse"


def test_detect_provider_lever():
    assert _detect_provider("https://jobs.lever.co/company/abc") == "lever"


def test_detect_provider_ashby():
    assert _detect_provider("https://jobs.ashbyhq.com/sierra/agent-eng") == "ashby"


def test_detect_provider_workday():
    assert _detect_provider("https://citi.wd5.myworkdayjobs.com/2/job/123") == "workday"


def test_detect_provider_oracle_cloud_is_generic():
    """JPM and other Oracle Cloud careers pages don't have a structured API
    we can probe — they fall to the generic static-fetch path."""
    assert _detect_provider("https://jpmc.fa.oraclecloud.com/hcmUI/...") == "generic"


def test_detect_provider_linkedin_is_generic():
    assert _detect_provider("https://www.linkedin.com/jobs/view/123") == "generic"


@pytest.mark.asyncio
async def test_fetch_too_short_body_returns_none():
    """JS-rendered pages return near-empty bodies (Oracle Cloud / LinkedIn).
    The fetcher returns None rather than building a bogus RawJob — caller is
    expected to fall back to `add_job_from_text` with a manual paste."""
    with patch(
        "compass.pipeline.add_url._fetch_generic",
        new=AsyncMock(return_value=("Page Title", "tiny body")),
    ):
        rj = await fetch_rawjob_from_url("https://jpmc.fa.oraclecloud.com/x")
        assert rj is None


@pytest.mark.asyncio
async def test_fetch_real_body_builds_rawjob():
    long_body = "Build LangGraph agents in production. " * 30
    with patch(
        "compass.pipeline.add_url._fetch_generic",
        new=AsyncMock(return_value=("Agent Engineer — Acme Co", long_body)),
    ):
        rj = await fetch_rawjob_from_url("https://acme.com/careers/abc")
        assert rj is not None
        assert rj.title == "Agent Engineer — Acme Co"
        assert rj.description == long_body
        assert rj.url == "https://acme.com/careers/abc"
        assert rj.source == "manual"


@pytest.mark.asyncio
async def test_fetch_explicit_company_and_title_overrides():
    long_body = "Build agents. " * 50
    with patch(
        "compass.pipeline.add_url._fetch_generic",
        new=AsyncMock(return_value=("Wrong Page Title", long_body)),
    ):
        rj = await fetch_rawjob_from_url(
            "https://jpmc.fa.oraclecloud.com/x",
            company="JPMorgan",
            title="AI Engineer, LLM Suite",
        )
        assert rj is not None
        assert rj.company == "JPMorgan"
        assert rj.title == "AI Engineer, LLM Suite"
