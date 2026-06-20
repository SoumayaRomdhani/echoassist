"""Dependency-light value types for the RAG layer.

Standard library only, so they can be imported anywhere without pulling in
fastembed / qdrant.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SparseVector:
    """A sparse (lexical) vector: parallel arrays of term indices and weights."""

    indices: list[int]
    values: list[float]


@dataclass(frozen=True, slots=True)
class Chunk:
    """A unit of indexed text plus its provenance (used for citations)."""

    id: str
    source: str           # document filename, e.g. "interview_process.md"
    text: str
    ordinal: int          # position of this chunk within its document
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    chunk: Chunk
    dense: list[float]
    sparse: SparseVector


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    """A retrieved chunk with its relevance score (and optional debug components)."""

    chunk: Chunk
    score: float
    components: dict = field(default_factory=dict)  # e.g. {"rrf": .., "rerank": ..}
