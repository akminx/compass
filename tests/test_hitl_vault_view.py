"""Tests for compass.hitl.vault_view — mirroring pending approvals into the vault."""

from __future__ import annotations

import frontmatter
import pytest

from compass.hitl import state_store, vault_view


@pytest.fixture
def sample_row():
    return {
        "thread_id": "abcd1234ef567890",
        "job_url": "https://jobs.example.com/role/1",
        "company": "Snowflake",
        "title": "Software Engineer - Ecosystem team",
        "score": 3.5,
        "score_reasoning": "Decent fit. Strong Python and SQL. Missing open-source contributions.",
        "matched_skills": ["Python", "SQL"],
        "missing_skills": ["Go", "JavaScript"],
        "status": "pending",
        "created_at": "2026-05-20T16:04:19+00:00",
        "resolved_at": None,
        "feedback": None,
    }


def test_write_pending_note_creates_file_with_frontmatter(temp_vault, sample_row):
    path = vault_view.write_pending_note(sample_row)
    assert path.exists()
    assert path.parent == temp_vault / "hitl-pending"
    # Filename uses thread_id + slugged company + slugged title
    assert sample_row["thread_id"] in path.name
    assert path.name.endswith(".md")

    post = frontmatter.load(path)
    assert post["type"] == "hitl-pending"
    assert post["thread_id"] == sample_row["thread_id"]
    assert post["status"] == "pending"
    assert post["score"] == 3.5
    assert post["matched_skills"] == ["Python", "SQL"]
    assert post["missing_skills"] == ["Go", "JavaScript"]
    assert "#hitl/pending" in post["tags"]
    assert "#company/snowflake" in post["tags"]


def test_write_pending_note_renders_wikilinks_in_body(temp_vault, sample_row):
    path = vault_view.write_pending_note(sample_row)
    body = frontmatter.load(path).content
    assert "[[Python]]" in body
    assert "[[SQL]]" in body
    assert "[[Go]]" in body
    # The approve hint must include the actual thread_id so the user can copy it
    assert sample_row["thread_id"] in body
    assert "approve(thread_id=" in body


def test_write_pending_note_aliases_multiword_skills(temp_vault, sample_row):
    sample_row["matched_skills"] = ["Machine Learning", "RAG"]
    path = vault_view.write_pending_note(sample_row)
    body = frontmatter.load(path).content
    # Multi-word skills use alias wikilink syntax so the link target matches
    # the SkillNote filename (Machine_Learning.md) while the display reads naturally.
    assert "[[Machine_Learning|Machine Learning]]" in body
    assert "[[RAG]]" in body


def test_write_pending_note_is_idempotent(temp_vault, sample_row):
    p1 = vault_view.write_pending_note(sample_row)
    p2 = vault_view.write_pending_note(sample_row)
    assert p1 == p2
    # Single file in directory
    files = list((temp_vault / "hitl-pending").glob("*.md"))
    assert len(files) == 1


def test_update_pending_note_status_changes_status_and_resolved_at(temp_vault, sample_row):
    vault_view.write_pending_note(sample_row)
    path = vault_view.update_pending_note_status(
        sample_row["thread_id"], status="approved", feedback="strong fit"
    )
    assert path is not None
    post = frontmatter.load(path)
    assert post["status"] == "approved"
    assert post["resolved_at"] is not None
    assert post["feedback"] == "strong fit"
    assert "#hitl/approved" in post["tags"]
    # In-body status string also updated
    assert "**Status:** approved" in post.content


def test_update_pending_note_status_returns_none_when_missing(temp_vault):
    path = vault_view.update_pending_note_status("nonexistent-thread", status="approved")
    assert path is None


def test_update_pending_note_status_preserves_skills(temp_vault, sample_row):
    vault_view.write_pending_note(sample_row)
    vault_view.update_pending_note_status(sample_row["thread_id"], status="rejected")
    post = frontmatter.load(
        next((temp_vault / "hitl-pending").glob(f"{sample_row['thread_id']}-*.md"))
    )
    assert post["matched_skills"] == ["Python", "SQL"]
    assert post["missing_skills"] == ["Go", "JavaScript"]


@pytest.mark.asyncio
async def test_regenerate_all_pending_notes_backfills_from_db(temp_vault, temp_hitl_db, sample_row):
    # Seed two pending rows in the state_store
    await state_store.add_pending(
        thread_id=sample_row["thread_id"],
        job_url=sample_row["job_url"],
        company=sample_row["company"],
        title=sample_row["title"],
        score=sample_row["score"],
        score_reasoning=sample_row["score_reasoning"],
        matched_skills=sample_row["matched_skills"],
        missing_skills=sample_row["missing_skills"],
    )
    await state_store.add_pending(
        thread_id="ffff0000aaaa1111",
        job_url="https://jobs.example.com/role/2",
        company="Databricks",
        title="AI Engineer",
        score=4.0,
        score_reasoning="Strong fit",
        matched_skills=["LangChain"],
        missing_skills=["DSPy"],
    )

    n = await vault_view.regenerate_all_pending_notes()
    assert n == 2
    files = sorted((temp_vault / "hitl-pending").glob("*.md"))
    assert len(files) == 2


@pytest.mark.asyncio
async def test_regenerate_handles_missing_db(temp_vault, tmp_path, monkeypatch):
    # Point HITL_STATE_DB at a path that doesn't exist
    import compass.config as cfg

    monkeypatch.setattr(cfg, "HITL_STATE_DB", tmp_path / "does-not-exist.db")
    n = await vault_view.regenerate_all_pending_notes()
    assert n == 0


def test_slug_handles_problematic_chars(temp_vault):
    sample = {
        "thread_id": "test1234",
        "job_url": "https://x",
        "company": "ACME / Inc. (subsidiary)",
        "title": "Engineer — Platform & Infra",
        "score": 3.5,
        "score_reasoning": "ok",
        "matched_skills": [],
        "missing_skills": [],
        "status": "pending",
    }
    path = vault_view.write_pending_note(sample)
    # Filename should be filesystem-safe: no /, no parens, no em-dashes
    name = path.name
    for c in "/():&—":
        assert c not in name, f"problematic char {c!r} leaked into filename {name!r}"
