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
import re
import warnings
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Diverse, professional filler acknowledgements rotated on slow grounded turns (no human
# mimicry). Override globally with FILLER_PHRASES ("a | b | c") or per domain in the YAML.
_DEFAULT_FILLER_PHRASES = [
    "Let me check that.",
    "One moment while I check.",
    "I'll look that up.",
    "Let me verify that.",
    "Give me one second to check.",
]

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
    groq = "groq"


class TTSProviderName(StrEnum):
    kokoro = "kokoro"
    deepgram = "deepgram"
    cartesia = "cartesia"
    elevenlabs = "elevenlabs"


class EmbeddingsProviderName(StrEnum):
    fastembed = "fastembed"
    bge_m3 = "bge_m3"


class RerankerProviderName(StrEnum):
    fastembed = "fastembed"
    bge = "bge"
    voyage = "voyage"
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
    # Coalesce each sentence's TTS audio into one chunk before playback: gap-free on the
    # local sd.play mic transport, but raises TTFA (waits for the whole sentence). Off by
    # default = true streaming (yield the first audio chunk as soon as TTS returns it).
    tts_local_smoothing: bool = False
    # Low-latency TTS text chunking (domain-agnostic): flush LLM text to TTS on a comma once
    # it holds MIN_WORDS, after MAX_WORDS, or when it stalls MAX_DELAY_MS — so the agent starts
    # speaking a clause into a long reply. Off => fall back to whole-sentence streaming. A
    # domain YAML may override any value under `tts_stream:` (min_words/max_words/max_delay_ms).
    tts_stream_early_chunking: bool = True
    tts_stream_min_words: int = 3
    tts_stream_max_words: int = 10
    tts_stream_max_delay_ms: int = 400
    # Perceived-latency filler (professional, pre-synthesized): on a SLOW substantive RAG/tool
    # turn, if no real audio is ready within FILLER_DELAY_MS, play a short cached acknowledgement
    # ("Let me check that.") while the real answer keeps preparing in the background. Never used
    # for slot answers or meta replies. A domain YAML may override the phrase under `filler:`.
    filler_enabled: bool = True
    filler_delay_ms: int = 800
    filler_only_for_rag: bool = True
    filler_phrases: list[str] = _DEFAULT_FILLER_PHRASES   # rotated for variety
    domain: str = "screening"

    # --- STT: faster-whisper ---
    whisper_model: str = "base"
    whisper_device: str = "auto"          # auto | cpu | cuda
    whisper_compute_type: str = "int8"    # int8 | int8_float16 | float16 | float32
    whisper_language: str | None = None   # None => auto-detect
    whisper_beam_size: int = 5
    whisper_cpu_threads: int = 0          # 0 = library default (uses all physical cores)

    # --- STT: Deepgram (paid drop-in, Sprint 8 Path B) ---
    deepgram_api_key: str | None = None
    deepgram_model: str = "nova-2"        # nova-2 (broad multilingual) | nova-3 | ...
    deepgram_language: str | None = None  # None => Deepgram default; e.g. "fr", "en", "multi"

    # --- LLM: Gemini (default) ---
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"

    # --- LLM: Ollama ---
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen3"

    # --- LLM: Groq (free, fast cloud drop-in, Sprint 8 Path B) ---
    # Generous free tier (won't exhaust mid-interview like Gemini's). Default is
    # 70b: it does function calling reliably, which the app needs (RAG SEARCH_TOOL
    # in grounding.py, notes extraction in notes.py). The faster llama-3.1-8b-instant
    # often emits malformed tool calls (Groq 400 tool_use_failed) — fine only if you
    # don't use the tool paths.
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    # --- TTS: Kokoro ---
    kokoro_lang_code: str = "a"
    kokoro_voice: str = "af_heart"
    kokoro_speed: float = 1.0

    # --- TTS: Deepgram Aura (paid drop-in, Sprint 8 Path B) ---
    # Its own key, separate from STT's DEEPGRAM_API_KEY, so TTS credits/usage stay on a
    # distinct billing line; falls back to DEEPGRAM_API_KEY when unset. The voice is the
    # model; no separate voice id. List at https://developers.deepgram.com/docs/tts-models
    deepgram_tts_api_key: str | None = None
    deepgram_tts_model: str = "aura-2-thalia-en"   # e.g. aura-2-thalia-en | aura-2-asteria-en
    deepgram_tts_sample_rate: int = 24000          # 8000|16000|24000|32000|48000 (linear16)

    # --- TTS: Cartesia (paid drop-in, Sprint 8 Path B) ---
    cartesia_api_key: str | None = None
    cartesia_model: str = "sonic-2"
    cartesia_voice_id: str | None = None       # pick a voice id at https://play.cartesia.ai
    cartesia_sample_rate: int = 24000          # 8000|16000|22050|24000|44100|48000
    cartesia_language: str | None = None       # None => model default; e.g. "fr", "en"

    # --- TTS: ElevenLabs (paid drop-in, Sprint 8 Path B) ---
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None     # pick a voice id at https://elevenlabs.io
    elevenlabs_model: str = "eleven_turbo_v2_5"
    elevenlabs_sample_rate: int = 24000        # 8000|16000|22050|24000|44100|48000

    # --- RAG: embeddings / reranker / vector store (Sprint 2) ---
    embeddings_provider: EmbeddingsProviderName = EmbeddingsProviderName.fastembed
    reranker_provider: RerankerProviderName = RerankerProviderName.fastembed
    # Multilingual (FR/EN) by default. English-only swaps: dense BAAI/bge-small-en-v1.5,
    # reranker Xenova/ms-marco-MiniLM-L-6-v2 (lighter, but English-only).
    fastembed_dense_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    fastembed_sparse_model: str = "Qdrant/bm25"
    fastembed_rerank_model: str = "BAAI/bge-reranker-base"
    # Reranker: Voyage (paid drop-in) — offloads the CPU-heavy rerank to the cloud, the slow
    # step of a grounded turn on a small box. Set RERANKER_PROVIDER=voyage + VOYAGE_API_KEY.
    voyage_api_key: str | None = None
    voyage_rerank_model: str = "rerank-2.5"    # or rerank-2.5-lite | rerank-2 (all multilingual)
    qdrant_url: str = "http://localhost:6333"
    rag_top_k: int = 6          # chunks returned after rerank
    rag_candidates: int = 20    # candidates per modality before fusion/rerank
    rrf_k: int = 60             # Reciprocal Rank Fusion constant
    chunk_size: int = 1200
    chunk_overlap: int = 150
    # Reject knowledge-base uploads larger than this (bytes); the route enforces it
    # while streaming, so an oversized file never fully buffers in memory. Default 10 MiB.
    max_upload_bytes: int = 10 * 1024 * 1024

    # --- Conversation state (Sprint 3) ---
    state_backend: StateBackendName = StateBackendName.redis
    redis_url: str = "redis://localhost:6379"
    redis_key_prefix: str = "echoassist:call:"

    # --- Persistence (Sprint 4) ---
    database_url: str = "postgresql+psycopg://echoassist:echoassist@localhost:5433/echoassist"
    default_campaign: str = "Screening — default campaign"

    # --- Guardrails (Sprint 5) ---
    # Min reranker confidence to answer (else refuse). Calibrated on eval/grounding_eval:
    # the light multilingual reranker scores some legitimate FR questions as low as
    # ~0.06 while clearly off-topic queries score ~0.00, so 0.05 accepts FR and still
    # refuses off-topic. The FR margin is thin — a stronger reranker (bge-reranker-v2-m3)
    # would give more room (tracked multilingual follow-up).
    grounding_min_confidence: float = 0.05
    redact_pii: bool = True                # mask emails/phones before persistence

    # --- Latency optimizations (AMELIORATIONS.md — Axe 1) ---
    # Pre-synthesize the flow's deterministic lines (greeting, questions, close…) in
    # the background during the disclosure, so most agent turns spend ~0 ms on TTS
    # (L5). On by default and transparent — a cached line is byte-for-byte the inner
    # provider's output, only ready sooner.
    tts_cache_static: bool = True
    # Skip the model's "decide to search" tool round-trip on grounded answers: retrieve
    # first, then read the passages in one LLM call (−1 round-trip/turn, L3). Screening
    # Q&A always needs the knowledge base, so the tool hop is pure latency.
    grounding_retrieve_then_read: bool = True

    # --- Backend API (Sprint 6) ---
    api_host: str = "0.0.0.0"              # noqa: S104 — bind all interfaces (containerised service)
    api_port: int = 8000
    # Comma-separated allowed CORS origins for the dashboard ("*" = any, dev only).
    api_cors_origins: str = "*"
    # Shared-secret WS auth (Sprint 8), stand-in for ACTEEK SSO: when set, WebSocket
    # clients must present ?access_token=<this>. Unset => open (dev only).
    api_auth_token: str | None = None

    # --- Provider failover (Sprint 6, ARCHITECTURE.md §10 — never silent) ---
    # Secondary LLM tried when the primary fails (quota/transport). None = no failover.
    llm_fallback_provider: LLMProviderName | None = None

    # --- Observability (Sprint 6) ---
    # OpenTelemetry tracing. Spans are always created when enabled; how they leave the
    # process depends on the exporter: an OTLP endpoint (collector/Tempo) if set, else
    # the console when otel_console_export is on, else dropped (zero overhead, ready to wire).
    otel_enabled: bool = True
    otel_service_name: str = "echoassist-backend"
    otel_exporter_otlp_endpoint: str | None = None   # e.g. http://localhost:4318/v1/traces
    otel_console_export: bool = False                 # print spans to stdout (noisy; debug only)

    # --- Telephony: LiveKit + SIP (Sprint 8 Path B) ---
    # The same Transport over WebRTC/PSTN instead of the local mic. Used by
    # scripts/run_livekit.py; the rest of the pipeline is unchanged.
    livekit_url: str | None = None                    # wss://<you>.livekit.cloud | ws://localhost:7880
    livekit_api_key: str | None = None
    livekit_api_secret: str | None = None
    livekit_room: str = "echoassist"
    livekit_identity: str = "agent"

    # --- Generation / misc ---
    llm_temperature: float = 0.3
    llm_max_tokens: int = 512
    log_level: str = "INFO"

    @field_validator("filler_phrases", mode="before")
    @classmethod
    def _split_filler_phrases(cls, value: object) -> object:
        # Accept a friendly delimited env string ("a | b ; c") as well as a real list.
        if isinstance(value, str):
            return [p.strip() for p in re.split(r"[|;\n]", value) if p.strip()]
        return value

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
            cpu_threads=settings.whisper_cpu_threads,
        )
    if settings.stt_provider is STTProviderName.deepgram:
        from src.providers.stt.deepgram import DeepgramSTT

        return DeepgramSTT(
            api_key=settings.deepgram_api_key,
            model=settings.deepgram_model,
            language=settings.deepgram_language,
        )
    raise NotImplementedError(f"STT provider not yet implemented: {settings.stt_provider.value}")


