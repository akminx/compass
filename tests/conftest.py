"""Shared pytest fixtures.

NOTE on env vars: `compass.config` reads `OPENROUTER_API_KEY` and `VAULT_PATH`
via `os.environ[...]` at import time — that raises KeyError on missing values.
We set sane defaults BEFORE any `compass.*` import so `uv run pytest` works
without requiring the executor to export envs on every invocation.
"""

import os

# MUST happen before any compass import below.
os.environ.setdefault("OPENROUTER_API_KEY", "test-stub")
os.environ.setdefault("VAULT_PATH", "/tmp/compass-vault-pytest-placeholder")
os.environ.setdefault("LEARNING_VAULT_PATH", "/tmp/learning-vault-pytest-placeholder")

# Seed the placeholder vault with a skill-taxonomy.md so taxonomy.normalize()
# tests have data to work with. Priority order:
#   1. User's real vault (so taxonomy edits are picked up immediately by tests)
#   2. Checked-in fixture at tests/fixtures/skill-taxonomy.md (CI fallback)
# Either way the file is copied each test session so the lru_cache stays fresh.
_real_taxonomy = os.path.expanduser("~/Documents/compass-vault/_meta/skill-taxonomy.md")
_fixture_taxonomy = os.path.join(os.path.dirname(__file__), "fixtures", "skill-taxonomy.md")
_placeholder_meta = os.path.join(os.environ["VAULT_PATH"], "_meta")
_placeholder_taxonomy = os.path.join(_placeholder_meta, "skill-taxonomy.md")
if os.path.exists(_real_taxonomy):
    _taxonomy_source = _real_taxonomy
elif os.path.exists(_fixture_taxonomy):
    _taxonomy_source = _fixture_taxonomy
else:
    _taxonomy_source = None
if _taxonomy_source is not None:
    os.makedirs(_placeholder_meta, exist_ok=True)
    import shutil as _shutil

    _shutil.copyfile(_taxonomy_source, _placeholder_taxonomy)

from pathlib import Path

import pytest


@pytest.fixture
def temp_vault(tmp_path: Path, monkeypatch):
    """Create a minimal compass-vault structure in a tmp dir and point config at it."""
    vault = tmp_path / "compass-vault"
    for sub in ["_profile", "_meta", "jobs", "skills", "companies", "applications", "study-plans"]:
        (vault / sub).mkdir(parents=True, exist_ok=True)
    # Seed minimal _profile files so reader tests can find them.
    (vault / "_profile" / "resume.md").write_text(
        "---\ntype: profile\n---\n# Resume\n\nFake resume body.\n"
    )
    (vault / "_profile" / "skill-inventory.md").write_text(
        "---\ntype: profile\n---\n# Skills\n\nPython: 3\n"
    )
    (vault / "_profile" / "preferences.md").write_text(
        "---\ntype: profile\n---\nPreferences body.\n"
    )
    (vault / "_meta" / "agent-log.md").write_text("# Agent Log\n")

    # Patch the config module's attributes.
    import compass.config as cfg

    monkeypatch.setattr(cfg, "VAULT_PATH", vault)
    monkeypatch.setattr(cfg, "AGENT_LOG_PATH", vault / "_meta" / "agent-log.md")
    monkeypatch.setattr(cfg, "SKILL_INVENTORY_PATH", vault / "_profile" / "skill-inventory.md")
    monkeypatch.setattr(cfg, "MASTER_GAP_PLAN_PATH", vault / "study-plans" / "master-gap-plan.md")

    # Also patch the modules that captured these via `from compass.config import VAULT_PATH`.
    # Guarded with hasattr because Task 5 runs BEFORE Task 6 implements the writer's
    # AGENT_LOG_PATH import — reader tests in Task 5 don't touch the writer module's
    # AGENT_LOG_PATH so the guard keeps that test wave green.
    import compass.vault.reader as reader_mod

    if hasattr(reader_mod, "VAULT_PATH"):
        monkeypatch.setattr(reader_mod, "VAULT_PATH", vault)

    import compass.vault.writer as writer_mod

    if hasattr(writer_mod, "VAULT_PATH"):
        monkeypatch.setattr(writer_mod, "VAULT_PATH", vault)
    if hasattr(writer_mod, "AGENT_LOG_PATH"):
        monkeypatch.setattr(writer_mod, "AGENT_LOG_PATH", vault / "_meta" / "agent-log.md")

    try:
        import compass.pipeline.nodes.extract as extract_mod

        if hasattr(extract_mod, "VAULT_PATH"):
            monkeypatch.setattr(extract_mod, "VAULT_PATH", vault)
    except ImportError:
        pass

    try:
        import compass.pipeline.graph as graph_mod

        if hasattr(graph_mod, "VAULT_PATH"):
            monkeypatch.setattr(graph_mod, "VAULT_PATH", vault)
    except ImportError:
        pass

    try:
        import compass.analysis.gap_aggregator as gap_mod

        if hasattr(gap_mod, "VAULT_PATH"):
            monkeypatch.setattr(gap_mod, "VAULT_PATH", vault)
        if hasattr(gap_mod, "MASTER_GAP_PLAN_PATH"):
            monkeypatch.setattr(
                gap_mod, "MASTER_GAP_PLAN_PATH", vault / "study-plans" / "master-gap-plan.md"
            )
    except ImportError:
        pass

    return vault
