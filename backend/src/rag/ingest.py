"""Offline ingestion: load domain docs -> chunk -> embed -> index in Qdrant.

Run as a batch step (scripts/ingest_docs.py), never during a call
(ARCHITECTURE.md §4: "never embed during a call").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from src.observability.tracing import span
from src.rag.chunking import chunk_text
from src.rag.embeddings import HybridEmbedder
from src.rag.loaders import SUPPORTED_SUFFIXES, DocumentLoadError, DocumentSection, extract
from src.rag.types import Chunk, EmbeddedChunk
from src.rag.vectorstore import VectorStore

log = logging.getLogger("echoassist.rag.ingest")


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    source: str
    sections: list[DocumentSection]


@dataclass(frozen=True, slots=True)
class IngestReport:
    documents: int
    chunks: int
    collection_count: int


def load_documents(docs_dir: Path) -> list[LoadedDocument]:
    """Extract every supported document under ``docs_dir`` into provenance-tagged sections.

    A file that cannot be parsed (corrupt PDF, missing text layer) is logged and
    skipped rather than aborting the whole domain ingest.
    """
    if not docs_dir.exists():
        raise FileNotFoundError(f"Domain docs directory not found: {docs_dir}")
    docs: list[LoadedDocument] = []
    for path in sorted(docs_dir.rglob("*")):
        if not (path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES):
            continue
        try:
            sections = [s for s in extract(path) if s.text.strip()]
        except DocumentLoadError as exc:
            log.warning("skipping %s: %s", path.name, exc)
            continue
        if sections:
            docs.append(LoadedDocument(source=path.name, sections=sections))
    return docs


def build_chunks(
    docs: list[LoadedDocument], *, chunk_size: int, chunk_overlap: int
) -> list[Chunk]:
    """Chunk each document's sections, carrying section provenance onto every chunk.

    A chunk never crosses a section boundary, so each one inherits exactly one
    ``page`` / ``heading_path`` (kept in ``Chunk.metadata`` for citations).
    """
    chunks: list[Chunk] = []
    for doc in docs:
        ordinal = 0
        for section in doc.sections:
            metadata = section.metadata()
            pieces = chunk_text(section.text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            for piece in pieces:
                chunks.append(
                    Chunk(
                        id=f"{doc.source}#{ordinal}",
                        source=doc.source,
                        text=piece,
                        ordinal=ordinal,
                        metadata=dict(metadata),
                    )
                )
                ordinal += 1
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
    with span("rag.ingest"):
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

        return IngestReport(
            documents=len(docs), chunks=len(chunks), collection_count=store.count()
        )
