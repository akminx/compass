"""
Tests for vault reader and writer.
Run: uv run pytest tests/test_vault.py -v
"""
import pytest
from pathlib import Path
from datetime import date
from compass.vault.schemas import JobNote, SkillNote


def test_job_note_schema_valid():
    """JobNote Pydantic model validates correctly."""
    note = JobNote(
        company="Databricks",
        title="Applied AI Engineer",
        url="https://databricks.com/jobs/123",
        source="greenhouse",
        date_found=date.today(),
        match_score=4.2,
        skills_required=["LangGraph", "MLflow", "Python"],
        skills_missing=["MLflow"],
        jd_summary="Build LLM features on the Databricks Lakehouse.",
    )
    assert note.company == "Databricks"
    assert note.match_score == 4.2
    assert "MLflow" in note.skills_missing


def test_skill_note_defaults():
    """SkillNote has sensible defaults."""
    note = SkillNote(skill="LangGraph", category="agent-framework")
    assert note.my_level == "none"
    assert note.appears_in_jobs == 0
    assert note.priority == "medium"


@pytest.mark.asyncio
async def test_vault_reader_skill_inventory(tmp_path, monkeypatch):
    """read_skill_inventory reads the skill-inventory.md from the vault."""
    # TODO: implement once vault reader is built
    pass


@pytest.mark.asyncio
async def test_job_url_deduplication(tmp_path, monkeypatch):
    """job_url_exists correctly identifies duplicate job URLs."""
    # TODO: implement once vault reader is built
    pass
