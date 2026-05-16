"""
Vault writer — writes structured notes to the Obsidian vault.

Rules:
- Never write raw markdown directly — always use these functions
- Never delete vault files — the vault is append-only from the pipeline
- Always validate frontmatter against schemas before writing
- File naming: jobs/YYYY-MM-DD-Company-Title.md
"""
from pathlib import Path
from compass.config import VAULT_PATH
from compass.vault.schemas import JobNote, SkillNote, CompanyNote


def write_job_note(note: JobNote) -> Path:
    """Write a job note to vault/jobs/. Creates the file, returns its path."""
    raise NotImplementedError("write_job_note not yet implemented")


def update_skill_note(skill: str, job_url: str) -> None:
    """Increment appears_in_jobs counter on a skill note. Creates it if missing."""
    raise NotImplementedError("update_skill_note not yet implemented")


def write_company_note(note: CompanyNote) -> Path:
    """Write or update a company note. Creates the file if it doesn't exist."""
    raise NotImplementedError("write_company_note not yet implemented")
