"""Offline ingestion: load domain docs -> chunk -> embed -> index in Qdrant.

Run as a batch step (scripts/ingest_docs.py), never during a call
(ARCHITECTURE.md §4: "never embed during a call").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from src.rag.chunking import chunk_text
from src.rag.embeddings import HybridEmbedder
from src.rag.types import Chunk, EmbeddedChunk
from src.rag.vectorstore import VectorStore

log = logging.getLogger("echoassist.rag.ingest")

_SUPPORTED_SUFFIXES = {".md", ".txt"}


@dataclass(frozen=True, slots=True)
class IngestReport:
    documents: int
    chunks: int
    collection_count: int


def load_documents(docs_dir: Path) -> list[tuple[str, str]]:
    """Return (source_name, text) for every supported document under ``docs_dir``."""
    if not docs_dir.exists():
        raise FileNotFoundError(f"Domain docs directory not found: {docs_dir}")
    docs: list[tuple[str, str]] = []
    for path in sorted(docs_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in _SUPPORTED_SUFFIXES:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                docs.append((path.name, text))
    return docs


def build_chunks(
    docs: list[tuple[str, str]], *, chunk_size: int, chunk_overlap: int
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for source, text in docs:
        pieces = chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        for ordinal, piece in enumerate(pieces):
            chunks.append(
                Chunk(id=f"{source}#{ordinal}", source=source, text=piece, ordinal=ordinal)
            )
    return chunks


def ingest(
    docs_dir: Path,
    embedder: HybridEmbedder,
    store: VectorStore,
    *,
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
    recreate: bool = True,
) -> IngestReport:
    """Index every document in ``docs_dir`` into the vector store."""
    docs = load_documents(docs_dir)
    chunks = build_chunks(docs, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    log.info("Ingesting %d documents -> %d chunks", len(docs), len(chunks))

    store.ensure_collection(embedder.dense_dim, recreate=recreate)
    vectors = embedder.embed_documents([c.text for c in chunks])
    embedded = [
        EmbeddedChunk(c, dense, sparse)
        for c, (dense, sparse) in zip(chunks, vectors, strict=True)
    ]
    store.upsert(embedded)

    return IngestReport(documents=len(docs), chunks=len(chunks), collection_count=store.count())
