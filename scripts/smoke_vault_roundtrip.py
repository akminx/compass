"""
scripts/test_vault_roundtrip.py — round-trip a fake JobNote through the real vault.

Writes -> reads -> validates -> cleans up. Run before deploying.

Usage:
    uv run python scripts/test_vault_roundtrip.py
"""

from __future__ import annotations

import sys
from datetime import date

import frontmatter

from compass.config import VAULT_PATH
from compass.vault.reader import job_url_exists, list_job_notes
from compass.vault.schemas import CompanyNote, JobNote
from compass.vault.writer import (
    append_agent_log,
    update_skill_note,
    write_company_note,
    write_job_note,
)

SENTINEL_URL = "https://example.com/compass-smoke-test/job/SENTINEL"
SENTINEL_COMPANY = "_SmokeTestCo"


def main() -> int:
    print(f"Vault path: {VAULT_PATH}")
    if not VAULT_PATH.exists():
        print("  X VAULT_PATH does not exist")
        return 1

    note = JobNote(
        company=SENTINEL_COMPANY,
        title="Smoke Test Role",
        url=SENTINEL_URL,
        source="smoke",
        date_found=date.today(),
        match_score=0.0,
        skills_required=["Python"],
        jd_summary="(smoke test - safe to delete)",
    )

    # 1. Write
    job_path = write_job_note(note)
    print(f"  OK wrote job note: {job_path.name}")

    company_path = write_company_note(
        CompanyNote(company=SENTINEL_COMPANY, tier="unknown", roles_seen=1)
    )
    print(f"  OK wrote company note: {company_path.name}")

    skill_path = update_skill_note("Python", SENTINEL_URL)
    print(f"  OK updated skill note: {skill_path.name}")

    append_agent_log("smoke test ran")
    print("  OK appended to agent-log")

    # 2. Read
    if not job_url_exists(SENTINEL_URL):
        print(f"  X job_url_exists returned False for {SENTINEL_URL}")
        return 1
    print("  OK job_url_exists found the URL")

    if job_path not in list_job_notes():
        print("  X list_job_notes did not include the new path")
        return 1
    print("  OK list_job_notes includes the new file")

    # 3. Validate round-tripped frontmatter
    loaded = frontmatter.load(job_path)
    if loaded.metadata.get("company") != SENTINEL_COMPANY:
        print(f"  X company mismatch on reload: {loaded.metadata.get('company')!r}")
        return 1
    print("  OK frontmatter round-trips cleanly")

    # 4. Clean up
    job_path.unlink()
    company_path.unlink()
    print("  OK cleaned up sentinel files (skill note retained - has real counter)")

    print("\nPASSED: vault round-trip works end-to-end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
