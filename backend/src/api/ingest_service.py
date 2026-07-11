"""Document upload → RAG ingest (Sprint 6).

``POST /domains/{domain}/documents`` saves an uploaded file into the domain's
docs folder and re-indexes the collection. Indexing is CPU-bound (FastEmbed) and
not concurrency-safe, so it runs in a worker thread under a shared lock — the
same constraint as the voice models. Heavy work sits behind ``indexer`` so the
route's validation and file handling are testable without loading models.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from src.rag.ingest import IngestReport, ingest
from src.rag.loaders import SUPPORTED_SUFFIXES

log = logging.getLogger("echoassist.api.ingest")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB
_READ_CHUNK = 1024 * 1024                      # 1 MiB read granularity

# (docs_dir, domain) -> report. Defaults to the real FastEmbed/Qdrant pipeline.
# Used for both incremental re-index (recreate=False) and full reindex (recreate=True).
Indexer = Callable[[Path, str], IngestReport]
# (domain, source) -> number of chunks removed from the vector store.
Deleter = Callable[[str, str], int]


@dataclass(frozen=True, slots=True)
class DeleteReport:
    filename: str
    file_removed: bool      # the document file was present on disk and deleted
    chunks_removed: int     # vectors purged from the collection


class UnsupportedDocument(ValueError):
    """Raised when an uploaded file is not a supported knowledge-base document."""


def _human_size(n: int) -> str:
    for unit, scale in (("MB", 1024 * 1024), ("KB", 1024)):
        if n >= scale:
            return f"{n // scale} {unit}"
    return f"{n} bytes"


class DocumentTooLarge(ValueError):
    """Raised when an upload exceeds the configured size limit."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"file exceeds the {_human_size(limit)} upload limit")
        self.limit = limit


