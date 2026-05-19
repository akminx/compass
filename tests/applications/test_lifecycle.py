from datetime import date
from pathlib import Path

import pytest


def _seed_jobnote(vault: Path, company="Sierra", title="Agent Engineer", url="https://x/s") -> Path:
    """Write a minimal JobNote frontmatter that the lifecycle can find."""
    from compass.vault.schemas import JobNote
    from compass.vault.writer import write_job_note

    note = JobNote(
        company=company,
        title=title,
        url=url,
        source="manual",
        date_found=date(2026, 5, 10),
        match_score=4.5,
    )
    return write_job_note(note)


class TestAddApplication:
    def test_creates_application_note(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application

        app = add_application(job_id="Sierra-Agent_Engineer")
        assert app.company == "Sierra"
        assert app.status == "applied"
        assert any((temp_vault / "applications").glob("*Sierra*"))

    def test_marks_jobnote_status_applied(self, temp_vault):
        job_path = _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application

        add_application(job_id="Sierra-Agent_Engineer")
        import frontmatter

        md = frontmatter.load(job_path)
        assert md["status"] == "applied"
        assert md["applied_at"] is not None

    def test_unknown_job_raises(self, temp_vault):
        from compass.applications.lifecycle import add_application

        with pytest.raises(LookupError):
            add_application(job_id="not-a-real-job")

    def test_ambiguous_job_raises(self, temp_vault):
        _seed_jobnote(temp_vault, company="Sierra", title="Agent Engineer", url="x1")
        _seed_jobnote(temp_vault, company="Sierra", title="Agent Engineer II", url="x2")
        from compass.applications.lifecycle import add_application

        with pytest.raises(LookupError, match="ambiguous"):
            add_application(job_id="Sierra-Agent")


class TestFindJobnoteCaseInsensitive:
    """Regression: scraper board_tokens are usually lowercase ("sierra"), but
    humans naturally type capitalized company names ("Sierra"). The filename
    substring match must be case-insensitive so MCP lookups don't fail on
    capitalization mismatches."""

    def test_capitalized_query_matches_lowercase_filename(self, temp_vault):
        # ATS scrapers pass lowercase board_tokens — simulate that.
        _seed_jobnote(temp_vault, company="sierra", title="Agent Engineer", url="https://x/s")
        from compass.applications.lifecycle import find_jobnote

        # Human types capital S as they see it in target-companies.md
        p = find_jobnote("Sierra-Agent_Engineer")
        assert "sierra-Agent_Engineer" in p.name

    def test_lowercase_query_still_works(self, temp_vault):
        _seed_jobnote(temp_vault, company="sierra", title="Agent Engineer", url="https://x/s")
        from compass.applications.lifecycle import find_jobnote

        p = find_jobnote("sierra-agent_engineer")
        assert p.exists()

    def test_url_match_is_case_sensitive(self, temp_vault):
        """URLs are spec-case-sensitive; don't fuzz them."""
        _seed_jobnote(temp_vault, company="sierra", title="X", url="https://x/CaseSensitive")
        from compass.applications.lifecycle import find_jobnote

        # Lookup by exact URL works
        assert find_jobnote("https://x/CaseSensitive").exists()
        # Different-case URL fails (no filename or URL match)
        with pytest.raises(LookupError):
            find_jobnote("https://x/casesensitive")

    def test_find_application_case_insensitive(self, temp_vault):
        """Same case-sensitivity guard for _find_application (Bug E regression)."""
        _seed_jobnote(temp_vault, company="sierra", title="Agent Engineer", url="https://x/s")
        from compass.applications.lifecycle import _find_application, add_application

        app = add_application(job_id="sierra-Agent_Engineer")
        # Capital S in app_id must still match the lowercase filename
        p = _find_application(f"{app.applied_date.isoformat()}-Sierra")
        assert p.exists()


class TestUpdateStatus:
    def test_valid_transition(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application, update_application_status

        app = add_application(job_id="Sierra")
        updated = update_application_status(
            app_id=f"{app.applied_date.isoformat()}-Sierra",
            status="screen",
            next_action="prep recruiter screen",
            next_action_date=date(2026, 5, 22),
        )
        assert updated.status == "screen"
        assert updated.next_action == "prep recruiter screen"

    def test_invalid_transition_raises(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application, update_application_status

        app = add_application(job_id="Sierra")
        with pytest.raises(ValueError, match="invalid transition"):
            update_application_status(
                app_id=f"{app.applied_date.isoformat()}-Sierra", status="offer"
            )

    def test_force_bypasses_validation(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application, update_application_status

        app = add_application(job_id="Sierra")
        updated = update_application_status(
            app_id=f"{app.applied_date.isoformat()}-Sierra",
            status="offer",
            force=True,
        )
        assert updated.status == "offer"


class TestListPending:
    def test_returns_due_actions(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import (
            add_application,
            list_pending_actions,
            update_application_status,
        )

        app = add_application(job_id="Sierra")
        update_application_status(
            app_id=f"{app.applied_date.isoformat()}-Sierra",
            status="screen",
            next_action="follow up",
            next_action_date=date(2026, 5, 18),
        )
        pending = list_pending_actions(through_date=date(2026, 5, 18))
        assert len(pending) == 1
        assert pending[0]["company"] == "Sierra"

    def test_filters_out_future_actions(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import (
            add_application,
            list_pending_actions,
            update_application_status,
        )

        app = add_application(job_id="Sierra")
        update_application_status(
            app_id=f"{app.applied_date.isoformat()}-Sierra",
            status="screen",
            next_action_date=date(2026, 12, 1),
        )
        pending = list_pending_actions(through_date=date(2026, 5, 18))
        assert pending == []


class TestNextActionSentinel:
    """update_application_status uses a sentinel to distinguish 'don't change'
    from 'clear this field'. Verify both branches and the preservation case."""

    def test_omitted_args_preserve_existing(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application, update_application_status

        app = add_application(job_id="Sierra")
        update_application_status(
            app_id=f"{app.applied_date.isoformat()}-Sierra",
            status="screen",
            next_action="prep call",
            next_action_date=date(2026, 5, 25),
        )
        # Transition again without specifying next_action* — must preserve them
        update_application_status(
            app_id=f"{app.applied_date.isoformat()}-Sierra",
            status="onsite",
        )
        import frontmatter

        path = next((temp_vault / "applications").glob("*Sierra*.md"))
        md = frontmatter.load(path).metadata
        assert md["next_action"] == "prep call"
        assert md["next_action_date"] == "2026-05-25"  # frontmatter stores ISO string

    def test_explicit_none_clears(self, temp_vault):
        _seed_jobnote(temp_vault)
        from compass.applications.lifecycle import add_application, update_application_status

        app = add_application(job_id="Sierra")
        update_application_status(
            app_id=f"{app.applied_date.isoformat()}-Sierra",
            status="screen",
            next_action="prep call",
            next_action_date=date(2026, 5, 25),
        )
        # Clear both with explicit None
        update_application_status(
            app_id=f"{app.applied_date.isoformat()}-Sierra",
            status="onsite",
            next_action=None,
            next_action_date=None,
        )
        import frontmatter

        path = next((temp_vault / "applications").glob("*Sierra*.md"))
        md = frontmatter.load(path).metadata
        assert md["next_action"] == ""
        assert md["next_action_date"] is None
