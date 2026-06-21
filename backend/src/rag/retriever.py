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
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from src.rag.embeddings import HybridEmbedder
from src.rag.reranker import Reranker
from src.rag.types import Chunk, ScoredChunk
from src.rag.vectorstore import VectorStore

log = logging.getLogger("echoassist.rag.retriever")


def reciprocal_rank_fusion(rankings: list[list[str]], *, k: int = 60) -> dict[str, float]:
    """Fuse ranked id lists into a combined score map. Higher score = better."""
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] += 1.0 / (k + rank + 1)
    return dict(scores)


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
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._reranker = reranker
        self._top_k = top_k
        self._candidates = candidates
        self._rrf_k = rrf_k

    def retrieve(self, query: str) -> list[ScoredChunk]:
        dense, sparse = self._embedder.embed_query(query)
        # Dense and sparse searches are independent — run them concurrently.
        with ThreadPoolExecutor(max_workers=2) as pool:
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
        rerank_scores = self._reranker.rerank(query, passages)

        scored = [
            ScoredChunk(
                chunk=chunks[cid],
                score=rerank_scores[i],
                components={"rrf": fused[cid], "rerank": rerank_scores[i]},
            )
            for i, cid in enumerate(ranked_ids)
        ]
        scored.sort(key=lambda sc: sc.score, reverse=True)
        return scored[: self._top_k]
