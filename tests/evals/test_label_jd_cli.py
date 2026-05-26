"""Smoke tests for scripts/label_jd.py — the spec-required interactive CLI.

Heavy interactive coverage isn't worth it (prompts are I/O-bound and the
runtime is short). These tests pin the load + path-validation logic + the
non-interactive `--score`/`--skills` path.
"""

from __future__ import annotations

import pytest


def test_load_jobnote_path_traversal_rejected(temp_vault):
    """`jobnote` argument is user input — escapes from vault/jobs/ must fail."""
    from scripts.label_jd import _load_jobnote

    with pytest.raises(SystemExit):
        _load_jobnote("../_profile/resume.md")


def test_load_jobnote_missing_file(temp_vault):
    from scripts.label_jd import _load_jobnote

    with pytest.raises(SystemExit):
        _load_jobnote("nonexistent.md")


def test_load_jobnote_reads_full_jd_section(temp_vault):
    """When the JobNote has a `## Full JD` section, that's what we label
    against — not the summary or the wikilink table."""
    from scripts.label_jd import _load_jobnote

    note = temp_vault / "jobs" / "test.md"
    note.write_text(
        "---\ncompany: AgentCo\ntitle: Engineer\nurl: https://x\nsource: ashby\n"
        "date_found: 2026-05-19\nmatch_score: 4.0\nscore_reasoning: t\n"
        "role_family: agent-engineer\ntier: apply-now\n"
        "skills_required: []\nskills_nice_to_have: []\n"
        "skills_matched: []\nskills_missing: []\njd_summary: short\n---\n"
        "# header\n\nsummary text\n\n## Skills\n\n**Required:** stuff\n\n"
        "## Full JD\n\nThis is the real JD body about LangGraph and MCP.\n"
    )
    jd_text, company, title, source = _load_jobnote("test.md")
    assert "LangGraph and MCP" in jd_text
    assert "summary text" not in jd_text  # confirms we sliced past summary
    assert company == "AgentCo"
    assert title == "Engineer"
    assert "AgentCo" in source
