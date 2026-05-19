"""One-time migration: re-classify existing JobNote role_family fields.

`role_family` is stored once at intake and never reconciled. When the
intake_filter OUT keyword list expands (e.g. commit 3828d8f added
"engineering manager", "solutions engineer", "security engineer",
"operations specialist"), existing JobNotes keep their old role_family
and continue to feed the gap plan. This script walks every JobNote
and rewrites role_family to whatever current `keyword_classify` decides.

Behavior:
- title resolves to out-of-scope → set role_family="out-of-scope"
- title resolves to a specific family → set role_family=that family
- title is ambiguous (None — LLM stage decides) → leave role_family alone

Dry-run by default; --apply to commit.

Usage:
    uv run python -m scripts.migrate_role_family            # dry-run
    uv run python -m scripts.migrate_role_family --apply    # commit changes
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

import frontmatter

from compass.config import VAULT_PATH
from compass.pipeline.role_family import keyword_classify

if TYPE_CHECKING:
    from pathlib import Path


def find_changes() -> list[tuple[Path, str, str]]:
    """Return [(file, old, new), ...] for JobNotes whose title now classifies as
    out-of-scope.

    Only out-of-scope transitions are migrated. In-scope re-classifications
    (e.g. keyword says swe-fullstack but body-signal upgrader originally set
    agent-engineer) are left alone — the original write had access to the JD
    body that this script doesn't re-evaluate.
    """
    changes: list[tuple[Path, str, str]] = []
    for path in sorted((VAULT_PATH / "jobs").glob("*.md")):
        post = frontmatter.load(path)
        title = post.metadata.get("title", "")
        old = post.metadata.get("role_family", "")
        in_scope, new = keyword_classify(title)
        if in_scope is False and old != "out-of-scope":
            changes.append((path, old, new))
    return changes


def apply_changes(changes: list[tuple[Path, str, str]]) -> None:
    for path, _, new in changes:
        post = frontmatter.load(path)
        post.metadata["role_family"] = new
        path.write_text(frontmatter.dumps(post), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually rewrite the JobNotes")
    args = parser.parse_args()

    changes = find_changes()
    if not changes:
        print("No JobNotes need role_family migration.")
        return 0

    print(f"Found {len(changes)} JobNote(s) whose role_family disagrees with current classifier:\n")
    for path, old, new in changes:
        print(f"  {path.name}")
        print(f"    {old!r} -> {new!r}")

    if not args.apply:
        print(f"\nDry-run. Pass --apply to rewrite {len(changes)} files.")
        return 0

    apply_changes(changes)
    print(f"\nMigrated {len(changes)} JobNote(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
