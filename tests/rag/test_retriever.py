"""retriever.retrieve(query, k) — top-k chunks by cosine similarity.

Lazy-init builds the index on first call so scoring works before any
explicit indexer invocation."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("embedding_model_cached")


async def test_retrieve_returns_top_k_relevant_chunks(tiny_inventory, temp_chroma_path):
    from compass.rag import indexer, retriever

    await indexer.build_index()

    hits = await retriever.retrieve("Python backend agent work", k=2)
    assert len(hits) == 2
    skills = [h.skill for h in hits]
    assert "Python" in skills
    assert any("Cisco MCP" in h.document for h in hits)
    assert all(0.0 <= h.score <= 1.0 for h in hits)


async def test_retrieve_lazy_inits_index_on_miss(tiny_inventory, temp_chroma_path):
    """If no index exists yet, retrieve() builds one before querying."""
    from compass.rag import retriever

    hits = await retriever.retrieve("LangGraph stateful pipeline", k=1)
    assert len(hits) == 1
    assert hits[0].skill == "LangGraph"


async def test_retrieve_returns_empty_when_inventory_empty(temp_vault, temp_chroma_path):
    """No sections in inventory → retrieve returns [] without crashing."""
    inv = temp_vault / "_profile" / "skill-inventory.md"
    inv.parent.mkdir(parents=True, exist_ok=True)
    inv.write_text("# Empty\n", encoding="utf-8")
    from compass.rag import retriever

    hits = await retriever.retrieve("anything", k=5)
    assert hits == []


async def test_retrieve_k_larger_than_corpus_returns_all(tiny_inventory, temp_chroma_path):
    from compass.rag import indexer, retriever

    await indexer.build_index()
    hits = await retriever.retrieve("python or react", k=99)
    assert 1 <= len(hits) <= 3
