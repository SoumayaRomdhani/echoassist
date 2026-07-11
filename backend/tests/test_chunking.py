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


def test_long_list_splits_between_items_not_mid_item() -> None:
    items = [f"- item number {i} with a fair amount of descriptive words here" for i in range(20)]
    chunks = chunk_text("\n".join(items), chunk_size=200, chunk_overlap=0)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    # Every list item survives intact in some chunk — none is broken across chunks.
    assert all(any(item in c for c in chunks) for item in items)


def test_table_like_rows_are_not_split_mid_row() -> None:
    rows = [f"Plan: Gold{i}; Price: {i * 100}; Region: EMEA" for i in range(30)]
    chunks = chunk_text("\n".join(rows), chunk_size=150, chunk_overlap=0)
    assert all(len(c) <= 150 for c in chunks)
    assert all(any(row in c for c in chunks) for row in rows)


def test_prefers_paragraph_boundaries_before_word_splitting() -> None:
    # Paragraphs that individually fit the budget must never be word-split.
    paragraphs = [f"Paragraph {i} " + "content " * 5 for i in range(8)]
    chunks = chunk_text("\n\n".join(paragraphs), chunk_size=120, chunk_overlap=0)
    assert all(len(c) <= 120 for c in chunks)
    assert all(any(p.strip() in c for c in chunks) for p in paragraphs)


def test_prefix_length_is_reserved_from_the_budget() -> None:
    prefix = "Section > Subsection Heading"
    chunks = chunk_text("word " * 200, chunk_size=200, chunk_overlap=20, prefix=prefix)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)          # final text (with prefix) fits
    assert all(c.startswith(prefix) for c in chunks)


def test_no_tiny_trailing_sliver_when_avoidable() -> None:
    # A short final paragraph should be folded into the previous chunk, not left alone.
    text = ("alpha " * 30).strip() + "\n\n" + ("beta " * 30).strip() + "\n\ntail."
    chunks = chunk_text(text, chunk_size=400, chunk_overlap=0)
    assert chunks[-1] != "tail."
