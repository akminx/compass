"""Top-k retrieval over the skill-inventory Chroma index.

Lazy-init on first call so scoring works before any explicit indexer run.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from compass.rag import indexer


@dataclass
class RetrievedChunk:
    skill: str
    document: str
    score: float  # cosine similarity in [0, 1]; 1.0 = identical


async def retrieve(query: str, k: int = 8) -> list[RetrievedChunk]:
    if not (query or "").strip():
        return []

    collection = indexer._collection(indexer._client())
    if collection.count() == 0 and await indexer.build_index() == 0:
        return []

    [query_emb] = await asyncio.to_thread(indexer._embed, [query])
    res = collection.query(
        query_embeddings=[query_emb],
        n_results=min(k, collection.count()),
    )

    # Collection is pinned to cosine (see indexer._collection); distance ∈ [0, 2].
    return [
        RetrievedChunk(skill=m["skill"], document=d, score=max(0.0, 1.0 - dist / 2.0))
        for m, d, dist in zip(
            res["metadatas"][0], res["documents"][0], res["distances"][0], strict=True
        )
    ]
