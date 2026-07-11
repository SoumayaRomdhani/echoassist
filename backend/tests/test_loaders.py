"""Document extraction layer: per-format loaders + provenance threading into chunks."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.rag.ingest import LoadedDocument, build_chunks, load_documents
from src.rag.loaders import (
    DocumentSection,
    UnsupportedDocumentType,
    extract,
)
from src.rag.metadata import DocumentMeta


# --- text / markdown ------------------------------------------------------- #
def test_text_and_markdown_are_a_single_whole_document_section(tmp_path: Path) -> None:
    md = tmp_path / "benefits.md"
    md.write_text("# Benefits\n\nUnlimited coffee.\n\nAnd tea.", encoding="utf-8")
    sections = extract(md)
    assert len(sections) == 1
    assert sections[0].page is None
    assert sections[0].heading_path == ()
    assert "Unlimited coffee." in sections[0].text
    # .txt shares the same loader.
    txt = tmp_path / "note.txt"
    txt.write_text("plain body", encoding="utf-8")
    assert extract(txt) == [DocumentSection(text="plain body")]


def test_empty_file_yields_no_sections(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("   \n\n  ", encoding="utf-8")
    assert extract(empty) == []


# --- PDF -------------------------------------------------------------------- #
# A committed 2-page fixture (page 1 "Hello from page one.", page 2 "Second page
# content here.") so the test runs without a PDF generator installed.
_SAMPLE_PDF = Path(__file__).parent / "data" / "sample_two_pages.pdf"


def test_pdf_yields_one_section_per_page_with_page_numbers() -> None:
    pytest.importorskip("pypdf")
    sections = extract(_SAMPLE_PDF)
    assert [s.page for s in sections] == [1, 2]
    assert "page one" in sections[0].text
    assert "Second page" in sections[1].text


# --- DOCX ------------------------------------------------------------------- #
def _write_docx(path: Path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("Benefits", level=1)
    document.add_paragraph("Unlimited coffee for everyone.")
    document.add_heading("Health", level=2)
    document.add_paragraph("Full medical coverage.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Plan"
    table.cell(0, 1).text = "Cost"
    table.cell(1, 0).text = "Gold"
    table.cell(1, 1).text = "100"
    document.save(str(path))


def test_docx_tracks_heading_path_and_renders_tables(tmp_path: Path) -> None:
    doc = tmp_path / "hr.docx"
    _write_docx(doc)
    sections = extract(doc)

    top = next(s for s in sections if s.heading_path == ("Benefits",))
    assert "Unlimited coffee" in top.text

    nested = next(s for s in sections if s.heading_path == ("Benefits", "Health"))
    assert "Full medical coverage." in nested.text
    # The table under "Health" is rendered as readable 'Header: value' text.
    assert "Plan: Gold" in nested.text
    assert "Cost: 100" in nested.text


# --- HTML ------------------------------------------------------------------- #
def test_html_is_heading_aware(tmp_path: Path) -> None:
    pytest.importorskip("bs4")
    html = tmp_path / "kb.htm"
    html.write_text(
        "<h1>Setup</h1><p>Install the app.</p>"
        "<h2>Login</h2><p>Enter your password.</p>"
        "<script>ignore()</script>",
        encoding="utf-8",
    )
    sections = extract(html)
    login = next(s for s in sections if s.heading_path == ("Setup", "Login"))
    assert "Enter your password." in login.text
    assert all("ignore()" not in s.text for s in sections)  # script stripped


# --- dispatch --------------------------------------------------------------- #
def test_unsupported_suffix_raises(tmp_path: Path) -> None:
    bad = tmp_path / "malware.exe"
    bad.write_bytes(b"MZ")
    with pytest.raises(UnsupportedDocumentType):
        extract(bad)


# --- end-to-end: provenance lands on the chunk ----------------------------- #
def test_load_documents_skips_unsupported_and_empty(tmp_path: Path) -> None:
    (tmp_path / "good.md").write_text("hello world", encoding="utf-8")
    (tmp_path / "skip.exe").write_bytes(b"MZ")
    (tmp_path / "blank.txt").write_text("  ", encoding="utf-8")
    result = load_documents(tmp_path)
    # Only good.md yields indexable text...
    assert [d.source for d in result.documents] == ["good.md"]
    # ...but the empty (supported) file is still "attempted" so re-ingest can clean it;
    # the unsupported .exe is not attempted at all.
    assert set(result.attempted_sources) == {"good.md", "blank.txt"}
    # The empty supported file is reported as skipped (not silently ignored).
    assert [s.source for s in result.skipped] == ["blank.txt"]
    assert "no extractable text" in result.skipped[0].reason


def test_corrupt_file_is_skipped_and_reported_not_fatal(tmp_path: Path) -> None:
    """A corrupt PDF must not abort the batch — good files still index, bad one reported."""
    pytest.importorskip("pypdf")
    (tmp_path / "good.md").write_text("Real, indexable content.", encoding="utf-8")
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.4 this is not really a pdf body")

    result = load_documents(tmp_path)

    assert [d.source for d in result.documents] == ["good.md"]     # good file survives
    assert [s.source for s in result.skipped] == ["broken.pdf"]    # bad file reported
    assert result.skipped[0].reason                                # with a reason
    assert "broken.pdf" in result.attempted_sources               # still tracked for cleanup


def _fake_doc_meta(source: str = "guide.pdf") -> DocumentMeta:
    return DocumentMeta(
        doc_id="doc-1",
        source=source,
        mime_type="application/pdf",
        content_hash="abc123",
        size_bytes=42,
        modified_at="2026-07-10T00:00:00+00:00",
        indexed_at="2026-07-10T00:00:00+00:00",
    )


def test_build_chunks_carries_page_and_heading_metadata() -> None:
    docs = [
        LoadedDocument(
            meta=_fake_doc_meta(),
            sections=[
                DocumentSection(text="Alpha on page one.", page=1),
                DocumentSection(
                    text="Beta under a heading.", heading_path=("Setup", "Login")
                ),
            ],
        )
    ]
    chunks = build_chunks(docs, chunk_size=200, chunk_overlap=20)

    # Section provenance lands per chunk...
    assert chunks[0].metadata["page"] == 1
    assert chunks[1].metadata["heading_path"] == ["Setup", "Login"]
    assert chunks[1].metadata["heading"] == "Setup > Login"
    # ...alongside the shared document facts and per-chunk size.
    assert chunks[0].metadata["doc_id"] == "doc-1"
    assert chunks[0].metadata["content_hash"] == "abc123"
    assert chunks[0].metadata["char_count"] == len("Alpha on page one.")
    # Ordinals run per-document across sections; ids stay deterministic.
    assert [c.id for c in chunks] == ["guide.pdf#0", "guide.pdf#1"]
