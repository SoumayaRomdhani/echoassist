"""Hybrid (dense + sparse) embeddings.

The interface returns both a dense semantic vector and a sparse lexical vector
per text, which the retriever searches separately before RRF fusion. BGE-M3 is
the architecture's open-source default; the runnable default here is FastEmbed
(small ONNX models, CPU-friendly). Switching is a config change (ARCHITECTURE.md
§2: open-source default, swappable).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from src.rag.types import SparseVector

if TYPE_CHECKING:
    from fastembed import SparseTextEmbedding, TextEmbedding

log = logging.getLogger("echoassist.rag.embeddings")


class HybridEmbedder(ABC):
    """Produces a (dense, sparse) pair per text."""

    @property
    @abstractmethod
    def dense_dim(self) -> int:
        """Dimensionality of the dense vectors (for the vector-store schema)."""
        raise NotImplementedError

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[tuple[list[float], SparseVector]]:
        """Embed passages for indexing."""
        raise NotImplementedError

    @abstractmethod
    def embed_query(self, text: str) -> tuple[list[float], SparseVector]:
        """Embed a single search query."""
        raise NotImplementedError


class FastEmbedHybrid(HybridEmbedder):
    """Dense + BM25 sparse embeddings via FastEmbed (ONNX, runs on CPU)."""

    def __init__(
        self,
        *,
        dense_model: str = "BAAI/bge-small-en-v1.5",
        sparse_model: str = "Qdrant/bm25",
    ) -> None:
        self._dense_model_name = dense_model
        self._sparse_model_name = sparse_model
        self._dense: TextEmbedding | None = None
        self._sparse: SparseTextEmbedding | None = None
        self._dense_dim: int | None = None

    # --- lazy model loading ------------------------------------------------
    def _ensure_models(self) -> tuple[TextEmbedding, SparseTextEmbedding]:
        if self._dense is None or self._sparse is None:
            from fastembed import SparseTextEmbedding, TextEmbedding

            log.info(
                "Loading FastEmbed dense=%s sparse=%s",
                self._dense_model_name,
                self._sparse_model_name,
            )
            self._dense = TextEmbedding(self._dense_model_name)
            self._sparse = SparseTextEmbedding(self._sparse_model_name)
        return self._dense, self._sparse

    @staticmethod
    def _to_sparse(embedding) -> SparseVector:
        return SparseVector(
            indices=[int(i) for i in embedding.indices],
            values=[float(v) for v in embedding.values],
        )

    @property
    def dense_dim(self) -> int:
        if self._dense_dim is None:
            self._dense_dim = len(self.embed_query("dimension probe")[0])
        return self._dense_dim

    # --- embedding ---------------------------------------------------------
    def embed_documents(self, texts: list[str]) -> list[tuple[list[float], SparseVector]]:
        if not texts:
            return []
        dense_model, sparse_model = self._ensure_models()
        dense = [vec.tolist() for vec in dense_model.embed(texts)]
        sparse = [self._to_sparse(s) for s in sparse_model.embed(texts)]
        return list(zip(dense, sparse, strict=True))

    def embed_query(self, text: str) -> tuple[list[float], SparseVector]:
        dense_model, sparse_model = self._ensure_models()
        # FastEmbed applies model-specific query handling (bge query prefix, BM25 IDF).
        dense = next(iter(dense_model.query_embed(text))).tolist()
        sparse = self._to_sparse(next(iter(sparse_model.query_embed(text))))
        return dense, sparse
