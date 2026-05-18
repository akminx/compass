from datetime import date

from compass.vault.schemas import ApplicationNote


def test_write_application_note_creates_file(temp_vault):
    from compass.vault.writer import write_application_note

    note = ApplicationNote(
        company="Sierra",
        title="Agent Engineer",
        job_ref="https://x/sierra",
        applied_date=date(2026, 5, 18),
    )
    path = write_application_note(note)
    assert path.exists()
    assert path.name.startswith("2026-05-18-Sierra-Agent_Engineer-")
    assert path.name.endswith(".md")
    # 8-char hash suffix present
    stem = path.stem  # "2026-05-18-Sierra-Agent_Engineer-<hash>"
    suffix = stem.rsplit("-", 1)[-1]
    assert len(suffix) == 8


def test_write_application_idempotent_same_jobref_same_day(temp_vault):
    """Same (company, title, applied_date, job_ref) → same file, updated."""
    from compass.vault.writer import write_application_note

    note = ApplicationNote(
        company="Sierra",
        title="Agent Engineer",
        job_ref="https://x/sierra-team-a",
        applied_date=date(2026, 5, 18),
    )
    p1 = write_application_note(note)
    note2 = note.model_copy(
        update={"next_action": "follow up", "next_action_date": date(2026, 5, 25)}
    )
    p2 = write_application_note(note2)
    assert p1 == p2
    import frontmatter

    md = frontmatter.load(p2)
    assert md["next_action"] == "follow up"


def test_write_application_same_company_title_same_day_different_jobref(temp_vault):
    """Two different postings at the same company on the same day produce
    distinct files (different job_ref → different filename hash)."""
    from compass.vault.writer import write_application_note

    n1 = ApplicationNote(
        company="Sierra",
        title="Agent Engineer",
        job_ref="https://x/sierra-team-a",
        applied_date=date(2026, 5, 18),
    )
    n2 = ApplicationNote(
        company="Sierra",
        title="Agent Engineer",
        job_ref="https://x/sierra-team-b",
        applied_date=date(2026, 5, 18),
    )
    assert write_application_note(n1) != write_application_note(n2)


def test_write_application_separate_files_per_date(temp_vault):
    """Re-applying to the same posting on a different date is allowed."""
    from compass.vault.writer import write_application_note

    n1 = ApplicationNote(
        company="Sierra",
        title="Agent Engineer",
        job_ref="https://x/sierra",
        applied_date=date(2026, 1, 1),
    )
    n2 = ApplicationNote(
        company="Sierra",
        title="Agent Engineer",
        job_ref="https://x/sierra",
        applied_date=date(2026, 5, 18),
    )
    assert write_application_note(n1) != write_application_note(n2)
