"""Shared fixtures for RAG tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def temp_chroma_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test Chroma path so the persistent client doesn't leak between tests."""
    p = tmp_path / "chroma"
    import compass.config as cfg

    monkeypatch.setattr(cfg, "CHROMA_PATH", p)
    return p


@pytest.fixture
def tiny_inventory(temp_vault) -> Path:
    """Small 3-section inventory for fast retrieval tests."""
    inv = temp_vault / "_profile" / "skill-inventory.md"
    inv.parent.mkdir(parents=True, exist_ok=True)
    inv.write_text(
        "# Skill Inventory\n\n"
        "## Python\n\n"
        "Level 4. 5 years building backends and agents in Python. "
        "Cisco MCP server, LangGraph pipelines, FastAPI services.\n\n"
        "## LangGraph\n\n"
        "Level 3. Built Compass pipeline with stateful graph, conditional "
        "edges, interrupt()+AsyncSqliteSaver checkpointing for HITL.\n\n"
        "## React\n\n"
        "Level 1. Touched in school projects. Not a primary skill.\n",
        encoding="utf-8",
    )
    return inv


@pytest.fixture(scope="session")
def embedding_model_cached():
    """Pre-load sentence-transformers once per test session. ~90MB on first run."""
    from sentence_transformers import SentenceTransformer

    SentenceTransformer("all-MiniLM-L6-v2")
