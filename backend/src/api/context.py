"""Application context: shared resources built once and reused across requests.

The Sprint 6 heads-up is enforced here: providers are created **once** (never per
request) and the non-reentrant CPU models (Whisper/Kokoro) are shared behind a
single lock so concurrent calls serialize their model work. The LLM is shared as
a network client and wrapped with failover. Everything heavy is built lazily, so
the data-serving API (and the test suite) starts without loading a model.

``build_resources`` wires the production context; tests build an
:class:`AppResources` with fakes and pass it to :func:`src.api.app.create_app`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from config.settings import (
    Settings,
    build_embedder,
    build_engine,
    build_llm,
    build_retriever,
    build_state_store,
    build_stt,
    build_tts,
    build_vector_store,
    get_settings,
)
from src.agent.dialogue import DialogueManager, LLMTurnClassifier
from src.agent.domain import DomainConfig, load_domain_config
from src.agent.finalize import FinalizedCall, finalize_call
from src.agent.grounding import GroundedResponder
from src.agent.notes import load_notes_schema
from src.agent.orchestrator import VoicePipeline
from src.agent.state import ConversationState, StateStore
from src.api.events import CallEventHub
from src.api.ingest_service import IngestService, default_indexer
from src.api.runner import AudioInput, CallEngine, CallManager, current_call_id
from src.audio.io import stream_wav
from src.providers.concurrency import SerializedSTT, SerializedTTS
from src.providers.errors import ProviderError
from src.providers.llm.base import LLMProvider
from src.providers.stt.base import STTProvider
from src.providers.tts.base import TTSProvider
from src.storage.db import make_sessionmaker

log = logging.getLogger("echoassist.api.context")

# Caller audio replayed for a server-started call (same clips as run_interview).
_CONSENT_CLIP = "sample_consent.wav"
_ANSWER_CLIPS = (
    "interview_question.wav",   # a mid-question detour (grounded Q&A)
    "interview_experience.wav",
    "interview_stack.wav",
    "interview_availability.wav",
    "interview_remote.wav",
    "interview_salary.wav",
    "interview_done.wav",
)


class ProviderPool:
    """Builds and caches the shared, expensive providers (lazily)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model_lock = asyncio.Lock()   # serializes all CPU model work (STT/TTS/ingest)
        self._llm: LLMProvider | None = None
        self._stt: STTProvider | None = None
        self._tts: TTSProvider | None = None
        self._embedder: object | None = None
        self._retrievers: dict[str, object] = {}
        self._on_degrade = None

    @property
    def model_lock(self) -> asyncio.Lock:
        return self._model_lock

    def set_degrade_hook(self, hook) -> None:
        self._on_degrade = hook

    def llm(self) -> LLMProvider:
        if self._llm is None:
            primary = build_llm(self._settings)
            fallback = self._settings.llm_fallback_provider
            if fallback is not None and fallback is not self._settings.llm_provider:
                from src.providers.llm.failover import FailoverLLM

                self._llm = FailoverLLM(
                    primary,
                    build_llm(self._settings, provider=fallback),
                    on_degrade=self._on_degrade,
                )
                log.info("LLM failover enabled: %s -> %s",
                         self._settings.llm_provider.value, fallback.value)
            else:
                self._llm = primary
        return self._llm

    def stt(self) -> STTProvider:
        if self._stt is None:
            self._stt = SerializedSTT(build_stt(self._settings), self._model_lock)
        return self._stt

    def tts(self) -> TTSProvider:
        if self._tts is None:
            self._tts = SerializedTTS(build_tts(self._settings), self._model_lock)
        return self._tts

    def retriever(self, domain: str):
        if domain not in self._retrievers:
            self._retrievers[domain] = build_retriever(self._settings, domain=domain)
        return self._retrievers[domain]

    def embedder(self):
        if self._embedder is None:
            self._embedder = build_embedder(self._settings)
        return self._embedder

    def vector_store(self, domain: str):
        return build_vector_store(self._settings, domain=domain)

    async def aclose(self) -> None:
        for provider in (self._llm, self._stt, self._tts):
            if provider is not None:
                await provider.aclose()


