"""Shared fixtures + fakes for the Sprint 6 API tests.

Everything here is model-free. The fakes encode text as audio bytes (so STT just
decodes), script the dialogue decisions, and persist canned notes/summary — which
lets the *real* runner, orchestrator, dialogue, event hub, and storage run end to
end without loading a model or touching Postgres (in-memory SQLite stands in).
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from config.settings import Settings, get_settings
from src.agent.dialogue import DialogueManager, TurnDecision, TurnIntent
from src.agent.domain import DomainConfig, load_domain_config
from src.agent.finalize import FinalizedCall
from src.agent.grounding import GroundedAnswer
from src.agent.orchestrator import VoicePipeline
from src.agent.state import ConversationState, InMemoryStateStore, StateStore
from src.api.app import create_app
from src.api.context import AppResources
from src.api.events import CallEventHub
from src.api.ingest_service import IngestService
from src.api.runner import AudioInput, CallEngine, CallManager, VoiceUnavailable
from src.providers.llm.base import LLMProvider
from src.providers.stt.base import STTProvider
from src.providers.tts.base import TTSProvider
from src.providers.types import AudioChunk, AudioFormat, LLMResponse, Transcript
from src.rag.ingest import IngestReport
from src.storage.db import init_db, make_sessionmaker, persist_call

_FMT = AudioFormat(sample_rate=16000)


def audio(text: str) -> AudioChunk:
    """Encode text as an audio chunk; the fake STT decodes it back."""
    return AudioChunk(data=text.encode("utf-8"), fmt=_FMT)


class Probe:
    """Records the peak number of concurrently-active model calls."""

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    def enter(self) -> None:
        self.active += 1
        self.max_active = max(self.max_active, self.active)

    def exit(self) -> None:
        self.active -= 1


class FakeSTT(STTProvider):
    def __init__(self, probe: Probe | None = None) -> None:
        self._probe = probe

    async def transcribe_stream(
        self, audio: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[Transcript]:
        if self._probe:
            self._probe.enter()
        try:
            buffer = bytearray()
            async for chunk in audio:
                buffer.extend(chunk.data)
            if self._probe:
                await asyncio.sleep(0.01)   # widen the window so missing serialization shows
            yield Transcript(text=buffer.decode("utf-8") or "yes", is_final=True)
        finally:
            if self._probe:
                self._probe.exit()


class FakeTTS(TTSProvider):
    def __init__(self, probe: Probe | None = None) -> None:
        self._probe = probe

    @property
    def output_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=24000)

    async def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
        if self._probe:
            self._probe.enter()
        try:
            if self._probe:
                await asyncio.sleep(0.01)
            yield AudioChunk(data=text.encode("utf-8"), fmt=self.output_format)
        finally:
            if self._probe:
                self._probe.exit()


class FakeLLM(LLMProvider):
    async def chat(self, messages, tools=None) -> LLMResponse:
        return LLMResponse(text="ok")


class _ScriptedClassifier:
    """Returns queued decisions in order; DONE once exhausted."""

    def __init__(self, decisions: list[TurnDecision]) -> None:
        self._decisions = list(decisions)

    async def classify(self, question: str, utterance: str) -> TurnDecision:
        return self._decisions.pop(0) if self._decisions else TurnDecision(TurnIntent.DONE)


class _CannedResponder:
    async def answer(self, question: str, *, search_query: str | None = None) -> GroundedAnswer:
        return GroundedAnswer(text="It is fully remote.", citations=["remote_work_policy.md"])

    async def answer_streaming(
        self, question: str, *, search_query: str | None = None
    ) -> AsyncIterator[str]:
        yield "It is fully remote "
        yield "[remote_work_policy.md]."


# The five answers fill the screening slots; the leading question is a RAG detour
# and the trailing "done" closes the candidate-questions stage.
_TURN_DECISIONS = [
    TurnDecision(TurnIntent.QUESTION, caller_question="is it remote?"),
    TurnDecision(TurnIntent.ANSWER, answer_value="6 years"),
    TurnDecision(TurnIntent.ANSWER, answer_value="Python, FastAPI"),
    TurnDecision(TurnIntent.ANSWER, answer_value="2 weeks"),
    TurnDecision(TurnIntent.ANSWER, answer_value="remote, CET"),
    TurnDecision(TurnIntent.ANSWER, answer_value="70k EUR"),
    TurnDecision(TurnIntent.DONE),
]
_ANSWER_TEXTS = [
    "wait, is it remote?", "six years", "python and fastapi",
    "two weeks", "remote, I'm in CET", "around 70k euros", "no more questions",
]
_DEFAULT_NOTES = {
    "candidate_name": "",
    "years_experience": "6 years",
    "primary_stack": "Python, FastAPI",
    "availability": "2 weeks",
    "remote_setup": "remote, CET",
    "salary_expectation": "70k EUR",
    "strengths": ["clear communicator"],
    "concerns": [],
    "overall_fit": "strong",
}
_DEFAULT_SUMMARY = "Strong candidate with six years of Python experience; available in 2 weeks."


class FakeCallEngine(CallEngine):
    """Runs the real pipeline/dialogue with fakes; persists canned notes/summary."""

    def __init__(
        self,
        settings: Settings,
        *,
        stt: STTProvider,
        tts: TTSProvider,
        preflight_error: str | None = None,
    ) -> None:
        self._settings = settings
        self._stt = stt
        self._tts = tts
        self._llm = FakeLLM()
        self._preflight_error = preflight_error

    def preflight(self) -> None:
        if self._preflight_error:
            raise VoiceUnavailable(self._preflight_error)

    def default_domain(self) -> str:
        return self._settings.domain

    def load_domain(self, domain: str) -> DomainConfig:
        return load_domain_config(domain, self._settings.config_dir)

    def build_pipeline(
        self, domain: str, domain_cfg: DomainConfig, state: ConversationState, store: StateStore
    ) -> VoicePipeline:
        dialogue = DialogueManager(
            classifier=_ScriptedClassifier(list(_TURN_DECISIONS)),
            responder=_CannedResponder(),
            domain=domain_cfg,
            state=state,
            store=store,
            redact=self._settings.redact_pii,
        )
        return VoicePipeline(self._stt, self._llm, self._tts, domain_cfg, dialogue=dialogue)

    def consent_audio(self, *, consent: bool) -> AudioInput:
        return audio("yes, that's fine" if consent else "no, I refuse")

    def answer_audios(self, domain_cfg: DomainConfig) -> list[AudioInput]:
        return [audio(text) for text in _ANSWER_TEXTS]

    async def finalize(
        self, session, state: ConversationState, *, domain: str, campaign: str
    ) -> FinalizedCall:
        call = await persist_call(
            session, campaign_name=campaign, domain=domain, state=state,
            notes=_DEFAULT_NOTES, summary=_DEFAULT_SUMMARY, status="completed",
        )
        return FinalizedCall(notes=_DEFAULT_NOTES, summary=_DEFAULT_SUMMARY, call=call)


def make_settings() -> Settings:
    """Deterministic settings: screening domain, tracing off, memory state (no Redis)."""
    return get_settings().model_copy(
        update={"otel_enabled": False, "domain": "screening", "state_backend": "memory"}
    )


def make_resources(
    engine,
    *,
    settings: Settings | None = None,
    stt: STTProvider | None = None,
    tts: TTSProvider | None = None,
    data_dir: Path | None = None,
    indexer=None,
    preflight_error: str | None = None,
) -> AppResources:
    settings = settings or make_settings()
    sessionmaker = make_sessionmaker(engine)
    hub = CallEventHub()
    call_manager = CallManager(
        engine=FakeCallEngine(
            settings, stt=stt or FakeSTT(), tts=tts or FakeTTS(), preflight_error=preflight_error
        ),
        sessionmaker=sessionmaker,
        state_store=InMemoryStateStore(),
        hub=hub,
        default_campaign=settings.default_campaign,
    )
    ingest_service = IngestService(
        data_dir=data_dir or Path(tempfile.mkdtemp()),
        indexer=indexer
        or (lambda docs_dir, domain: IngestReport(documents=1, chunks=1, collection_count=1)),
    )
    return AppResources(
        settings=settings,
        engine=engine,
        sessionmaker=sessionmaker,
        state_store=InMemoryStateStore(),
        hub=hub,
        call_manager=call_manager,
        ingest_service=ingest_service,
        pool=None,
    )


async def run_call_to_completion(
    resources: AppResources, *, consent: bool = True, domain: str | None = None,
    campaign: str | None = None, timeout: float = 5.0,
):
    """Start a call and wait until its background task finishes."""
    session = resources.call_manager.start(consent=consent, domain=domain, campaign=campaign)
    deadline = time.monotonic() + timeout
    while session.ended_at is None:
        await asyncio.sleep(0.01)
        if time.monotonic() > deadline:
            raise TimeoutError(f"call {session.call_id} did not finish in {timeout}s")
    return session


@pytest_asyncio.fixture
async def sqlite_engine():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    await init_db(engine)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def resources(sqlite_engine):
    res = make_resources(sqlite_engine)
    try:
        yield res
    finally:
        await res.call_manager.aclose()


@pytest_asyncio.fixture
async def client(resources):
    from httpx import ASGITransport, AsyncClient

    app = create_app(resources)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
