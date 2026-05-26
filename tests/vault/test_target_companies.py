import pytest

TIERED_MD = """---
type: profile
---
# Target Companies

## Tier `apply-now`

### Top-tier
| Company | Title | Geo |
|---|---|---|
| AgentCo | Agent Engineer | SF |
| BotCo | MTS | SF |
| Ramp | Engineer | NYC |

### Big tech
| Company | Notes |
|---|---|
| TierCloudCo Agent Platform | Remote |
| TierMobileCo Intelligence Frameworks | Remote |

## Tier `6-month`

| Company | Title |
|---|---|
| OpenAI | Member of Technical Staff |
| Cursor | Frontend |

## Tier `stretch`

| Company | Why |
|---|---|
| Anthropic | dream role |
"""


@pytest.fixture
def tiered_vault(tmp_path, monkeypatch):
    vault = tmp_path / "v"
    (vault / "_profile").mkdir(parents=True)
    (vault / "_profile" / "target-companies.md").write_text(TIERED_MD)
    import compass.config as cfg

    monkeypatch.setattr(cfg, "VAULT_PATH", vault)
    import compass.vault.target_companies as tc

    tc.refresh()
    return vault


def test_get_tier_apply_now(tiered_vault):
    from compass.vault.target_companies import get_tier

    assert get_tier("AgentCo") == "apply-now"
    assert get_tier("Ramp") == "apply-now"
    assert get_tier("TierMobileCo Intelligence Frameworks") == "apply-now"


def test_get_tier_six_month(tiered_vault):
    from compass.vault.target_companies import get_tier

    assert get_tier("OpenAI") == "6-month"
    assert get_tier("Cursor") == "6-month"


def test_get_tier_stretch(tiered_vault):
    from compass.vault.target_companies import get_tier

    assert get_tier("Anthropic") == "stretch"


def test_get_tier_unknown_company(tiered_vault):
    from compass.vault.target_companies import get_tier

    assert get_tier("Random Inc") == "unknown"


def test_case_insensitive_normalization(tiered_vault):
    from compass.vault.target_companies import get_tier

    assert get_tier("agentco") == "apply-now"
    assert get_tier("AGENTCO") == "apply-now"
    # Whitespace + casing normalization: "Agent Co" / "agent co" should also resolve
    assert get_tier("agent co") == "apply-now"


def test_missing_file_returns_unknown(tmp_path, monkeypatch):
    import compass.config as cfg
    import compass.vault.target_companies as tc

    monkeypatch.setattr(cfg, "VAULT_PATH", tmp_path)
    tc.refresh()
    assert tc.get_tier("AgentCo") == "unknown"


def test_refresh_picks_up_edits(tiered_vault):
    from compass.vault.target_companies import get_tier, refresh

    new = TIERED_MD.replace(
        "| Anthropic | dream role |",
        "| Anthropic | nope |\n| NewCo | x |",
    )
    (tiered_vault / "_profile" / "target-companies.md").write_text(
        new + "\n## Tier `apply-now`\n\n| Company | Notes |\n|---|---|\n| NewCo | added |\n"
    )
    refresh()
    assert get_tier("NewCo") == "apply-now"


def test_multiple_adjacent_tables_one_tier(tmp_path, monkeypatch):
    """Parser must handle two tables back-to-back under one tier heading
    (the real target-companies.md has 'Top-tier startups' and 'Big tech' under
    apply-now)."""
    md = """## Tier `apply-now`

### Startups
| Company | Geo |
|---|---|
| AgentCo | SF |
### Big tech
| Company | Notes |
|---|---|
| TierCloudCo | Remote |
"""
    vault = tmp_path / "v"
    (vault / "_profile").mkdir(parents=True)
    (vault / "_profile" / "target-companies.md").write_text(md)
    import compass.config as cfg
    import compass.vault.target_companies as tc

    monkeypatch.setattr(cfg, "VAULT_PATH", vault)
    tc.refresh()
    assert tc.get_tier("AgentCo") == "apply-now"
    assert tc.get_tier("TierCloudCo") == "apply-now"


