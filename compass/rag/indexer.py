"""Chroma index of _profile/skill-inventory.md.

One chunk per `## SkillName` section. Collection metric is cosine — the
retriever's similarity score formula depends on this.
"""

from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "skill_inventory"
_SECTION_RE = re.compile(r"^## +(.+)$", re.M)
# Auto-generated assessor output; not a skill — exclude from the index.
_EXCLUDED_HEADINGS = {"Assessor-current grades"}


def _client():
    from chromadb import PersistentClient

    import compass.config as cfg

    cfg.CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    return PersistentClient(path=str(cfg.CHROMA_PATH))


def _collection(client):
    """Return the skill_inventory collection pinned to cosine distance.

    `get_or_create_collection` does NOT update an existing collection's
    metadata — so a pre-existing L2 collection would silently keep the wrong
    metric and break the retriever's score formula. Drop and recreate if so.
    """
    existing = {c.name for c in client.list_collections()}
    if _COLLECTION_NAME in existing:
        col = client.get_collection(_COLLECTION_NAME)
        if (col.metadata or {}).get("hnsw:space") == "cosine":
            return col
        client.delete_collection(_COLLECTION_NAME)
    return client.create_collection(
        name=_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def _kebab(name: str) -> str:
    # Drop parenthetical asides and em-dash commentary — they're not identity.
    # `Fine-Tuning (awareness only — ...)` -> `fine-tuning`
    # `MCP — your strongest cluster` -> `mcp`
    primary = re.sub(r"\s*(?:\(|[—–]\s).*$", "", name).strip()
    return re.sub(r"[^a-z0-9]+", "-", primary.lower()).strip("-") or "untitled"


def _parse_inventory(text: str) -> list[tuple[str, str]]:
    """Return [(skill_name, section_text), ...] — one entry per ## heading.

    Skips headings in _EXCLUDED_HEADINGS (auto-generated metadata that isn't
    a real skill and would otherwise pollute retrieval).
    """
    matches = list(_SECTION_RE.finditer(text))
    sections = []
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        if any(name.startswith(prefix) for prefix in _EXCLUDED_HEADINGS):
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((name, text[m.start() : end].strip()))
    return sections


_EMBEDDING_MODEL = None


def _get_embedding_model():
    """Lazy-load + cache the sentence-transformers model. Loading model weights
    from disk on every retriever call (and on every score in production) made
    each RAG query pay the model-load cost; singleton-cache eliminates that.
    """
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None:
        from sentence_transformers import SentenceTransformer

        import compass.config as cfg

        _EMBEDDING_MODEL = SentenceTransformer(cfg.EMBEDDING_MODEL)
    return _EMBEDDING_MODEL


def _embed(documents: list[str]) -> list[list[float]]:
    arr = _get_embedding_model().encode(documents, convert_to_numpy=True, show_progress_bar=False)
    return [vec.tolist() for vec in arr]


async def build_index(force_rebuild: bool = False) -> int:
    """Embed each `## Section` of skill-inventory.md and upsert into Chroma.

    Idempotent — repeat calls upsert by stable id. Pass `force_rebuild=True`
    to drop the collection first (use when the inventory shrinks; otherwise
    deleted skills' stale chunks linger).
    """
    import compass.config as cfg

    if not cfg.SKILL_INVENTORY_PATH.exists():
        logger.warning("rag: skill-inventory.md not found at %s", cfg.SKILL_INVENTORY_PATH)
        return 0

    sections = _parse_inventory(cfg.SKILL_INVENTORY_PATH.read_text(encoding="utf-8"))
    if not sections:
        logger.info("rag: 0 ## sections in skill-inventory.md; nothing to index")
        return 0

    client = _client()
    if force_rebuild and _COLLECTION_NAME in {c.name for c in client.list_collections()}:
        client.delete_collection(_COLLECTION_NAME)
    collection = _collection(client)

    documents = [body for _, body in sections]
    new_ids = [_kebab(name) for name, _ in sections]
    embeddings = await asyncio.to_thread(_embed, documents)

    collection.upsert(
        ids=new_ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=[{"skill": name, "source": "skill-inventory.md"} for name, _ in sections],
    )

    # ORPHAN CLEANUP: upsert only adds/updates — it never deletes. If a skill
    # was renamed ("LangGraph" → "LangGraph (async)") or removed from
    # skill-inventory.md, the old chunk's id stays in the collection forever
    # and pollutes future RAG retrievals. After every build, drop any id in
    # the collection that's NOT in the current section list.
    existing = collection.get(include=[]).get("ids", [])
    orphan_ids = [eid for eid in existing if eid not in set(new_ids)]
    if orphan_ids:
        collection.delete(ids=orphan_ids)
        logger.info("rag: pruned %d orphaned chunks (skills removed/renamed)", len(orphan_ids))

    logger.info("rag: indexed %d sections at %s", len(sections), cfg.CHROMA_PATH)
    return len(sections)


def _main() -> None:
    import argparse

    import compass.config as cfg

    parser = argparse.ArgumentParser(description="Rebuild Chroma index of skill-inventory.md")
    parser.add_argument("--force", action="store_true", help="Drop+rebuild the collection")
    n = asyncio.run(build_index(force_rebuild=parser.parse_args().force))
    print(f"Indexed {n} sections from {cfg.SKILL_INVENTORY_PATH}")


if __name__ == "__main__":
    _main()
