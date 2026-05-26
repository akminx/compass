"""Tests for compass.pipeline.location_filter.is_us_compatible — the
conservative non-US location gate added to intake_filter."""

from __future__ import annotations

import pytest

from compass.pipeline.location_filter import is_us_compatible


@pytest.mark.parametrize(
    "location",
    [
        "San Francisco, CA",
        "Test City, TS",
        "New York, NY",
        "Remote - US",
        "Remote (US)",
        "Seattle",
        "Boston, MA",
        "Plano, TX",
        "McLean, VA",
        "Charlotte, NC",
        "United States",
        "USA",
    ],
)
def test_us_locations_are_kept(location):
    keep, _ = is_us_compatible(location)
    assert keep is True, f"expected keep=True for {location!r}"


@pytest.mark.parametrize(
    "location",
    [
        "",
        None,
        "Remote",
        "Anywhere",
        "Multiple Locations",
        "N/A",
        "Worldwide",
    ],
)
def test_ambiguous_locations_are_kept_permissively(location):
    """When the ATS doesn't expose a country or only says 'Remote', we
    keep — better to score and drop later than to drop blindly."""
    keep, _ = is_us_compatible(location)
    assert keep is True


@pytest.mark.parametrize(
    "location",
    [
        "London, United Kingdom",
        "Remote - United Kingdom",
        "London",
        "Bengaluru, India",
        "Dublin, Ireland",
        "Berlin, Germany",
        "Tokyo, Japan",
        "Singapore",
        "Toronto, Canada",  # explicitly per preferences.md → US-only
        "Vancouver",
        "Sydney, Australia",
        "Tel Aviv, Israel",
        "São Paulo, Brazil",
        "Mexico City",
        "EMEA",
        "APAC",
    ],
)
def test_non_us_locations_are_dropped(location):
    keep, reason = is_us_compatible(location)
    assert keep is False, f"expected keep=False for {location!r}"
    assert "non-US location" in reason


def test_mixed_us_and_non_us_keeps():
    """If the JD lists both a US and non-US location ('London or NYC'),
    the user is US-eligible — keep it."""
    keep, _ = is_us_compatible("Remote - US or Canada")
    assert keep is True
    keep, _ = is_us_compatible("London or San Francisco")
    assert keep is True


def test_case_insensitive():
    keep, _ = is_us_compatible("LONDON, UNITED KINGDOM")
    assert keep is False
    keep, _ = is_us_compatible("austin, tx")
    assert keep is True
