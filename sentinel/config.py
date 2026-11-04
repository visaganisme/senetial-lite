"""Env + path config. Secrets are read from .env and never logged, printed, or returned
in values (only presence is exposed via secrets_status)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE_DIR / "cache"
RESULTS_DIR = BASE_DIR / "results"
EVALS_DIR = BASE_DIR / "evals"
NOTES_DIR = BASE_DIR / "notes"

KEY_NAMES = (
    "COHERE_API_KEY",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_ACCOUNT_ID",
    "OPENROUTER_API_KEY",
    "GROQ_API_KEY",
)


def load_env(path: Path | None = None) -> None:
    """Minimal stdlib .env loader. Real OS env vars always win (setdefault)."""
    path = path or BASE_DIR / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in KEY_NAMES and value:
            os.environ.setdefault(key, value)


def secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def secrets_status() -> dict[str, bool]:
    """Presence of keys only - safe to print/log."""
    return {name: secret(name) is not None for name in KEY_NAMES}


def ensure_dirs() -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    RESULTS_DIR.mkdir(exist_ok=True)


load_env()
ensure_dirs()