def test_punctuation_stripped(tiered_vault):
    """Spec: strip non-alphanumerics. 'DocCo/Glean'-style names should normalize."""
    # Append a punctuated company to the fixture
    md = (tiered_vault / "_profile" / "target-companies.md").read_text()
    md += "\n## Tier `apply-now`\n\n| Company | Notes |\n|---|---|\n| DocCo/Glean | combo |\n"
    (tiered_vault / "_profile" / "target-companies.md").write_text(md)
    import compass.vault.target_companies as tc

    tc.refresh()
    # All three should resolve to the same canonical entry
    assert tc.get_tier("DocCo/Glean") == "apply-now"
    assert tc.get_tier("DocCoGlean") == "apply-now"
    assert tc.get_tier("docco glean") == "apply-now"


def test_bidirectional_substring_match(tiered_vault):
    """Scraper board_tokens (single words) must match longer descriptive names
    listed in target-companies.md, and vice versa. Bug A regression."""
    import compass.vault.target_companies as tc

    tc.refresh()
    # query ⊂ key — short scraper-token "tiercloudco" matches cell "TierCloudCo Agent Platform"
    assert tc.get_tier("tiercloudco") == "apply-now"
    # query ⊂ key — short scraper-token "tiermobileco" matches cell "TierMobileCo Intelligence Frameworks"
    assert tc.get_tier("tiermobileco") == "apply-now"
    # key ⊂ query — listed "Cursor" matches scraper token "cursoranysphere"
    # (no such entry in fixture; instead exercise key⊂query with docco/DocCoLabs)
    md = (tiered_vault / "_profile" / "target-companies.md").read_text()
    md += "\n## Tier `apply-now`\n\n| Company | Notes |\n|---|---|\n| DocCo | combo |\n"
    (tiered_vault / "_profile" / "target-companies.md").write_text(md)
    tc.refresh()
    assert tc.get_tier("doccolabs") == "apply-now"  # key 'docco' ⊂ query 'doccolabs'


def test_bidirectional_match_respects_min_length(tiered_vault):
    """'ai' / 'ml' should NOT match every long key via the fuzzy fallback."""
    import compass.vault.target_companies as tc

    tc.refresh()
    # 'ai' is only 2 chars — below _MIN_FUZZY_LEN, so the fallback is skipped
    assert tc.get_tier("ai") == "unknown"
    # 'ml' likewise
    assert tc.get_tier("ml") == "unknown"


def test_bidirectional_match_higher_tier_wins(tmp_path, monkeypatch):
    """When a query matches keys in multiple tiers, the highest tier (apply-now) wins."""
    md = """## Tier `apply-now`

| Company | Notes |
|---|---|
| GoogleCloudGenAI | apply-now match |

## Tier `6-month`

| Company | Notes |
|---|---|
| Google Vertex | weaker match |
"""
    vault = tmp_path / "v"
    (vault / "_profile").mkdir(parents=True)
    (vault / "_profile" / "target-companies.md").write_text(md)
    import compass.config as cfg
    import compass.vault.target_companies as tc

    monkeypatch.setattr(cfg, "VAULT_PATH", vault)
    tc.refresh()
    # 'google' is contained by both keys — pick the higher tier
    assert tc.get_tier("google") == "apply-now"


def test_unrelated_query_still_unknown(tiered_vault):
    """Bidirectional match must not over-match unrelated long queries."""
    import compass.vault.target_companies as tc

    tc.refresh()
    # No key contains 'salesforce' nor vice versa → unknown
    assert tc.get_tier("salesforce") == "unknown"


def test_company_header_row_skipped(tmp_path, monkeypatch):
    """Defensive: a literal '| Company |' header must NOT be parsed as a company."""
    md = """## Tier `apply-now`

| Company | Notes |
|---|---|
| AgentCo | SF |
"""
    vault = tmp_path / "v"
    (vault / "_profile").mkdir(parents=True)
    (vault / "_profile" / "target-companies.md").write_text(md)
    import compass.config as cfg
    import compass.vault.target_companies as tc

    monkeypatch.setattr(cfg, "VAULT_PATH", vault)
    tc.refresh()
    assert tc.get_tier("Company") == "unknown"
    assert tc.get_tier("AgentCo") == "apply-now"
