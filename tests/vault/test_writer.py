"""Tests for compass.vault.writer."""

from datetime import date

import frontmatter


def _make_job_note(**overrides):
    from compass.vault.schemas import JobNote

    defaults = dict(
        company="AgentCo",
        title="Agent Engineer",
        url="https://jobs.ashbyhq.com/agentco/abc-123",
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
    assert path.name.startswith("2026-05-17-AgentCo-")
    assert path.suffix == ".md"


def test_write_job_note_frontmatter_roundtrips(temp_vault):
    from compass.vault.writer import write_job_note

    note = _make_job_note()
    path = write_job_note(note)
    loaded = frontmatter.load(path)
    assert loaded.metadata["company"] == "AgentCo"
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


def test_write_job_note_strips_html_from_full_jd(temp_vault):
    """Belt-and-suspenders: if a scraper leaks HTML, the writer normalizes it
    before persisting. Archived JobNotes showed `</span></strong></p></div>`
    cruft from a historical scrape path that bypassed `_strip_html` — this
    guards the writer-side boundary regardless of upstream behavior."""
    from compass.vault.writer import write_job_note

    leaky = (
        "<p><strong>About Databricks</strong></p>"
        '<p><span style="font-family: arial;">Databricks is the data and AI company.</span></p>'
        "</div>"
    )
    path = write_job_note(_make_job_note(), full_description=leaky)
    body = path.read_text()
    assert "<p>" not in body
    assert "</span>" not in body
    assert "</div>" not in body
    assert "Databricks is the data and AI company." in body
    assert "About Databricks" in body


def test_write_job_note_preserves_plain_text_with_angle_brackets(temp_vault):
    """A JD containing literal `<` (e.g. `<200ms latency`) must pass through
    untouched — only visibly-HTML inputs get stripped."""
    from compass.vault.writer import write_job_note

    plain = "Build agents with <200ms latency. Use Python 3.12 (>=3.12 OK)."
    path = write_job_note(_make_job_note(), full_description=plain)
    body = path.read_text()
    assert "<200ms latency" in body
    assert ">=3.12" in body


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


def test_jobnote_body_has_skills_section_with_wikilinks(temp_vault):
    """Day 1 Obsidian P1: JobNote body renders a `## Skills` block with
    wikilinks so the graph view shows JobNote → SkillNote edges. Section
    sits between the LLM summary and `## Full JD`."""
    from compass.vault.writer import write_job_note

    note = _make_job_note(
        skills_required=["Python", "LangGraph"],
        skills_nice_to_have=["FastAPI"],
        skills_matched=["Python"],
        skills_missing=["LangGraph"],
    )
    path = write_job_note(note, full_description="raw jd text here")
    body = path.read_text()
    assert "## Skills" in body
    assert "[[Python]]" in body
    assert "[[LangGraph]]" in body
    assert "[[FastAPI]]" in body
    assert "**Required:**" in body
    assert "**Nice to have:**" in body
    assert "**Matched:**" in body
    assert "**Missing:**" in body
    # ## Skills must appear before ## Full JD
    assert body.index("## Skills") < body.index("## Full JD")


def test_jobnote_body_omits_empty_skill_categories(temp_vault):
    """Empty categories are omitted entirely — no '(none)' placeholder."""
    from compass.vault.writer import write_job_note

    note = _make_job_note(
        skills_required=["Python"],
        skills_nice_to_have=[],
        skills_matched=[],
        skills_missing=["Python"],
    )
    path = write_job_note(note)
    body = path.read_text()
    assert "**Nice to have:**" not in body
    assert "**Matched:**" not in body
    assert "**Required:** [[Python]]" in body
    assert "**Missing:** [[Python]]" in body


def test_jobnote_skill_wikilink_aliases_unsafe_filenames(temp_vault):
    """Skills with spaces or punctuation resolve to a safe-segment filename;
    the wikilink must point at the actual file via alias form so the link
    resolves AND the display matches the user-facing skill name."""
    from compass.vault.writer import write_job_note

    note = _make_job_note(
        skills_required=["AWS Bedrock", "C++"],
        skills_matched=[],
        skills_missing=[],
        skills_nice_to_have=[],
    )
    path = write_job_note(note)
    body = path.read_text()
    assert "[[AWS_Bedrock|AWS Bedrock]]" in body
    # `_safe_segment` collapses non-word runs to `_` then strips trailing `_`,
    # so "C++" becomes the file "C.md" — alias keeps the original display.
    assert "[[C|C++]]" in body


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


def test_write_company_note_creates_file(temp_vault):
    from compass.vault.schemas import CompanyNote
    from compass.vault.writer import write_company_note

    note = CompanyNote(company="AgentCo", tier="apply-now", roles_seen=1, geo=["NYC"])
    path = write_company_note(note)
    assert path.exists()
    assert path.name == "AgentCo.md"
    loaded = frontmatter.load(path)
    assert loaded.metadata["tier"] == "apply-now"
    assert loaded.metadata["roles_seen"] == 1


def test_write_company_note_does_not_increment_roles_seen(temp_vault):
    """Post-Phase-1A: write_company_note no longer accumulates roles_seen — that
    raced under MAX_CONCURRENT_JOBS=5. Counter is now derived by
    gap_aggregator._sync_company_counters from JobNote count. See
    tests/vault/test_company_counters.py for the derivation tests."""
    from compass.vault.schemas import CompanyNote
    from compass.vault.writer import write_company_note

    write_company_note(CompanyNote(company="AgentCo", tier="apply-now", roles_seen=1))
    write_company_note(CompanyNote(company="AgentCo", tier="apply-now", roles_seen=1))
    loaded = frontmatter.load(temp_vault / "companies" / "AgentCo.md")
    # First write set it to 1; subsequent writes preserve existing (1), NOT add to it
    assert loaded.metadata["roles_seen"] == 1


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
    write_company_note(CompanyNote(company="AgentCo", tier="unknown", roles_seen=1))

    # User edits the file in Obsidian to set tier + a why_interesting note
    company_path = temp_vault / "companies" / "AgentCo.md"
    text = company_path.read_text()
    text = text.replace("tier: unknown", "tier: apply-now")
    text = text.replace("why_interesting: ''", "why_interesting: 'Top tier agentic startup'")
    company_path.write_text(text)

    # Pipeline runs again with default-shaped note — must NOT clobber human edits
    write_company_note(CompanyNote(company="AgentCo", tier="unknown", roles_seen=1))

    import frontmatter

    loaded = frontmatter.load(company_path).metadata
    assert loaded["tier"] == "apply-now", "human-set tier was clobbered"
    assert "Top tier" in loaded["why_interesting"], "human-set why_interesting was clobbered"
    # Post-Phase-1A: roles_seen is preserved verbatim by write_company_note;
    # gap_aggregator's _sync_company_counters owns the actual value.
    assert loaded["roles_seen"] == 1, "roles_seen should be preserved (not incremented)"
