"""Vector store abstraction + Qdrant implementation (per-domain collection).

Each collection holds two named vectors per point: a ``dense`` semantic vector
and a ``bm25`` sparse lexical vector. They are searched independently; fusion
(RRF) happens in the retriever so the k constant is explicit (ARCHITECTURE.md §4).
"""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from src.rag.types import Chunk, EmbeddedChunk, ScoredChunk, SparseVector

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

log = logging.getLogger("echoassist.rag.vectorstore")

_DENSE = "dense"
_SPARSE = "bm25"
_POINT_NAMESPACE = uuid.UUID("a3f1c2d4-0000-4000-8000-000000000000")


class VectorStore(ABC):
    @abstractmethod
    def ensure_collection(self, dense_dim: int, *, recreate: bool = False) -> None: ...

    @abstractmethod
    def upsert(self, chunks: list[EmbeddedChunk]) -> None: ...

    @abstractmethod
    def search_dense(self, dense: list[float], limit: int) -> list[ScoredChunk]: ...

    @abstractmethod
    def search_sparse(self, sparse: SparseVector, limit: int) -> list[ScoredChunk]: ...

    @abstractmethod
    def delete_document(self, source: str) -> int:
        """Remove every chunk of ``source``; return how many points were deleted."""
        ...

    @abstractmethod
    def count(self) -> int: ...

    def chunk_counts(self) -> dict[str, int]:
        """Map each ``source`` to how many chunks it has (for the admin document list).

        Auxiliary/read-only; the default is empty so non-Qdrant stores need not implement it.
        """
        return {}


class QdrantVectorStore(VectorStore):
    """Qdrant store. ``location`` is an HTTP(S) URL (server), ``:memory:``, or a
    filesystem path (embedded local mode — same API, no server, persists to disk)."""

    def __init__(self, *, location: str, collection: str) -> None:
        from qdrant_client import QdrantClient

        if location.startswith(("http://", "https://")):
            # Generous timeout for the first (cold) write; skip the noisy client/server
            # minor-version compatibility warning.
            self._client: QdrantClient = QdrantClient(
                url=location, timeout=60, check_compatibility=False
            )
        elif location == ":memory:":
            self._client = QdrantClient(location=":memory:")
        else:
            self._client = QdrantClient(path=location)
        self._collection = collection

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        return str(uuid.uuid5(_POINT_NAMESPACE, chunk_id))

    @staticmethod
    def _to_chunk(payload: dict) -> Chunk:
        return Chunk(
            id=payload["chunk_id"],
            source=payload["source"],
            text=payload["text"],
            ordinal=payload["ordinal"],
            metadata=payload.get("metadata", {}),
        )

    def ensure_collection(self, dense_dim: int, *, recreate: bool = False) -> None:
        from qdrant_client import models

        exists = self._client.collection_exists(self._collection)
        if exists and not recreate:
            return
        if exists:
            self._client.delete_collection(self._collection)
        log.info("Creating Qdrant collection '%s' (dense_dim=%d)", self._collection, dense_dim)
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config={
                _DENSE: models.VectorParams(size=dense_dim, distance=models.Distance.COSINE)
            },
            # Modifier.IDF lets Qdrant apply the IDF term for FastEmbed's BM25 weights.
            sparse_vectors_config={
                _SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )

    def upsert(self, chunks: list[EmbeddedChunk]) -> None:
        from qdrant_client import models

        if not chunks:
            return
        points = [
            models.PointStruct(
                id=self._point_id(ec.chunk.id),
                vector={
                    _DENSE: ec.dense,
                    _SPARSE: models.SparseVector(
                        indices=ec.sparse.indices, values=ec.sparse.values
                    ),
                },
                payload={
                    "chunk_id": ec.chunk.id,
                    "source": ec.chunk.source,
                    "text": ec.chunk.text,
                    "ordinal": ec.chunk.ordinal,
                    "metadata": ec.chunk.metadata,
                },
            )
            for ec in chunks
        ]
        self._client.upsert(self._collection, points=points, wait=True)

    def search_dense(self, dense: list[float], limit: int) -> list[ScoredChunk]:
        result = self._client.query_points(
            self._collection, query=dense, using=_DENSE, limit=limit, with_payload=True
        )
        return [ScoredChunk(self._to_chunk(p.payload), float(p.score)) for p in result.points]

    def search_sparse(self, sparse: SparseVector, limit: int) -> list[ScoredChunk]:
        from qdrant_client import models

        result = self._client.query_points(
            self._collection,
            query=models.SparseVector(indices=sparse.indices, values=sparse.values),
            using=_SPARSE,
            limit=limit,
            with_payload=True,
        )
        return [ScoredChunk(self._to_chunk(p.payload), float(p.score)) for p in result.points]

    def delete_document(self, source: str) -> int:
        """Delete all points whose payload ``source`` matches (by filter, any ordinal).

        Deterministic point ids only overwrite same-ordinal chunks on re-upsert, so a
        shorter new version of a document would otherwise leave its higher-ordinal
        chunks orphaned — retrievable content from a file that no longer says it. This
        removes the whole document by source before the fresh chunks are written.
        """
        from qdrant_client import models

        if not self._client.collection_exists(self._collection):
            return 0
        selector = models.Filter(
            must=[models.FieldCondition(key="source", match=models.MatchValue(value=source))]
        )
        removed = self._client.count(self._collection, count_filter=selector, exact=True).count
        if removed:
            self._client.delete(
                self._collection,
                points_selector=models.FilterSelector(filter=selector),
                wait=True,
            )
        return removed

    def count(self) -> int:
        if not self._client.collection_exists(self._collection):
            return 0
        return self._client.count(self._collection, exact=True).count

    def chunk_counts(self) -> dict[str, int]:
        """Tally chunks per ``source`` by scrolling the collection's source payloads."""
        if not self._client.collection_exists(self._collection):
            return {}
        counts: dict[str, int] = {}
        offset = None
        while True:
            points, offset = self._client.scroll(
                self._collection,
                limit=256,
                offset=offset,
                with_payload=["source"],
                with_vectors=False,
            )
            for point in points:
                source = (point.payload or {}).get("source")
                if source:
                    counts[source] = counts.get(source, 0) + 1
            if offset is None:
                break
        return counts
