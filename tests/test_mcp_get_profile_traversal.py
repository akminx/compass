"""Regression — `get_profile` MCP tool must NOT leak files outside `_profile/`.

Pre-fix (2026-05-19 wave 3) `get_profile("../.env")` resolved to the vault root
and returned the contents of any sibling .env-like file. Same threat class as
the `generate_cover_letter` path-traversal fix from wave 1.
"""

from __future__ import annotations


def test_path_traversal_rejected(temp_vault):
    from compass.mcp_server.server import get_profile

    out = get_profile("../.env")
    assert "invalid section name" in out.lower() or "must be inside" in out.lower()


def test_absolute_path_rejected(temp_vault):
    from compass.mcp_server.server import get_profile

    out = get_profile("/etc/passwd")
    assert "invalid section name" in out.lower() or "must be inside" in out.lower()


def test_normal_section_works(temp_vault):
    """The path-traversal fix shouldn't break the happy path. Write a known
    file explicitly to avoid order-dependence on the conftest seed (other
    tests may delete _profile/* files in the same session)."""
    from compass.mcp_server.server import get_profile

    (temp_vault / "_profile" / "resume.md").write_text("# Resume\n\nReal content here.\n")
    out = get_profile("resume")
    assert "Real content here" in out
