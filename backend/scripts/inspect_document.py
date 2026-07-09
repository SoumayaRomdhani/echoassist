"""Inspect how a document is extracted and chunked — no Qdrant, no embedding.

    python scripts/inspect_document.py path/to/file.pdf
    python scripts/inspect_document.py path/to/file.docx --chunk-size 1200 --chunk-overlap 150

Prints the provenance-tagged sections a loader produces (page / heading_path) and
the chunks they become, so you can eyeball extraction quality before ingesting.
Supported types: .md .markdown .txt .pdf .docx .html .htm
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.rag.chunking import chunk_text
from src.rag.loaders import extract


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect document extraction + chunking.")
    parser.add_argument("path", type=Path, help="Document to inspect.")
    parser.add_argument("--chunk-size", type=int, default=1200)
    parser.add_argument("--chunk-overlap", type=int, default=150)
    parser.add_argument("--full", action="store_true", help="Print full text, not a preview.")
    args = parser.parse_args()

    sections = [s for s in extract(args.path) if s.text.strip()]
    print(f"\n{args.path.name}: {len(sections)} section(s)\n" + "-" * 60)

    total_chunks = 0
    for i, section in enumerate(sections):
        prov = section.metadata() or "(no page/heading)"
        preview = section.text if args.full else section.text[:120].replace("\n", " ")
        print(f"\n[section {i}] {prov}\n  {preview}{'' if args.full else '...'}")
        pieces = chunk_text(
            section.text, chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap
        )
        total_chunks += len(pieces)
        for j, piece in enumerate(pieces):
            body = piece if args.full else piece[:90].replace("\n", " ")
            print(f"    chunk {j}: {len(piece):4d} chars  {body}{'' if args.full else '...'}")

    print("\n" + "-" * 60)
    print(f"{len(sections)} section(s) -> {total_chunks} chunk(s)\n")


if __name__ == "__main__":
    main()
