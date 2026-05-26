"""Mirror the HiTL pending-approvals queue into the Obsidian vault as one
markdown note per paused thread, so the user sees paused jobs in the dashboard
alongside JobNotes and SkillNotes — and resolves them via the MCP `approve`
tool.

Lifecycle:
- `write_pending_note(row)` — called from `graph.py` after `state_store.add_pending`.
  Creates `hitl-pending/<thread_id>-<company>-<title_slug>.md` with status=pending.
- `update_pending_note_status(thread_id, status, feedback)` — called from
  `resume.py` and `timeout_checker.py` after `state_store.mark_resolved`.
  Updates frontmatter in place (resolved notes stay as audit trail).
- `regenerate_all_pending_notes()` — backfill from the current state_store DB.
  Idempotent. Use to seed the vault after schema/state changes or first-time
  setup.

All writes are best-effort: callers wrap in try/except so a vault-write failure
never blocks the HiTL flow itself.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import frontmatter

import compass.config as cfg
from compass.hitl import state_store

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_SUBDIR_NAME = "hitl-pending"


def _hitl_dir() -> Path:
    d = cfg.VAULT_PATH / _SUBDIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(s: str) -> str:
    """Filename-safe slug. Mirrors JobNote naming: alphanumeric + underscores."""
    cleaned = re.sub(r"[^\w\s-]", "", s).strip()
    cleaned = re.sub(r"[-\s]+", "_", cleaned)
    return cleaned[:60] or "untitled"


def _note_path(thread_id: str, company: str, title: str) -> Path:
    return _hitl_dir() / f"{thread_id}-{_slug(company)}-{_slug(title)}.md"


def _company_tag(company: str) -> str:
    tag = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")
    return tag or "unknown"


def _wikilinks(skills: list[str]) -> str:
    if not skills:
        return "_(none)_"
    parts = []
    for s in skills:
        if " " in s:
            parts.append(f"[[{s.replace(' ', '_')}|{s}]]")
        else:
            parts.append(f"[[{s}]]")
    return " · ".join(parts)


def _body(row: dict[str, Any]) -> str:
    matched = list(row.get("matched_skills") or [])
    missing = list(row.get("missing_skills") or [])
    score = float(row["score"])
    tid = row["thread_id"]
    return (
        f"# {row['company']} — {row['title']}\n"
        f"\n"
        f"**Score:** {score:.1f}  ·  **Status:** {row.get('status', 'pending')}\n"
        f"\n"
        f"**Job URL:** <{row['job_url']}>\n"
        f"\n"
        f"## Score reasoning\n"
        f"\n"
        f"{row.get('score_reasoning', '')}\n"
        f"\n"
        f"## Skills\n"
        f"\n"
        f"**Matched:** {_wikilinks(matched)}\n"
        f"**Missing:** {_wikilinks(missing)}\n"
        f"\n"
        f"## Approve or reject\n"
        f"\n"
        f"From Claude Code / Cursor (compass MCP server):\n"
        f"\n"
        f'- Approve: `approve(thread_id="{tid}", approved=True)`\n'
        f'- Reject:  `approve(thread_id="{tid}", approved=False, feedback="...")`\n'
        f"\n"
        f"Or programmatically:\n"
        f"\n"
        f"```python\n"
        f"import asyncio\n"
        f"from compass.hitl.resume import resume_pending\n"
        f"asyncio.run(resume_pending(\n"
        f'    "{tid}",\n'
        f'    decision={{"approved": True}},\n'
        f"))\n"
        f"```\n"
    )


def _frontmatter(row: dict[str, Any]) -> dict[str, Any]:
    status = row.get("status", "pending")
    return {
        "type": "hitl-pending",
        "thread_id": row["thread_id"],
        "company": row["company"],
        "title": row["title"],
        "job_url": row["job_url"],
        "score": float(row["score"]),
        "status": status,
        "created_at": row.get("created_at"),
        "resolved_at": row.get("resolved_at"),
        "feedback": row.get("feedback"),
        "matched_skills": list(row.get("matched_skills") or []),
        "missing_skills": list(row.get("missing_skills") or []),
        "tags": [
            f"#hitl/{status}",
            f"#company/{_company_tag(row['company'])}",
        ],
    }


def write_pending_note(row: dict[str, Any]) -> Path:
    """Write the hitl-pending note for `row` (a `state_store` dict-shaped record).
    Upserts in place — calling twice with the same `thread_id` is a no-op
    beyond updating frontmatter."""
    path = _note_path(row["thread_id"], row["company"], row["title"])
    post = frontmatter.Post(content=_body(row), **_frontmatter(row))
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return path


def update_pending_note_status(
    thread_id: str,
    status: str,
    feedback: str | None = None,
) -> Path | None:
    """Update status + resolved_at + feedback on the hitl-pending note for this
    thread. Located by `thread_id` prefix in filename. Returns the path on
    success, None if the note isn't present."""
    matches = list(_hitl_dir().glob(f"{thread_id}-*.md"))
    if not matches:
        logger.warning(
            "hitl_view: no pending note found for thread_id=%s — skipping update", thread_id
        )
        return None
    path = matches[0]
    post = frontmatter.load(path)
    post["status"] = status
    post["resolved_at"] = datetime.now(UTC).isoformat()
    if feedback is not None:
        post["feedback"] = feedback
    company_tag = _company_tag(str(post.get("company", "")))
    post["tags"] = [f"#hitl/{status}", f"#company/{company_tag}"]
    # Update the in-body status line so the file still reads correctly when
    # opened directly (without relying on Dataview to re-derive from frontmatter).
    content = post.content
    content = re.sub(
        r"(\*\*Status:\*\*\s+)\S+",
        rf"\1{status}",
        content,
        count=1,
    )
    post.content = content
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return path


async def regenerate_all_pending_notes() -> int:
    """Backfill: scan the state_store DB for every row (pending and resolved)
    and write a note for each. Idempotent — overwrites existing notes. Useful
    on first-time setup or after manually editing the DB. Returns count
    written."""
    import aiosqlite

    db = state_store._db_path()
    if not db.exists():
        return 0
    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM pending_approvals") as cur:
            rows = await cur.fetchall()
    count = 0
    for r in rows:
        d = dict(r)
        d["matched_skills"] = json.loads(d.get("matched_skills") or "[]")
        d["missing_skills"] = json.loads(d.get("missing_skills") or "[]")
        write_pending_note(d)
        count += 1
    return count
