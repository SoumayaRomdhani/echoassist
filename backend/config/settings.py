"""Runtime configuration and the provider/domain factory.

This module is the single source of truth for configuration. Business logic
never reads environment variables directly and never imports a vendor SDK; it
asks here for a provider via :func:`build_stt` / :func:`build_llm` /
:func:`build_tts`. Switching a provider is therefore a one-line change in
``.env`` (ARCHITECTURE.md §2, §5).

Provider implementations are imported lazily inside the factory functions so
that code which only needs configuration (the API layer, tests, the setup
doctor) does not pull heavy ML dependencies into its import path.
"""

from __future__ import annotations

import os
import warnings
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_settings import BaseSettings, SettingsConfigDict

# Quiet a noisy multi-line Hugging Face warning on Windows (no symlink support).
# Set here because settings is imported before any model library loads.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# FastEmbed pooling notice — we pin fastembed (pyproject) so behaviour is fixed.
warnings.filterwarnings("ignore", message=".*mean pooling.*")

if TYPE_CHECKING:  # avoid importing provider modules (and their heavy deps) at module load
    from sqlalchemy.ext.asyncio import AsyncEngine

    from src.agent.state import StateStore
    from src.providers.llm.base import LLMProvider
    from src.providers.stt.base import STTProvider
    from src.providers.tts.base import TTSProvider
    from src.rag.embeddings import HybridEmbedder
    from src.rag.reranker import Reranker
    from src.rag.retriever import Retriever
    from src.rag.vectorstore import VectorStore

# Anchor all paths to the backend directory so behaviour is independent of CWD.
BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
CONFIG_DIR = BACKEND_DIR / "config"


class STTProviderName(StrEnum):
    whisper_local = "whisper_local"
    deepgram = "deepgram"


class LLMProviderName(StrEnum):
    gemini = "gemini"
    ollama = "ollama"
    claude = "claude"


class TTSProviderName(StrEnum):
    kokoro = "kokoro"
    cartesia = "cartesia"
    elevenlabs = "elevenlabs"


class EmbeddingsProviderName(StrEnum):
    fastembed = "fastembed"
    bge_m3 = "bge_m3"


class RerankerProviderName(StrEnum):
    fastembed = "fastembed"
    bge = "bge"
    none = "none"


class StateBackendName(StrEnum):
    redis = "redis"
    memory = "memory"


class Settings(BaseSettings):
    """Environment-driven settings. Field ``foo_bar`` maps to env var ``FOO_BAR``."""

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Active selection (ARCHITECTURE.md §5) ---
    # Open-source by default (ARCHITECTURE.md §2): the shipped default LLM is
    # Ollama. Set LLM_PROVIDER=gemini in .env for the easiest start without a GPU.
    stt_provider: STTProviderName = STTProviderName.whisper_local
    llm_provider: LLMProviderName = LLMProviderName.ollama
    tts_provider: TTSProviderName = TTSProviderName.kokoro
    domain: str = "screening"

    # --- STT: faster-whisper ---
    whisper_model: str = "base"
    whisper_device: str = "auto"          # auto | cpu | cuda
    whisper_compute_type: str = "int8"    # int8 | int8_float16 | float16 | float32
    whisper_language: str | None = None   # None => auto-detect
    whisper_beam_size: int = 5

    # --- LLM: Gemini (default) ---
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"

    # --- LLM: Ollama ---
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen3"

    # --- TTS: Kokoro ---
    kokoro_lang_code: str = "a"
    kokoro_voice: str = "af_heart"
    kokoro_speed: float = 1.0

    # --- RAG: embeddings / reranker / vector store (Sprint 2) ---
    embeddings_provider: EmbeddingsProviderName = EmbeddingsProviderName.fastembed
    reranker_provider: RerankerProviderName = RerankerProviderName.fastembed
    # Multilingual (FR/EN) by default. English-only swaps: dense BAAI/bge-small-en-v1.5,
    # reranker Xenova/ms-marco-MiniLM-L-6-v2 (lighter, but English-only).
    fastembed_dense_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    fastembed_sparse_model: str = "Qdrant/bm25"
    fastembed_rerank_model: str = "BAAI/bge-reranker-base"
    qdrant_url: str = "http://localhost:6333"
    rag_top_k: int = 6          # chunks returned after rerank
    rag_candidates: int = 20    # candidates per modality before fusion/rerank
    rrf_k: int = 60             # Reciprocal Rank Fusion constant
    chunk_size: int = 1200
    chunk_overlap: int = 150

    # --- Conversation state (Sprint 3) ---
    state_backend: StateBackendName = StateBackendName.redis
    redis_url: str = "redis://localhost:6379"
    redis_key_prefix: str = "echoassist:call:"

    # --- Persistence (Sprint 4) ---
    database_url: str = "postgresql+psycopg://echoassist:echoassist@localhost:5433/echoassist"
    default_campaign: str = "Screening — default campaign"

    # --- Generation / misc ---
    llm_temperature: float = 0.3
    llm_max_tokens: int = 512
    log_level: str = "INFO"

    @property
    def backend_dir(self) -> Path:
        return BACKEND_DIR

    @property
    def data_dir(self) -> Path:
        return DATA_DIR

    @property
    def config_dir(self) -> Path:
        return CONFIG_DIR


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()


