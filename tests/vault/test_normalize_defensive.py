"""Regression — `taxonomy.normalize` accepts defensively-bad inputs without
crashing. A JobNote with a YAML list-entry written as `- ` parses as `[None]`;
without the guard, gap_aggregator.aggregate() crashed the whole regenerate()
call on a single malformed JobNote.

Wave-3 adversarial review, 2026-05-19.
"""

from __future__ import annotations

from compass.vault.taxonomy import normalize


def test_none_returns_none():
    assert normalize(None) is None  # type: ignore[arg-type]


def test_empty_string_returns_none():
    assert normalize("") is None


def test_whitespace_string_returns_none():
    assert normalize("   ") is None


def test_non_str_returns_none():
    """Defensive: a dict/list/int slipping through YAML parsing shouldn't crash."""
    assert normalize(123) is None  # type: ignore[arg-type]
    assert normalize({}) is None  # type: ignore[arg-type]
    assert normalize([]) is None  # type: ignore[arg-type]


def test_valid_skill_still_works():
    """Confirm the defensive guard didn't break the happy path."""
    assert normalize("Python") == "Python"
