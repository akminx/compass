"""Regression tests for aliases + mtime-aware reload — both surfaced by the
2026-05-19 adversarial review.

Aliases bug: JPM's Workday/Oracle tenant slug is "jpmc" but the YAML lists
the company as "JPMorgan". Pre-fix, `get_tier("JPMC")` returned "unknown"
because no substring match. With aliases, `JPMC` → "JPMorgan" → apply-now.

Mtime-aware reload bug: long-running MCP server cached the YAML at startup;
edits to the YAML file were invisible until process restart.
"""

from __future__ import annotations

import time

import pytest

_BASE_YAML = """
schema_version: 1
companies:
  - company: JPMorgan
    aliases: [JPMC, JPM, JPMorgan Chase]
    tier: apply-now
    section: banks
    ats: {provider: manual, slug: oracle-cloud}
    interview_difficulty: hackerrank
"""


@pytest.fixture
def yaml_vault(temp_vault):
    (temp_vault / "_profile" / "target-companies.yaml").write_text(_BASE_YAML, encoding="utf-8")
    import compass.vault.target_companies as tc

    tc.refresh_yaml()
    yield temp_vault
    tc.refresh_yaml()


def test_alias_resolves_to_primary_tier(yaml_vault):
    """Every alias in the aliases list should resolve to the same tier as the
    primary name. This fixes the JPMC↔JPMorgan slug mismatch."""
    from compass.vault.target_companies import get_tier

    assert get_tier("JPMorgan") == "apply-now"
    assert get_tier("JPMC") == "apply-now"
    assert get_tier("JPM") == "apply-now"
    assert get_tier("JPMorgan Chase") == "apply-now"
    # Lowercase + whitespace shouldn't matter
    assert get_tier("jpmc") == "apply-now"
    assert get_tier("jp morgan chase") == "apply-now"


def test_alias_resolves_to_primary_meta(yaml_vault):
    """get_company_meta should also resolve aliases to the primary entry."""
    from compass.vault.target_companies import get_company_meta

    assert get_company_meta("JPMC")["company"] == "JPMorgan"
    assert get_company_meta("JPM")["company"] == "JPMorgan"


def test_yaml_reload_picks_up_disk_edits(yaml_vault):
    """Long-running MCP server should see YAML edits within one accessor call."""
    from compass.vault.target_companies import get_tier

    assert get_tier("JPMorgan") == "apply-now"

    # Edit the YAML on disk — flip tier
    yaml_path = yaml_vault / "_profile" / "target-companies.yaml"
    edited = yaml_path.read_text().replace("tier: apply-now", "tier: opportunistic")
    # Tiny sleep so the mtime resolution catches the change (some filesystems
    # only have second-level mtime granularity)
    time.sleep(0.01)
    yaml_path.write_text(edited)
    # Force mtime to definitely be newer
    import os

    now = time.time()
    os.utime(yaml_path, (now, now + 1))

    # No explicit refresh — accessor should auto-reload via mtime check
    assert get_tier("JPMorgan") == "opportunistic"


def test_yaml_deletion_clears_cache(yaml_vault):
    """If the YAML file is removed (vault wipe), accessors should return
    fallback values, not stale cache."""
    from compass.vault.target_companies import get_company_meta

    assert get_company_meta("JPMorgan") is not None

    (yaml_vault / "_profile" / "target-companies.yaml").unlink()
    assert get_company_meta("JPMorgan") is None
