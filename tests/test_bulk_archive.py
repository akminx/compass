"""Tests for compass.applications.bulk_archive — bulk-move JobNotes marked
with `manual_action: archive` out of the dashboard's view."""

from __future__ import annotations

import frontmatter

from compass.applications.bulk_archive import archive_marked_jobs


def _write_jobnote(jobs_dir, name: str, manual_action: str | None = None) -> str:
    fm = {"company": "Acme", "title": name, "match_score": 1.0, "status": "new"}
    if manual_action is not None:
        fm["manual_action"] = manual_action
    post = frontmatter.Post(content=f"# {name}\n", **fm)
    fname = f"2026-05-20-acme-{name}-abcd1234.md"
    (jobs_dir / fname).write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return fname


def test_returns_empty_when_no_jobs_dir(temp_vault):
    # temp_vault already created jobs/ — remove to test missing-dir case
    import shutil

    shutil.rmtree(temp_vault / "jobs")
    result = archive_marked_jobs()
    assert result == {"archived": [], "errors": []}


def test_returns_empty_when_no_markers(temp_vault):
    jobs = temp_vault / "jobs"
    _write_jobnote(jobs, "engineer-a")
    _write_jobnote(jobs, "engineer-b")
    result = archive_marked_jobs()
    assert result["archived"] == []
    # Both files still in jobs/
    assert len(list(jobs.glob("*.md"))) == 2


def test_archives_marked_files(temp_vault):
    jobs = temp_vault / "jobs"
    keep = _write_jobnote(jobs, "engineer-keep")
    drop = _write_jobnote(jobs, "engineer-drop", manual_action="archive")

    result = archive_marked_jobs()
    assert result["archived"] == [drop]
    assert (temp_vault / "jobs-archive" / drop).exists()
    assert not (jobs / drop).exists()
    # The keep file is unchanged
    assert (jobs / keep).exists()


def test_stamps_archived_at_and_status(temp_vault):
    jobs = temp_vault / "jobs"
    fname = _write_jobnote(jobs, "engineer-archived", manual_action="archive")
    archive_marked_jobs()

    archived = frontmatter.load(temp_vault / "jobs-archive" / fname)
    assert archived["status"] == "archived"
    assert archived["archived_at"] is not None
    # Original marker is preserved (audit trail)
    assert archived["manual_action"] == "archive"


def test_case_insensitive_marker(temp_vault):
    jobs = temp_vault / "jobs"
    _write_jobnote(jobs, "a", manual_action="ARCHIVE")
    _write_jobnote(jobs, "b", manual_action="Archive")
    _write_jobnote(jobs, "c", manual_action="archive")
    result = archive_marked_jobs()
    assert len(result["archived"]) == 3


def test_ignores_unknown_marker_values(temp_vault):
    jobs = temp_vault / "jobs"
    _write_jobnote(jobs, "a", manual_action="delete")  # not "archive"
    _write_jobnote(jobs, "b", manual_action="apply")
    result = archive_marked_jobs()
    assert result["archived"] == []
    assert len(list(jobs.glob("*.md"))) == 2


def test_idempotent_second_run_does_nothing(temp_vault):
    jobs = temp_vault / "jobs"
    fname = _write_jobnote(jobs, "engineer", manual_action="archive")
    archive_marked_jobs()
    # File now in jobs-archive, not jobs — second call finds no markers
    result2 = archive_marked_jobs()
    assert result2["archived"] == []
    # File still safely in jobs-archive
    assert (temp_vault / "jobs-archive" / fname).exists()
