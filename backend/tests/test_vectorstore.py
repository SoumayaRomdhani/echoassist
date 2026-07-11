"""QdrantVectorStore.delete_document against an in-memory Qdrant (no server needed)."""

from __future__ import annotations

import pytest

from src.rag.types import Chunk, EmbeddedChunk, SparseVector


def _embedded(source: str, ordinal: int) -> EmbeddedChunk:
    chunk = Chunk(
        id=f"{source}#{ordinal}", source=source, text=f"{source} {ordinal}", ordinal=ordinal
    )
    return EmbeddedChunk(chunk, [0.1, 0.2, 0.3], SparseVector([ordinal], [1.0]))


def _store():
    pytest.importorskip("qdrant_client")
    from src.rag.vectorstore import QdrantVectorStore

    store = QdrantVectorStore(location=":memory:", collection="stale_test")
    store.ensure_collection(3, recreate=True)
    return store


def test_delete_document_removes_only_that_source() -> None:
    store = _store()
    store.upsert(
        [_embedded("a.md", 0), _embedded("a.md", 1), _embedded("a.md", 2), _embedded("b.md", 0)]
    )
    assert store.count() == 4

    assert store.delete_document("a.md") == 3     # returns how many were removed
    assert store.count() == 1                     # only b.md remains
    assert store.delete_document("missing.md") == 0


def test_reupsert_after_delete_has_no_orphans() -> None:
    store = _store()
    # A 3-chunk version of the document...
    store.upsert([_embedded("doc.md", 0), _embedded("doc.md", 1), _embedded("doc.md", 2)])
    assert store.count() == 3

    # ...replaced by a 1-chunk version: delete-then-upsert leaves exactly one point.
    store.delete_document("doc.md")
    store.upsert([_embedded("doc.md", 0)])
    assert store.count() == 1
