"""Index a domain's knowledge base into Qdrant (offline RAG ingest).

    python scripts/ingest_docs.py            # ingest the active DOMAIN
    python scripts/ingest_docs.py --domain screening

Requires Qdrant running: `docker compose up -d qdrant`.
"""

from __future__ import annotations

import argparse

from config.settings import build_embedder, build_vector_store, get_settings
from src.console import bold, init_console
from src.log import setup_logging
from src.rag.ingest import ingest


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest domain docs into the vector store.")
    parser.add_argument("--domain", default=None, help="Domain to ingest (default: DOMAIN).")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Add to the existing collection instead of recreating it.",
    )
    args = parser.parse_args()

    settings = get_settings()
    init_console()
    setup_logging(settings.log_level)
    domain = args.domain or settings.domain

    docs_dir = settings.data_dir / "docs" / domain
    embedder = build_embedder(settings)
    store = build_vector_store(settings, domain=domain)

    report = ingest(
        docs_dir,
        embedder,
        store,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        recreate=not args.keep,
    )
    print(
        bold(
            f"\ningested domain={domain}: {report.documents} docs -> "
            f"{report.chunks} chunks  (collection now holds {report.collection_count})\n"
        )
    )
    if report.skipped:
        print(bold(f"skipped {len(report.skipped)} file(s):"))
        for skip in report.skipped:
            print(f"  - {skip.source}: {skip.reason}")
        print()


if __name__ == "__main__":
    main()
