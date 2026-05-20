"""Regression — `learning_bridge.resolve()` must NOT escape LEARNING_VAULT_PATH.

Pre-fix (2026-05-19 wave 3) a URI like `learning-vault://../../.env` resolved
through the bare `LEARNING_VAULT_PATH / rest` join (Path doesn't normalize `..`
components) and would return the contents of the secret file. Verified live
that the leak was real before the fix.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def isolated_learning_vault(tmp_path, monkeypatch):
    lv = tmp_path / "learning-vault"
    lv.mkdir()
    (lv / "real.md").write_text("# Real evidence\n\nSafe content.")
    # Place a sensitive sibling we'd want to NOT leak
    secret = tmp_path / "secret.env"
    secret.write_text("OPENROUTER_API_KEY=sk-leaked-DO-NOT-RETURN")

    import compass.config as cfg
    import compass.vault.learning_bridge as lb

    monkeypatch.setattr(cfg, "LEARNING_VAULT_PATH", lv)
    monkeypatch.setattr(lb, "LEARNING_VAULT_PATH", lv)
    return lv


def test_normal_uri_resolves_within_vault(isolated_learning_vault):
    from compass.vault.learning_bridge import resolve

    result = resolve("learning-vault://real.md")
    assert result is not None
    assert "Safe content" in result.snippet


def test_dot_dot_uri_rejected_returns_none(isolated_learning_vault):
    """`../secret.env` escapes the vault root — `_parse_uri` raises ValueError
    which `resolve` catches and returns None. The user-observable contract is
    "no file contents leaked." Pre-fix, the .env contents WERE returned."""
    from compass.vault.learning_bridge import resolve

    # The critical assertion: secret content does NOT appear in any returned object
    result = resolve("learning-vault://../secret.env")
    assert result is None, "path-traversal must not return an artifact"


def test_dot_dot_uri_raises_at_parse(isolated_learning_vault):
    """The lower-level `_parse_uri` raises ValueError on traversal — that's
    the security guard. `resolve` catches it as part of its existing
    None-on-error contract."""
    from compass.vault.learning_bridge import _parse_uri

    with pytest.raises(ValueError, match="resolves outside the vault root"):
        _parse_uri("learning-vault://../secret.env")


def test_deep_dot_dot_uri_blocked(isolated_learning_vault):
    from compass.vault.learning_bridge import _parse_uri, resolve

    assert resolve("learning-vault://../../etc/passwd") is None
    with pytest.raises(ValueError):
        _parse_uri("learning-vault://../../etc/passwd")


def test_absolute_path_attempt_blocked(isolated_learning_vault):
    """An absolute path in the URI would resolve relative to / not LEARNING_VAULT_PATH."""
    from compass.vault.learning_bridge import _parse_uri, resolve

    assert resolve("learning-vault:///etc/passwd") is None
    with pytest.raises(ValueError):
        _parse_uri("learning-vault:///etc/passwd")


def test_url_encoded_traversal_still_blocked(isolated_learning_vault):
    """Path components with literal `..` are caught by resolve+relative_to;
    URL-encoded variants like %2e%2e/ would bypass that if we decoded. We
    don't decode, so they're treated as literal filenames — not vulnerable
    to encoding tricks. This test pins that behavior."""
    from compass.vault.learning_bridge import resolve

    # A literal "%2e%2e" filename inside the vault wouldn't exist; expect None.
    result = resolve("learning-vault://%2e%2e/secret.env")
    assert result is None
