"""Tests for compass.vault.writer."""

from datetime import date

import frontmatter


def _make_job_note(**overrides):
    from compass.vault.schemas import JobNote

    defaults = dict(
        company="Sierra",
        title="Agent Engineer",
        url="https://jobs.ashbyhq.com/sierra/abc-123",
        source="ashby",
        date_found=date(2026, 5, 17),
        match_score=4.2,
        score_reasoning="Strong MCP match",
        location="New York, NY",
        skills_required=["MCP", "LangGraph"],
        skills_matched=["MCP"],
        skills_missing=["LangGraph"],
        jd_summary="Build agentic systems",
    )
    defaults.update(overrides)
    return JobNote(**defaults)


def test_write_job_note_creates_file(temp_vault):
    from compass.vault.writer import write_job_note

    note = _make_job_note()
    path = write_job_note(note)
    assert path.exists()
    assert path.parent == temp_vault / "jobs"
    assert path.name.startswith("2026-05-17-Sierra-")
    assert path.suffix == ".md"


def test_write_job_note_frontmatter_roundtrips(temp_vault):
    from compass.vault.writer import write_job_note

    note = _make_job_note()
    path = write_job_note(note)
    loaded = frontmatter.load(path)
    assert loaded.metadata["company"] == "Sierra"
    assert loaded.metadata["match_score"] == 4.2
    assert loaded.metadata["url"] == note.url
    assert "MCP" in loaded.metadata["skills_required"]


def test_write_job_note_sanitizes_filename(temp_vault):
    from compass.vault.writer import write_job_note

    note = _make_job_note(title="Senior Engineer / Slash & Special: Chars?")
    path = write_job_note(note)
    assert "/" not in path.name
    assert ":" not in path.name
    assert "?" not in path.name


def test_write_job_note_persists_full_jd_when_provided(temp_vault):
    """Regression: pre-fix JobNotes only carried the LLM-generated summary; the
    raw JD was discarded after extract+score. Humans then couldn't verify what
    the agent actually saw without going back to the URL. Now the full JD is
    appended below the summary in a `## Full JD` section."""
    from compass.vault.writer import write_job_note

    full = "Posthog is hiring an ingestion engineer.\nPrimary language: Go.\nKafka required."
    note = _make_job_note()
    path = write_job_note(note, full_description=full)
    body = path.read_text()
    assert "## Full JD" in body
    assert "Posthog is hiring an ingestion engineer." in body
    assert "Kafka required." in body


def test_write_job_note_omits_full_jd_section_when_not_provided(temp_vault):
    """Backwards-compatibility: callers that don't pass full_description still work."""
    from compass.vault.writer import write_job_note

    path = write_job_note(_make_job_note())
    assert "## Full JD" not in path.read_text()


def test_write_job_note_idempotent_on_duplicate_url(temp_vault):
    """Writing the same URL twice should overwrite the same file, not create a second."""
    from compass.vault.writer import write_job_note

    note = _make_job_note()
    p1 = write_job_note(note)
    p2 = write_job_note(_make_job_note(match_score=4.5))
    assert p1 == p2
    assert len(list((temp_vault / "jobs").glob("*.md"))) == 1
    loaded = frontmatter.load(p2)
    assert loaded.metadata["match_score"] == 4.5


def test_update_skill_note_increments_counter(temp_vault):
    from compass.vault.writer import update_skill_note

    skill_path = temp_vault / "skills" / "LangGraph.md"
    skill_path.write_text(
        "---\ntype: skill\nskill: LangGraph\ncategory: agent-framework\nappears_in_jobs: 5\n---\n# LangGraph\n"
    )
    update_skill_note("LangGraph", "https://example.com/jobs/x")
    loaded = frontmatter.load(skill_path)
    assert loaded.metadata["appears_in_jobs"] == 6


def test_update_skill_note_creates_if_missing(temp_vault):
    from compass.vault.writer import update_skill_note

    update_skill_note("Python", "https://example.com/jobs/x")
    skill_path = temp_vault / "skills" / "Python.md"
    assert skill_path.exists()
    loaded = frontmatter.load(skill_path)
    assert loaded.metadata["skill"] == "Python"
    assert loaded.metadata["appears_in_jobs"] == 1