class DefaultCallEngine(CallEngine):
    """Production call engine: real (shared) providers + replayed audio."""

    def __init__(self, settings: Settings, pool: ProviderPool) -> None:
        self._settings = settings
        self._pool = pool
        self._config_dir = settings.config_dir
        self._audio_dir = settings.data_dir / "test_audio"

    def default_domain(self) -> str:
        return self._settings.domain

    def load_domain(self, domain: str) -> DomainConfig:
        return load_domain_config(domain, self._config_dir)

    def build_pipeline(
        self, domain: str, domain_cfg: DomainConfig, state: ConversationState, store: StateStore
    ) -> VoicePipeline:
        llm = self._pool.llm()
        responder = GroundedResponder(
            llm,
            self._pool.retriever(domain),
            system_prompt=domain_cfg.system_prompt,
            min_confidence=self._settings.grounding_min_confidence,
        )
        dialogue = DialogueManager(
            classifier=LLMTurnClassifier(llm),
            responder=responder,
            domain=domain_cfg,
            state=state,
            store=store,
            redact=self._settings.redact_pii,
        )
        return VoicePipeline(self._pool.stt(), llm, self._pool.tts(), domain_cfg, dialogue=dialogue)

    def consent_audio(self, *, consent: bool) -> AudioInput:
        # The bundled clip consents; simulating a refusal needs a "no" clip (tests do this).
        if not consent:
            log.warning("consent=False requested but no refusal clip bundled; using consent clip")
        return stream_wav(self._audio_dir / _CONSENT_CLIP, realtime=False)

    def answer_audios(self, domain_cfg: DomainConfig) -> list[AudioInput]:
        return [stream_wav(self._audio_dir / name, realtime=False) for name in _ANSWER_CLIPS]

    async def finalize(
        self, session, state: ConversationState, *, domain: str, campaign: str
    ) -> FinalizedCall:
        schema = load_notes_schema(domain, self._config_dir)
        return await finalize_call(
            session, state, llm=self._pool.llm(), schema=schema,
            campaign_name=campaign, domain=domain, redact=self._settings.redact_pii,
        )


@dataclass
class AppResources:
    """Everything the API process shares. Attached to ``app.state.resources``."""

    settings: Settings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker
    state_store: StateStore
    hub: CallEventHub
    call_manager: CallManager
    ingest_service: IngestService
    pool: ProviderPool | None = None

    async def aclose(self) -> None:
        await self.call_manager.aclose()
        if self.pool is not None:
            await self.pool.aclose()
        await self.state_store.aclose()
        await self.engine.dispose()


def _degrade_hook(hub: CallEventHub):
    """Surface a provider failover on the live event stream for the current call."""

    def hook(failed: str, nxt: str | None, exc: ProviderError) -> None:
        call_id = current_call_id.get()
        if call_id is not None:
            hub.publish(call_id, "degraded", {"from": failed, "to": nxt, "reason": str(exc)})

    return hook


def build_resources(settings: Settings | None = None) -> AppResources:
    """Assemble the production application context (heavy providers stay lazy)."""
    settings = settings or get_settings()
    engine = build_engine(settings)
    sessionmaker = make_sessionmaker(engine)
    state_store = build_state_store(settings)
    hub = CallEventHub()

    pool = ProviderPool(settings)
    pool.set_degrade_hook(_degrade_hook(hub))

    call_manager = CallManager(
        engine=DefaultCallEngine(settings, pool),
        sessionmaker=sessionmaker,
        state_store=state_store,
        hub=hub,
        default_campaign=settings.default_campaign,
    )
    ingest_service = IngestService(
        data_dir=settings.data_dir,
        indexer=default_indexer(
            pool.embedder, pool.vector_store,
            chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap,
        ),
        lock=pool.model_lock,
    )
    return AppResources(
        settings=settings,
        engine=engine,
        sessionmaker=sessionmaker,
        state_store=state_store,
        hub=hub,
        call_manager=call_manager,
        ingest_service=ingest_service,
        pool=pool,
    )


# --- FastAPI dependencies -------------------------------------------------- #
def get_resources(request: Request) -> AppResources:
    return request.app.state.resources
