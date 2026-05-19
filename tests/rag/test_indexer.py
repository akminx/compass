"""indexer parses skill-inventory.md by ## SkillName, embeds, persists.

Idempotent on rebuild (upsert by stable kebab id). Uses real sentence-
transformers (model cached at session scope — ~90MB on first run only)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("embedding_model_cached")


async def test_indexer_builds_one_chunk_per_section(tiny_inventory, temp_chroma_path):
    from compass.rag import indexer

    assert await indexer.build_index() == 3


async def test_indexer_uses_kebab_case_ids(tiny_inventory, temp_chroma_path):
    from compass.rag import indexer

    await indexer.build_index()
    col = indexer._collection(indexer._client())
    assert set(col.get()["ids"]) == {"python", "langgraph", "react"}


async def test_indexer_metadata_carries_skill_and_source(tiny_inventory, temp_chroma_path):
    from compass.rag import indexer

    await indexer.build_index()
    col = indexer._collection(indexer._client())
    res = col.get(ids=["python"])
    assert res["metadatas"][0]["skill"] == "Python"
    assert res["metadatas"][0]["source"] == "skill-inventory.md"


async def test_indexer_is_idempotent_on_rebuild(tiny_inventory, temp_chroma_path):
    from compass.rag import indexer

    await indexer.build_index()
    await indexer.build_index()
    col = indexer._collection(indexer._client())
    assert col.count() == 3


async def test_indexer_force_rebuild_clears_stale_chunks(tiny_inventory, temp_chroma_path):
    from compass.rag import indexer

    await indexer.build_index()
    tiny_inventory.write_text(
        "# Skill Inventory\n\n## Python\n\nLevel 4.\n",
        encoding="utf-8",
    )
    await indexer.build_index(force_rebuild=True)
    col = indexer._collection(indexer._client())
    assert set(col.get()["ids"]) == {"python"}


async def test_indexer_repairs_stale_l2_collection(temp_vault, temp_chroma_path):
    """Pre-1.B.2 installs may have an L2 collection — must be dropped+recreated
    so the retriever's cosine-score formula stays valid."""
    from chromadb import PersistentClient

    from compass.rag import indexer

    client = PersistentClient(path=str(temp_chroma_path))
    client.create_collection(name="skill_inventory")  # default = L2

    col = indexer._collection(client)
    assert (col.metadata or {}).get("hnsw:space") == "cosine"


async def test_indexer_excludes_assessor_grades_heading(temp_vault, temp_chroma_path):
    """Auto-generated `## Assessor-current grades` is metadata, not a skill —
    must NOT land in the index or it pollutes retrieval with every skill name."""
    inv = temp_vault / "_profile" / "skill-inventory.md"
    inv.parent.mkdir(parents=True, exist_ok=True)
    inv.write_text(
        "## Python\n\nLevel 4.\n\n"
        "## Assessor-current grades\n\nPython: 4 / LangGraph: 3 / MCP: 5\n",
        encoding="utf-8",
    )
    from compass.rag import indexer

    assert await indexer.build_index() == 1
    col = indexer._collection(indexer._client())
    assert set(col.get()["ids"]) == {"python"}


async def test_indexer_handles_empty_inventory_gracefully(temp_vault, temp_chroma_path):
    inv = temp_vault / "_profile" / "skill-inventory.md"
    inv.parent.mkdir(parents=True, exist_ok=True)
    inv.write_text("# Skill Inventory\n\nNo skills yet.\n", encoding="utf-8")
    from compass.rag import indexer

    assert await indexer.build_index() == 0
