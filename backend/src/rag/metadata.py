"""Chunk provenance metadata — the fields every indexed chunk carries.

Assembled once per document at ingest and stored in the Qdrant payload
(``Chunk.metadata``) so downstream layers can answer *where did this come from*:

  * citations / debug views  — ``source``, ``page``, ``heading`` breadcrumb;
  * lifecycle (future steps)  — ``doc_id`` (find a document's chunks), ``content_hash``
                                (skip re-indexing an unchanged file);
  * auditability              — ``indexed_at``, ``modified_at``, ``parser_version``.

Document-level facts live in :class:`DocumentMeta`; :func:`build_chunk_metadata`
merges them with a section's page/heading and per-chunk size into the flat dict that
goes on the chunk. Keys are defined here once so retrieval/citation code never has to
guess a payload key.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Bump when extraction/chunking changes enough that indexes should be rebuilt.
# 1.1: heading-aware Markdown sections + structure-aware chunking + heading-breadcrumb prefix.
# 1.2: table-aware extraction (HTML/Markdown tables rendered to 'Header: value' text).
PARSER_VERSION = "1.2"

# Stable namespace so the same filename always maps to the same doc_id (lets the
# lifecycle layer delete/replace a document's chunks by id).
_DOC_NAMESPACE = uuid.UUID("b7e6a1c2-0000-4000-8000-000000000001")

_MIME_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".htm": "text/html",
}


def doc_id_for(source: str) -> str:
    """Deterministic id for a document within its domain (same name -> same id)."""
    return str(uuid.uuid5(_DOC_NAMESPACE, source))


def mime_type_for(suffix: str) -> str:
    return _MIME_TYPES.get(suffix.lower(), "application/octet-stream")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_iso(timestamp: float | None = None) -> str:
    """UTC ISO-8601 (second precision). ``timestamp`` is a POSIX time, or now."""
    when = datetime.fromtimestamp(timestamp, UTC) if timestamp is not None else datetime.now(UTC)
    return when.replace(microsecond=0).isoformat()


def heading_breadcrumb(heading_path: list[str] | tuple[str, ...]) -> str:
    """Render a heading path as a human-readable trail, e.g. ``Benefits > Health``."""
    return " > ".join(heading_path)


@dataclass(frozen=True, slots=True)
class DocumentMeta:
    """Provenance shared by every chunk of one source document."""

    doc_id: str
    source: str
    mime_type: str
    content_hash: str        # sha256 of the raw file bytes
    size_bytes: int
    modified_at: str         # file mtime (≈ upload time on the API path), UTC ISO
    indexed_at: str          # when this ingest run happened, UTC ISO
    parser_version: str = PARSER_VERSION

    @classmethod
    def describe(
        cls, path: Path, *, source: str | None = None, indexed_at: str | None = None
    ) -> DocumentMeta:
        """Read ``path`` and capture its document-level provenance.

        ``source`` is the document's identity within its domain — pass the path relative
        to the docs dir (e.g. ``a/faq.md``) so files with the same name in different
        folders get distinct ``source`` and ``doc_id``. Defaults to the bare filename.
        """
        data = path.read_bytes()
        src = source or path.name
        return cls(
            doc_id=doc_id_for(src),
            source=src,
            mime_type=mime_type_for(path.suffix),
            content_hash=sha256_hex(data),
            size_bytes=len(data),
            modified_at=utc_iso(path.stat().st_mtime),
            indexed_at=indexed_at or utc_iso(),
        )

    def as_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "source": self.source,
            "mime_type": self.mime_type,
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
            "indexed_at": self.indexed_at,
            "parser_version": self.parser_version,
        }


def build_chunk_metadata(doc: DocumentMeta, section_meta: dict, *, char_count: int) -> dict:
    """Flat provenance dict for one chunk: document facts + section + chunk size."""
    meta = doc.as_dict()
    meta.update(section_meta)  # page and/or heading_path (omitted when absent)
    meta["char_count"] = char_count
    heading_path = section_meta.get("heading_path")
    if heading_path:
        meta["heading"] = heading_breadcrumb(heading_path)
    return meta
