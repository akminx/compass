"""Application lifecycle — wraps ApplicationNote CRUD and JobNote status updates.

Exposed via MCP server. Single-writer assumption: only the human (via MCP)
mutates applications. The pipeline writes JobNotes; it never creates
ApplicationNotes. Status transitions are validated (see VALID_TRANSITIONS).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

import frontmatter

if TYPE_CHECKING:
    from pathlib import Path

import compass.config as cfg  # read VAULT_PATH at call time, not at import
from compass.vault.schemas import ApplicationNote
from compass.vault.writer import append_agent_log, write_application_note

logger = logging.getLogger(__name__)

# Sentinel for "caller didn't pass this argument" vs "caller passed None to clear it"
_UNSET: object = object()


VALID_TRANSITIONS: dict[str, set[str]] = {
    "applied": {"screen", "rejected", "withdrawn", "ghosted"},
    "screen": {"onsite", "rejected", "withdrawn", "ghosted"},
    "onsite": {"offer", "rejected", "withdrawn", "ghosted"},
    "offer": {"accepted", "declined", "withdrawn"},
    "rejected": set(),
    "withdrawn": set(),
    "ghosted": {"rejected"},
    "accepted": set(),
    "declined": set(),
}


def find_jobnote(job_id: str) -> Path:
    """Public: resolve a job_id (filename substring or url) to a JobNote path.

    Used by add_application AND by the MCP tailor_resume tool. The filename
    substring match is CASE-INSENSITIVE because Obsidian renders frontmatter
    `company` fields as written (often lowercase from ATS board_tokens), but
    humans naturally type capitalized names — so e.g. `"Acme-Agent_Engineer"`
    must find a file named `2025-02-13-acme-Agent_Engineer-<hash>.md`. The
    URL field comparison stays exact (URLs are case-sensitive by spec).
    """
    jobs_dir = cfg.VAULT_PATH / "jobs"
    if not jobs_dir.exists():
        raise LookupError(f"no jobs/ directory in vault at {cfg.VAULT_PATH}")
    job_id_lower = job_id.lower()
    matches: list[Path] = []
    for p in jobs_dir.glob("*.md"):
        if job_id_lower in p.name.lower():
            matches.append(p)
            continue
        try:
            md = frontmatter.load(p).metadata
        except Exception:
            continue
        if md.get("url") == job_id:
            matches.append(p)
    if not matches:
        raise LookupError(f"no JobNote matched job_id={job_id!r}")
    if len(matches) > 1:
        names = ", ".join(p.name for p in matches)
        raise LookupError(f"ambiguous job_id={job_id!r} — matches {names}")
    return matches[0]


def _find_application(app_id: str) -> Path:
    """Resolve an app_id (filename substring) to an ApplicationNote path.

    Case-insensitive substring match for the same reason as `find_jobnote`:
    filenames preserve the case of the company name from the source JobNote
    (often lowercase from scraper board_tokens), but humans naturally type
    capitalized company names.
    """
    apps_dir = cfg.VAULT_PATH / "applications"
    app_id_lower = app_id.lower()
    matches = [p for p in apps_dir.glob("*.md") if app_id_lower in p.name.lower()]
    if not matches:
        raise LookupError(f"no ApplicationNote matched app_id={app_id!r}")
    if len(matches) > 1:
        raise LookupError(f"ambiguous app_id={app_id!r}")
    return matches[0]


def _update_jobnote_status(jobnote_path: Path, status: str) -> None:
    md = frontmatter.load(jobnote_path)
    md["status"] = status
    if status == "applied":
        md["applied_at"] = datetime.now().isoformat()
    jobnote_path.write_text(frontmatter.dumps(md) + "\n", encoding="utf-8")


# JobNote.status values that mean "this job already has an application in flight"
# — refuse to silently overwrite an in-flight application.
_POST_APPLIED_STATUSES = frozenset(
    {
        "applied",
        "screen",
        "onsite",
        "offer",
        "rejected",
        "withdrawn",
        "ghosted",
        "accepted",
        "declined",
    }
)


def add_application(
    job_id: str,
    *,
    resume_variant: str = "resume.md",
    referral: bool = False,
    force: bool = False,
) -> ApplicationNote:
    """Create an ApplicationNote linked to a JobNote and mark the JobNote applied.

    Refuses to overwrite an existing in-flight ApplicationNote unless force=True.
    The ApplicationNote filename is deterministic on (company, title, applied_date,
    job_ref hash) — so re-running this on the same JobNote on the same day would
    silently clobber any status transitions or contacts you'd recorded against the
    first application. The force=True path is for legitimate re-applications to
    a reposted job (transitions through screen/onsite are wiped intentionally).
    """
    job_path = find_jobnote(job_id)
    job_md = frontmatter.load(job_path).metadata

    current_status = job_md.get("status", "new")
    if current_status in _POST_APPLIED_STATUSES and not force:
        raise FileExistsError(
            f"JobNote {job_path.name!r} already has status={current_status!r}. "
            f"Re-applying would overwrite the existing ApplicationNote and lose "
            f"any status transitions or contacts. Pass force=True to override "
            f"(use this when applying to a reposted job)."
        )

    note = ApplicationNote(
        company=job_md["company"],
        title=job_md["title"],
        job_ref=job_md.get("url", str(job_path)),
        applied_date=date.today(),
        resume_variant=resume_variant,
        status="applied",
        referral=referral,
    )
    write_application_note(note)
    _update_jobnote_status(job_path, "applied")
    append_agent_log(
        f"application added {note.company} {note.title}" + (" (FORCED re-apply)" if force else "")
    )
    return note


def update_application_status(
    app_id: str,
    status: str,
    *,
    next_action: object = _UNSET,
    next_action_date: object = _UNSET,
    force: bool = False,
) -> ApplicationNote:
    """Transition an application's status.

    next_action / next_action_date semantics:
        omitted (sentinel) → existing value preserved
        passed as None     → existing value cleared
        passed as a value  → existing value replaced
    """
    path = _find_application(app_id)
    md = frontmatter.load(path).metadata
    current = md.get("status", "applied")

    if not force:
        allowed = VALID_TRANSITIONS.get(current, set())
        if status not in allowed:
            raise ValueError(
                f"invalid transition {current!r} → {status!r} "
                f"(allowed: {sorted(allowed) or '(terminal)'})"
            )

    note = ApplicationNote(**{**md, "status": status})
    if next_action is not _UNSET:
        note = note.model_copy(update={"next_action": next_action or ""})
    if next_action_date is not _UNSET:
        note = note.model_copy(update={"next_action_date": next_action_date})
    write_application_note(note)

    # Mirror status on the JobNote so dashboard queries reflect current state
    job_id = note.job_ref
    try:
        job_path = find_jobnote(job_id)
        _update_jobnote_status(job_path, status)
    except LookupError:
        logger.warning("update_status: could not find linked JobNote for %r", job_id)

    append_agent_log(f"application status {note.company} {note.title} {current}→{status}")
    return note


def list_pending_actions(through_date: date | None = None) -> list[dict]:
    """Return application rows with next_action_date <= cutoff, sorted ascending.

    Each row is JSON-serializable: dates are emitted as ISO strings (via the
    ApplicationNote schema's model_dump). The MCP server returns this directly
    over the wire, so raw `date` objects in the dict would fail JSON encoding.
    """
    cutoff = through_date or date.today()
    rows: list[tuple[date, dict]] = []  # keep a typed sort key separately
    apps_dir = cfg.VAULT_PATH / "applications"
    if not apps_dir.exists():
        return []
    for p in apps_dir.glob("*.md"):
        md = frontmatter.load(p).metadata
        nad_raw = md.get("next_action_date")
        if nad_raw is None:
            continue
        if isinstance(nad_raw, str):
            try:
                nad = date.fromisoformat(nad_raw)
            except ValueError:
                continue
        else:
            nad = nad_raw  # already a date (YAML auto-parsed)
        if nad > cutoff:
            continue
        # Serialize via the schema so every field is JSON-safe (dates → ISO strings).
        try:
            note = ApplicationNote(**md)
        except Exception:
            logger.warning("list_pending: skipping malformed note %s", p.name)
            continue
        row = {"file": p.name, **note.model_dump(mode="json")}
        rows.append((nad, row))
    rows.sort(key=lambda r: r[0])
    return [row for _, row in rows]
