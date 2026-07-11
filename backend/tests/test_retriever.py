"""Hybrid retriever fuse + rerank logic, validated with fakes (no models/Qdrant)."""

from __future__ import annotations

from src.rag.embeddings import HybridEmbedder
from src.rag.reranker import Reranker
from src.rag.retriever import Retriever
from src.rag.types import Chunk, ScoredChunk, SparseVector
from src.rag.vectorstore import VectorStore


def _chunk(cid: str, source: str = "doc.md") -> Chunk:
    return Chunk(id=cid, source=source, text=f"text-{cid}", ordinal=0)


class FakeEmbedder(HybridEmbedder):
    @property
    def dense_dim(self) -> int:
        return 3

    def embed_documents(self, texts):
        return [([0.0, 0.0, 0.0], SparseVector([], [])) for _ in texts]

    def embed_query(self, text):
        return [0.0, 0.0, 0.0], SparseVector([0], [1.0])


class FakeStore(VectorStore):
    def __init__(self, dense: list[ScoredChunk], sparse: list[ScoredChunk]) -> None:
        self._dense = dense
        self._sparse = sparse

    def ensure_collection(self, dense_dim, *, recreate=False): ...
    def upsert(self, chunks): ...
    def delete_document(self, source) -> int:
        return 0
    def count(self) -> int:
        return len(self._dense)

    def search_dense(self, dense, limit):
        return self._dense[:limit]

    def search_sparse(self, sparse, limit):
        return self._sparse[:limit]


class FakeReranker(Reranker):
    """Scores by a fixed preference map so we can assert ordering deterministically."""

    def __init__(self, preference: dict[str, float]) -> None:
        self._pref = preference

    def rerank(self, query, passages):
        return [self._pref.get(p, 0.0) for p in passages]


def test_retrieve_fuses_both_modalities_and_reranks() -> None:
    a, b, c = _chunk("a"), _chunk("b"), _chunk("c")
    dense = [ScoredChunk(a, 0.9), ScoredChunk(b, 0.8)]
    sparse = [ScoredChunk(b, 5.0), ScoredChunk(c, 4.0)]
    # Rerank prefers c's text most, then a, then b.
    reranker = FakeReranker({"text-c": 3.0, "text-a": 2.0, "text-b": 1.0})

    retriever = Retriever(
        FakeEmbedder(), FakeStore(dense, sparse), reranker, top_k=2, candidates=10, rrf_k=60
    )
    results = retriever.retrieve("anything")

    assert [r.chunk.id for r in results] == ["c", "a"]  # top_k=2, ordered by rerank score
    assert results[0].components["rerank"] == 3.0
    assert "rrf" in results[0].components


def test_retrieve_with_no_candidates_returns_empty() -> None:
    retriever = Retriever(
        FakeEmbedder(), FakeStore([], []), FakeReranker({}), top_k=5, candidates=10
    )
    assert retriever.retrieve("anything") == []


class _BrokenReranker(Reranker):
    """Simulates a cloud reranker that is rate-limited or down."""

    def rerank(self, query, passages):
        raise RuntimeError("reranker rate limited (e.g. Voyage free tier: 3 RPM)")


def test_retrieve_falls_back_to_rrf_order_when_reranker_fails() -> None:
    """A reranker outage must not fail the turn — degrade to the RRF-fused ranking so the
    caller still gets grounded results instead of a refusal."""
    a, b, c = _chunk("a"), _chunk("b"), _chunk("c")
    dense = [ScoredChunk(a, 0.9), ScoredChunk(b, 0.8)]
    sparse = [ScoredChunk(b, 5.0), ScoredChunk(c, 4.0)]

    retriever = Retriever(
        FakeEmbedder(), FakeStore(dense, sparse), _BrokenReranker(), top_k=3, candidates=10
    )
    results = retriever.retrieve("anything")

    assert results, "must still return candidates when the reranker is down"
    # b appears in both modalities -> highest RRF -> ranked first without the reranker.
    assert results[0].chunk.id == "b"
    assert all(r.components["rerank"] is None for r in results)   # marked as un-reranked
    assert results[0].score == results[0].components["rrf"]        # gate uses the RRF score
