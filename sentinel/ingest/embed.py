"""Embedders with per-batch on-disk caching. Providers from models.yaml only."""

from __future__ import annotations

import hashlib

import sentinel.config as cfg
from sentinel.router.cache import OnDiskCache
from sentinel.router.factory import CF_AI_BASE, MissingKey
from sentinel.router.schema import ChainEntry

_cache = OnDiskCache(cfg.CACHE_DIR / "embeddings", ttl_s=30 * 24 * 3600)


def _batch_key(entry: ChainEntry, texts: list[str]) -> str:
    blob = "|".join(texts)
    return hashlib.sha256(f"{entry.provider}|{entry.model}|{blob}".encode()).hexdigest()


def embed_texts(entry: ChainEntry, texts: list[str]) -> list[list[float]]:
    """Embed a batch with cache. list-of-floats per input text, order preserved."""
    if not texts:
        return []
    ns = f"embed:{entry.provider}:{entry.model}"
    key = _batch_key(entry, texts)
    cached = _cache.get(ns, {"k": key})
    if cached is not None:
        return cached
    vecs = _embed_uncached(entry, texts)
    _cache.set(ns, {"k": key}, vecs)
    return vecs


def _embed_uncached(entry: ChainEntry, texts: list[str]) -> list[list[float]]:
    if entry.provider == "cohere":
        from langchain_cohere import CohereEmbeddings

        key = cfg.secret("COHERE_API_KEY")
        if not key:
            raise MissingKey("cohere")
        model = CohereEmbeddings(model=entry.model, cohere_api_key=key)
        return [list(v) for v in model.embed_documents(texts)]
    if entry.provider == "cloudflare":
        import httpx

        account, token = cfg.secret("CLOUDFLARE_ACCOUNT_ID"), cfg.secret("CLOUDFLARE_API_TOKEN")
        if not account or not token:
            raise MissingKey("cloudflare")
        resp = httpx.post(
            f"{CF_AI_BASE}/{account}/ai/run/{entry.model}",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": texts},
            timeout=45.0,
        )
        resp.raise_for_status()
        data = resp.json()
        vectors = (data.get("result") or {}).get("data") or data.get("data")
        if not vectors or len(vectors) != len(texts):
            raise ValueError(f"cloudflare embed returned {len(vectors or [])} vectors")
        return [list(v) for v in vectors]
    raise ValueError(f"embed unsupported for provider {entry.provider}")
