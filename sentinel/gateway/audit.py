"""Structured JSONL Audit Logger for the Sentinel Gateway."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sentinel.gateway.schema import AuditRecord, Decision, GuardType

logger = logging.getLogger(__name__)


class AuditLogger:
    def __init__(self, log_path: Path | str | None = None):
        if log_path:
            self.log_path = Path(log_path)
        else:
            from sentinel.config import RESULTS_DIR

            self.log_path = RESULTS_DIR / "audit_log.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._buffer: list[AuditRecord] = []

    def record(
        self,
        guard: GuardType,
        decision: Decision,
        target: str = "",
        latency_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> AuditRecord:
        meta = dict(decision.metadata)
        if metadata:
            meta.update(metadata)

        record = AuditRecord(
            id=f"audit-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}",
            timestamp=datetime.now(UTC).isoformat(),
            guard=guard,
            action=decision.action,
            reason=decision.reason,
            target=target[:200],
            latency_ms=round(latency_ms, 2),
            metadata=meta,
        )

        self._buffer.append(record)
        if len(self._buffer) > 500:
            self._buffer.pop(0)

        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record.model_dump(), default=str) + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

        return record

    def get_recent(self, limit: int = 50) -> list[AuditRecord]:
        if self._buffer:
            return self._buffer[-limit:]
        if not self.log_path.exists():
            return []
        records = []
        try:
            with self.log_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(AuditRecord.model_validate(json.loads(line)))
        except Exception:
            return []
        return records[-limit:]
