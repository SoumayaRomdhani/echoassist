"""Hybrid retriever: dense + sparse search -> RRF fusion -> cross-encoder rerank.

Pipeline (ARCHITECTURE.md §4, ROADMAP §Sprint 2):
  1. embed the query (dense + sparse)
  2. search each modality for ``candidates`` hits
  3. fuse the two rankings with Reciprocal Rank Fusion (k=60)
  4. rerank the fused candidates with a cross-encoder
  5. return the top ``top_k`` chunks (with source for citations)
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from src.observability import latency
from src.observability.tracing import span
from src.rag.embeddings import HybridEmbedder
from src.rag.reranker import Reranker
from src.rag.types import Chunk, ScoredChunk
from src.rag.vectorstore import VectorStore

log = logging.getLogger("echoassist.rag.retriever")

_WORD = re.compile(r"\w+")


def reciprocal_rank_fusion(rankings: list[list[str]], *, k: int = 60) -> dict[str, float]:
    """Fuse ranked id lists into a combined score map. Higher score = better."""
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] += 1.0 / (k + rank + 1)
    return dict(scores)


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedup_near_duplicates(
    scored: list[ScoredChunk], *, threshold: float
) -> list[ScoredChunk]:
    """Drop chunks whose word-overlap (Jaccard) with an already-kept one is >= ``threshold``.

    Order is preserved. Run this on the *whole* fused candidate pool **before** the rerank
    cutoff, so repeated boilerplate (page headers/footers) can't fill the head of the list
    and starve the rerank pool of distinct chunks — the distinct ones below simply move up.
    """
    kept: list[ScoredChunk] = []
    seen_tokens: list[set[str]] = []
    for candidate in scored:
        tokens = _tokens(candidate.chunk.text)
        if any(_jaccard(tokens, other) >= threshold for other in seen_tokens):
            continue
        kept.append(candidate)
        seen_tokens.append(tokens)
    return kept


def cap_per_source(
    scored: list[ScoredChunk], *, top_k: int, max_per_source: int
) -> list[ScoredChunk]:
    """Take the top ``top_k`` chunks, optionally capping how many come from one source."""
    selected: list[ScoredChunk] = []
    per_source: dict[str, int] = defaultdict(int)
    for candidate in scored:
        if len(selected) >= top_k:
            break
        if max_per_source and per_source[candidate.chunk.source] >= max_per_source:
            continue
        selected.append(candidate)
        per_source[candidate.chunk.source] += 1
    return selected


class Retriever:
    def __init__(
        self,
        embedder: HybridEmbedder,
        store: VectorStore,
        reranker: Reranker,
        *,
        top_k: int = 6,
        candidates: int = 20,
        rerank_candidates: int = 12,
        rrf_k: int = 60,
        dedup_threshold: float = 0.8,
        max_per_source: int = 0,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._reranker = reranker
        self._top_k = top_k
        self._candidates = candidates
        # The cross-encoder is the CPU-heavy step; rerank only the top fused candidates
        # (not all ``candidates``) to cut latency while keeping fusion's recall breadth.
        self._rerank_candidates = rerank_candidates
        self._rrf_k = rrf_k
        self._dedup_threshold = dedup_threshold  # Jaccard >= this => near-duplicate (>1 disables)
        self._max_per_source = max_per_source    # 0 => no per-source cap

    def retrieve(self, query: str) -> list[ScoredChunk]:
        # Stage span — never put the query text in attributes (it can carry PII).
        with span("rag.retrieve", **{"rag.top_k": self._top_k}):
            return self._retrieve(query)

    def _retrieve(self, query: str) -> list[ScoredChunk]:
        with latency.span("rag_embed_ms"):
            dense, sparse = self._embedder.embed_query(query)
        # Dense and sparse searches are independent — run them concurrently.
        with latency.span("rag_qdrant_ms"), ThreadPoolExecutor(max_workers=2) as pool:
            dense_future = pool.submit(self._store.search_dense, dense, self._candidates)
            sparse_future = pool.submit(self._store.search_sparse, sparse, self._candidates)
            dense_hits = dense_future.result()
            sparse_hits = sparse_future.result()

        chunks: dict[str, Chunk] = {}
        for hit in (*dense_hits, *sparse_hits):
            chunks[hit.chunk.id] = hit.chunk
        if not chunks:
            log.info("retrieve: no candidates for query=%r", query)
            return []

        fused = reciprocal_rank_fusion(
            [[h.chunk.id for h in dense_hits], [h.chunk.id for h in sparse_hits]],
            k=self._rrf_k,
        )
        fused_ranked = sorted(fused, key=fused.get, reverse=True)[: self._candidates]
        # Dedup the WHOLE fused pool before the rerank cutoff, so leading duplicates don't
        # starve the rerank pool — distinct lower-ranked chunks move up to fill the freed
        # slots. Only then take the top few distinct candidates for the CPU-heavy rerank.
        distinct = dedup_near_duplicates(
            [
                ScoredChunk(
                    chunk=chunks[cid], score=fused[cid],
                    components={"rrf": fused[cid], "rerank": None},
                )
                for cid in fused_ranked
            ],
            threshold=self._dedup_threshold,
        )
        rerank_pool = distinct[: self._rerank_candidates]

        passages = [sc.chunk.text for sc in rerank_pool]
        try:
            with latency.span("rag_rerank_ms"):
                rerank_scores = self._reranker.rerank(query, passages)
        except Exception as exc:  # noqa: BLE001 — reranker resilience: never fail a live turn
            # A cloud reranker (e.g. Voyage free tier: 3 RPM) can rate-limit or go down. Rather
            # than error the whole turn — which surfaces to the caller as a refusal — degrade
            # gracefully to the (deduped) RRF-fused order and use the RRF score for the gate.
            log.warning("reranker failed (%s); falling back to RRF-fused order", exc)
            return cap_per_source(
                distinct, top_k=self._top_k, max_per_source=self._max_per_source
            )

        scored = [
            ScoredChunk(
                chunk=sc.chunk,
                score=rerank_scores[i],
                components={"rrf": sc.components["rrf"], "rerank": rerank_scores[i]},
            )
            for i, sc in enumerate(rerank_pool)
        ]
        scored.sort(key=lambda sc: sc.score, reverse=True)
        # The reranked chunks come first (best signal); the remaining distinct candidates
        # below the rerank cutoff follow (RRF order) as backfill, so the per-source cap can
        # reach other sources instead of starving the result when the pool is single-source.
        backfill = distinct[self._rerank_candidates :]
        return cap_per_source(
            scored + backfill, top_k=self._top_k, max_per_source=self._max_per_source
        )