def build_llm(
    settings: Settings | None = None, *, provider: LLMProviderName | None = None
) -> LLMProvider:
    """Build the active LLM, or a specific ``provider`` (used for failover)."""
    settings = settings or get_settings()
    provider = provider or settings.llm_provider
    if provider is LLMProviderName.gemini:
        from src.providers.llm.gemini import GeminiLLM

        return GeminiLLM(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    if provider is LLMProviderName.ollama:
        from src.providers.llm.ollama_local import OllamaLLM

        return OllamaLLM(
            host=settings.ollama_host,
            model=settings.ollama_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    if provider is LLMProviderName.groq:
        from src.providers.llm.groq import GroqLLM

        return GroqLLM(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    raise NotImplementedError(f"LLM provider not yet implemented: {provider.value}")


def build_llm_with_failover(settings: Settings | None = None) -> LLMProvider:
    """Build the primary LLM, wrapped with a fallback when ``llm_fallback_provider`` is set.

    Graceful degradation (ARCHITECTURE.md §10): on a primary failure (quota/transport)
    the secondary answers; the switch is logged, never silent.
    """
    settings = settings or get_settings()
    primary = build_llm(settings)
    fallback_name = settings.llm_fallback_provider
    if fallback_name is None or fallback_name is settings.llm_provider:
        return primary

    from src.providers.llm.failover import FailoverLLM

    fallback = build_llm(settings, provider=fallback_name)
    return FailoverLLM(primary, fallback)


def build_tts(settings: Settings | None = None) -> TTSProvider:
    settings = settings or get_settings()
    if settings.tts_provider is TTSProviderName.kokoro:
        from src.providers.tts.kokoro_local import KokoroTTS

        return KokoroTTS(
            lang_code=settings.kokoro_lang_code,
            voice=settings.kokoro_voice,
            speed=settings.kokoro_speed,
        )
    if settings.tts_provider is TTSProviderName.deepgram:
        from src.providers.tts.deepgram import DeepgramTTS

        return DeepgramTTS(
            api_key=settings.deepgram_tts_api_key or settings.deepgram_api_key,
            model=settings.deepgram_tts_model,
            sample_rate=settings.deepgram_tts_sample_rate,
        )
    if settings.tts_provider is TTSProviderName.cartesia:
        from src.providers.tts.cartesia import CartesiaTTS

        return CartesiaTTS(
            api_key=settings.cartesia_api_key,
            model=settings.cartesia_model,
            voice_id=settings.cartesia_voice_id,
            sample_rate=settings.cartesia_sample_rate,
            language=settings.cartesia_language,
        )
    if settings.tts_provider is TTSProviderName.elevenlabs:
        from src.providers.tts.elevenlabs import ElevenLabsTTS

        return ElevenLabsTTS(
            api_key=settings.elevenlabs_api_key,
            voice_id=settings.elevenlabs_voice_id,
            model=settings.elevenlabs_model,
            sample_rate=settings.elevenlabs_sample_rate,
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
    if settings.reranker_provider is RerankerProviderName.voyage:
        from src.rag.reranker import VoyageReranker

        return VoyageReranker(api_key=settings.voyage_api_key, model=settings.voyage_rerank_model)
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
