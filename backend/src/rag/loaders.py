"""Document extraction layer: raw file -> ordered text sections with provenance.

One loader per file type, all behind a single :func:`extract` dispatcher keyed by
suffix. Each loader returns a list of :class:`DocumentSection` — a run of text plus
the *provenance* the retriever/citation layer cares about:

  * ``page``          — 1-based page number (PDF), for "answer is on page 4" citations.
  * ``heading_path``  — the heading breadcrumb the text lives under (DOCX/HTML),
                        e.g. ``("Benefits", "Health")``, for section-level citations.

The sections feed the existing chunker unchanged (``rag.ingest.build_chunks``): a
chunk never spans two sections, so every chunk inherits exactly one page/heading and
provenance stays precise.

Heavy parsers (pypdf, python-docx, BeautifulSoup) are imported lazily *inside* their
loader, so importing this module is cheap and only the file types you actually ingest
need their dependency installed (``pip install 'echoassist-backend[rag]'``).

Section granularity by type: Markdown, DOCX, and HTML are **heading-aware** — one
section per heading, carrying its ``heading_path`` breadcrumb. PDF is one section per
page (carrying ``page``). Plain ``.txt`` has no structure, so it is a single
whole-document section.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("echoassist.rag.loaders")


@dataclass(frozen=True, slots=True)
class DocumentSection:
    """A contiguous run of extracted text plus where it came from."""

    text: str
    page: int | None = None                       # 1-based page (PDF)
    heading_path: tuple[str, ...] = field(default_factory=tuple)  # ("H1", "H2", ...)

    def metadata(self) -> dict:
        """Provenance as a plain dict for the chunk payload (omits empty fields)."""
        meta: dict = {}
        if self.page is not None:
            meta["page"] = self.page
        if self.heading_path:
            meta["heading_path"] = list(self.heading_path)
        return meta


class UnsupportedDocumentType(ValueError):
    """Raised when :func:`extract` is asked for a suffix with no loader."""


class DocumentLoadError(RuntimeError):
    """A supported file could not be parsed (corrupt file, or missing parser dep)."""


# --- text / markdown ------------------------------------------------------- #
def _read_text(path: Path) -> str:
    # utf-8 is the norm for KB docs; fall back to latin-1 so a stray byte in an
    # otherwise-fine file does not abort the read (robust per-file handling of a
    # whole broken corpus stays in the ingest layer).
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        log.warning("%s is not valid utf-8; re-reading as latin-1", path.name)
        return path.read_text(encoding="latin-1")


def _load_text(path: Path) -> list[DocumentSection]:
    text = _read_text(path).strip()
    return [DocumentSection(text=text)] if text else []


# --- Markdown (heading-aware) ---------------------------------------------- #
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_MD_FENCE = re.compile(r"^\s*(```|~~~)")


def _load_markdown(path: Path) -> list[DocumentSection]:
    """Split Markdown into one section per heading, tracking the heading path.

    Keeps each section coherent (a chunk never mixes content from two headings) and
    records the breadcrumb (``Setup > Login``) so the chunker can prefix it. Headings
    inside fenced code blocks (```/~~~) are ignored so code comments aren't misread.
    """
    sections: list[DocumentSection] = []
    stack: list[tuple[int, str]] = []  # (heading level, title)
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append(
                DocumentSection(text=body, heading_path=tuple(t for _, t in stack))
            )
        buffer.clear()

    for line in _read_text(path).splitlines():
        if _MD_FENCE.match(line):
            in_fence = not in_fence
            buffer.append(line)
            continue
        heading = None if in_fence else _MD_HEADING.match(line)
        if heading:
            flush()  # the previous section ends where a new heading begins
            level = len(heading.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading.group(2).strip()))
        else:
            buffer.append(line)
    flush()
    return sections


# --- PDF (pypdf, one section per page) ------------------------------------- #
def _load_pdf(path: Path) -> list[DocumentSection]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - install-time guard
        raise DocumentLoadError(
            "Reading PDFs needs pypdf. Install it with: pip install 'echoassist-backend[rag]'"
        ) from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001 - pypdf raises assorted errors on bad files
        raise DocumentLoadError(f"could not open PDF {path.name}: {exc}") from exc

    sections: list[DocumentSection] = []
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            sections.append(DocumentSection(text=text, page=number))
    if not sections:
        # A text layer is required — scanned/image-only PDFs need OCR (future step).
        log.warning("%s yielded no extractable text (scanned PDF? OCR needed)", path.name)
    return sections


# --- DOCX (python-docx, heading-aware + tables) ---------------------------- #
_HEADING_STYLE = re.compile(r"^Heading (\d+)$")


def _iter_docx_blocks(document) -> Iterator[tuple[str, object]]:
    """Yield ("paragraph"|"table", block) in document order (python-docx recipe)."""
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield "paragraph", Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield "table", Table(child, document)


def _table_to_text(table) -> str:
    """Render a table as readable 'Header: value' lines so it survives embedding."""
    rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    if len(rows) == 1:
        return " | ".join(c for c in rows[0] if c)
    header = rows[0]
    lines: list[str] = []
    for row in rows[1:]:
        pairs = [f"{h}: {v}" for h, v in zip(header, row, strict=False) if v]
        lines.append("; ".join(pairs) if pairs else " | ".join(c for c in row if c))
    return "\n".join(line for line in lines if line)


def _load_docx(path: Path) -> list[DocumentSection]:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - install-time guard
        raise DocumentLoadError(
            "Reading .docx needs python-docx. Install it with: "
            "pip install 'echoassist-backend[rag]'"
        ) from exc

    try:
        document = docx.Document(str(path))
    except Exception as exc:  # noqa: BLE001 - python-docx raises assorted errors on bad files
        raise DocumentLoadError(f"could not open DOCX {path.name}: {exc}") from exc

    sections: list[DocumentSection] = []
    stack: list[tuple[int, str]] = []  # (heading level, title)
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append(
                DocumentSection(text=body, heading_path=tuple(t for _, t in stack))
            )
        buffer.clear()

    for kind, block in _iter_docx_blocks(document):
        if kind == "table":
            rendered = _table_to_text(block)
            if rendered:
                buffer.append(rendered)
            continue
        style = (block.style.name if block.style else "") or ""
        text = block.text.strip()
        heading = _HEADING_STYLE.match(style)
        if heading:
            flush()  # the previous section ends where a new heading begins
            level = int(heading.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            if text:
                stack.append((level, text))
        elif text:
            buffer.append(text)
    flush()
    return sections


# --- HTML (BeautifulSoup, heading-aware) ----------------------------------- #
_HTML_HEADING = re.compile(r"^h([1-6])$")
_HTML_BLOCKS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre"]


def _load_html(path: Path) -> list[DocumentSection]:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - install-time guard
        raise DocumentLoadError(
            "Reading HTML needs beautifulsoup4. Install it with: "
            "pip install 'echoassist-backend[rag]'"
        ) from exc

    soup = BeautifulSoup(_read_text(path), "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    sections: list[DocumentSection] = []
    stack: list[tuple[int, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append(
                DocumentSection(text=body, heading_path=tuple(t for _, t in stack))
            )
        buffer.clear()

    for element in soup.find_all(_HTML_BLOCKS):
        text = element.get_text(" ", strip=True)
        heading = _HTML_HEADING.fullmatch(element.name or "")
        if heading:
            flush()
            level = int(heading.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            if text:
                stack.append((level, text))
        elif text:
            buffer.append(text)
    flush()

    if not sections:  # unstructured page — keep the whole visible text
        whole = soup.get_text(" ", strip=True)
        if whole:
            sections.append(DocumentSection(text=whole))
    return sections


# --- dispatch -------------------------------------------------------------- #
_LOADERS = {
    ".md": _load_markdown,
    ".markdown": _load_markdown,
    ".txt": _load_text,
    ".pdf": _load_pdf,
    ".docx": _load_docx,
    ".html": _load_html,
    ".htm": _load_html,
}

# Single source of truth for "what can the KB ingest" (ingest + upload API share it).
SUPPORTED_SUFFIXES = frozenset(_LOADERS)


def extract(path: Path) -> list[DocumentSection]:
    """Extract ordered, provenance-tagged sections from ``path`` by its suffix."""
    loader = _LOADERS.get(path.suffix.lower())
    if loader is None:
        raise UnsupportedDocumentType(
            f"unsupported file type '{path.suffix}'; allowed: "
            f"{', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )
    return loader(path)
