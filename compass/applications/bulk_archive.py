"""Bulk-archive JobNotes that the user has marked for archiving.

Flow:
1. User opens a JobNote (e.g. an auto-rejected one cluttering the dashboard)
   in Obsidian.
2. Adds `manual_action: archive` to its frontmatter (or directly via the
   property pane).
3. Runs the MCP tool `archive_marked_jobs()` (or CLI
   `uv run python -m compass.applications.bulk_archive`).
4. Every marked file is moved into `compass-vault/jobs-archive/` —
   a sibling folder, not a subfolder, so dashboard Dataview queries
   (`FROM "jobs"`) don't see archived rows.

Audit trail: files aren't deleted, just relocated. The frontmatter is
updated with `archived_at` so the move is reversible by hand.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import frontmatter

import compass.config as cfg
from compass.vault.writer import append_agent_log

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_ARCHIVE_DIRNAME = "jobs-archive"
_MARKER_FIELD = "manual_action"
_MARKER_VALUE = "archive"


def _archive_dir() -> Path:
    d = cfg.VAULT_PATH / _ARCHIVE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def archive_marked_jobs() -> dict:
    """Scan `jobs/*.md` for `manual_action: archive` frontmatter and move each
    to `jobs-archive/`. Returns {"archived": [...], "errors": [...]}.

    Idempotent. Doesn't touch JobNotes without the marker. Doesn't touch
    files already in jobs-archive/ (recursive globs are not used)."""
    jobs_dir = cfg.VAULT_PATH / "jobs"
    if not jobs_dir.exists():
        return {"archived": [], "errors": []}

    archived: list[str] = []
    errors: list[dict[str, str]] = []
    archive_dir = _archive_dir()

    for path in sorted(jobs_dir.glob("*.md")):
        try:
            post = frontmatter.load(path)
        except Exception as e:
            errors.append({"file": path.name, "error": f"parse failed: {e}"})
            continue

        marker = str(post.get(_MARKER_FIELD) or "").strip().lower()
        if marker != _MARKER_VALUE:
            continue

        # Stamp the archive timestamp + status
        post["archived_at"] = datetime.now(UTC).isoformat()
        post["status"] = "archived"
        try:
            target = archive_dir / path.name
            if target.exists():
                # Already archived (e.g. retry after a partial run). Don't
                # overwrite — the existing copy carries the original archive
                # timestamp; clobbering would silently lose that signal.
                logger.warning(
                    "archive_marked_jobs: %s already at %s; leaving both in place",
                    path.name, target,
                )
                errors.append({"file": path.name, "error": "already archived; skipped"})
                continue
            # Write target first, then atomically remove the source. If the
            # process dies between the two we re-enter the `target.exists()`
            # branch on retry rather than double-archiving.
            target.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
            path.unlink()
        except Exception as e:
            logger.exception("archive_marked_jobs: failed for %s", path.name)
            errors.append({"file": path.name, "error": f"move failed: {e}"})
            continue

        archived.append(path.name)
        try:
            append_agent_log(
                f"archive jobnote {path.name} (company={post.get('company')}, "
                f"score={post.get('match_score')})"
            )
        except Exception:
            logger.exception("archive_marked_jobs: agent-log append failed")

    return {"archived": archived, "errors": errors}


def _main() -> None:
    import json

    result = archive_marked_jobs()
    print(f"Archived: {len(result['archived'])}  Errors: {len(result['errors'])}")
    for fname in result["archived"]:
        print(f"  → jobs-archive/{fname}")
    for e in result["errors"]:
        print(f"  ! {e['file']}: {e['error']}")
    print()
    print(json.dumps({"counts": {k: len(v) for k, v in result.items()}}))


if __name__ == "__main__":
    _main()
