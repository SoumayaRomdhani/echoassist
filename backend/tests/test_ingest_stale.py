"""Re-ingest must not leave orphaned chunks when a document shrinks or changes.

Exercises ``ingest()`` with an in-memory fake store + fake embedder, so it needs
neither Qdrant nor FastEmbed. See ``test_vectorstore.py`` for the real Qdrant
``delete_document`` behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.rag.embeddings import HybridEmbedder
from src.rag.ingest import ingest
from src.rag.types import EmbeddedChunk, SparseVector
from src.rag.vectorstore import VectorStore


class FakeEmbedder(HybridEmbedder):
    @property
    def dense_dim(self) -> int:
        return 3

    def embed_documents(self, texts):
        return [([0.0, 0.0, 0.0], SparseVector([], [])) for _ in texts]

    def embed_query(self, text):
        return [0.0, 0.0, 0.0], SparseVector([], [])


class FailingEmbedder(FakeEmbedder):
    """Raises while embedding documents — to prove the index survives an embed failure."""

    def embed_documents(self, texts):
        raise RuntimeError("embedding backend is down")


class FakeStore(VectorStore):
    """A dict keyed by chunk id, mimicking Qdrant's deterministic-id upsert semantics."""

    def __init__(self) -> None:
        self.points: dict[str, EmbeddedChunk] = {}

    def ensure_collection(self, dense_dim, *, recreate=False):
        if recreate:
            self.points.clear()

    def upsert(self, chunks):
        for ec in chunks:
            self.points[ec.chunk.id] = ec  # same id overwrites, like Qdrant

    def delete_document(self, source) -> int:
        stale = [cid for cid, ec in self.points.items() if ec.chunk.source == source]
        for cid in stale:
            del self.points[cid]
        return len(stale)

    def search_dense(self, dense, limit):
        return []

    def search_sparse(self, sparse, limit):
        return []

    def count(self) -> int:
        return len(self.points)

    def all_text(self) -> str:
        return " ".join(ec.chunk.text for ec in self.points.values())


def test_reingest_shorter_document_removes_orphaned_chunks(tmp_path: Path) -> None:
    store, embedder = FakeStore(), FakeEmbedder()
    doc = tmp_path / "policy.md"
    doc.write_text("\n\n".join(f"Paragraph {i} about subject {i}." for i in range(6)), "utf-8")

    first = ingest(tmp_path, embedder, store, chunk_size=40, chunk_overlap=5, recreate=True)
    assert first.chunks > 1 and store.count() == first.chunks

    # The document is edited down to a single short line.
    doc.write_text("Only one short line now.", "utf-8")
    second = ingest(tmp_path, embedder, store, chunk_size=40, chunk_overlap=5, recreate=False)

    assert second.chunks == 1
    assert store.count() == 1                      # no orphans from the 6-paragraph version
    assert "Only one short line now." in store.all_text()
    assert "Paragraph 5" not in store.all_text()   # deleted content is truly gone


def test_reingest_one_document_leaves_others_untouched(tmp_path: Path) -> None:
    store, embedder = FakeStore(), FakeEmbedder()
    (tmp_path / "a.md").write_text("\n\n".join(f"A paragraph {i}." for i in range(4)), "utf-8")
    (tmp_path / "b.md").write_text("\n\n".join(f"B paragraph {i}." for i in range(3)), "utf-8")

    ingest(tmp_path, embedder, store, chunk_size=40, chunk_overlap=5, recreate=True)
    b_before = {cid for cid, ec in store.points.items() if ec.chunk.source == "b.md"}

    # Shrink only a.md and re-ingest the folder.
    (tmp_path / "a.md").write_text("A single line.", "utf-8")
    ingest(tmp_path, embedder, store, chunk_size=40, chunk_overlap=5, recreate=False)

    a_after = {cid for cid, ec in store.points.items() if ec.chunk.source == "a.md"}
    b_after = {cid for cid, ec in store.points.items() if ec.chunk.source == "b.md"}
    assert a_after == {"a.md#0"}      # only the new single chunk
    assert b_after == b_before        # b.md untouched by a.md's re-ingest


