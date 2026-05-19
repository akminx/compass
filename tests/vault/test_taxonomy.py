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


def test_normalize_ml_foundations():
    """Regression: 'Large Language Models', 'LLM', 'Machine Learning', 'Deep
    Learning', 'Reinforcement Learning' used to drop to the unknown-skills log,
    suppressing match scores for the agentic-AI JDs the project targets."""
    from compass.vault.taxonomy import normalize

    for raw in [
        "Large Language Models",
        "Large Language Model",
        "LLM",
        "LLMs",
        "language models",
        "Generative AI",
        "Gen AI",
    ]:
        assert normalize(raw) == "LLMs", f"{raw!r} should map to LLMs"
    for raw in ["Machine Learning", "ML", "applied ML", "machine-learning"]:
        assert normalize(raw) == "Machine Learning", f"{raw!r} should map to Machine Learning"
    assert normalize("Deep Learning") == "Deep Learning"
    assert normalize("Neural Networks") == "Deep Learning"
    assert normalize("Reinforcement Learning") == "Reinforcement Learning"
    assert normalize("RL") == "Reinforcement Learning"


def test_normalize_does_not_resolve_demand_tokens():
    """Regression: 3-column tables (Voice, Fine-Tuning) in skill-taxonomy.md
    used to leak demand-level strings ('low', 'medium') into the synonym
    index because the parser treated cells[1] as synonyms regardless of
    column count. normalize('low') used to return 'DPO'."""
    from compass.vault.taxonomy import normalize

    for token in ["low", "medium", "high", "highest"]:
        assert normalize(token) is None, f"normalize({token!r}) should be None"


def test_normalize_react_does_not_collapse_to_react_pattern():
    """Regression: 'React' (the framework, capital R only) used to silently map
    to 'ReAct' (the agentic prompting pattern, capital R and A) because
    _norm_key lowercases everything. _CASE_SENSITIVE_CANONICALS blocks this."""
    from compass.vault.taxonomy import normalize

    assert normalize("React") is None  # the framework — not in our taxonomy
    assert normalize("react") is None  # lowercase, definitely not ReAct
    assert normalize("ReAct") == "ReAct"  # the canonical, exact case match


def test_normalize_go_disambiguation():
    """'Go' the language is in the taxonomy but case-sensitive — bare 'go' or
    'Go ahead' substrings shouldn't return 'Go'."""
    from compass.vault.taxonomy import normalize

    assert normalize("Go") == "Go"  # exact canonical match
    assert normalize("golang") == "Go"  # explicit synonym in the taxonomy
    # 'go' alone is ambiguous — case-sensitive guard rejects lowercase
    # bare-canonical (not an explicit synonym)
    assert normalize("go") is None
