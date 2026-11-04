"""Phase 2 comparison: chunking strategies x embedding providers on the seed question set.

Reports recall@k (k=1,3,5), MRR@10 and refusal behavior per arm.
Run: uv run python scripts/compare_rag.py [--docs docs_synthetic]
Note: retrieval metrics use the ranked list (no threshold); `refuse` rows check NOT_FOUND.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sentinel.config as cfg  # noqa: E402
from sentinel.retrieval.metrics import (  # noqa: E402
    GroundTruth,  # noqa: E402
    mrr,
    recall_at_k,
    refusal_scores,
)
from sentinel.retrieval.retrieve import RetrievalResult, hybrid_search  # noqa: E402
from sentinel.router.schema import ChainEntry, load_models_config  # noqa: E402

TOP_K = 10


def load_questions(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def run_arm(arm: dict, questions: list[dict], models) -> dict:
    embed_entry = ChainEntry(provider=arm["provider"], model=arm["model"])
    rerank_entries = list(models.roles.get("rerank", []))
    from sentinel.router.limiter import RateLimiter

    limiter = RateLimiter({p: limit.rpm for p, limit in models.limits.items()})
    obj_out, notes, t_lat = [], [], 0.0
    for q in questions:
        rec = None
        t0 = time.perf_counter()
        try:
            rec = hybrid_search(
                q["question"],
                arm["strategy"],
                embed_entry,
                rerank_entries,
                models,
                k=TOP_K,
                limiter=limiter,
            )
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning("%s failed: %s", q["id"], exc)
            rec = RetrievalResult(not_found=True, reason="error")
        t_lat += time.perf_counter() - t0
        obj_out.append(rec or RetrievalResult(not_found=True, reason="error"))
        if rec and rec.reason and rec.reason != "no index":
            notes.append(rec.reason)
    gts = {q["id"]: [GroundTruth(**g) for g in q["expected"]] for q in questions}
    # zip explicitly: a bare `for res in obj_out` would leave `q` bound to the leftover
    # loop variable (the last question) and pair every result with the wrong GT
    pairs = [(res, gts[q["id"]]) for res, q in zip(obj_out, questions, strict=True)]
    return {
        "arm": f"{arm['strategy']} x {arm['provider']}:{arm['model']}",
        "recall@1": round(recall_at_k(pairs, k=1), 3),
        "recall@3": round(recall_at_k(pairs, k=3), 3),
        "recall@5": round(recall_at_k(pairs, k=5), 3),
        "mrr@10": round(mrr(pairs), 3),
        "refusal": round(
            refusal_scores(
                [
                    (res, not q["expected"])  # empty GT list == unanswerable (refuse)
                    for res, q in zip(obj_out, questions, strict=True)
                ]
            )[0],
            2,
        ),
        "rerank_health": ",".join(sorted({n.split("(")[0] for n in notes})) or "ok",
        "avg_latency_ms": round(1000 * t_lat / max(1, len(questions))),
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", default="docs_synthetic")
    parser.add_argument("--questions", default="evals/seed_questions.jsonl")
    args = parser.parse_args()

    qpath = cfg.BASE_DIR / args.questions
    questions = load_questions(qpath)
    builds = json.loads((cfg.RESULTS_DIR / "index_builds.json").read_text(encoding="utf-8"))
    models = load_models_config()

    rows = []
    from sentinel.ingest.store import collection_name  # late import keeps head light

    for arm in builds:
        # only compare arms built from the requested docs dir
        collection_name(arm["strategy"], arm["model"])
        rows.append(run_arm(arm, questions, models))
    rows.sort(key=lambda r: r["mrr@10"], reverse=True)
    print(
        f"\nRAG comparison over {len(questions)} seed questions "
        f"(access=internal, k={TOP_K}, cohere rerank)"
    )
    cols = [
        "arm",
        "recall@1",
        "recall@3",
        "recall@5",
        "mrr@10",
        "refusal",
        "rerank_health",
        "avg_latency_ms",
    ]
    widths = [48, 9, 9, 9, 7, 7, 26, 15]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths, strict=False)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(r[c]).ljust(w) for c, w in zip(cols, widths, strict=False)))
    out = cfg.RESULTS_DIR / "rag_comparison.json"
    out.write_text(
        json.dumps(
            {
                "rows": rows,
                "questions": qpath.name,
                "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
