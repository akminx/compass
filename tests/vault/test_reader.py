"""Tests for compass.vault.reader."""


def test_read_profile_section_returns_content(temp_vault):
    from compass.vault.reader import read_profile_section

    content = read_profile_section("resume")
    assert "Fake resume body" in content


def test_read_profile_section_missing_returns_empty_string(temp_vault):
    from compass.vault.reader import read_profile_section

    assert read_profile_section("nonexistent") == ""


def test_read_skill_inventory(temp_vault):
    from compass.vault.reader import read_skill_inventory

    content = read_skill_inventory()
    assert "Python: 3" in content


def test_read_resume(temp_vault):
    from compass.vault.reader import read_resume

    assert "Fake resume body" in read_resume()


def test_job_url_exists_false_when_no_jobs(temp_vault):
    from compass.vault.reader import job_url_exists

    assert job_url_exists("https://example.com/jobs/123") is False


def test_job_url_exists_true_when_present(temp_vault):
    from compass.vault.reader import job_url_exists

    (temp_vault / "jobs" / "2026-05-15-Sample-Title.md").write_text(
        "---\ntype: job\nurl: https://example.com/jobs/123\ncompany: Sample\ntitle: Title\nmatch_score: 0\nsource: greenhouse\ndate_found: 2026-05-15\n---\n# Sample\n"
    )
    assert job_url_exists("https://example.com/jobs/123") is True
    assert job_url_exists("https://example.com/jobs/456") is False


def test_list_job_notes_returns_all_files(temp_vault):
    from compass.vault.reader import list_job_notes

    assert list_job_notes() == []
    (temp_vault / "jobs" / "a.md").write_text("---\ntype: job\n---\n")
    (temp_vault / "jobs" / "b.md").write_text("---\ntype: job\n---\n")
    paths = list_job_notes()
    assert len(paths) == 2
    assert all(p.name in {"a.md", "b.md"} for p in paths)
