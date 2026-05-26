"""Tests for compass.scrapers._pre_filter — the title/jd/location predicates
applied at the scraper layer, BEFORE round_robin_by_board, so the global cap
isn't burned on title-doomed jobs."""

from __future__ import annotations

from datetime import date

import pytest

from compass.pipeline.state import RawJob
from compass.scrapers._pre_filter import pre_filter_board, pre_filter_many


def _job(
    title: str,
    company: str = "Acme",
    location: str = "Test City, TS",
    body: str = "Build great agentic systems.",
) -> RawJob:
    return RawJob(
        company=company,
        title=title,
        url=f"https://x/{hash((company, title))}",
        source="manual",
        description=body,
        location=location,
        date_posted=date(2026, 5, 20),
    )


_RULES_REAL = {
    "title": ["senior", "sr.", "staff", "principal", "lead", "director", "architect", "manager"],
    "jd": ["5+ years", "6+ years", "7+ years", "phd required"],
}


def test_kept_when_no_rules_match():
    jobs = [_job("Software Engineer"), _job("AI Engineer")]
    kept, dropped = pre_filter_board(jobs, _RULES_REAL)
    assert len(kept) == 2
    assert dropped == []


def test_title_reject_drops_with_reason():
    jobs = [_job("Senior Software Engineer"), _job("Software Engineer")]
    kept, dropped = pre_filter_board(jobs, _RULES_REAL)
    assert len(kept) == 1
    assert kept[0].title == "Software Engineer"
    assert len(dropped) == 1
    assert "title rejects" in dropped[0][1]
    assert "senior" in dropped[0][1]


def test_jd_reject_drops_with_reason():
    jobs = [_job("Engineer", body="Must have 5+ years building distributed systems.")]
    kept, dropped = pre_filter_board(jobs, _RULES_REAL)
    assert kept == []
    assert "jd rejects" in dropped[0][1]
    assert "5+ years" in dropped[0][1]


def test_location_reject_drops_with_reason():
    jobs = [_job("Engineer", location="London, United Kingdom")]
    kept, dropped = pre_filter_board(jobs, _RULES_REAL)
    assert kept == []
    assert "non-US location" in dropped[0][1]


def test_first_matching_rule_wins():
    """A job that violates BOTH a title rule and a location rule is logged
    only once — order: title → jd → location. Caller gets the title reason."""
    jobs = [_job("Senior Engineer", location="London")]
    kept, dropped = pre_filter_board(jobs, _RULES_REAL)
    assert kept == []
    assert len(dropped) == 1
    assert "title rejects" in dropped[0][1]


def test_pre_filter_many_preserves_board_grouping(temp_vault):
    """Multi-board input: each board's filtered list comes back in the same
    position. Empty input → empty output."""
    prefs = temp_vault / "_profile" / "preferences.md"
    prefs.write_text(
        "---\ntype: profile\n---\n\n"
        "```yaml\nreject_if_title_contains:\n  - Senior\nreject_if_jd_contains: []\n```\n"
    )
    board_a = [_job("Software Engineer", company="A"), _job("Senior Engineer", company="A")]
    board_b = [_job("AI Engineer", company="B")]
    board_c: list[RawJob] = []

    out = pre_filter_many([board_a, board_b, board_c])
    assert len(out) == 3
    assert len(out[0]) == 1  # board_a dropped 1
    assert len(out[1]) == 1  # board_b kept its 1
    assert out[2] == []  # board_c stays empty


def test_signal_density_improves_per_board():
    """Regression scenario: MongoDB-style high-volume board where 70% of titles
    are senior-tier. Pre-fix, round-robin would pick 5 jobs from this board
    and have 3-4 of them dropped at intake_filter. Post-fix, pre_filter
    drops them at the scraper level so round-robin sees only the eligible 30%."""
    titles = [
        "Senior Software Engineer", "Staff Engineer", "Principal Architect",
        "Engineering Manager", "Director of Engineering",
        "Software Engineer", "AI Engineer", "Platform Engineer",
    ]
    board = [_job(t, company="MongoDB") for t in titles]
    kept, dropped = pre_filter_board(board, _RULES_REAL)
    # 5 senior+ titles dropped, 3 ICs survive
    assert {j.title for j in kept} == {"Software Engineer", "AI Engineer", "Platform Engineer"}
    assert len(dropped) == 5


@pytest.mark.asyncio
async def test_greenhouse_many_applies_pre_filter(temp_vault):
    """End-to-end at the scraper level: senior-titled jobs from the scraper
    don't reach the round-robin output."""
    from unittest.mock import patch

    from compass.scrapers import greenhouse

    async def fake_one(token):
        return [
            _job("Senior Engineer", company=token),
            _job("Software Engineer", company=token),
            _job("Engineering Manager", company=token),
            _job("AI Engineer", company=token),
        ]

    # Seed preferences so load_reject_rules returns the real list
    prefs = temp_vault / "_profile" / "preferences.md"
    prefs.write_text(
        "---\ntype: profile\n---\n\n"
        "```yaml\n"
        "reject_if_title_contains:\n"
        "  - Senior\n"
        "  - Manager\n"
        "reject_if_jd_contains: []\n"
        "```\n"
    )

    with patch.object(greenhouse, "scrape_greenhouse", side_effect=fake_one):
        out = await greenhouse.scrape_greenhouse_many(["mongodb", "anthropic"])

    titles = [j.title for j in out]
    # Senior + Manager titles dropped; only "Software Engineer" and "AI Engineer" survive
    assert "Senior Engineer" not in titles
    assert "Engineering Manager" not in titles
    assert titles.count("Software Engineer") == 2
    assert titles.count("AI Engineer") == 2
    # Interleaved: m-SWE, a-SWE, m-AI, a-AI
    companies = [j.company for j in out]
    assert companies[:2] == ["mongodb", "anthropic"]
