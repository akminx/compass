"""Regression tests for taxonomy normalizer — substring false positives.

These were silently producing wrong canonicals before Phase 0.B strict-match fix.
"""


def test_normalize_strict_match_no_substring_false_positives():
    """Substring fallback used to map non-skills to canonical names because
    short canonical keys (go, react, modal, python) appeared as substrings of
    unrelated input. Strict match now returns None for these."""
    from compass.vault.taxonomy import normalize

    # Each of these used to match a canonical via substring; must now be None.
    false_positives = [
        ("Pythonist", "Python"),
        ("Goblet", "Go"),
        ("Reactivity", "ReAct"),
        ("Modal verb", "Modal"),
    ]
    for raw, would_have_matched in false_positives:
        assert normalize(raw) is None, (
            f"{raw!r} should be None now; previously matched {would_have_matched!r}"
        )


def test_normalize_still_works_for_real_synonyms():
    """The strict-match fix should not break legitimate synonym lookups."""
    from compass.vault.taxonomy import normalize

    cases = [
        ("py", "Python"),
        ("python", "Python"),
        ("langgraph", "LangGraph"),
        ("LangGraph", "LangGraph"),
        ("k8s", "Kubernetes"),
        ("function calling", "Function calling"),
        ("mcp-server", "MCP server authoring"),
    ]
    for raw, expected in cases:
        actual = normalize(raw)
        assert actual == expected, f"{raw!r}: expected {expected!r}, got {actual!r}"


def test_normalize_returns_none_for_truly_unknown():
    from compass.vault.taxonomy import normalize

    assert normalize("MLOps") is None
    assert normalize("Salesforce") is None
    assert normalize("totally-fake-skill") is None


def test_normalize_does_not_resolve_demand_tokens():
    """Regression: 3-column tables (Voice, Fine-Tuning) in skill-taxonomy.md
    used to leak demand-level strings ('low', 'medium') into the synonym
    index because the parser treated cells[1] as synonyms regardless of
    column count. normalize('low') used to return 'DPO'."""
    from compass.vault.taxonomy import normalize

    for token in ["low", "medium", "high", "highest"]:
        assert normalize(token) is None, f"normalize({token!r}) should be None"
