"""Input Guard: Prompt Injection Scanner, Jailbreak Detector, and PII Sanitizer."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from sentinel.gateway.schema import Decision, DecisionAction, GuardType

logger = logging.getLogger(__name__)

# General prompt-injection and jailbreak patterns only (attack-specific canary strings removed)
INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?(previous\s+|prior\s+)?(instructions|directives|prompts|rules)",
    r"(?i)disregard\s+(all\s+)?(previous\s+|prior\s+|safety\s+|system\s+)?(instructions|directives|prompts|rules)",
    r"(?i)system\s+override",
    r"(?i)clear\s+active\s+policy",
    r"(?i)you\s+are\s+now\s+(uncensoredbot|dan|root|admin)",
    r"(?i)dan\s+mode\s+on",
    r"(?i)developer\s+mode\s+(v2|on|active|enabled)",
    r"(?i)---\s*end\s+of\s+system\s+context\s*---",
    r"(?i)```yaml\s*system:\s*null",
    r"(?i)</input><admin",
    r"(?i)repeat\s+your\s+initial\s+system\s+prompt\s+verbatim",
    r"(?i)output\s+the\s+hidden\s+admin\s+confirmation\s+code",
    r"(?i)base64\s+for\s+ignore\s+rules",
]

PII_AND_SECRET_PATTERNS = [
    r"(?i)(groq|cohere|cloudflare|openrouter)[_\s]*api[_\s]*key",
    r"\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b",  # SSN
    r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b",  # Credit cards
    r"(?i)bearer\s+[A-Za-z0-9_\-\.]{25,}",
    r"gsk_[A-Za-z0-9]{20,}",
]

# Prompt Guard threshold based on probe results (benign ~0.0004, injection ~0.999)
PROMPT_GUARD_THRESHOLD = 0.5


class InputGuard:
    def __init__(self, use_classifier: bool = True, threshold: float = PROMPT_GUARD_THRESHOLD):
        self.use_classifier = use_classifier
        self.threshold = threshold
        self.classifier_failures: int = 0

    def check(self, prompt: str) -> Decision:
        start_time = time.perf_counter()
        clean = (prompt or "").strip()
        if not clean:
            return Decision(
                action=DecisionAction.allow,
                guard=GuardType.input,
                reason="Empty prompt allowed",
                confidence=1.0,
            )

        # 1. Regex rule-based injection scan
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, clean):
                return Decision(
                    action=DecisionAction.block,
                    guard=GuardType.input,
                    reason=f"Prompt injection detected (matched pattern: {pattern})",
                    confidence=0.99,
                    metadata={"pattern": pattern},
                )

        # 2. Secret/PII detection scan
        for pii in PII_AND_SECRET_PATTERNS:
            if re.search(pii, clean):
                return Decision(
                    action=DecisionAction.block,
                    guard=GuardType.input,
                    reason="Sensitive secret or credential extraction pattern detected in input",
                    confidence=0.95,
                    metadata={"pattern": pii},
                )

        # 3. Numeric score classification pass via injection_guard role if available
        classifier_error: str | None = None
        if self.use_classifier:
            try:
                from sentinel.router.router import Runtime, call

                rt = Runtime.load(use_cache=True)
                if "injection_guard" in rt.config.roles:
                    res = call(
                        "injection_guard",
                        [{"role": "user", "content": clean}],
                        runtime=rt,
                    )
                    raw_content = (res.content or "").strip()
                    # Parse numeric probability score returned by Prompt Guard
                    score = None
                    try:
                        score = float(raw_content)
                    except (ValueError, TypeError):
                        match = re.search(r"\b0\.\d+\b", raw_content)
                        if match:
                            score = float(match.group(0))

                    if score is None:
                        self.classifier_failures += 1
                        classifier_error = f"Unparseable classifier output: {raw_content!r}"
                        logger.error(
                            f"Prompt Guard returned unparseable score: {raw_content!r}"
                        )
                    elif score >= self.threshold:
                        model_name = res.meta.model if res.meta else "prompt-guard"
                        return Decision(
                            action=DecisionAction.block,
                            guard=GuardType.input,
                            reason=(
                                f"Prompt Guard classified input as injection "
                                f"(score {score:.4f} >= {self.threshold})"
                            ),
                            confidence=round(score, 4),
                            metadata={"classifier": model_name, "score": score},
                        )
            except Exception as e:
                self.classifier_failures += 1
                classifier_error = str(e)
                logger.error(f"Prompt Guard classifier invocation failed: {e}", exc_info=True)

        elapsed = round((time.perf_counter() - start_time) * 1000, 2)
        meta: dict[str, Any] = {"latency_ms": elapsed}
        if classifier_error:
            meta["classifier_error"] = classifier_error
            meta["classifier_failures"] = self.classifier_failures

        return Decision(
            action=DecisionAction.allow,
            guard=GuardType.input,
            reason="Input verified clean",
            confidence=1.0,
            metadata=meta,
        )
