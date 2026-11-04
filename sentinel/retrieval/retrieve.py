"""Hybrid retrieval: vector (Chroma, access-filtered) + BM25 -> RRF -> Cohere rerank ->
threshold. Access filtering happens INSIDE the query (Chroma where + BM25 corpus subset)."""

from __future__ import annotations

from pydantic import BaseModel, Field

import sentinel.config as cfg
from sentinel.ingest.embed import embed_texts
from sentinel.ingest.store import client, collection_name, load_all
from sentinel.retrieval.bm25 import BM25
from sentinel.router.schema import ChainEntry

RRF_K = 60
RERANK_URL = "https://api.cohere.com/v2/rerank"


class Retrieved(BaseModel):
    chunk_id: str
    source: str
    page: int
    section: str
    text: str
    access_label: str
    rerank_score: float
    hit: bool = False  # True -> passed threshold


class RetrievalResult(BaseModel):
    query: str = ""
    chunks: list[Retrieved] = Field(default_factory=list)
    not_found: bool = False
    reason: str | None = None


def _candidates(
    query: str, name: str, embed_entry: ChainEntry, user_access: str, k0: int
) -> list[str]:
    allowed = ["public", "internal"] if user_access == "internal" else ["public"]
    coll = client().get_collection(collection_name("", "") if False else name)
    qvec = embed_texts(embed_entry, [query])[0]
    res = coll.query(
        query_embeddings=[qvec],
        where={"access_label": {"$in": allowed}},
        n_results=min(k0, max(1, coll.count())) or 1,
        include=["metadatas"],
    )
    vec_ids = list(res["ids"][0])
    dump = load_all(name)
    bm = BM25({i: d["text"] for i, d in dump.items() if d["meta"]["access_label"] in allowed})
    bm_ids = bm.top(query, k0)
    seen: set[str] = set()
    ordered: list[str] = []
    for i in vec_ids + bm_ids:  # RRF's score is applied downstream; this is just the pool
        if i and i not in seen:
            seen.add(i)
            ordered.append(i)
    return ordered


def _rrf_weights(vec_ids: list[str], bm_ids: list[str]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for rank, cid in enumerate(vec_ids, start=1):
        weights[cid] = weights.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    for rank, cid in enumerate(bm_ids, start=1):
        weights[cid] = weights.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    return weights


def _rerank(
    query: str, texts: list[str], entries: list[ChainEntry], limiter=None
) -> tuple[list[float] | None, str]:
    """Cohere rerank via chain fallback, limited and cached. Returns (scores|None, note)."""
    import httpx

    key = cfg.secret("COHERE_API_KEY")
    if not key or not texts:
        return None, "no_key_or_empty"
    from sentinel.router.cache import OnDiskCache

    ns = "rerank:cohere"
    cache = OnDiskCache(cfg.CACHE_DIR / "rerank", ttl_s=24 * 3600)
    notes = []
    for entry in entries:
        payload = {"entry": entry.key, "query": query, "texts": texts}
        if (cached := cache.get(ns, payload)) is not None:
            return cached.get("scores"), f"cached:{entry.model}"
        if limiter is not None:
            limiter.acquire("cohere")
        try:
            resp = httpx.post(
                RERANK_URL,
                headers={"Authorization": f"Bearer {key}"},
                json={"model": entry.model, "query": query, "documents": texts},
                timeout=45.0,
            )
            if resp.status_code != 200:
                notes.append(f"{entry.model}:http_{resp.status_code}")
                continue
            results = resp.json().get("results") or []
            scores = [0.0] * len(texts)
            for r in results:
                scores[r["index"]] = float(r.get("relevance_score", 0.0))
            out = [round(s, 6) for s in scores]
            cache.set(ns, payload, {"scores": out})
            return out, f"ok:{entry.model}"
        except Exception as exc:  # noqa: BLE001 - rerank failure degrades to RRF order
            notes.append(f"{entry.model}:{type(exc).__name__}")
    return None, ";".join(notes) or "no_entry"


def hybrid_search(
    query: str,
    strategy: str,
    embed_entry: ChainEntry,
    rerank_entries: list[ChainEntry],
    models_config,
    *,
    user_access: str = "internal",
    k: int = 10,
    k0: int = 25,
    threshold: float = 0.35,
    rerank: bool = True,
    limiter=None,
) -> RetrievalResult:
    name = collection_name(strategy, embed_entry.model)
    if not client().list_collections():
        return RetrievalResult(query=query, not_found=True, reason="no index")
    dump = load_all(name)
    allowed = ["public", "internal"] if user_access == "internal" else ["public"]

    coll = client().get_collection(name)
    qvec = embed_texts(embed_entry, [query])[0]
    res = coll.query(
        query_embeddings=[qvec],
        where={"access_label": {"$in": allowed}},
        n_results=min(k0, max(1, coll.count())),
        include=["metadatas"],
    )
    vec_ids = list(res["ids"][0])
    bm = BM25({i: d["text"] for i, d in dump.items() if d["meta"]["access_label"] in allowed})
    bm_scores = bm.score(query)
    bm_ids = list(bm_scores)[:k0]

    weights = _rrf_weights(vec_ids, bm_ids)
    pool = sorted(weights, key=lambda i: -weights[i])[:k0]
    if not pool:
        return RetrievalResult(
            query=query, not_found=True, reason=f"no accessible chunks for access={user_access}"
        )

    texts = [dump[i]["text"] for i in pool]
    scores: list[float] | None = None
    note = ""
    if rerank and rerank_entries:
        scores, note = _rerank(query, texts, rerank_entries, limiter=limiter)
    if scores is None:  # RRF order fallback
        note = f"rrf_fallback({note})" if note else "rrf_fallback(no_rerank_entries)"
        scores = [weights[i] * 100.0 for i in pool]

    ranked = sorted(zip(pool, texts, scores, strict=False), key=lambda t: -t[2])[:k]
    out = [
        Retrieved(
            chunk_id=cid,
            source=dump[cid]["meta"]["source"],
            page=dump[cid]["meta"]["page"],
            section=dump[cid]["meta"]["section"],
            text=text,
            access_label=dump[cid]["meta"]["access_label"],
            rerank_score=round(float(score), 4),
            hit=float(score) >= threshold,
        )
        for cid, text, score in ranked
    ]
    not_found = not out or not out[0].hit
    reason_field = None if (out and out[0].hit) else ("no_chunks" if not out else "below_threshold")
    if note.startswith("rrf_fallback"):
        reason_field = reason_field or note
    return RetrievalResult(
        query=query,
        chunks=out,
        not_found=not_found,
        reason=reason_field,
    )
