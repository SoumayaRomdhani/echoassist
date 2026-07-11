"""Structure-aware document chunking.

A small, dependency-free recursive splitter. Given the text of one
:class:`~src.rag.loaders.DocumentSection`, it chooses the *coarsest structural
boundary* that keeps pieces within budget — paragraphs first, then lines (Markdown
list items and rendered table rows are one line each), then words, and only as a last
resort a mid-word character split. So a long list or table is broken *between* items
and rows, never through them.

Sizing is character-based (not token-based) to stay dependency-free; the defaults map
to roughly 200-400 tokens. ``prefix`` reserves room for a heading breadcrumb the caller
prepends to each chunk, so the final chunk text still respects ``chunk_size``. Overlap
is conservative and only ever within this single section (the caller never spans two).
"""

from __future__ import annotations

import re

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_WHITESPACE = re.compile(r"[ \t]+")
# Structural separators, coarsest first: paragraph, line (list item / table row), word.
# "" is the final fallback: an unavoidable mid-word character split.
_SEPARATORS = ("\n\n", "\n", " ", "")
# A trailing chunk smaller than this fraction of the budget is a "sliver" worth merging.
_SLIVER_RATIO = 0.35


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(_WHITESPACE.sub(" ", line).rstrip() for line in text.split("\n")).strip()


def _split_recursive(text: str, budget: int, separators: tuple[str, ...]) -> list[str]:
    """Greedily pack ``text`` into <= ``budget`` pieces, preferring a coarse separator."""
    if len(text) <= budget:
        return [text] if text else []
    separator = separators[0]
    finer = separators[1:]
    if separator == "":
        # No structural boundary left: a single word longer than the budget.
        return [text[i : i + budget] for i in range(0, len(text), budget)]
    parts = text.split(separator)
    if len(parts) == 1:
        return _split_recursive(text, budget, finer)  # separator absent -> go finer

    pieces: list[str] = []
    current = ""
    for part in parts:
        if not part:
            continue
        candidate = f"{current}{separator}{part}" if current else part
        if len(candidate) <= budget:
            current = candidate
            continue
        if current:
            pieces.append(current)
            current = ""
        if len(part) <= budget:
            current = part
        else:
            pieces.extend(_split_recursive(part, budget, finer))  # oversized part -> finer
    if current:
        pieces.append(current)
    return pieces


def _merge_sliver_tail(pieces: list[str], budget: int) -> list[str]:
    """Fold a tiny trailing chunk back into the previous one when it still fits."""
    if len(pieces) >= 2 and len(pieces[-1]) < budget * _SLIVER_RATIO:
        merged = f"{pieces[-2]}\n\n{pieces[-1]}"
        if len(merged) <= budget:
            pieces[-2:] = [merged]
    return pieces


def _overlap_tail(previous: str, overlap: int) -> str:
    """A trailing slice of ``previous`` up to ``overlap`` chars, starting at a word."""
    tail = previous[-overlap:]
    if len(tail) < len(previous) and " " in tail:
        tail = tail.split(" ", 1)[1]  # drop the leading partial word
    return tail.strip()


def _apply_overlap(pieces: list[str], overlap: int, budget: int) -> list[str]:
    """Prepend a short tail of each chunk to the next for cross-chunk continuity."""
    if overlap <= 0 or len(pieces) <= 1:
        return pieces
    out = [pieces[0]]
    for previous, piece in zip(pieces, pieces[1:], strict=False):
        tail = _overlap_tail(previous, overlap)
        combined = f"{tail}\n\n{piece}" if tail else piece
        out.append(combined if len(combined) <= budget else piece)
    return out


def chunk_text(
    text: str,
    *,
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
    prefix: str = "",
) -> list[str]:
    """Split ``text`` into overlapping, structure-aware chunks within ``chunk_size``.

    ``prefix`` (a heading breadcrumb) is prepended to every returned chunk; its length
    is reserved from the budget so the final text still fits ``chunk_size``.
    """
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    normalized = _normalize(text)
    if not normalized:
        return []

    reserve = len(prefix) + 2 if prefix else 0            # breadcrumb + "\n\n"
    budget = max(1, chunk_size - reserve)                 # room for the content
    content_budget = max(1, budget - chunk_overlap - 2)   # leave room for the overlap tail

    pieces = _split_recursive(normalized, content_budget, _SEPARATORS)
    pieces = _merge_sliver_tail(pieces, content_budget)
    pieces = _apply_overlap(pieces, chunk_overlap, budget)
    if prefix:
        pieces = [f"{prefix}\n\n{piece}" for piece in pieces]
    return pieces
