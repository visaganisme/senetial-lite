"""Offline RAG tests: parsers, chunkers, BM25, metrics, and hybrid_search end-to-end
against a real local Chroma collection with stubbed embeddings. No network."""

from __future__ import annotations

import numpy as np
import pytest

import sentinel.config as cfg
import sentinel.ingest.store as store_mod
import sentinel.retrieval.retrieve as retrieve_mod
from sentinel.ingest.chunk import chunk_recursive, chunk_structure
from sentinel.ingest.parse import MD_HEADING, Page, ParsedDoc, split_sections
from sentinel.retrieval.bm25 import BM25
from sentinel.retrieval.metrics import (
    GroundTruth,
    is_hit,
    mrr,
    rank_of_first_hit,
    recall_at_k,
    refusal_scores,
)
from sentinel.retrieval.retrieve import RetrievalResult, Retrieved
from sentinel.router.schema import ChainEntry


def _doc(pages: list[tuple[int, str]], source: str = "t.pdf", access: str = "public") -> ParsedDoc:
    return ParsedDoc(
        source=source,
        kind="pdf",
        access_label=access,
        pages=[Page(page=p, text=t) for p, t in pages],
    )


def test_split_sections_detects_pdf_headings():
    text = (
        "Some intro line.\n1 Operating limits\nMax pressure 12.5 bar at 40 degC.\n"
        "24 VDC, tolerance +/-10 percent is not a heading.\n2 Safety valve"
    )
    secs = split_sections(text)
    titles = [t for t, _ in secs]
    assert "1 Operating limits" in titles and "2 Safety valve" in titles
    assert "24 VDC, tolerance +/-10 percent is not a heading." not in titles


def test_md_headings_parse():
    assert MD_HEADING.match("## 2 Electrical specifications")
    body = "intro\n## C1 Copper\n27 A per core\n## C2 Derating\n0.94 factor"
    secs = split_sections(body)
    titles = [t for t, _ in secs if t]
    assert titles == ["C1 Copper", "C2 Derating"]


def test_structure_chunking_keeps_section_and_page():
    doc = _doc([(1, "## 1 Limits\nMax is 12.5 bar.\nX"), (2, "## 2 Valve\nSet at 13.8 bar.")])
    chunks = chunk_structure(doc)
    secs = {c.section: c for c in chunks if c.section}
    assert "1 Limits" in secs and "2 Valve" in secs
    assert secs["2 Valve"].page == 2


def test_recursive_chunking_caps_length():
    long_text = "para one. " * 200
    doc = _doc([(1, long_text)])
    chunks = chunk_recursive(doc, target=300, overlap=50)
    assert len(chunks) >= 3
    assert all(len(c.text) <= 400 for c in chunks)


def test_bm25_ranks_keyword_doc_first():
    docs = {
        "a": ids_of("vibration limits alarm 4.5 mm/s RMS bearing housing"),
        "b": ids_of("torque table M8 25 Nm M10 40 Nm fasteners"),
        "c": ids_of("efficiency motor 92.5 percent load"),
        "d": " ".join(["vibration"] * 5) + " vibration limit 7.1 mm/s",
    }
    bm = BM25(docs)
    top = bm.top("vibration alarm limit", k=2)
    assert top[0] in {"a", "d"}


def ids_of(text: str) -> str:  # helper used once; kept tiny for the table above
    return text


def test_metrics_recall_mrr_refusal():
    def chunk_res(rows: list[tuple[str, int, str]]):
        return RetrievalResult(
            chunks=[
                Retrieved(
                    chunk_id=f"c{i}",
                    source=s,
                    page=p,
                    section=sec,
                    text="",
                    access_label="internal",
                    rerank_score=0.9,
                )
                for i, (s, p, sec) in enumerate(rows)
            ]
        )

    res_a = chunk_res([("ves.pdf", 2, "2 Safety valve"), ("ves.pdf", 1, "1 Operating limits")])
    gt_a = [GroundTruth(source="ves.pdf", page=1)]
    assert rank_of_first_hit(res_a, gt_a) == 2
    assert is_hit(res_a.chunks[1], gt_a[0]) and not is_hit(res_a.chunks[0], gt_a[0])

    # unanswerable GT ([]) excluded from recall/MRR
    recall = recall_at_k([(res_a, gt_a), (chunk_res([]), [])], k=3)
    assert recall == 1.0
    total_mrr = mrr([(res_a, gt_a)])
    assert total_mrr == 0.5

    # refusal: not_found flags vs expectation (0 FPs -> precision 1.0, recall 0.5)
    res_nf = RetrievalResult(chunks=[], not_found=True)
    p, r = refusal_scores([(res_nf, True), (res_a, True), (res_a, False)], k=5)
    assert (p, r) == (1.0, 0.5)