def test_reingest_document_that_now_extracts_nothing_removes_old_chunks(tmp_path: Path) -> None:
    """A revision that extracts zero chunks (scanned/empty) must still purge old chunks."""
    store, embedder = FakeStore(), FakeEmbedder()
    doc = tmp_path / "guide.md"
    doc.write_text("\n\n".join(f"Section {i} with content." for i in range(5)), "utf-8")
    ingest(tmp_path, embedder, store, chunk_size=40, chunk_overlap=5, recreate=True)
    assert store.count() > 1

    # The file is replaced by something that yields no indexable text (e.g. a scanned PDF).
    doc.write_text("   \n\n   ", "utf-8")
    report = ingest(tmp_path, embedder, store, chunk_size=40, chunk_overlap=5, recreate=False)

    assert report.chunks == 0
    assert store.count() == 0          # old chunks are gone, not left as ghosts


def test_zero_chunk_document_does_not_remove_other_documents(tmp_path: Path) -> None:
    store, embedder = FakeStore(), FakeEmbedder()
    (tmp_path / "a.md").write_text("\n\n".join(f"A paragraph {i}." for i in range(4)), "utf-8")
    (tmp_path / "b.md").write_text("\n\n".join(f"B paragraph {i}." for i in range(3)), "utf-8")
    ingest(tmp_path, embedder, store, chunk_size=40, chunk_overlap=5, recreate=True)
    b_before = {cid for cid, ec in store.points.items() if ec.chunk.source == "b.md"}

    # a.md becomes empty; b.md is unchanged.
    (tmp_path / "a.md").write_text("   ", "utf-8")
    ingest(tmp_path, embedder, store, chunk_size=40, chunk_overlap=5, recreate=False)

    a_after = {cid for cid, ec in store.points.items() if ec.chunk.source == "a.md"}
    b_after = {cid for cid, ec in store.points.items() if ec.chunk.source == "b.md"}
    assert a_after == set()            # a.md fully removed
    assert b_after == b_before         # b.md preserved


def test_embedding_failure_on_reingest_leaves_index_intact(tmp_path: Path) -> None:
    """If embedding fails during re-ingest, the existing vectors must not be deleted."""
    store = FakeStore()
    doc = tmp_path / "policy.md"
    doc.write_text("\n\n".join(f"Rule {i} applies here." for i in range(4)), "utf-8")
    ingest(tmp_path, FakeEmbedder(), store, chunk_size=40, chunk_overlap=5, recreate=True)
    before = set(store.points)
    assert len(before) > 1

    # A new version is uploaded, but embedding blows up mid-ingest.
    doc.write_text("A shorter policy.", "utf-8")
    with pytest.raises(RuntimeError, match="embedding backend is down"):
        ingest(tmp_path, FailingEmbedder(), store, chunk_size=40, chunk_overlap=5, recreate=False)

    assert set(store.points) == before  # nothing deleted, index still complete


def test_ingest_reports_skipped_files_and_indexes_the_rest(tmp_path: Path) -> None:
    """A bad file is skipped+reported in the IngestReport; the good file still indexes."""
    pytest.importorskip("pypdf")
    store, embedder = FakeStore(), FakeEmbedder()
    (tmp_path / "good.md").write_text("Indexable content here.", "utf-8")
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.4 not a real pdf")

    report = ingest(tmp_path, embedder, store, chunk_size=200, chunk_overlap=20, recreate=True)

    assert report.documents == 1 and report.chunks >= 1
    assert [s.source for s in report.skipped] == ["broken.pdf"]
    assert {ec.chunk.source for ec in store.points.values()} == {"good.md"}


def test_same_filename_in_different_folders_do_not_collide(tmp_path: Path) -> None:
    """a/faq.md and b/faq.md must index as distinct documents, not overwrite each other."""
    store, embedder = FakeStore(), FakeEmbedder()
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "faq.md").write_text("Alpha answer about widgets.", "utf-8")
    (tmp_path / "b" / "faq.md").write_text("Bravo answer about gadgets.", "utf-8")

    ingest(tmp_path, embedder, store, chunk_size=200, chunk_overlap=20, recreate=True)

    sources = {ec.chunk.source for ec in store.points.values()}
    assert sources == {"a/faq.md", "b/faq.md"}          # relative-path identity, no collision
    assert "a/faq.md#0" in store.points and "b/faq.md#0" in store.points
    text = store.all_text()
    assert "Alpha answer" in text and "Bravo answer" in text   # neither overwrote the other
    doc_ids = {ec.chunk.metadata["doc_id"] for ec in store.points.values()}
    assert len(doc_ids) == 2                            # distinct doc_ids too
