"""Chunker behavior (size bounds, overlap, hard-splitting)."""

from __future__ import annotations

from src.rag.chunking import chunk_text


def test_empty_text_yields_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_short_text_is_a_single_chunk() -> None:
    chunks = chunk_text("A short paragraph.", chunk_size=100, chunk_overlap=10)
    assert chunks == ["A short paragraph."]


def test_chunks_respect_size_bound() -> None:
    text = "\n\n".join(f"Paragraph number {i} with some filler words." for i in range(40))
    chunks = chunk_text(text, chunk_size=120, chunk_overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)


def test_oversized_paragraph_is_hard_split() -> None:
    text = "word " * 200  # one long paragraph, no blank lines
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=10)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)


def test_overlap_carries_context_between_chunks() -> None:
    text = "\n\n".join(f"Sentence {i} aaaa bbbb cccc." for i in range(30))
    chunks = chunk_text(text, chunk_size=120, chunk_overlap=30)
    # Consecutive chunks should share some trailing/leading text via the overlap.
    assert any(chunks[i][-15:] in chunks[i + 1] for i in range(len(chunks) - 1))
