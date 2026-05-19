"""YAML-driven per-company metadata accessors. Coexist with the legacy
markdown-based `get_tier`."""

from __future__ import annotations

import pytest

_SAMPLE_YAML = """
schema_version: 1
companies:
  - company: Databricks
    tier: apply-now
    section: data-ai-infra
    ats: {provider: greenhouse, slug: databricks}
    geos: [NYC, SF]
    interview_difficulty: lc-medium-hard
    cisco_adjacency: low
    notes: "Mosaic AI Agent Framework"

  - company: New Relic
    tier: apply-now
    section: observability-aiops
    ats: {provider: greenhouse, slug: newrelic}
    geos: [SF, Remote]
    interview_difficulty: lc-medium
    cisco_adjacency: high
    notes: "AI observability"

  - company: TypoCo
    tier: apply-now
    ats: {provider: greenhouse, slug: typoco}
    interview_difficulty: super-easy   # invalid Literal — must collapse to "unknown"
    cisco_adjacency: very-high         # invalid — must collapse to "none"
"""


@pytest.fixture
def yaml_vault(temp_vault, monkeypatch):
    (temp_vault / "_profile" / "target-companies.yaml").write_text(_SAMPLE_YAML, encoding="utf-8")
    import compass.vault.target_companies as tc

    tc.refresh_yaml()
    yield temp_vault
    # Reset module-level cache between tests
    tc.refresh_yaml()


def test_get_company_meta_returns_full_entry(yaml_vault):
    from compass.vault.target_companies import get_company_meta

    meta = get_company_meta("Databricks")
    assert meta is not None
    assert meta["tier"] == "apply-now"
    assert meta["ats"]["slug"] == "databricks"
    assert "NYC" in meta["geos"]


def test_get_interview_difficulty_known_value(yaml_vault):
    from compass.vault.target_companies import get_interview_difficulty

    assert get_interview_difficulty("Databricks") == "lc-medium-hard"
    assert get_interview_difficulty("New Relic") == "lc-medium"


def test_get_interview_difficulty_invalid_collapses_to_unknown(yaml_vault):
    """Hand-edited YAML may carry typos. Accessor must collapse to "unknown"
    so JobNote Literal validation never fails on human edits."""
    from compass.vault.target_companies import get_interview_difficulty

    assert get_interview_difficulty("TypoCo") == "unknown"


def test_get_interview_difficulty_unknown_company(yaml_vault):
    from compass.vault.target_companies import get_interview_difficulty

    assert get_interview_difficulty("CompanyNotInYAML") == "unknown"


def test_get_cisco_adjacency_known_value(yaml_vault):
    from compass.vault.target_companies import get_cisco_adjacency

    assert get_cisco_adjacency("New Relic") == "high"
    assert get_cisco_adjacency("Databricks") == "low"


def test_get_cisco_adjacency_invalid_collapses_to_none(yaml_vault):
    from compass.vault.target_companies import get_cisco_adjacency

    assert get_cisco_adjacency("TypoCo") == "none"


def test_get_cisco_adjacency_unknown_company_defaults_to_none(yaml_vault):
    from compass.vault.target_companies import get_cisco_adjacency

    assert get_cisco_adjacency("RandomCo") == "none"


def test_get_ats_returns_tuple(yaml_vault):
    from compass.vault.target_companies import get_ats

    assert get_ats("Databricks") == ("greenhouse", "databricks")


def test_get_ats_returns_none_for_unknown_company(yaml_vault):
    from compass.vault.target_companies import get_ats

    assert get_ats("RandomCo") is None


def test_list_yaml_companies_tier_filter(yaml_vault):
    from compass.vault.target_companies import list_yaml_companies

    assert len(list_yaml_companies()) == 3
    assert len(list_yaml_companies(tier_filter="apply-now")) == 3
    assert len(list_yaml_companies(tier_filter="stretch")) == 0


def test_bidirectional_substring_match(yaml_vault):
    """`get_company_meta("Databricks Inc")` should still find the "Databricks"
    entry — same substring fallback as `get_tier`."""
    from compass.vault.target_companies import get_company_meta

    meta = get_company_meta("Databricks Inc")
    assert meta is not None
    assert meta["company"] == "Databricks"
