"""Regression: Workday _to_rawjob used to emit relative paths like
`/job/abc` as the RawJob.url, which then mangled through url_dedup into
the invalid string `https:///job/abc`. Fixed in 2026-05-19 wave-2 review."""

from __future__ import annotations

from compass.scrapers.workday import _to_rawjob


def test_absolute_apply_url_is_kept():
    raw = {"title": "AI Eng", "externalPath": "/job/123", "postedOn": "Posted Today"}
    rj = _to_rawjob("Citi", raw, "Build agents.", "https://example.com/apply/123")
    assert rj is not None
    assert rj.url == "https://example.com/apply/123"


def test_relative_externalpath_absolutized_against_base():
    """When the detail endpoint didn't return an externalUrl (apply_url=None),
    the relative `externalPath` must be combined with the tenant base URL
    instead of stored bare."""
    raw = {"title": "AI Eng", "externalPath": "/job/abc", "postedOn": "Posted Today"}
    rj = _to_rawjob(
        "Citi", raw, "Build agents.", None,
        base_url="https://citi.wd5.myworkdayjobs.com",
    )
    assert rj is not None
    assert rj.url == "https://citi.wd5.myworkdayjobs.com/job/abc"
    assert not rj.url.startswith("https:///")


def test_no_url_at_all_drops_job():
    """Without any URL source the job can't be dedup'd or applied to —
    drop with a warning rather than persist a broken vault row."""
    raw = {"title": "AI Eng", "externalPath": "", "postedOn": "Posted Today"}
    rj = _to_rawjob("Citi", raw, "Build agents.", None, base_url="https://x")
    assert rj is None


def test_externalpath_already_absolute_kept_as_is():
    """Some Workday tenants return a fully-qualified externalPath. Don't
    double-prefix the base URL."""
    raw = {
        "title": "AI Eng",
        "externalPath": "https://other.example.com/job/xyz",
        "postedOn": "Posted Today",
    }
    rj = _to_rawjob("Citi", raw, "Build agents.", None, base_url="https://x")
    assert rj is not None
    assert rj.url == "https://other.example.com/job/xyz"
