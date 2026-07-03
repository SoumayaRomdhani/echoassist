"""Cross-encoder reranking.

Reorders the fused candidate set by scoring each (query, passage) pair jointly —
more accurate than the bi-encoder similarity used for first-stage retrieval. The
architecture default is bge-reranker-v2-m3; the runnable default here is a small
MiniLM cross-encoder via FastEmbed (ONNX, CPU-friendly).
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from src.providers.errors import ProviderConfigError, ProviderError, ProviderQuotaError

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


def _relevance_to_logit(p: float) -> float:
    """Convert a 0..1 relevance to a logit (inverse sigmoid).

    Rerankers return a *logit*: the grounding gate (guardrails.confidence) applies
    ``sigmoid`` to get a 0..1 confidence. Voyage returns a 0..1 relevance directly, so we
    invert it — then ``confidence(score)`` recovers Voyage's relevance and the gate keeps a
    consistent 0..1 scale (and sorting stays correct, since the logit is monotonic in ``p``).
    Clamped to avoid ±inf at the 0/1 extremes.
    """
    p = min(max(p, 1e-6), 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def _to_provider_error(exc: Exception) -> ProviderError:
    """Map a Voyage/transport error to a clean ProviderError (no raw traceback)."""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "auth" in name or "unauthor" in text or "invalid api key" in text or "api key" in text:
        return ProviderConfigError(
            "Voyage rejected the API key. Check VOYAGE_API_KEY in backend/.env "
            "(get one at https://dashboard.voyageai.com), or set RERANKER_PROVIDER=fastembed."
        )
    if "ratelimit" in name or "rate limit" in text or "quota" in text or "429" in text:
        return ProviderQuotaError(
            "Voyage rate limit / quota exceeded. Wait and retry, or fall back with "
            "RERANKER_PROVIDER=fastembed in backend/.env."
        )
    return ProviderError(f"Voyage rerank error: {str(exc)[:200]} — please retry in a moment.")


class VoyageReranker(Reranker):
    """Voyage AI reranking (paid drop-in) — offloads the CPU-heavy rerank to the cloud.

    A config-only swap for the open-source default (``fastembed``): set
    ``RERANKER_PROVIDER=voyage`` + ``VOYAGE_API_KEY`` and nothing else changes. On a small
    box the local cross-encoder is the slow step of a grounded turn; Voyage's hosted
    reranker returns in ~one network round-trip instead.

    Voyage returns a 0..1 relevance per passage, possibly reordered; we map each score back
    to the input position and return its logit (see :func:`_relevance_to_logit`) so the
    grounding gate is unchanged. **Calibration note:** ``grounding_min_confidence`` (0.05)
    was tuned for the FastEmbed reranker's score distribution — with Voyage, ``confidence``
    equals Voyage's relevance, so re-tune the threshold if you see over/under-refusal.

    The SDK is imported lazily, only after the API-key check, so importing this module
    never requires ``voyageai`` to be installed.
    """

    def __init__(self, *, api_key: str | None, model: str = "rerank-2.5") -> None:
        if not api_key:
            raise ProviderConfigError(
                "VOYAGE_API_KEY is not set. Get a key at https://dashboard.voyageai.com "
                "and add it to backend/.env (or set RERANKER_PROVIDER=fastembed for the default)."
            )
        import voyageai

        self._client = voyageai.Client(api_key=api_key)
        self._model = model

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        try:
            result = self._client.rerank(query, passages, model=self._model, top_k=None)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — map any SDK/transport error to a clean ProviderError
            raise _to_provider_error(exc) from exc
        # A passage Voyage doesn't score stays at a low-confidence logit (won't pass the gate).
        scores = [_relevance_to_logit(0.0)] * len(passages)
        for item in result.results:
            scores[item.index] = _relevance_to_logit(float(item.relevance_score))
        return scores
