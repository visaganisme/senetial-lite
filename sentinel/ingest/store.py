"""Chroma persistence: one collection per (chunk-strategy x embedder)."""

from __future__ import annotations

import sentinel.config as cfg
from sentinel.ingest.chunk import Chunk
from sentinel.ingest.embed import embed_texts
from sentinel.router.schema import ChainEntry


def collection_name(strategy: str, embed_model: str) -> str:
    slug = embed_model.replace("/", "_").replace("@", "").replace(".", "-").lower()
    return f"rag_{strategy}_{slug}"


def client():
    import chromadb

    return chromadb.PersistentClient(path=str(cfg.BASE_DIR / "chroma"))


def build(
    chunks: list[Chunk], strategy: str, embed_entry: ChainEntry, batch: int = 64
) -> tuple[str, int]:
    """(Re)build the collection for (strategy, embed_entry). Returns (name, n_chunks)."""
    name = collection_name(strategy, embed_entry.model)
    coll = client().get_or_create_collection(name, metadata={"hnsw:space": "cosine"})
    if coll.count():
        coll.delete(coll.get()["ids"])
    for i in range(0, len(chunks), batch):
        part = chunks[i : i + batch]
        vecs = embed_texts(embed_entry, [c.text for c in part])
        coll.add(
            ids=[c.id for c in part],
            embeddings=vecs,
            documents=[c.text for c in part],
            metadatas=[
                {
                    "source": c.source,
                    "page": c.page,
                    "section": c.section or "",
                    "access_label": c.access_label,
                    "chunk_id": c.id,
                    "strategy": strategy,
                }
                for c in part
            ],
        )
    return name, len(chunks)


def load_all(name: str) -> dict:
    """Full dump (id -> {text, metadata}) for the BM25 side of retrieval."""
    coll = client().get_collection(name)
    data = coll.get(include=["documents", "metadatas"])
    return {
        did: {"text": text, "meta": meta}
        for did, text, meta in zip(data["ids"], data["documents"], data["metadatas"], strict=False)
    }
