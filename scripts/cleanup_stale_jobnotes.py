"""
One-time cleanup: delete JobNotes written before the score-constrain fix shipped.

The 16-silent-bug retro (2026-05-18) fixed bug #5 (matched/missing must be a subset
of the JD's required+nice_to_have lists) at commit 5fa8d2e — 2026-05-18 01:22 local.
JobNotes written before that timestamp can contain hallucinated matched/missing
skills (e.g. claiming AWS/Azure/Docker were matched against a JD with empty
required_skills). URL-dedup prevents `run_pipeline` from refreshing them.

Per CLAUDE.md this script is human-triggered — it never deletes without `--apply`.

Usage:
    uv run python -m scripts.cleanup_stale_jobnotes              # dry-run; lists candidates
    uv run python -m scripts.cleanup_stale_jobnotes --apply      # actually delete
    uv run python -m scripts.cleanup_stale_jobnotes --cutoff '2026-05-18 02:06:23'
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import TYPE_CHECKING

import frontmatter

from compass.config import VAULT_PATH

if TYPE_CHECKING:
    from pathlib import Path

# Final fix commit `275c920` shipped 2026-05-18 02:06:23 local; anything older
# than this may have hallucinated matched/missing skills or stale taxonomy data.
DEFAULT_CUTOFF = "2026-05-18 02:06:23"


def _violates_constraint(meta: dict) -> bool:
    """Returns True if matched∪missing leak skills outside the JD universe.

    This is the exact check the score_node._constrain_to_jd_skills filter
    enforces today. Any JobNote that fails this check was written before
    the fix.
    """
    universe = set(meta.get("skills_required") or []) | set(meta.get("skills_nice_to_have") or [])
    surface = set(meta.get("skills_matched") or []) | set(meta.get("skills_missing") or [])
    return bool(surface - universe)


def find_stale(cutoff_dt: datetime) -> list[tuple[Path, str]]:
    jobs_dir = VAULT_PATH / "jobs"
    stale: list[tuple[Path, str]] = []
    for path in sorted(jobs_dir.glob("*.md")):
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        reasons: list[str] = []
        if mtime < cutoff_dt:
            reasons.append(f"mtime {mtime.isoformat(timespec='seconds')} < cutoff")
        try:
            meta = frontmatter.load(path).metadata
        except Exception as e:
            reasons.append(f"unparseable frontmatter ({e})")
            stale.append((path, "; ".join(reasons)))
            continue
        if _violates_constraint(meta):
            reasons.append("matched/missing leak outside JD universe")
        if reasons:
            stale.append((path, "; ".join(reasons)))
    return stale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", default=DEFAULT_CUTOFF, help="Local-time cutoff")
    parser.add_argument("--apply", action="store_true", help="Actually delete (default: dry-run)")
    args = parser.parse_args()

    cutoff_dt = datetime.fromisoformat(args.cutoff)
    stale = find_stale(cutoff_dt)

    if not stale:
        print("No stale JobNotes found.")
        return 0

    print(f"Found {len(stale)} stale JobNotes (cutoff={cutoff_dt.isoformat()}):\n")
    for path, reason in stale:
        print(f"  {path.name}\n      {reason}")

    if not args.apply:
        print("\nDry-run — pass --apply to delete. After deletion, re-run the pipeline")
        print("to re-score these URLs cleanly.")
        return 0

    for path, _ in stale:
        path.unlink()
        print(f"deleted {path.name}")
    print(f"\nDeleted {len(stale)} files. Re-run the pipeline to re-score these URLs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