@pytest.fixture()
def mini_chroma(monkeypatch, tmp_path):
    """A real local Chroma collection with stubbed embeddings; no network anywhere.
    cfg.BASE_DIR is redirected to tmp so Chroma persists into a disposable dir."""
    monkeypatch.setattr(cfg, "BASE_DIR", tmp_path)

    docs = {
        "c1": (
            "ves-manual.pdf",
            1,
            "1 Operating limits",
            "private",
            "Maximum allowable working pressure 12.5 bar at 40 degC derates at 150 degC.",
        ),
        "c2": (
            "pump-guide.pdf",
            2,
            "2 Fastener torque table",
            "public",
            "Torque M8 fasteners 25 Nm and M10 fasteners 40 Nm wrench calibrated.",
        ),
        "c3": (
            "motor.pdf",
            3,
            "3 Bearings",
            "public",
            "Relubricate DE bearing after 12000 hours with 4 g grease LGHP.",
        ),
        "c4": (
            "secret.pdf",
            1,
            "1 Confidential",
            "internal",
            "Torque M8 fasteners 55 Nm confidential addendum QA values.",
        ),
    }
    rng = np.random.default_rng(42)

    def fake_embed(entry, texts):  # deterministic distinct vectors, stub only
        return [rng.normal(size=64).tolist() for _ in texts]

    monkeypatch.setattr(retrieve_mod, "embed_texts", fake_embed)

    client = store_mod.client()
    name = store_mod.collection_name("structure", "dummy-embed")
    coll = client.get_or_create_collection(name)
    if coll.count():
        coll.delete(coll.get()["ids"])
    vecs = fake_embed(None, [d[4] for d in docs.values()])
    coll.add(
        ids=list(docs),
        embeddings=vecs,
        documents=[d[4] for d in docs.values()],
        metadatas=[
            {"source": d[0], "page": d[1], "section": d[2], "access_label": d[3], "chunk_id": did}
            for did, d in docs.items()
        ],
    )
    yield name
    monkeypatch.undo()


def test_hybrid_search_finds_torque_offline(mini_chroma):
    res = retrieve_mod.hybrid_search(
        "what torque applies to M8 fasteners",
        "structure",
        ChainEntry(provider="x", model="dummy-embed"),
        rerank_entries=[],
        models_config=None,
        k=5,
        threshold=0.0,
        rerank=False,
    )
    assert res.chunks
    top = res.chunks[0]
    assert top.source == "pump-guide.pdf" and top.page == 2
    assert top.hit


def test_hybrid_search_threshold_refuses(mini_chroma):
    res = retrieve_mod.hybrid_search(
        "what torque applies to M8 fasteners",
        "structure",
        ChainEntry(provider="x", model="dummy-embed"),
        rerank_entries=[],
        models_config=None,
        threshold=10**9,
        rerank=False,
    )
    assert res.not_found and res.reason == "below_threshold"


def test_hybrid_search_access_filter(mini_chroma):
    res = retrieve_mod.hybrid_search(
        "torque M8 fasteners",
        "structure",
        ChainEntry(provider="x", model="dummy-embed"),
        rerank_entries=[],
        models_config=None,
        user_access="public",
        k=10,
        threshold=0.0,
        rerank=False,
    )
    assert all(c.access_label == "public" for c in res.chunks)
    assert not any(c.source == "secret.pdf" for c in res.chunks)

    res_internal = retrieve_mod.hybrid_search(
        "torque M8 fasteners 55 Nm confidential addendum",
        "structure",
        ChainEntry(provider="x", model="dummy-embed"),
        rerank_entries=[],
        models_config=None,
        user_access="internal",
        k=10,
        threshold=0.0,
        rerank=False,
    )
    assert not res_internal.not_found  # internal user may see the poisoned doc (gateway's job)
