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
from compass.vault.schemas import ApplicationNote, CompanyNote, JobNote, SkillCategory, SkillNote
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
    """Write or update a company note.

    `roles_seen` is intentionally NOT accumulated here — that would race under
    parallel writes (MAX_CONCURRENT_JOBS=5 jobs for the same company could each
    read roles_seen=0, all increment to 1, last writer wins → lost 4 increments).
    Instead, `gap_aggregator._sync_company_counters()` derives the value from
    `len(JobNotes for company)` at end of each pipeline run — same pattern as
    skill counters (bug #12 from Phase 0). The value passed in via `note.roles_seen`
    is preserved only when there's no existing CompanyNote yet (first write).

    Human edits to non-default fields (tier, why_interesting, geo, etc.) are
    preserved across pipeline runs.
    """
    companies_dir = VAULT_PATH / "companies"
    companies_dir.mkdir(parents=True, exist_ok=True)
    path = companies_dir / f"{_safe_segment(note.company)}.md"

    if path.exists():
        existing = frontmatter.load(path).metadata
        update: dict = {
            # Preserve existing roles_seen verbatim — gap_aggregator owns this counter.
            "roles_seen": int(existing.get("roles_seen", 0)),
        }
        # Preserve human-set fields when the incoming note has the default value.
        # CompanyNote.tier is a Literal — a typo in Obsidian (e.g. `tier: applynow`
        # or `tier: favorite`) would crash model_copy with ValidationError. Guard
        # against that by ignoring invalid tier values (they get reset to
        # whatever the pipeline computed).
        existing_tier = existing.get("tier", "unknown")
        _valid_tiers = {"apply-now", "6-month", "stretch", "skip", "unknown"}
        if existing_tier not in _valid_tiers:
            logger.warning(
                "write_company_note: %s has invalid tier=%r (expected one of %s); "
                "ignoring existing value and using incoming tier=%r",
                note.company, existing_tier, sorted(_valid_tiers), note.tier,
            )
        elif note.tier == "unknown" and existing_tier != "unknown":
            update["tier"] = existing_tier
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


def _application_filename(note: ApplicationNote) -> str:
    """Filename includes a short hash of job_ref so applying to two different
    postings at one company on the same day produces two separate files.
    Mirrors the JobNote-filename strategy from bug #11 in Phase 0."""
    job_ref_hash = hashlib.sha1(note.job_ref.encode("utf-8")).hexdigest()[:8]
    return (
        f"{note.applied_date.isoformat()}"
        f"-{_safe_segment(note.company)}"
        f"-{_safe_segment(note.title)}"
        f"-{job_ref_hash}.md"
    )


def write_application_note(note: ApplicationNote) -> Path:
    """Write or update an application note. Idempotent on (company, title, applied_date, job_ref).

    Re-running with the same identity overwrites the file in place; downstream
    callers use this to record status transitions without duplicating notes.
    Two different postings at the same company on the same day produce distinct
    files because the filename includes a hash of job_ref.
    """
    apps_dir = VAULT_PATH / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    path = apps_dir / _application_filename(note)

    body = f"# {note.company} — {note.title}\n\n"
    body += f"Applied: {note.applied_date.isoformat()}\n"
    body += f"Status: {note.status}\n"
    if note.next_action:
        body += f"\n**Next action:** {note.next_action}"
        if note.next_action_date:
            body += f" (by {note.next_action_date.isoformat()})"
        body += "\n"

    post = frontmatter.Post(content=body)
    post.metadata = _to_metadata(note)
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    append_agent_log(
        f"vault_write application {note.company} {note.title} "
        f"applied={note.applied_date} status={note.status}"
    )
    return path


def append_agent_log(action: str) -> None:
    """Append a one-line, timestamped entry to _meta/agent-log.md."""
    AGENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {action}\n"
    with AGENT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)
