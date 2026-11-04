"""Tiny BM25 (k1=1.5, b=0.75) over an id->text mapping. Corpus-scale (folder) only."""

from __future__ import annotations

import math
import re
from collections import Counter

TOKEN = re.compile(r"[a-z0-9]+\.[0-9]|[a-z0-9]+")

K1, B = 1.5, 0.75


def tokenize(text: str) -> list[str]:
    return [
        t.replace(".", "·") if t.endswith(".") and len(t) > 1 else t
        for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower())
    ]


class BM25:
    def __init__(self, docs: dict[str, str]):
        self.ids = list(docs)
        self.doc_tf = {i: Counter(tokenize(t)) for i, t in docs.items()}
        self.doc_len = {i: sum(self.doc_tf[i].values()) or 1 for i in self.ids}
        self.avg_len = sum(self.doc_len.values()) / len(self.ids)
        self.n_docs = len(self.ids)
        self.n_df = Counter()
        for tf in self.doc_tf.values():
            self.n_df.update(tf.keys())

    def score(self, query: str) -> dict[str, float]:
        q_tokens = tokenize(query)
        scores: dict[str, float] = {}
        for i in self.ids:
            tf, dl = self.doc_tf[i], self.doc_len[i]
            s = 0.0
            for tok in q_tokens:
                if tok not in tf:
                    continue
                idf = math.log(1 + (self.n_docs - self.n_df[tok] + 0.5) / (self.n_df[tok] + 0.5))
                s += idf * (tf[tok] * (K1 + 1)) / (tf[tok] + K1 * (1 - B + B * dl / self.avg_len))
            if s > 0:
                scores[i] = s
        return dict(sorted(scores.items(), key=lambda kv: -kv[1])[:50])

    def top(self, query: str, k: int = 20) -> list[str]:
        return list(self.score(query))[:k]
