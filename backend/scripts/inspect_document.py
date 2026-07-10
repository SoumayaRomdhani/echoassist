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

from src.rag.ingest import LoadedDocument, build_chunks
from src.rag.loaders import extract
from src.rag.metadata import DocumentMeta


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect document extraction + chunking.")
    parser.add_argument("path", type=Path, help="Document to inspect.")
    parser.add_argument("--chunk-size", type=int, default=1200)
    parser.add_argument("--chunk-overlap", type=int, default=150)
    parser.add_argument("--full", action="store_true", help="Print full text, not a preview.")
    args = parser.parse_args()

    sections = [s for s in extract(args.path) if s.text.strip()]
    doc = LoadedDocument(meta=DocumentMeta.describe(args.path), sections=sections)
    chunks = build_chunks(
        [doc], chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap
    )

    print(f"\n{args.path.name}\n" + "-" * 60)
    for key, value in doc.meta.as_dict().items():
        print(f"  {key:15} {value}")
    print("-" * 60)

    for chunk in chunks:
        page = chunk.metadata.get("page")
        heading = chunk.metadata.get("heading")
        prov = " · ".join(
            part for part in (f"p{page}" if page else "", heading or "") if part
        ) or "(no page/heading)"
        body = chunk.text if args.full else chunk.text[:90].replace("\n", " ")
        print(f"\n  {chunk.id}  [{prov}]  {chunk.metadata['char_count']} chars")
        print(f"    {body}{'' if args.full else '...'}")

    print("\n" + "-" * 60)
    print(f"{len(sections)} section(s) -> {len(chunks)} chunk(s)\n")


if __name__ == "__main__":
    main()
