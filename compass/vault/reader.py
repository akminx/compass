"""
Vault reader — reads structured notes from the Obsidian vault.

Used by pipeline nodes to load the candidate profile, skill inventory,
and check for existing job notes (deduplication).
"""
from pathlib import Path
from compass.config import VAULT_PATH


def read_profile_section(section: str) -> str:
    """Read a section from _profile/. section = filename without .md"""
    raise NotImplementedError("read_profile_section not yet implemented")


def read_skill_inventory() -> str:
    """Read the full skill-inventory.md as a string for LLM context."""
    raise NotImplementedError("read_skill_inventory not yet implemented")


def read_resume() -> str:
    """Read resume.md as a string."""
    raise NotImplementedError("read_resume not yet implemented")


def job_url_exists(url: str) -> bool:
    """Check if a job with this URL already exists in the vault (for deduplication)."""
    raise NotImplementedError("job_url_exists not yet implemented")


def list_job_notes() -> list[Path]:
    """Return all job note paths in vault/jobs/."""
    raise NotImplementedError("list_job_notes not yet implemented")
