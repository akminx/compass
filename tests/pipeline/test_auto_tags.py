"""P3 Obsidian leverage: vault_write_node auto-generates Obsidian tag-pane
filterable tags from JobNote fields so `#fit/strong AND #role/agent-engineer`
queries work naturally in the tag pane and Dataview."""

from __future__ import annotations

from compass.pipeline.nodes.vault_write import _build_auto_tags


def test_build_auto_tags_strong_fit_approved():
    tags = _build_auto_tags(
        tier="apply-now",
        match_score=4.2,
        role_family="agent-engineer",
        hitl_decision="approved",
    )
    assert tags == [
        "#tier/apply-now",
        "#fit/strong",
        "#role/agent-engineer",
        "#decision/approved",
    ]


def test_build_auto_tags_fit_buckets():
    assert "#fit/strong" in _build_auto_tags(
        tier="apply-now",
        match_score=4.0,
        role_family="x",
        hitl_decision=None,
    )
    assert "#fit/decent" in _build_auto_tags(
        tier="apply-now",
        match_score=3.5,
        role_family="x",
        hitl_decision=None,
    )
    assert "#fit/stretch" in _build_auto_tags(
        tier="apply-now",
        match_score=2.5,
        role_family="x",
        hitl_decision=None,
    )
    assert "#fit/weak" in _build_auto_tags(
        tier="apply-now",
        match_score=1.5,
        role_family="x",
        hitl_decision=None,
    )


def test_build_auto_tags_omits_none_decision():
    """When hitl never ran (extract errored, etc.) no #decision/ tag is emitted."""
    tags = _build_auto_tags(
        tier="opportunistic",
        match_score=3.0,
        role_family="agent-engineer",
        hitl_decision=None,
    )
    assert not any(t.startswith("#decision/") for t in tags)


def test_build_auto_tags_omits_empty_role_family():
    """role_family can be the empty string when classification deferred. No tag in that case."""
    tags = _build_auto_tags(
        tier="apply-now",
        match_score=4.0,
        role_family="",
        hitl_decision="approved",
    )
    assert not any(t.startswith("#role/") for t in tags)


def test_build_auto_tags_includes_all_tiers():
    for tier in ["apply-now", "opportunistic", "backend-prep", "stretch", "skip", "unknown"]:
        tags = _build_auto_tags(
            tier=tier,
            match_score=3.0,
            role_family="agent-engineer",
            hitl_decision=None,
        )
        assert f"#tier/{tier}" in tags
