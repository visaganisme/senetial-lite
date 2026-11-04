"""MCP Server: docs_search
Exposes hybrid RAG search over technical documentation to agents.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server.mcpserver import MCPServer

import sentinel.config as cfg
from sentinel.retrieval.bm25 import BM25

logger = logging.getLogger(__name__)

server = MCPServer("docs_search")


def _fallback_keyword_search(query: str, top_k: int, access_level: str) -> list[dict[str, Any]]:
    """Fallback search over markdown/text in docs_synthetic or docs when vector DB is unindexed."""
    roots = [cfg.BASE_DIR / "docs_synthetic", cfg.BASE_DIR / "docs"]
    corpus: dict[str, str] = {}
    metadata: dict[str, dict[str, Any]] = {}

    idx = 0
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in (".md", ".txt"):
                try:
                    text = p.read_text(encoding="utf-8")
                except Exception:
                    continue
                # Split into simple sections or paragraphs
                paragraphs = [par.strip() for par in text.split("\n\n") if par.strip()]
                for p_idx, par in enumerate(paragraphs):
                    cid = f"{p.name}:{p_idx}"
                    corpus[cid] = par
                    metadata[cid] = {
                        "source": p.name,
                        "page": 1,
                        "section": f"paragraph {p_idx + 1}",
                        "access_label": "internal" if "internal" in p.name.lower() else "public",
                    }
                    idx += 1

    if not corpus:
        return []

    bm = BM25(corpus)
    top_ids = bm.top(query, top_k)
    results = []
    for rank, cid in enumerate(top_ids, 1):
        meta = metadata[cid]
        if access_level == "public" and meta["access_label"] != "public":
            continue
        results.append(
            {
                "chunk_id": cid,
                "source": meta["source"],
                "page": meta["page"],
                "section": meta["section"],
                "text": corpus[cid][:500],
                "score": round(1.0 / (rank + 1), 4),
            }
        )
    return results


def search_docs(query: str, top_k: int = 5, access_level: str = "internal") -> str:
    """Search engineering specifications, datasheets, manuals, and standards.

    Args:
        query: Technical search query or engineering question.
        top_k: Maximum number of relevant chunks to return (default: 5).
        access_level: Access role, either 'internal' or 'public'.
    """
    try:
        from sentinel.retrieval.retrieve import hybrid_search
        from sentinel.router.schema import load_models_config

        models = load_models_config()
        embed_entries = models.roles.get("embed", [])
        rerank_entries = models.roles.get("rerank", [])

        if embed_entries:
            embed_entry = embed_entries[0]
            res = hybrid_search(
                query=query,
                strategy="structure",
                embed_entry=embed_entry,
                rerank_entries=rerank_entries,
                models_config=models,
                user_access=access_level,
                k=top_k,
                threshold=0.25,
            )
            if not res.not_found and res.chunks:
                hits = []
                for c in res.chunks[:top_k]:
                    hits.append(
                        {
                            "chunk_id": c.chunk_id,
                            "source": c.source,
                            "page": c.page,
                            "section": c.section,
                            "text": c.text,
                            "score": round(c.rerank_score, 4),
                        }
                    )
                return json.dumps(hits, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Hybrid retrieval unavailable, using fallback keyword search: {e}")

    fallback_hits = _fallback_keyword_search(query, top_k, access_level)
    return json.dumps(fallback_hits, ensure_ascii=False, indent=2)


@server.tool()
def docs_search(query: str, top_k: int = 5, access_level: str = "internal") -> str:
    """Search engineering documents (manuals, guides, standards) using hybrid retrieval."""
    return search_docs(query, top_k, access_level)


if __name__ == "__main__":
    server.run(transport="stdio")
