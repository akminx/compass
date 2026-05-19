"""Regression tests for the roles_seen-race fix.

Phase-1.A-patch concern: under MAX_CONCURRENT_JOBS=5, write_company_note's old
"increment existing + incoming" logic raced — 5 parallel writers reading
roles_seen=0 would all increment to 1, last writer wins, 4 increments lost.

Fix: write_company_note preserves existing roles_seen verbatim; gap_aggregator
derives the value from len(JobNotes for company) at end of each run.
"""

from __future__ import annotations

from datetime import date

import frontmatter

from compass.vault.schemas import CompanyNote, JobNote
from compass.vault.writer import write_company_note, write_job_note


def _company_roles_seen(vault, company: str) -> int:
    return frontmatter.load(vault / "companies" / f"{company}.md").metadata["roles_seen"]


def test_write_company_note_does_not_increment(temp_vault):
    """5 sequential writes (simulating parallel writes) must NOT inflate roles_seen."""
    for _ in range(5):
        write_company_note(CompanyNote(company="sierra", tier="apply-now", roles_seen=1))
    # Existing value preserved each write — never accumulates
    assert _company_roles_seen(temp_vault, "sierra") == 1


def test_first_write_uses_incoming_roles_seen(temp_vault):
    """When no CompanyNote exists yet, the incoming value is used."""
    write_company_note(CompanyNote(company="newco", tier="apply-now", roles_seen=3))
    # First write: no existing → preserved as incoming
    # Note: the writer doesn't have an existing record so the dict-merge branch
    # doesn't fire and `note.roles_seen` is what gets persisted.
    assert _company_roles_seen(temp_vault, "newco") == 3


def test_gap_aggregator_derives_roles_seen_from_jobnotes(temp_vault):
    """The actual count should come from gap_aggregator counting JobNotes."""
    # Create 3 JobNotes for sierra, 1 for decagon
    for i, url in enumerate(["https://x/s1", "https://x/s2", "https://x/s3"]):
        write_job_note(
            JobNote(
                company="sierra",
                title=f"Engineer {i}",
                url=url,
                source="manual",
                date_found=date(2026, 5, 18),
                match_score=4.0,
            )
        )
    write_job_note(
        JobNote(
            company="decagon",
            title="MTS",
            url="https://x/d1",
            source="manual",
            date_found=date(2026, 5, 18),
            match_score=4.0,
        )
    )

    # Seed CompanyNotes with stale roles_seen=0
    write_company_note(CompanyNote(company="sierra", tier="apply-now", roles_seen=0))
    write_company_note(CompanyNote(company="decagon", tier="apply-now", roles_seen=0))

    # Regenerate — derives roles_seen from JobNote count
    from compass.analysis.gap_aggregator import regenerate

    regenerate(write=True)

    assert _company_roles_seen(temp_vault, "sierra") == 3
    assert _company_roles_seen(temp_vault, "decagon") == 1


def test_sync_company_counters_zeroes_orphan_companies(temp_vault):
    """CompanyNote for a company with no JobNotes gets roles_seen=0."""
    # CompanyNote exists with roles_seen=5 but no JobNotes for that company
    write_company_note(CompanyNote(company="orphan", tier="unknown", roles_seen=5))

    from compass.analysis.gap_aggregator import regenerate

    regenerate(write=True)

    assert _company_roles_seen(temp_vault, "orphan") == 0


def test_human_edits_preserved_through_resync(temp_vault):
    """Resync only touches roles_seen — human edits to tier/why_interesting stay."""
    # Seed with human edits
    write_company_note(
        CompanyNote(
            company="sierra",
            tier="stretch",  # human override
            roles_seen=0,
            why_interesting="They love Cisco MCP work",  # human edit
        )
    )
    # JobNote for sierra
    write_job_note(
        JobNote(
            company="sierra",
            title="Eng",
            url="https://x/1",
            source="manual",
            date_found=date(2026, 5, 18),
            match_score=4.0,
        )
    )
    from compass.analysis.gap_aggregator import regenerate

    regenerate(write=True)

    md = frontmatter.load(temp_vault / "companies" / "sierra.md").metadata
    assert md["roles_seen"] == 1  # updated
    assert md["tier"] == "stretch"  # preserved
    assert md["why_interesting"] == "They love Cisco MCP work"  # preserved
