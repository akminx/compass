"""Bulk-apply human decisions edited in Obsidian.

Flow:
1. User opens `compass-vault/hitl-pending/*.md` in Obsidian.
2. For jobs they want to approve/reject, they edit the `status:` frontmatter
   field from `pending` to `approved` or `rejected` (and optionally add a
   `feedback:` string). Property pane in Obsidian makes this one-click.
3. User runs either:
     - MCP tool `sync_pending_decisions()` from Claude Code, or
     - CLI `uv run python -m compass.hitl.sync_decisions`
4. This module scans the dir, calls `resume_pending()` for each newly-edited
   row, and returns a summary.

Idempotent: rows that match state_store (status already resolved) are skipped.
"""

from __future__ import annotations

import logging
from typing import Any

import frontmatter

import compass.config as cfg
from compass.hitl import state_store
from compass.hitl.resume import resume_pending

logger = logging.getLogger(__name__)

_ACTIONABLE_STATUSES = {"approved", "rejected"}


async def sync_decisions() -> dict[str, Any]:
    """Scan `hitl-pending/*.md` and apply any user-edited approve/reject
    decisions to the state_store + LangGraph.

    Returns:
        {
          "processed": [{thread_id, company, title, action, result}, ...],
          "skipped":   [{thread_id, reason}, ...],
          "errors":    [{thread_id, error}, ...],
        }
    """
    pending_dir = cfg.VAULT_PATH / "hitl-pending"
    if not pending_dir.exists():
        return {"processed": [], "skipped": [], "errors": []}

    processed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for path in sorted(pending_dir.glob("*.md")):
        try:
            post = frontmatter.load(path)
        except Exception as e:
            errors.append({"file": path.name, "error": f"parse failed: {e}"})
            continue

        thread_id = post.get("thread_id")
        status_str = (post.get("status") or "").strip().lower()
        if not thread_id:
            errors.append({"file": path.name, "error": "missing thread_id frontmatter"})
            continue

        if status_str == "pending":
            continue  # user hasn't decided yet
        if status_str not in _ACTIONABLE_STATUSES:
            # Already resolved (or typo). Check state_store to disambiguate.
            row = await state_store.get_pending(thread_id)
            if row is None:
                skipped.append({"thread_id": thread_id, "reason": "no state_store row"})
            elif row["status"] == status_str:
                # Frontmatter matches DB — already in sync, nothing to do.
                continue
            else:
                skipped.append(
                    {
                        "thread_id": thread_id,
                        "reason": f"unknown status {status_str!r} (DB has {row['status']!r})",
                    }
                )
            continue

        # Check state_store before invoking — avoid trying to resume an
        # already-resolved thread (the resume call would raise but we'd
        # rather summarize cleanly).
        row = await state_store.get_pending(thread_id)
        if row is None:
            skipped.append({"thread_id": thread_id, "reason": "no state_store row"})
            continue
        if row["status"] != "pending":
            skipped.append(
                {"thread_id": thread_id, "reason": f"already {row['status']!r} in DB"}
            )
            continue

        approved = status_str == "approved"
        feedback = post.get("feedback")
        try:
            final = await resume_pending(
                thread_id,
                decision={"approved": approved, "feedback": feedback},
            )
        except (LookupError, ValueError) as e:
            errors.append({"thread_id": thread_id, "error": str(e)})
            continue
        except Exception as e:
            logger.exception("sync_decisions: resume failed for %s", thread_id)
            errors.append({"thread_id": thread_id, "error": f"{type(e).__name__}: {e}"})
            continue

        processed.append(
            {
                "thread_id": thread_id,
                "company": post.get("company"),
                "title": post.get("title"),
                "action": "approved" if approved else "rejected",
                "vault_written": bool(final.get("vault_written")),
            }
        )

    return {"processed": processed, "skipped": skipped, "errors": errors}


def _main() -> None:
    import asyncio
    import json

    result = asyncio.run(sync_decisions())
    p, s, e = result["processed"], result["skipped"], result["errors"]
    print(f"Processed: {len(p)}  Skipped: {len(s)}  Errors: {len(e)}")
    if p:
        print("\n=== processed ===")
        for r in p:
            print(f"  [{r['action']}] {r['company']} — {r['title']}")
    if s:
        print("\n=== skipped ===")
        for r in s:
            print(f"  {r['thread_id'][:10]}  {r['reason']}")
    if e:
        print("\n=== errors ===")
        for r in e:
            print(f"  {r.get('thread_id', r.get('file', '?'))[:20]}  {r['error']}")
    print()
    print(json.dumps({"counts": {"processed": len(p), "skipped": len(s), "errors": len(e)}}))


if __name__ == "__main__":
    _main()
