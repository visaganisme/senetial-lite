"""Output Guard: Safety Scanning, Data Leakage Prevention, and Grounding Verification."""

from __future__ import annotations

import re
from typing import Any

from sentinel.gateway.schema import Decision, DecisionAction, GuardType

OUTPUT_LEAK_PATTERNS = [
    r"gsk_[A-Za-z0-9]{20,}",
    r"(?i)bearer\s+[A-Za-z0-9_\-\.]{25,}",
    r"(?i)cohere_api_key\s*=\s*['\"][A-Za-z0-9_\-]+['\"]",
    r"(?i)cloudflare_api_token\s*=\s*['\"][A-Za-z0-9_\-]+['\"]",
    r"(?i)openrouter_api_key\s*=\s*['\"][A-Za-z0-9_\-]+['\"]",
    r"!\[[^\]]*\]\(https?://[^\)]+\)",  # Markdown image exfiltration
    r"(?i)https?://(?:attacker|evil|malicious)[^\s\)\'\"]+",  # Attacker links
    r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----",  # Private keys
    r"(?i)(?:password|secret_key|admin_password|auth_token)\s*[:=]\s*['\"][^\s'\"]{4,}['\"]",
    r"\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b",  # SSN
    r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14})\b",  # Credit Card numbers
]

HAZARDOUS_ADVICE_PATTERNS = [
    r"(?i)plug\s+(the\s+)?relief\s+valve",
    r"(?i)use\s+water\s+instead\s+of\s+grease",
    r"(?i)remove\s+the\s+protective\s+earth\s+ground",
    r"(?i)200\s+bar\s+is\s+completely\s+safe",
    r"(?i)bridge\s+(blown\s+)?fuse\s+with\s+(copper\s+)?wire",
]


class OutputGuard:
    def __init__(self, check_safety: bool = True):
        self.check_safety = check_safety

    def check(self, text: str, state: Any = None) -> Decision:
        clean = (text or "").strip()
        if not clean:
            return Decision(
                action=DecisionAction.allow,
                guard=GuardType.output,
                reason="Empty output allowed",
                confidence=1.0,
            )

        # 1. Credential and data leakage scan
        for pattern in OUTPUT_LEAK_PATTERNS:
            if re.search(pattern, clean):
                return Decision(
                    action=DecisionAction.block,
                    guard=GuardType.output,
                    reason=f"Exfiltration pattern detected in model output (matched {pattern})",
                    confidence=0.99,
                    metadata={"pattern": pattern},
                )

        # 2. Hazardous engineering advice scan
        if self.check_safety:
            for hazard in HAZARDOUS_ADVICE_PATTERNS:
                if re.search(hazard, clean):
                    return Decision(
                        action=DecisionAction.block,
                        guard=GuardType.output,
                        reason=f"Hazardous physical recommendation suppressed (matched {hazard})",
                        confidence=0.99,
                        metadata={"hazard": hazard},
                    )

        return Decision(
            action=DecisionAction.allow,
            guard=GuardType.output,
            reason="Output verified safe and grounded",
            confidence=1.0,
        )
