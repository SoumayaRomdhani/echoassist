"""Cross-encoder reranking.

Reorders the fused candidate set by scoring each (query, passage) pair jointly —
more accurate than the bi-encoder similarity used for first-stage retrieval. The
architecture default is bge-reranker-v2-m3; the runnable default here is a small
MiniLM cross-encoder via FastEmbed (ONNX, CPU-friendly).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastembed.rerank.cross_encoder import TextCrossEncoder

log = logging.getLogger("echoassist.rag.reranker")


class Reranker(ABC):
    @abstractmethod
    def rerank(self, query: str, passages: list[str]) -> list[float]:
        """Return a relevance score per passage (higher = more relevant)."""
        raise NotImplementedError


class NoOpReranker(Reranker):
    """Passes the fused order through unchanged (keeps RRF ranking)."""

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        # Descending scores preserve the incoming order after a stable sort.
        return [float(len(passages) - i) for i in range(len(passages))]


class FastEmbedReranker(Reranker):
    def __init__(self, *, model: str = "Xenova/ms-marco-MiniLM-L-6-v2") -> None:
        self._model_name = model
        self._model: TextCrossEncoder | None = None

    def _ensure_model(self) -> TextCrossEncoder:
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            log.info("Loading FastEmbed reranker=%s", self._model_name)
            self._model = TextCrossEncoder(self._model_name)
        return self._model

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return [float(score) for score in self._ensure_model().rerank(query, passages)]