class IngestService:
    def __init__(
        self,
        *,
        data_dir: Path,
        indexer: Indexer,
        deleter: Deleter | None = None,
        reindexer: Indexer | None = None,
        lock: asyncio.Lock | None = None,
        max_upload_bytes: int = _DEFAULT_MAX_UPLOAD_BYTES,
    ) -> None:
        self._data_dir = data_dir
        self._indexer = indexer
        self._deleter = deleter
        self._reindexer = reindexer
        self._lock = lock or asyncio.Lock()
        self._max_upload_bytes = max_upload_bytes

    async def read_capped(self, file) -> bytes:
        """Read an upload without ever buffering more than the limit in memory.

        ``file`` is anything with an async ``read(size)`` (e.g. Starlette's
        ``UploadFile``); an optional ``.size`` hint is checked first for a fast reject.
        Reads in ``_READ_CHUNK`` slices and raises :class:`DocumentTooLarge` the moment
        the running total passes the limit, so a multi-GB upload can't exhaust RAM.
        """
        limit = self._max_upload_bytes
        hint = getattr(file, "size", None)
        if hint is not None and hint > limit:
            raise DocumentTooLarge(limit)
        chunks: list[bytes] = []
        total = 0
        while piece := await file.read(_READ_CHUNK):
            total += len(piece)
            if total > limit:
                raise DocumentTooLarge(limit)
            chunks.append(piece)
        return b"".join(chunks)

    def docs_dir(self, domain: str) -> Path:
        return self._data_dir / "docs" / domain

    @staticmethod
    def _require_supported(name: str) -> None:
        if PurePosixPath(name).suffix.lower() not in SUPPORTED_SUFFIXES:
            raise UnsupportedDocument(
                f"unsupported file type '{PurePosixPath(name).suffix}'; allowed: "
                f"{', '.join(sorted(SUPPORTED_SUFFIXES))}"
            )

    @classmethod
    def _safe_filename(cls, filename: str) -> str:
        """Sanitize an uploaded filename to a single flat name (uploads have no subdirs)."""
        name = _SAFE_NAME.sub("_", Path(filename).name).strip("._")
        if not name:
            raise UnsupportedDocument("empty or invalid filename")
        cls._require_supported(name)
        return name

    @classmethod
    def _safe_source(cls, raw: str) -> str:
        """Sanitize a document *source* for delete, preserving subdirectories.

        Documents ingested from folders keep a relative source like ``a/faq.md`` (the
        collision fix), so delete must accept and preserve the path — while still
        neutralizing traversal (``..``) and absolute paths so it can only ever address a
        file inside the domain's docs folder.
        """
        pure = PurePosixPath(raw.replace("\\", "/"))
        if pure.is_absolute():
            raise UnsupportedDocument("absolute paths are not allowed")
        parts: list[str] = []
        for part in pure.parts:
            if part in ("", ".", ".."):
                raise UnsupportedDocument(f"invalid path component '{part}'")
            clean = _SAFE_NAME.sub("_", part).strip("._")
            if not clean:
                raise UnsupportedDocument("empty or invalid filename")
            parts.append(clean)
        if not parts:
            raise UnsupportedDocument("empty or invalid filename")
        source = "/".join(parts)
        cls._require_supported(source)
        return source

    async def add_document(self, domain: str, filename: str, content: bytes) -> IngestReport:
        """Persist ``content`` as a domain document, then re-index the collection."""
        safe = self._safe_filename(filename)
        if not content.strip():
            raise UnsupportedDocument("document is empty")

        docs_dir = self.docs_dir(domain)
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / safe).write_bytes(content)
        log.info("stored document %s for domain %s", safe, domain)

        # Indexing is not reentrant and is CPU-heavy — serialize and offload it.
        async with self._lock:
            report = await asyncio.to_thread(self._indexer, docs_dir, domain)
        log.info(
            "re-indexed domain %s: %d docs -> %d chunks", domain, report.documents, report.chunks
        )
        return report

    async def delete_document(self, domain: str, source: str) -> DeleteReport:
        """Remove a document from a domain: purge its vectors, then delete its file.

        ``source`` is the document identity, possibly a relative path (``a/faq.md``).
        Vectors are purged *before* the file is unlinked, so if the store errors the file
        is left untouched and the caller can retry cleanly. Purges even when the file is
        already gone (cleaning orphans left by a file deleted outside the app). The store
        is not concurrency-safe, so the purge runs under the shared model lock.
        """
        safe = self._safe_source(source)

        chunks_removed = 0
        if self._deleter is not None:
            async with self._lock:
                chunks_removed = await asyncio.to_thread(self._deleter, domain, safe)

        path = self.docs_dir(domain).joinpath(*safe.split("/"))
        file_removed = path.exists()
        if file_removed:
            path.unlink()
        log.info(
            "deleted document %s from domain %s: %d chunk(s) purged, file_removed=%s",
            safe, domain, chunks_removed, file_removed,
        )
        return DeleteReport(filename=safe, file_removed=file_removed, chunks_removed=chunks_removed)

    async def reindex(self, domain: str) -> IngestReport:
        """Rebuild a domain's collection from the current files on disk (recreate=True).

        A clean rebuild, so it also drops vectors for documents deleted outside the app.
        """
        if self._reindexer is None:
            raise RuntimeError("reindexer is not configured")
        docs_dir = self.docs_dir(domain)
        docs_dir.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            report = await asyncio.to_thread(self._reindexer, docs_dir, domain)
        log.info(
            "reindexed domain %s: %d docs -> %d chunks", domain, report.documents, report.chunks
        )
        return report


def default_indexer(
    build_embedder: Callable[[], object],
    build_store: Callable[[str], object],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> Indexer:
    """Build the production indexer: re-embed the domain folder into its collection."""

    def index(docs_dir: Path, domain: str) -> IngestReport:
        embedder = build_embedder()
        store = build_store(domain)
        # recreate=False: keep the collection and upsert (chunk ids are deterministic,
        # so re-uploading a doc overwrites rather than duplicates).
        return ingest(
            docs_dir, embedder, store,  # type: ignore[arg-type]
            chunk_size=chunk_size, chunk_overlap=chunk_overlap, recreate=False,
        )

    return index


def default_reindexer(
    build_embedder: Callable[[], object],
    build_store: Callable[[str], object],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> Indexer:
    """Build the production reindexer: rebuild the collection from scratch (recreate=True)."""

    def reindex(docs_dir: Path, domain: str) -> IngestReport:
        embedder = build_embedder()
        store = build_store(domain)
        return ingest(
            docs_dir, embedder, store,  # type: ignore[arg-type]
            chunk_size=chunk_size, chunk_overlap=chunk_overlap, recreate=True,
        )

    return reindex


def default_deleter(build_store: Callable[[str], object]) -> Deleter:
    """Build the production deleter: purge a document's chunks from its collection."""

    def delete(domain: str, source: str) -> int:
        store = build_store(domain)
        return store.delete_document(source)  # type: ignore[attr-defined]

    return delete
