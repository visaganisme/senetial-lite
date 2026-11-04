"""Build vector index collections for the requested arms.

Usage:
  uv run python scripts/build_index.py [--docs docs_synthetic]
Arms: (structure, cohere embed-v5.0-pro), (structure, embed-v4.0), (recursive, ...x2),
plus cloudflare bge-large when its token works.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sentinel.config as cfg  # noqa: E402
from sentinel.ingest.chunk import chunk_all  # noqa: E402
from sentinel.ingest.parse import parse_dir  # noqa: E402
from sentinel.ingest.store import build  # noqa: E402
from sentinel.router.factory import MissingKey  # noqa: E402
from sentinel.router.schema import ChainEntry, load_models_config  # noqa: E402

ARMS = [
    ("structure", "cohere", "embed-v5.0-pro"),
    ("structure", "cohere", "embed-v4.0"),
    ("recursive", "cohere", "embed-v5.0-pro"),
    ("recursive", "cohere", "embed-v4.0"),
    ("structure", "cloudflare", "@cf/baai/bge-large-en-v1.5"),
    ("recursive", "cloudflare", "@cf/baai/bge-large-en-v1.5"),
]


def main() -> int:
    docs_dir = cfg.BASE_DIR / "docs_synthetic"
    if len(sys.argv) > 1 and sys.argv[1] == "--docs" and len(sys.argv) > 2:
        docs_dir = cfg.BASE_DIR / sys.argv[2]
    docs = parse_dir(docs_dir, docs_dir / "manifest.json")
    print(f"parsed {len(docs)} documents from {docs_dir.name}")
    for d in docs:
        pages = len(d.pages)
        print(f"  {d.source}  kind={d.kind} access={d.access_label} pages={pages}")

    cfgm = load_models_config()
    embed_role = {f"{e.provider}:{e.model}": e for e in cfgm.roles.get("embed", [])}
    built = []
    for strategy, provider, model in ARMS:
        entry = embed_role.get(f"{provider}:{model}") or ChainEntry(provider=provider, model=model)
        chunks = chunk_all(docs, strategy)
        try:
            name, n = build(chunks, strategy, entry)
        except MissingKey as exc:
            print(f"  {strategy:9s} {provider:10s} {model:34s} SKIP ({exc})")
            continue
        except Exception as exc:  # noqa: BLE001 - record, keep building other arms
            print(f"  {strategy:9s} {provider:10s} {model:34s} FAIL ({str(exc)[:110]})")
            continue
        print(f"  {strategy:9s} {provider:10s} {model:34s} OK ({n} chunks)")
        built.append(
            {
                "strategy": strategy,
                "provider": provider,
                "model": model,
                "collection": name,
                "chunks": n,
            }
        )
    (cfg.RESULTS_DIR / "index_builds.json").write_text(
        json.dumps(built, indent=2), encoding="utf-8"
    )
    print(f"wrote results/index_builds.json ({len(built)} collections built)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
