"""On-disk response cache: cache/<xdomain>/<sha256>.json, optional TTL seconds."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sentinel.router.schema import cache_key


class OnDiskCache:
    def __init__(self, root: Path, ttl_s: float = 24 * 3600):
        self.root = root
        self.ttl_s = ttl_s
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, ns: str, key: str) -> Path:
        sub = self.root / ns
        sub.mkdir(parents=True, exist_ok=True)
        return sub / f"{key}.json"

    def get(self, ns: str, payload: Any) -> dict[str, Any] | None:
        path = self._path(ns, cache_key(ns, payload))
        if not path.exists():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() - doc.get("ts", 0) > self.ttl_s:
            return None
        return doc.get("value")

    def set(self, ns: str, payload: Any, value: Any) -> None:
        path = self._path(ns, cache_key(ns, payload))
        path.write_text(
            json.dumps({"ts": time.time(), "value": value}, default=str), encoding="utf-8"
        )
