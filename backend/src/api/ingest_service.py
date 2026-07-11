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
from pathlib import Path

from src.rag.ingest import IngestReport, ingest
from src.rag.loaders import SUPPORTED_SUFFIXES

log = logging.getLogger("echoassist.api.ingest")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB
_READ_CHUNK = 1024 * 1024                      # 1 MiB read granularity

# (docs_dir, domain) -> report. Defaults to the real FastEmbed/Qdrant pipeline.
Indexer = Callable[[Path, str], IngestReport]


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
        lock: asyncio.Lock | None = None,
        max_upload_bytes: int = _DEFAULT_MAX_UPLOAD_BYTES,
    ) -> None:
        self._data_dir = data_dir
        self._indexer = indexer
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
    def _safe_filename(filename: str) -> str:
        name = _SAFE_NAME.sub("_", Path(filename).name).strip("._")
        if not name:
            raise UnsupportedDocument("empty or invalid filename")
        if Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
            raise UnsupportedDocument(
                f"unsupported file type '{Path(name).suffix}'; allowed: "
                f"{', '.join(sorted(SUPPORTED_SUFFIXES))}"
            )
        return name

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