def test_write_company_note_creates_file(temp_vault):
    from compass.vault.schemas import CompanyNote
    from compass.vault.writer import write_company_note

    note = CompanyNote(company="Sierra", tier="apply-now", roles_seen=1, geo=["NYC"])
    path = write_company_note(note)
    assert path.exists()
    assert path.name == "Sierra.md"
    loaded = frontmatter.load(path)
    assert loaded.metadata["tier"] == "apply-now"
    assert loaded.metadata["roles_seen"] == 1


def test_write_company_note_increments_roles_seen(temp_vault):
    from compass.vault.schemas import CompanyNote
    from compass.vault.writer import write_company_note

    write_company_note(CompanyNote(company="Sierra", tier="apply-now", roles_seen=1))
    write_company_note(CompanyNote(company="Sierra", tier="apply-now", roles_seen=1))
    loaded = frontmatter.load(temp_vault / "companies" / "Sierra.md")
    assert loaded.metadata["roles_seen"] == 2


def test_append_agent_log_writes_line(temp_vault):
    from compass.vault.writer import append_agent_log

    append_agent_log("test action")
    log_text = (temp_vault / "_meta" / "agent-log.md").read_text()
    assert "test action" in log_text
    assert "\n" in log_text


def test_append_agent_log_preserves_existing_content(temp_vault):
    from compass.vault.writer import append_agent_log

    append_agent_log("first")
    append_agent_log("second")
    log_text = (temp_vault / "_meta" / "agent-log.md").read_text()
    assert "first" in log_text
    assert "second" in log_text
    assert log_text.index("first") < log_text.index("second")


def test_job_filenames_unique_per_url_even_with_identical_titles(temp_vault):
    """Regression: titles that sanitize to the same string used to collide on
    disk (e.g. "Engineer / Backend" and "Engineer (Backend)" both became
    "Engineer_Backend.md"), causing silent overwrites for different URLs.
    Including a URL hash in the filename eliminates this class of bug."""
    from compass.vault.writer import write_job_note

    note_a = _make_job_note(
        title="Senior Engineer / Backend",
        url="https://jobs.ashbyhq.com/co/aaa-111",
    )
    note_b = _make_job_note(
        title="Senior Engineer (Backend)",
        url="https://jobs.ashbyhq.com/co/bbb-222",
    )
    p_a = write_job_note(note_a)
    p_b = write_job_note(note_b)

    assert p_a != p_b, "different URLs must never produce the same filename"
    assert p_a.exists()
    assert p_b.exists()
    assert len(list((temp_vault / "jobs").glob("*.md"))) == 2


def test_write_company_note_preserves_human_edits(temp_vault):
    """Regression: every pipeline run used to clobber companies/Co.md fields
    (tier, geo, why_interesting) back to defaults, destroying human edits
    made in Obsidian. Now the writer reads existing values and preserves
    non-default fields when the incoming note has defaults."""
    from compass.vault.schemas import CompanyNote
    from compass.vault.writer import write_company_note

    # First write: pipeline-default (unknown tier, empty fields)
    write_company_note(CompanyNote(company="Sierra", tier="unknown", roles_seen=1))

    # User edits the file in Obsidian to set tier + a why_interesting note
    company_path = temp_vault / "companies" / "Sierra.md"
    text = company_path.read_text()
    text = text.replace("tier: unknown", "tier: apply-now")
    text = text.replace("why_interesting: ''", "why_interesting: 'Top tier agentic startup'")
    company_path.write_text(text)

    # Pipeline runs again with default-shaped note — must NOT clobber human edits
    write_company_note(CompanyNote(company="Sierra", tier="unknown", roles_seen=1))

    import frontmatter

    loaded = frontmatter.load(company_path).metadata
    assert loaded["tier"] == "apply-now", "human-set tier was clobbered"
    assert "Top tier" in loaded["why_interesting"], "human-set why_interesting was clobbered"
    assert loaded["roles_seen"] == 2, "roles_seen should still increment"
