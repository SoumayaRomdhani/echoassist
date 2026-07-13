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


def _tchunk(cid: str, text: str, source: str = "doc.md") -> Chunk:
    return Chunk(id=cid, source=source, text=text, ordinal=0)


def test_retrieve_drops_near_duplicate_boilerplate() -> None:
    # Two page headers differing only in the page number are near-identical boilerplate.
    boiler1 = _tchunk("h1", "IBM Security Access Manager Help Desk Guide page one")
    boiler2 = _tchunk("h2", "IBM Security Access Manager Help Desk Guide page two")
    distinct = _tchunk("d", "How to revoke a second authentication factor")
    dense = [ScoredChunk(boiler1, 0.9), ScoredChunk(boiler2, 0.85), ScoredChunk(distinct, 0.7)]
    reranker = FakeReranker({boiler1.text: 3.0, boiler2.text: 2.5, distinct.text: 1.0})

    retriever = Retriever(
        FakeEmbedder(), FakeStore(dense, []), reranker, top_k=2, candidates=10
    )
    ids = [r.chunk.id for r in retriever.retrieve("anything")]
    assert ids == ["h1", "d"]  # h2 dropped as a near-duplicate; distinct backfills its slot


def test_retrieve_keeps_distinct_chunks() -> None:
    a = _tchunk("a", "how to reset your password using the self-service portal")
    b = _tchunk("b", "vpn troubleshooting steps for remote network access")
    dense = [ScoredChunk(a, 0.9), ScoredChunk(b, 0.8)]
    reranker = FakeReranker({a.text: 2.0, b.text: 1.0})

    retriever = Retriever(FakeEmbedder(), FakeStore(dense, []), reranker, top_k=5, candidates=10)
    # Distinct content -> both kept, never over-deduped.
    assert [r.chunk.id for r in retriever.retrieve("x")] == ["a", "b"]


def test_leading_duplicates_do_not_starve_top_k_after_rerank_cutoff() -> None:
    """12 near-identical chunks ahead of the unique ones must not collapse the result to 1.

    Dedup runs on the full fused pool *before* the rerank cutoff, so the distinct chunks
    below position 12 move up into the rerank pool instead of being dropped.
    """
    dups = [
        ScoredChunk(
            _tchunk(f"dup{i}", "the same repeated boilerplate header line for the guide"), 1.0
        )
        for i in range(12)
    ]
    uniques = [
        ScoredChunk(_tchunk(f"u{i}", f"unique distinct passage number {i} on subject {i}"), 0.5)
        for i in range(6)
    ]
    reranker = FakeReranker({})  # neutral: preserves the deduped pool order

    retriever = Retriever(
        FakeEmbedder(), FakeStore(dups + uniques, []), reranker,
        top_k=6, candidates=20, rerank_candidates=12,
    )
    ids = [r.chunk.id for r in retriever.retrieve("x")]
    assert len(ids) == 6                                   # not starved down to 1
    assert ids.count("dup0") == 1 and not any(i.startswith("dup") and i != "dup0" for i in ids)
    assert len([i for i in ids if i.startswith("u")]) == 5  # uniques backfilled the freed slots


def test_retrieve_respects_max_per_source() -> None:
    a1 = _tchunk("a1", "alpha content about the very first distinct topic", source="a.md")
    a2 = _tchunk("a2", "beta material covering a completely separate second topic", source="a.md")
    b1 = _tchunk("b1", "gamma notes on yet another unrelated third subject", source="b.md")
    dense = [ScoredChunk(a1, 0.9), ScoredChunk(a2, 0.85), ScoredChunk(b1, 0.7)]
    reranker = FakeReranker({a1.text: 3.0, a2.text: 2.0, b1.text: 1.0})

    retriever = Retriever(
        FakeEmbedder(), FakeStore(dense, []), reranker, top_k=2, candidates=10, max_per_source=1
    )
    ids = [r.chunk.id for r in retriever.retrieve("x")]
    assert ids == ["a1", "b1"]  # a2 skipped by the per-source cap; b1 (other source) fills in


def test_per_source_cap_backfills_from_distinct_below_rerank_cutoff() -> None:
    """A single-source rerank pool must not starve the cap — backfill from sources below it.

    12 distinct chunks from a.md fill the rerank pool; six other sources sit below the
    cutoff. With max_per_source=1 the result should still reach top_k by pulling them in.
    """
    a = [
        ScoredChunk(
            _tchunk(f"a{i}", f"alpha content number {i} on a distinct topic {i}", source="a.md"),
            1.0,
        )
        for i in range(12)
    ]
    others = [
        ScoredChunk(
            _tchunk(
                f"b{i}", f"other content number {i} on a distinct topic {i}", source=f"b{i}.md"
            ),
            0.5,
        )
        for i in range(6)
    ]
    reranker = FakeReranker({})  # neutral order

    retriever = Retriever(
        FakeEmbedder(), FakeStore(a + others, []), reranker,
        top_k=6, candidates=20, rerank_candidates=12, max_per_source=1,
    )
    ids = [r.chunk.id for r in retriever.retrieve("x")]
    assert len(ids) == 6                                   # not starved down to 1
    assert sum(1 for i in ids if i.startswith("a")) == 1   # a.md capped at 1
    assert len([i for i in ids if i.startswith("b")]) == 5  # backfilled from other sources


class _RecordingReranker(Reranker):
    """Records how many passages it was asked to score."""

    def __init__(self) -> None:
        self.scored_count: int | None = None

    def rerank(self, query, passages):
        self.scored_count = len(passages)
        return [float(len(passages) - i) for i in range(len(passages))]


def test_reranker_only_scores_the_top_fused_candidates() -> None:
    # 10 distinct candidates fused, but only the top 4 should reach the cross-encoder.
    dense = [
        ScoredChunk(
            _tchunk(f"c{i}", f"distinct passage number {i} about subject {i}"), 1.0 / (i + 1)
        )
        for i in range(10)
    ]
    reranker = _RecordingReranker()
    retriever = Retriever(
        FakeEmbedder(), FakeStore(dense, []), reranker,
        top_k=3, candidates=10, rerank_candidates=4,
    )
    results = retriever.retrieve("anything")

    assert reranker.scored_count == 4          # only the top-4 fused were reranked, not all 10
    assert len(results) == 3                    # top_k still returned from the reranked subset
    assert [r.chunk.id for r in results] == ["c0", "c1", "c2"]


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
