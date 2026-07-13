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


def diversify(
    scored: list[ScoredChunk],
    *,
    top_k: int,
    dedup_threshold: float,
    max_per_source: int,
) -> list[ScoredChunk]:
    """Pick the top ``top_k`` chunks best-first, skipping near-duplicates and (optionally)
    capping how many come from one source.

    Boilerplate that repeats across a document (page headers/footers, a section restated
    on every page) surfaces as several near-identical chunks that would otherwise fill the
    result set; dropping them backfills the freed slots with distinct, lower-ranked chunks.
    """
    selected: list[ScoredChunk] = []
    seen_tokens: list[set[str]] = []
    per_source: dict[str, int] = defaultdict(int)
    for candidate in scored:
        if len(selected) >= top_k:
            break
        if max_per_source and per_source[candidate.chunk.source] >= max_per_source:
            continue
        tokens = _tokens(candidate.chunk.text)
        if any(_jaccard(tokens, other) >= dedup_threshold for other in seen_tokens):
            continue
        selected.append(candidate)
        seen_tokens.append(tokens)
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
        rrf_k: int = 60,
        dedup_threshold: float = 0.8,
        max_per_source: int = 0,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._reranker = reranker
        self._top_k = top_k
        self._candidates = candidates
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
        ranked_ids = sorted(fused, key=fused.get, reverse=True)[: self._candidates]

        passages = [chunks[cid].text for cid in ranked_ids]
        try:
            with latency.span("rag_rerank_ms"):
                rerank_scores = self._reranker.rerank(query, passages)
        except Exception as exc:  # noqa: BLE001 — reranker resilience: never fail a live turn
            # A cloud reranker (e.g. Voyage free tier: 3 RPM) can rate-limit or go down. Rather
            # than error the whole turn — which surfaces to the caller as a refusal — degrade
            # gracefully to the RRF-fused order. ranked_ids is already sorted by RRF, so we keep
            # that ranking and use the RRF score for the grounding gate.
            log.warning("reranker failed (%s); falling back to RRF-fused order", exc)
            fallback = [
                ScoredChunk(
                    chunk=chunks[cid], score=fused[cid],
                    components={"rrf": fused[cid], "rerank": None},
                )
                for cid in ranked_ids  # already in RRF order
            ]
            return self._diversify(fallback)

        scored = [
            ScoredChunk(
                chunk=chunks[cid],
                score=rerank_scores[i],
                components={"rrf": fused[cid], "rerank": rerank_scores[i]},
            )
            for i, cid in enumerate(ranked_ids)
        ]
        scored.sort(key=lambda sc: sc.score, reverse=True)
        return self._diversify(scored)

    def _diversify(self, scored: list[ScoredChunk]) -> list[ScoredChunk]:
        return diversify(
            scored,
            top_k=self._top_k,
            dedup_threshold=self._dedup_threshold,
            max_per_source=self._max_per_source,
        )
