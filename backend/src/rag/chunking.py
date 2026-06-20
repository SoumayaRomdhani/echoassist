"""Document chunking.

A small, dependency-free recursive splitter: it packs whole paragraphs into
chunks up to ``chunk_size`` characters, keeps a ``chunk_overlap`` tail between
consecutive chunks for context continuity, and hard-splits any single paragraph
that exceeds the size. Character-based (not token-based) to stay dependency-free;
sizes are chosen to map to roughly 200-400 tokens.
"""

from __future__ import annotations

import re

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_WHITESPACE = re.compile(r"[ \t]+")


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(_WHITESPACE.sub(" ", line).rstrip() for line in text.split("\n")).strip()


def _hard_split(paragraph: str, chunk_size: int) -> list[str]:
    """Split an oversized paragraph on word boundaries into <= chunk_size pieces."""
    words = paragraph.split(" ")
    pieces: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > chunk_size and current:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def chunk_text(text: str, *, chunk_size: int = 1200, chunk_overlap: int = 150) -> list[str]:
    """Split ``text`` into overlapping chunks of at most ``chunk_size`` characters."""
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    normalized = _normalize(text)
    if not normalized:
        return []

    # Expand paragraphs, hard-splitting any that are individually too large.
    units: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT.split(normalized):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > chunk_size:
            units.extend(_hard_split(paragraph, chunk_size))
        else:
            units.append(paragraph)

    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}".strip()
        if len(candidate) > chunk_size and current:
            chunks.append(current)
            current = f"{_overlap_tail(current, chunk_overlap, unit, chunk_size)}{unit}".strip()
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _overlap_tail(previous: str, chunk_overlap: int, unit: str, chunk_size: int) -> str:
    """Return a trailing slice of ``previous`` (+ separator) that fits before ``unit``."""
    if not chunk_overlap:
        return ""
    allowed = min(chunk_overlap, max(0, chunk_size - len(unit) - 2))
    tail = previous[-allowed:] if allowed else ""
    return f"{tail}\n\n" if tail else ""
