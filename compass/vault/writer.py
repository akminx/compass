"""
Vault writer — writes structured notes to the Obsidian vault.

Rules:
- Never write raw markdown directly — always go through these functions.
- Every write validates frontmatter against compass.vault.schemas.
- Every mutation appends a one-line entry to _meta/agent-log.md.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

import frontmatter

from compass.config import AGENT_LOG_PATH, VAULT_PATH

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import BaseModel

    from compass.vault.schemas import ApplicationNote, CompanyNote, JobNote

logger = logging.getLogger(__name__)


_FILENAME_BAD = re.compile(r"[^\w\-.]+")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _safe_segment(s: str) -> str:
    return _FILENAME_BAD.sub("_", s).strip("_")


def _looks_like_html(text: str) -> bool:
    """Cheap detector — `<p>`, `</div>`, `<span ...>` style tags. Avoids the
    rare case where a JD contains a literal `<` (e.g. ASCII art, code snippet)."""
    return bool(
        re.search(r"</[a-z]+>|<[a-z]+ [^>]*>|<(p|div|span|strong|br|h\d)\b", text, re.IGNORECASE)
    )


def _normalize_full_jd(text: str) -> str:
    """Safety-net HTML strip applied to JD bodies at vault-write time.

    Each ATS scraper already strips HTML at its boundary (greenhouse/lever
    via `_strip_html`, ashby via `descriptionPlain`). This is belt-and-
    suspenders: if a future scraper or a hand-built RawJob bypasses that,
    the vault still gets clean text instead of `</span></strong></p>` cruft.

    Only fires when the input visibly looks like HTML — JDs containing
    literal `<` (code snippets, ASCII art) pass through untouched.
    """
    if not _looks_like_html(text):
        return text
    out = _SCRIPT_STYLE_RE.sub(" ", text)
    out = _HTML_TAG_RE.sub(" ", out)
    out = html.unescape(out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


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


def _wikilink(skill: str) -> str:
    """Render a skill as an Obsidian wikilink pointing at skills/<safe>.md.

    SkillNotes are stored under filenames produced by `_safe_segment`. When the
    skill name contains characters that get rewritten (e.g. "AWS Bedrock" →
    "AWS_Bedrock", "C++" → "C__"), emit the alias form `[[target|display]]` so
    the link resolves AND the display matches what the user typed.
    """
    target = _safe_segment(skill)
    return f"[[{target}|{skill}]]" if target != skill else f"[[{skill}]]"


def _render_skills_section(note: JobNote) -> str:
    """Render `## Skills` body block. Empty categories are omitted entirely."""
    rows: list[tuple[str, list[str]]] = [
        ("Required", note.skills_required),
        ("Nice to have", note.skills_nice_to_have),
        ("Matched", note.skills_matched),
        ("Missing", note.skills_missing),
    ]
    lines = ["## Skills", ""]
    any_row = False
    for label, skills in rows:
        if not skills:
            continue
        any_row = True
        lines.append(f"**{label}:** " + " · ".join(_wikilink(s) for s in skills))
    if not any_row:
        return ""
    return "\n".join(lines) + "\n"


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
    skills_block = _render_skills_section(note)
    if skills_block:
        body += f"\n{skills_block}"
    if full_description:
        body += f"\n## Full JD\n\n{_normalize_full_jd(full_description).strip()}\n"
    post = frontmatter.Post(content=body)
    post.metadata = _to_metadata(note)
    target.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    append_agent_log(f"vault_write job {note.company} {note.title} score={note.match_score}")
    return target


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
        _valid_tiers = {
            "apply-now",
            "opportunistic",
            "backend-prep",
            "6-month",
            "stretch",
            "skip",
            "unknown",
        }
        if existing_tier not in _valid_tiers:
            logger.warning(
                "write_company_note: %s has invalid tier=%r (expected one of %s); "
                "ignoring existing value and using incoming tier=%r",
                note.company,
                existing_tier,
                sorted(_valid_tiers),
                note.tier,
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
