"""Offline ingestion: load domain docs -> chunk -> embed -> index in Qdrant.

Run as a batch step (scripts/ingest_docs.py), never during a call
(ARCHITECTURE.md §4: "never embed during a call").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.observability.tracing import span
from src.rag.chunking import chunk_text
from src.rag.embeddings import HybridEmbedder
from src.rag.loaders import SUPPORTED_SUFFIXES, DocumentSection, extract
from src.rag.metadata import DocumentMeta, build_chunk_metadata, heading_breadcrumb, utc_iso
from src.rag.types import Chunk, EmbeddedChunk
from src.rag.vectorstore import VectorStore

log = logging.getLogger("echoassist.rag.ingest")


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    meta: DocumentMeta
    sections: list[DocumentSection]

    @property
    def source(self) -> str:
        return self.meta.source


@dataclass(frozen=True, slots=True)
class SkippedDocument:
    """A supported file that could not be indexed, with a human-readable reason."""

    source: str
    reason: str


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Outcome of scanning a docs folder.

    ``documents`` are the files that yielded indexable text. ``attempted_sources`` is
    *every* supported file seen — including ones that extracted to zero sections or
    failed to parse — so a re-ingest can clean their stale chunks even when the new
    version indexes nothing. ``skipped`` records those that could not be indexed (corrupt
    file, no extractable text) so the caller can report them instead of failing silently.
    """

    documents: list[LoadedDocument]
    attempted_sources: list[str]
    skipped: list[SkippedDocument] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class IngestReport:
    documents: int
    chunks: int
    collection_count: int
    skipped: list[SkippedDocument] = field(default_factory=list)


def load_documents(docs_dir: Path) -> LoadResult:
    """Extract every supported document under ``docs_dir`` into provenance-tagged sections.

    Each supported file is handled independently: a corrupt or unreadable file (or one
    with no extractable text — an empty or scanned document) is skipped and recorded in
    ``skipped`` rather than aborting the whole domain ingest. Every supported file is also
    recorded in ``attempted_sources`` so its old chunks are cleaned on re-ingest.
    """
    if not docs_dir.exists():
        raise FileNotFoundError(f"Domain docs directory not found: {docs_dir}")
    # One timestamp for the whole run, so every document shares a consistent indexed_at.
    indexed_at = utc_iso()
    docs: list[LoadedDocument] = []
    attempted: list[str] = []
    skipped: list[SkippedDocument] = []
    for path in sorted(docs_dir.rglob("*")):
        if not (path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES):
            continue
        # Identity is the path relative to the docs dir (POSIX), so a/faq.md and
        # b/faq.md don't collide into one source / chunk-id namespace.
        source = path.relative_to(docs_dir).as_posix()
        attempted.append(source)
        try:
            sections = [s for s in extract(path) if s.text.strip()]
            if not sections:
                reason = "no extractable text (empty or scanned document?)"
                log.warning("skipping %s: %s", source, reason)
                skipped.append(SkippedDocument(source, reason))
                continue
            meta = DocumentMeta.describe(path, source=source, indexed_at=indexed_at)
            docs.append(LoadedDocument(meta=meta, sections=sections))
        except Exception as exc:  # noqa: BLE001 - one bad file must not abort the whole ingest
            log.warning("skipping %s: %s", source, exc)
            skipped.append(SkippedDocument(source, str(exc)))
    return LoadResult(documents=docs, attempted_sources=attempted, skipped=skipped)


def build_chunks(
    docs: list[LoadedDocument], *, chunk_size: int, chunk_overlap: int
) -> list[Chunk]:
    """Chunk each document's sections, carrying rich provenance onto every chunk.

    A chunk never crosses a section boundary, so each one inherits exactly one
    ``page`` / ``heading_path`` plus its document's facts (doc_id, content_hash,
    timestamps, ...) — all kept in ``Chunk.metadata`` for citations and lifecycle.
    Each chunk's text is prefixed with its heading breadcrumb (``Setup > Login``) so it
    embeds self-contained — the section context travels with every piece, which lifts
    retrieval on short chunks that would otherwise lose the topic they belong to.
    """
    chunks: list[Chunk] = []
    for doc in docs:
        ordinal = 0
        for section in doc.sections:
            section_meta = section.metadata()
            breadcrumb = heading_breadcrumb(section.heading_path)
            # The breadcrumb is prepended *inside* chunk_text, which reserves its length
            # from the budget so the final chunk text still respects chunk_size.
            pieces = chunk_text(
                section.text,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                prefix=breadcrumb,
            )
            for piece in pieces:
                metadata = build_chunk_metadata(doc.meta, section_meta, char_count=len(piece))
                chunks.append(
                    Chunk(
                        id=f"{doc.source}#{ordinal}",
                        source=doc.source,
                        text=piece,
                        ordinal=ordinal,
                        metadata=metadata,
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
        load = load_documents(docs_dir)
        chunks = build_chunks(load.documents, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        log.info("Ingesting %d documents -> %d chunks", len(load.documents), len(chunks))
        if load.skipped:
            log.warning(
                "skipped %d file(s): %s",
                len(load.skipped),
                ", ".join(s.source for s in load.skipped),
            )

        store.ensure_collection(embedder.dense_dim, recreate=recreate)
        # Embed BEFORE touching the existing index: if embedding fails, we raise here and
        # the current vectors are left intact rather than half-deleted.
        vectors = embedder.embed_documents([c.text for c in chunks])
        embedded = [
            EmbeddedChunk(c, dense, sparse)
            for c, (dense, sparse) in zip(chunks, vectors, strict=True)
        ]

        # Re-ingest (recreate=False): drop the existing chunks of every re-ingested source
        # before writing the new ones — keyed on *attempted* sources, so a revision that now
        # extracts nothing (scanned/empty/corrupt) still has its stale content removed.
        # recreate=True already starts from an empty collection, so no cleanup is needed.
        if not recreate:
            removed = sum(store.delete_document(source) for source in set(load.attempted_sources))
            if removed:
                log.info("re-ingest: removed %d stale chunk(s) before upsert", removed)

        store.upsert(embedded)

        return IngestReport(
            documents=len(load.documents),
            chunks=len(chunks),
            collection_count=store.count(),
            skipped=load.skipped,
        )
