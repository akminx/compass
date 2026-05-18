"""
Vault writer — writes structured notes to the Obsidian vault.

Rules:
- Never write raw markdown directly — always go through these functions.
- Every write validates frontmatter against compass.vault.schemas.
- Every mutation appends a one-line entry to _meta/agent-log.md.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

import frontmatter

from compass.config import AGENT_LOG_PATH, VAULT_PATH
from compass.vault.schemas import CompanyNote, JobNote, SkillCategory, SkillNote
from compass.vault.taxonomy import category_for

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import BaseModel

logger = logging.getLogger(__name__)


_FILENAME_BAD = re.compile(r"[^\w\-.]+")


def _safe_segment(s: str) -> str:
    return _FILENAME_BAD.sub("_", s).strip("_")


def _job_filename(note: JobNote) -> str:
    """JobNote filename includes a short URL hash so titles that sanitize to
    the same string (e.g. "Engineer / Backend" vs "Engineer (Backend)") never
    collide on disk. Two different URLs can never produce the same filename."""
    url_suffix = hashlib.sha1(note.url.encode("utf-8")).hexdigest()[:8]
    return (
        f"{note.date_found.isoformat()}"
        f"-{_safe_segment(note.company)}"
        f"-{_safe_segment(note.title)}"
        f"-{url_suffix}.md"
    )


def _to_metadata(model: BaseModel) -> dict:
    """Serialize a Pydantic model to a frontmatter-safe dict.

    JSON mode converts dates/datetimes/enums to strings; everything else is YAML-friendly.
    """
    return model.model_dump(mode="json", by_alias=True)


def write_job_note(note: JobNote, full_description: str | None = None) -> Path:
    """Write a JobNote to vault/jobs/. Idempotent on URL — same URL overwrites the same file.

    When `full_description` is provided, the raw scraped JD is appended below the
    LLM summary in a `## Full JD` section so the human can verify what the agent
    actually saw without going back to the source URL.
    """
    jobs_dir = VAULT_PATH / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    target: Path | None = None
    for existing in jobs_dir.glob("*.md"):
        try:
            post = frontmatter.load(existing)
        except Exception:
            continue
        if post.metadata.get("url") == note.url:
            target = existing
            break
    if target is None:
        target = jobs_dir / _job_filename(note)

    body = f"# {note.company} — {note.title}\n\n{note.jd_summary}\n"
    if full_description:
        body += f"\n## Full JD\n\n{full_description.strip()}\n"
    post = frontmatter.Post(content=body)
    post.metadata = _to_metadata(note)
    target.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    append_agent_log(f"vault_write job {note.company} {note.title} score={note.match_score}")
    return target


def update_skill_note(canonical_skill: str, job_url: str) -> Path:
    """Increment appears_in_jobs on a skill note. Creates a minimal note if missing."""
    skills_dir = VAULT_PATH / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    path = skills_dir / f"{_safe_segment(canonical_skill)}.md"

    if path.exists():
        post = frontmatter.load(path)
        post.metadata["appears_in_jobs"] = int(post.metadata.get("appears_in_jobs", 0)) + 1
    else:
        category: SkillCategory = category_for(canonical_skill) or "language"  # type: ignore[assignment]
        if category_for(canonical_skill) is None:
            logger.warning(
                "update_skill_note: %r not in canonical taxonomy; defaulting category=language",
                canonical_skill,
            )
        skill = SkillNote(skill=canonical_skill, category=category, appears_in_jobs=1)
        post = frontmatter.Post(content=f"# {canonical_skill}\n")
        post.metadata = _to_metadata(skill)

    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    append_agent_log(f"vault_write skill {canonical_skill} += 1 (from {job_url})")
    return path


def write_company_note(note: CompanyNote) -> Path:
    """Write or update a company note. Merges roles_seen with existing count
    AND preserves any non-default fields the user edited in Obsidian (tier,
    why_interesting, geo, etc.) — otherwise every pipeline run would clobber
    human edits back to defaults."""
    companies_dir = VAULT_PATH / "companies"
    companies_dir.mkdir(parents=True, exist_ok=True)
    path = companies_dir / f"{_safe_segment(note.company)}.md"

    if path.exists():
        existing = frontmatter.load(path).metadata
        update: dict = {
            "roles_seen": int(existing.get("roles_seen", 0)) + note.roles_seen,
        }
        # Preserve human-set fields when the incoming note has the default value.
        if note.tier == "unknown" and existing.get("tier", "unknown") != "unknown":
            update["tier"] = existing["tier"]
        if (
            note.hiring_signal == "unknown"
            and existing.get("hiring_signal", "unknown") != "unknown"
        ):
            update["hiring_signal"] = existing["hiring_signal"]
        if not note.why_interesting and existing.get("why_interesting"):
            update["why_interesting"] = existing["why_interesting"]
        if not note.geo and existing.get("geo"):
            update["geo"] = existing["geo"]
        if not note.known_stack and existing.get("known_stack"):
            update["known_stack"] = existing["known_stack"]
        if not note.interview_format_notes and existing.get("interview_format_notes"):
            update["interview_format_notes"] = existing["interview_format_notes"]
        if not note.tags and existing.get("tags"):
            update["tags"] = existing["tags"]
        note = note.model_copy(update=update)

    post = frontmatter.Post(content=f"# {note.company}\n\n{note.why_interesting}\n")
    post.metadata = _to_metadata(note)
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    append_agent_log(f"vault_write company {note.company} roles_seen={note.roles_seen}")
    return path


def append_agent_log(action: str) -> None:
    """Append a one-line, timestamped entry to _meta/agent-log.md."""
    AGENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {action}\n"
    with AGENT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)