# --------------------------------------------------------------------------- #
# Provider factory                                                            #
# --------------------------------------------------------------------------- #
def build_stt(settings: Settings | None = None) -> STTProvider:
    settings = settings or get_settings()
    if settings.stt_provider is STTProviderName.whisper_local:
        from src.providers.stt.whisper_local import WhisperLocalSTT

        return WhisperLocalSTT(
            model_size=settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            language=settings.whisper_language,
            beam_size=settings.whisper_beam_size,
        )
    raise NotImplementedError(f"STT provider not yet implemented: {settings.stt_provider.value}")


def build_llm(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    if settings.llm_provider is LLMProviderName.gemini:
        from src.providers.llm.gemini import GeminiLLM

        return GeminiLLM(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    if settings.llm_provider is LLMProviderName.ollama:
        from src.providers.llm.ollama_local import OllamaLLM

        return OllamaLLM(
            host=settings.ollama_host,
            model=settings.ollama_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    raise NotImplementedError(f"LLM provider not yet implemented: {settings.llm_provider.value}")


def build_tts(settings: Settings | None = None) -> TTSProvider:
    settings = settings or get_settings()
    if settings.tts_provider is TTSProviderName.kokoro:
        from src.providers.tts.kokoro_local import KokoroTTS

        return KokoroTTS(
            lang_code=settings.kokoro_lang_code,
            voice=settings.kokoro_voice,
            speed=settings.kokoro_speed,
        )
    raise NotImplementedError(f"TTS provider not yet implemented: {settings.tts_provider.value}")


# --- RAG factory ----------------------------------------------------------- #
def build_embedder(settings: Settings | None = None) -> HybridEmbedder:
    settings = settings or get_settings()
    if settings.embeddings_provider is EmbeddingsProviderName.fastembed:
        from src.rag.embeddings import FastEmbedHybrid

        return FastEmbedHybrid(
            dense_model=settings.fastembed_dense_model,
            sparse_model=settings.fastembed_sparse_model,
        )
    raise NotImplementedError(
        f"Embeddings provider not yet implemented: {settings.embeddings_provider.value}"
    )


def build_reranker(settings: Settings | None = None) -> Reranker:
    settings = settings or get_settings()
    if settings.reranker_provider is RerankerProviderName.fastembed:
        from src.rag.reranker import FastEmbedReranker

        return FastEmbedReranker(model=settings.fastembed_rerank_model)
    if settings.reranker_provider is RerankerProviderName.none:
        from src.rag.reranker import NoOpReranker

        return NoOpReranker()
    raise NotImplementedError(
        f"Reranker provider not yet implemented: {settings.reranker_provider.value}"
    )


def build_vector_store(
    settings: Settings | None = None, *, domain: str | None = None
) -> VectorStore:
    settings = settings or get_settings()
    from src.rag.vectorstore import QdrantVectorStore

    # QDRANT_URL=local -> embedded on-disk Qdrant (no server); otherwise an HTTP URL.
    location = settings.qdrant_url
    if location == "local":
        location = str(settings.data_dir / "qdrant_local")
    return QdrantVectorStore(location=location, collection=domain or settings.domain)


def build_retriever(settings: Settings | None = None, *, domain: str | None = None) -> Retriever:
    settings = settings or get_settings()
    from src.rag.retriever import Retriever

    return Retriever(
        build_embedder(settings),
        build_vector_store(settings, domain=domain),
        build_reranker(settings),
        top_k=settings.rag_top_k,
        candidates=settings.rag_candidates,
        rrf_k=settings.rrf_k,
    )


def build_state_store(settings: Settings | None = None) -> StateStore:
    settings = settings or get_settings()
    if settings.state_backend is StateBackendName.redis:
        from src.agent.state import RedisStateStore

        return RedisStateStore(url=settings.redis_url, key_prefix=settings.redis_key_prefix)
    from src.agent.state import InMemoryStateStore

    return InMemoryStateStore()


def build_engine(settings: Settings | None = None) -> AsyncEngine:
    settings = settings or get_settings()
    from src.storage.db import make_engine

    return make_engine(settings.database_url)
