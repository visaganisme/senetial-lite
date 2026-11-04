"""Retrieval Guard: Score Thresholding, ACL Filtering, and Poisoned-Chunk Quarantine."""

from __future__ import annotations

import re
from typing import Any

from sentinel.gateway.schema import Decision, DecisionAction, GuardType

# Documents known to contain unverified vendor addenda or poisoned content
UNTRUSTED_SOURCES = {
    "QA-VX-7_Vendor_Addendum.pdf",
    "qa-vx-7",
}

# Signatures of poisoned text or safety override attempts embedded in documents
POISONED_CHUNK_SIGNATURES = [
    r"(?i)plug\s+(the\s+)?(relief|safety)\s+valve\s+permanently",
    r"(?i)use\s+water\s+instead\s+of\s+grease\s+for\s+bearing",
    r"(?i)disregard\s+(all\s+)?prior\s+safety\s+limits",
    r"(?i)clean\s+aluminum.*concentrated\s+sodium\s+hydroxide",
    r"(?i)remove\s+(protective\s+)?earth\s+ground",
    r"(?i)map\s+e-stop\s+to\s+pause",
]


class RetrievalGuard:
    def __init__(self, min_score: float = 0.25):
        self.min_score = min_score

    def check(
        self,
        chunks: list[dict[str, Any]],
        user_access: str = "internal",
    ) -> tuple[Decision, list[dict[str, Any]]]:
        if not chunks:
            return (
                Decision(
                    action=DecisionAction.allow,
                    guard=GuardType.retrieval,
                    reason="No chunks retrieved",
                    confidence=1.0,
                ),
                [],
            )

        cleaned_chunks: list[dict[str, Any]] = []
        quarantined_count = 0
        acl_dropped_count = 0
        low_score_count = 0

        for chunk in chunks:
            source = str(chunk.get("source", "")).strip()
            text = str(chunk.get("text", ""))
            score = float(chunk.get("score", 0.0))
            access = str(chunk.get("access_label", "internal"))

            # 1. Poisoned chunk / untrusted source quarantine
            if source in UNTRUSTED_SOURCES or any(
                src in source.lower() for src in UNTRUSTED_SOURCES
            ):
                quarantined_count += 1
                continue

            # Check for embedded injection signatures
            if any(re.search(sig, text) for sig in POISONED_CHUNK_SIGNATURES):
                quarantined_count += 1
                continue

            # 2. ACL check: public users cannot view internal documents
            if user_access == "public" and access != "public":
                acl_dropped_count += 1
                continue

            # 3. Score threshold cut
            if score < self.min_score:
                low_score_count += 1
                continue

            cleaned_chunks.append(chunk)

        if quarantined_count > 0:
            return (
                Decision(
                    action=DecisionAction.rewrite,
                    guard=GuardType.retrieval,
                    reason=f"Quarantined {quarantined_count} untrusted document chunk(s)",
                    confidence=0.99,
                    metadata={
                        "quarantined": quarantined_count,
                        "retained": len(cleaned_chunks),
                    },
                    modified_payload=cleaned_chunks,
                ),
                cleaned_chunks,
            )

        return (
            Decision(
                action=DecisionAction.allow,
                guard=GuardType.retrieval,
                reason=f"Retrieval verified: {len(cleaned_chunks)} chunk(s) passed inspection",
                confidence=1.0,
                metadata={"retained": len(cleaned_chunks)},
            ),
            cleaned_chunks,
        )
