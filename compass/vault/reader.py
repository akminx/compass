"""
Vault reader — reads structured notes from the Obsidian vault.
"""
from __future__ import annotations

from pathlib import Path

import frontmatter

from compass.config import VAULT_PATH


def read_profile_section(section: str) -> str:
    """Read a file from _profile/. Returns empty string if missing."""
    path = VAULT_PATH / "_profile" / f"{section}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_skill_inventory() -> str:
    return read_profile_section("skill-inventory")


def read_resume() -> str:
    return read_profile_section("resume")


def job_url_exists(url: str) -> bool:
    """Check whether any job note in the vault has the given URL in its frontmatter."""
    jobs_dir = VAULT_PATH / "jobs"
    if not jobs_dir.exists():
        return False
    for path in jobs_dir.glob("*.md"):
        try:
            post = frontmatter.load(path)
        except Exception:
            continue
        if post.metadata.get("url") == url:
            return True
    return False


def list_job_notes() -> list[Path]:
    jobs_dir = VAULT_PATH / "jobs"
    if not jobs_dir.exists():
        return []
    return sorted(jobs_dir.glob("*.md"))
