"""Chunk provenance metadata: document facts, hashing, and per-chunk assembly."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from src.rag.metadata import (
    PARSER_VERSION,
    DocumentMeta,
    build_chunk_metadata,
    doc_id_for,
    heading_breadcrumb,
    mime_type_for,
)

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")


def test_doc_id_is_stable_per_source() -> None:
    assert doc_id_for("benefits.md") == doc_id_for("benefits.md")
    assert doc_id_for("benefits.md") != doc_id_for("policy.pdf")


def test_mime_type_mapping() -> None:
    assert mime_type_for(".PDF") == "application/pdf"
    assert mime_type_for(".md") == "text/markdown"
    assert mime_type_for(".xyz") == "application/octet-stream"


def test_describe_captures_document_facts(tmp_path: Path) -> None:
    body = b"# Benefits\nUnlimited coffee."
    path = tmp_path / "benefits.md"
    path.write_bytes(body)

    meta = DocumentMeta.describe(path)
    assert meta.source == "benefits.md"
    assert meta.mime_type == "text/markdown"
    assert meta.content_hash == hashlib.sha256(body).hexdigest()
    assert meta.size_bytes == len(body)
    assert meta.doc_id == doc_id_for("benefits.md")
    assert _ISO.match(meta.indexed_at) and _ISO.match(meta.modified_at)
    assert meta.parser_version  # non-empty


def test_describe_uses_relative_source_for_identity(tmp_path: Path) -> None:
    path = tmp_path / "faq.md"
    path.write_text("body", encoding="utf-8")
    meta = DocumentMeta.describe(path, source="hr/faq.md")
    assert meta.source == "hr/faq.md"
    assert meta.doc_id == doc_id_for("hr/faq.md")
    assert meta.doc_id != doc_id_for("faq.md")   # folder disambiguates same-named files


def test_build_chunk_metadata_merges_and_adds_breadcrumb() -> None:
    doc = DocumentMeta(
        doc_id="d1", source="hr.docx", mime_type="x", content_hash="h",
        size_bytes=1, modified_at="t", indexed_at="t",
    )
    result = build_chunk_metadata(
        doc, {"heading_path": ["Benefits", "Health"]}, char_count=123
    )
    assert result["doc_id"] == "d1"
    assert result["source"] == "hr.docx"
    assert result["heading_path"] == ["Benefits", "Health"]
    assert result["heading"] == "Benefits > Health"
    assert result["char_count"] == 123
    # No heading -> no breadcrumb key.
    assert "heading" not in build_chunk_metadata(doc, {"page": 2}, char_count=5)


def test_heading_breadcrumb() -> None:
    assert heading_breadcrumb(["A", "B", "C"]) == "A > B > C"
    assert heading_breadcrumb(()) == ""


def test_parser_version_bumped_for_structure_aware_chunking() -> None:
    # Extraction + chunking changed, so the version must move off "1.0" to force re-index.
    assert PARSER_VERSION != "1.0"
