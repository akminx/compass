"""Regression test for the path-traversal fix in generate_cover_letter — added
2026-05-19 after the adversarial review found that `job_filename` was joined
to VAULT_PATH without validation."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_generate_cover_letter_rejects_path_traversal(temp_vault):
    from compass.mcp_server.server import generate_cover_letter

    out = await generate_cover_letter("../_profile/resume.md")
    assert "error" in out, "path traversal must be rejected"
    assert "inside jobs/" in out["error"]


@pytest.mark.asyncio
async def test_generate_cover_letter_rejects_absolute_path(temp_vault):
    from compass.mcp_server.server import generate_cover_letter

    out = await generate_cover_letter("/etc/passwd")
    assert "error" in out


@pytest.mark.asyncio
async def test_generate_cover_letter_accepts_valid_filename(temp_vault):
    """A real JobNote filename inside jobs/ — even if the file doesn't exist,
    the path-traversal guard should pass; only the not-found error fires."""
    from compass.mcp_server.server import generate_cover_letter

    out = await generate_cover_letter("2026-05-19-Sierra-Engineer-abc.md")
    # Path passes the traversal check but file doesn't exist
    assert "error" in out
    assert "JobNote not found" in out["error"]
