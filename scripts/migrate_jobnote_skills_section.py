"""One-time migration: backfill the `## Skills` wikilink section into existing JobNote bodies.

Day-1 Obsidian P1 work added a `## Skills` block to `write_job_note` that
renders `[[Python]] · [[LangGraph]]` style wikilinks so the Obsidian graph view
edges JobNotes to SkillNotes. Existing JobNotes written before this change
have the right frontmatter but no body section; this script rewrites them
in-place by re-rendering with the current `write_job_note` logic.

Idempotent: re-running is safe — replaces an existing `## Skills` block if
present, inserts before `## Full JD` (or appends) otherwise.

Dry-run by default; --apply to commit.

Usage:
    uv run python -m scripts.migrate_jobnote_skills_section            # dry-run
    uv run python -m scripts.migrate_jobnote_skills_section --apply    # commit
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import TYPE_CHECKING

import frontmatter

from compass.config import VAULT_PATH
from compass.vault.schemas import JobNote
from compass.vault.writer import _render_skills_section

if TYPE_CHECKING:
    from pathlib import Path


# Matches `## Skills` heading through (but not including) the next `## ` heading or EOF.
_SKILLS_BLOCK = re.compile(r"(?ms)^## Skills\s*\n.*?(?=^## |\Z)")


def _splice_skills_section(body: str, rendered: str) -> str:
    """Insert or replace the `## Skills` block in a JobNote body.

    - If a `## Skills` block already exists, replace it (re-runs stay clean).
    - Else, insert before the first `## ` heading (typically `## Full JD`).
    - Else, append at end.
    - If `rendered` is empty (note has zero skills in all four lists), strip
      any existing block and return.
    """
    if _SKILLS_BLOCK.search(body):
        # The regex consumes through the blank line separator before the next
        # heading. Re-add a single blank line so subsequent re-runs are no-ops.
        # If `rendered` is empty (no skills), substitute with empty — collapse
        # leftover whitespace below.
        replacement = (rendered + "\n") if rendered else ""
        new_body = _SKILLS_BLOCK.sub(replacement, body, count=1)
        return re.sub(r"\n{3,}", "\n\n", new_body)

    if not rendered:
        return body

    next_heading = re.search(r"(?m)^## ", body)
    block = rendered if rendered.endswith("\n") else rendered + "\n"
    if next_heading:
        idx = next_heading.start()
        return body[:idx] + block + "\n" + body[idx:]
    # No subheading at all — append after a blank line.
    return body.rstrip() + "\n\n" + block


def _rewrite_body(path: Path) -> tuple[bool, str]:
    """Return (changed, new_full_text). Does not write."""
    post = frontmatter.load(path)
    try:
        note = JobNote.model_validate(post.metadata)
    except Exception as exc:
        print(f"  SKIP {path.name}: frontmatter does not validate as JobNote ({exc})")
        return False, ""
    rendered = _render_skills_section(note)
    new_body = _splice_skills_section(post.content, rendered)
    if new_body == post.content:
        return False, ""
    post.content = new_body
    return True, frontmatter.dumps(post) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually rewrite the JobNotes")
    args = parser.parse_args()

    jobs_dir = VAULT_PATH / "jobs"
    paths = sorted(jobs_dir.glob("*.md"))
    changes: list[tuple[Path, str]] = []
    for path in paths:
        changed, new_text = _rewrite_body(path)
        if changed:
            changes.append((path, new_text))

    if not changes:
        print(f"All {len(paths)} JobNote(s) already have a current `## Skills` section.")
        return 0

    print(f"Will update {len(changes)} of {len(paths)} JobNote(s):\n")
    for path, _ in changes:
        print(f"  {path.name}")

    if not args.apply:
        print(f"\nDry-run. Pass --apply to rewrite {len(changes)} files.")
        return 0

    for path, new_text in changes:
        path.write_text(new_text, encoding="utf-8")
    print(f"\nMigrated {len(changes)} JobNote(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
