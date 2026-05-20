"""
Vault reader — reads structured notes from the Obsidian vault.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import frontmatter
import yaml

from compass.config import VAULT_PATH

if TYPE_CHECKING:
    from pathlib import Path


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


# ── reject rules (preferences.md) ─────────────────────────────────────────────

# Match a labelled YAML block: `<label>:\n  - item\n  - item`.
_REJECT_BLOCK = re.compile(
    r"(?m)^(reject_if_title_contains|reject_if_jd_contains):[ \t]*\n((?:[ \t]+-[^\n]*\n?)+)"
)


def load_reject_rules() -> dict[str, list[str]]:
    """Parse the `reject_if_title_contains` + `reject_if_jd_contains` YAML blocks
    from `_profile/preferences.md`. Returns lower-cased strings for cheap
    substring matching.

    Returns:
      {"title": [...], "jd": [...]} — empty lists when preferences.md is
      missing or the block doesn't exist.
    """
    text = read_profile_section("preferences")
    out: dict[str, list[str]] = {"title": [], "jd": []}
    for m in _REJECT_BLOCK.finditer(text):
        label = m.group(1)
        try:
            items = yaml.safe_load(m.group(2)) or []
        except yaml.YAMLError:
            continue
        if not isinstance(items, list):
            continue
        rules = [str(s).strip().lower() for s in items if isinstance(s, str | int)]
        if label == "reject_if_title_contains":
            out["title"] = rules
        elif label == "reject_if_jd_contains":
            out["jd"] = rules
    return out
