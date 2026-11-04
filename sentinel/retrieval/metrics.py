"""Recall@k and MRR with ground truth of {source, page?, section?}.

Convention: a question with an EMPTY ground-truth list is unanswerable and only
counts toward refusal metrics, never retrieval metrics.
"""

from __future__ import annotations

from pydantic import BaseModel

from sentinel.retrieval.retrieve import Retrieved


class GroundTruth(BaseModel):
    source: str
    page: int | None = None  # PDFs: 1-based page; Markdown: None
    section: str | None = None  # Markdown section title prefix; PDFs optional


def is_hit(chunk: Retrieved, gt: GroundTruth) -> bool:
    if chunk.source != gt.source:
        return False
    if gt.page is not None:
        return chunk.page == gt.page
    if gt.section:
        return bool(chunk.section) and chunk.section.startswith(gt.section)
    return False


def rank_of_first_hit(res, gts: list[GroundTruth], k: int | None = None) -> int | None:
    """1-based rank of the first hit chunk in res.chunks, or None. k clamps the rank."""
    for idx, chunk in enumerate(res.chunks, start=1):
        if k is not None and idx > k:
            return None
        if any(is_hit(chunk, gt) for gt in gts):
            return idx
    return None


def recall_at_k(results: list[tuple], k: int) -> float:
    """results: (RetrievalResult, list[GroundTruth]); empty-GT rows (unanswerable) excluded."""
    rows = [(res, gts) for res, gts in results if gts]
    if not rows:
        return 0.0
    hits = sum(rank_of_first_hit(res, gts, k=k) is not None for res, gts in rows)
    return hits / len(rows)


def mrr(results: list[tuple]) -> float:
    reciprocal = 0.0
    rows = [(res, rank_of_first_hit(res, gts)) for res, gts in results if gts]
    for _, rank in rows:
        reciprocal += 0.0 if rank is None else 1.0 / rank
    return reciprocal / len(rows) if rows else 0.0


def refusal_scores(results: list[tuple], k: int = 10) -> tuple[float, float]:
    """(refusal_precision, refusal_recall) over rows carrying (res, expected_not_found)."""
    rows = [(res, expected) for res, expected in results]
    if not rows:
        return 0.0, 0.0
    true_pos = sum(1 for res, exp in rows if exp and res.not_found)
    false_pos = sum(1 for res, exp in rows if not exp and res.not_found)
    total_expected_refused = sum(1 for _, exp in rows if exp)
    precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) else 0.0
    recall = true_pos / total_expected_refused if total_expected_refused else 0.0
    return precision, recall
