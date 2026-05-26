"""One-shot seed: create a CompanyNote in compass-vault/companies/ for every
company in _profile/target-companies.yaml, pre-populated with tier, geo,
why_interesting, interview_difficulty, prior_employer_adjacency from the YAML.

Why this exists: write_company_note auto-creates default-shaped notes on
first sighting (tier=unknown, geo=[], etc.). Without this seed step, the
dashboard would be empty for 41 companies until the human filled them in by
hand. With it, the dashboard works the moment the pipeline produces its
first JobNote.

Preserves existing CompanyNote human edits — same merge logic as
write_company_note (preserve incoming-default vs. existing-non-default).

Dry-run by default; --apply to commit.

Usage:
    uv run python -m scripts.seed_companies_from_yaml            # dry-run
    uv run python -m scripts.seed_companies_from_yaml --apply    # commit
"""

from __future__ import annotations

import argparse
import sys

from compass.vault.schemas import CompanyNote
from compass.vault.target_companies import list_yaml_companies, refresh_yaml
from compass.vault.writer import write_company_note


def _to_company_note(entry: dict) -> CompanyNote:
    """Project a YAML entry onto the CompanyNote schema. Invalid Literal values
    collapse to safe defaults — write_company_note + Pydantic will validate."""
    tier = entry.get("tier") or "unknown"
    if tier not in {
        "apply-now",
        "opportunistic",
        "backend-prep",
        "6-month",
        "stretch",
        "skip",
        "unknown",
    }:
        tier = "unknown"

    difficulty = str(entry.get("interview_difficulty") or "unknown").strip().lower()
    if difficulty not in {
        "hackerrank",
        "case",
        "lc-easy",
        "lc-medium",
        "lc-medium-hard",
        "lc-hard",
        "takehome",
        "unknown",
    }:
        difficulty = "unknown"

    return CompanyNote(
        company=entry["company"],
        tier=tier,  # type: ignore[arg-type]
        geo=list(entry.get("geos") or []),
        why_interesting=str(entry.get("notes") or ""),
        interview_difficulty=difficulty,  # type: ignore[arg-type]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually write the CompanyNotes")
    args = parser.parse_args()

    refresh_yaml()
    entries = list_yaml_companies()
    if not entries:
        print("No companies found in _profile/target-companies.yaml.")
        return 1

    # Defense against an empty-string `company:` field in YAML (would otherwise
    # write `companies/.md` as a dotfile carrying no information). Drop with
    # a warning rather than persist garbage.
    valid_entries = []
    for e in entries:
        if not (e.get("company") or "").strip():
            print(f"  ! skipping YAML entry with empty company name: {e!r}")
            continue
        valid_entries.append(e)
    notes = [_to_company_note(e) for e in valid_entries]
    print(f"Will seed {len(notes)} CompanyNote(s):\n")
    for n in notes:
        print(f"  {n.company:25s}  tier={n.tier:14s}  diff={n.interview_difficulty}")

    if not args.apply:
        print(f"\nDry-run. Pass --apply to write {len(notes)} files.")
        return 0

    for n in notes:
        write_company_note(n)
    print(f"\nSeeded {len(notes)} CompanyNote(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
