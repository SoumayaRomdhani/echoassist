"""Call runner — drives a screening call in the background and streams live events.

``POST /calls`` starts one call here. The runner walks the same lifecycle as
``scripts/run_interview.py`` (disclosure → consent → interview → finalize) but,
instead of playing audio locally, it publishes every step to the
:class:`CallEventHub` so WebSocket clients see live status + transcript, and it
persists the result to Postgres at the end.

The provider/domain/finalize specifics live behind :class:`CallEngine` so the
runner itself is model-free: production wires real (shared, serialized) providers
in :mod:`src.api.context`; tests inject fakes and exercise the full lifecycle,
event fan-out, and concurrency without loading a single model.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker

from src.agent.consent import ConsentDecision, disclosure_hash
from src.agent.domain import DomainConfig
from src.agent.finalize import FinalizedCall
from src.agent.orchestrator import VoicePipeline
from src.agent.state import ConversationState, StateStore
from src.api.events import CallEventHub
from src.observability.tracing import span
from src.providers.errors import ProviderError
from src.providers.types import AudioChunk
from src.storage.db import persist_call

log = logging.getLogger("echoassist.api.runner")

# Audio accepted by the pipeline: one chunk, or a (fresh) async stream of chunks.
AudioInput = AudioChunk | AsyncIterator[AudioChunk]

# The call whose work is running in the current task — lets shared providers (e.g.
# the failover LLM) attribute a degradation event to the right call on the hub.
current_call_id: ContextVar[str | None] = ContextVar("current_call_id", default=None)


def _now() -> datetime:
    return datetime.now(UTC)


class VoiceUnavailable(RuntimeError):
    """The voice models needed to run a call are not installed in this image."""


class CallEngine(ABC):
    """Everything call-specific the runner needs, behind one seam (real or fake)."""

    def preflight(self) -> None:  # noqa: B027 — optional override hook, default no-op
        """Raise :class:`VoiceUnavailable` if a call cannot run here. Default: no-op."""

    @abstractmethod
    def default_domain(self) -> str: ...

    @abstractmethod
    def load_domain(self, domain: str) -> DomainConfig: ...

    @abstractmethod
    def build_pipeline(
        self, domain: str, domain_cfg: DomainConfig, state: ConversationState, store: StateStore
    ) -> VoicePipeline: ...

    @abstractmethod
    def consent_audio(self, *, consent: bool) -> AudioInput:
        """Audio for the caller's answer to the consent question."""

    @abstractmethod
    def answer_audios(self, domain_cfg: DomainConfig) -> list[AudioInput]:
        """Audio for each interview turn, in order."""

    @abstractmethod
    async def finalize(
        self, session, state: ConversationState, *, domain: str, campaign: str
    ) -> FinalizedCall: ...


@dataclass(slots=True)
class CallSession:
    """Live, in-memory view of a running (or finished) call."""

    call_id: str
    domain: str
    campaign: str
    status: str = "started"          # started|interviewing|completed|declined|failed
    consent_granted: bool = False
    started_at: datetime = field(default_factory=_now)
    ended_at: datetime | None = None
    error: str | None = None


class CallManager:
    """Starts calls, tracks their live sessions, and owns their background tasks."""

    def __init__(
        self,
        *,
        engine: CallEngine,
        sessionmaker: async_sessionmaker,
        state_store: StateStore,
        hub: CallEventHub,
        default_campaign: str,
    ) -> None:
        self._engine = engine
        self._sessionmaker = sessionmaker
        self._state_store = state_store
        self._hub = hub
        self._default_campaign = default_campaign
        self._sessions: dict[str, CallSession] = {}
        self._tasks: set[asyncio.Task] = set()

    # --- registry ----------------------------------------------------------
    def get(self, call_id: str) -> CallSession | None:
        return self._sessions.get(call_id)

    def list(self) -> list[CallSession]:
        return sorted(self._sessions.values(), key=lambda s: s.started_at, reverse=True)

    def preflight(self) -> None:
        """Verify a call can run here (voice models installed); raises VoiceUnavailable."""
        self._engine.preflight()

    # --- lifecycle ---------------------------------------------------------
    def start(self, *, domain: str | None = None, campaign: str | None = None,
              consent: bool = True) -> CallSession:
        """Register a call and launch its background task; returns immediately."""
        session = CallSession(
            call_id=uuid4().hex,
            domain=domain or self._engine.default_domain(),
            campaign=campaign or self._default_campaign,
        )
        self._sessions[session.call_id] = session
        task = asyncio.create_task(self._run(session, consent=consent))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return session

    async def aclose(self) -> None:
        """Cancel any in-flight calls (used on app shutdown)."""
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            try:  # noqa: SIM105 - want to swallow CancelledError and any teardown error
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    # --- the call itself ---------------------------------------------------
    async def _run(self, session: CallSession, *, consent: bool) -> None:
        current_call_id.set(session.call_id)
        call_id = session.call_id
        try:
            domain_cfg = self._engine.load_domain(session.domain)
        except (FileNotFoundError, ValueError) as exc:
            self._fail(session, f"unknown domain '{session.domain}': {exc}")
            return

        state = ConversationState(call_id=call_id)
        # Build off the event loop: a real engine loads heavy models here (FastEmbed
        # retriever, Whisper, Kokoro), which must never block the API while a call starts.
        pipeline = await asyncio.to_thread(
            self._engine.build_pipeline, session.domain, domain_cfg, state, self._state_store
        )

        try:
            with span("call.run", call_id=call_id, domain=session.domain):
                await self._drive(session, pipeline, state, consent=consent)
        except ProviderError as exc:
            log.warning("call %s failed: provider error: %s", call_id, exc)
            await self._persist_terminal(session, state, status="failed",
                                         summary=f"Call failed: {exc}")
            self._fail(session, str(exc), persisted=True)
        except Exception as exc:  # noqa: BLE001 - a runner crash must end the call cleanly
            log.exception("call %s crashed", call_id)
            self._fail(session, str(exc))
        finally:
            await pipeline.aclose()

    async def _drive(
        self, session: CallSession, pipeline: VoicePipeline, state: ConversationState,
        *, consent: bool,
    ) -> None:
        call_id = session.call_id
        self._hub.publish(call_id, "status", {"status": "started"})

        # 1) Mandatory spoken AI disclosure.
        with span("call.disclosure"):
            disclosure, _ = await pipeline.speak_disclosure()
        self._emit_transcript(call_id, "assistant", disclosure)

        # 2) Consent gate — captured and logged before anything is stored (§10).
        with span("call.consent"):
            outcome = await pipeline.handle_consent(self._engine.consent_audio(consent=consent))
        self._emit_transcript(call_id, "caller", outcome.transcript)
        self._emit_transcript(call_id, "assistant", outcome.reply)
        session.consent_granted = outcome.decision is ConsentDecision.ACCEPTED
        await self._log_consent(session, outcome.decision, disclosure_hash(disclosure))
        self._hub.publish(call_id, "consent", {
            "decision": outcome.decision.value, "granted": session.consent_granted,
        })

        if not outcome.proceed:
            await self._persist_terminal(
                session, state, status="declined",
                summary="Call ended: consent not granted.",
            )
            self._complete(session, status="declined")
            return

        # 3) Structured interview, one turn at a time.
        session.status = "interviewing"
        self._hub.publish(call_id, "status", {"status": "interviewing"})
        question, _ = await pipeline.begin_interview()
        self._emit_transcript(call_id, "assistant", question)

        for audio in self._engine.answer_audios(self._engine.load_domain(session.domain)):
            with span("call.turn"):
                turn = await pipeline.interview_turn(audio)
            self._emit_transcript(call_id, "caller", turn.transcript)
            self._emit_transcript(call_id, "assistant", turn.reply, citations=turn.citations)
            if turn.ended:
                break

        # 4) Finalize: notes + summary + persistence (PII redacted) (Sprint 4/5).
        with span("call.finalize"):
            final = await self._finalize(session, state)
        self._hub.publish(call_id, "notes", {"notes": final.notes})
        self._hub.publish(call_id, "summary", {"summary": final.summary})
        self._complete(session, status="completed")

    # --- helpers -----------------------------------------------------------
    def _emit_transcript(
        self, call_id: str, role: str, text: str, *, citations: list[str] | None = None
    ) -> None:
        if not text:
            return
        data = {"role": role, "text": text}
        if citations:
            data["citations"] = citations
        self._hub.publish(call_id, "transcript", data)

    async def _log_consent(
        self, session: CallSession, decision: ConsentDecision, disclosure_hash: str
    ) -> None:
        from src.storage.queries import log_consent

        async with self._sessionmaker() as db:
            await log_consent(
                db, call_id=session.call_id, domain=session.domain,
                decision=decision.value, granted=session.consent_granted,
                disclosure_hash=disclosure_hash,
            )

    async def _finalize(self, session: CallSession, state: ConversationState) -> FinalizedCall:
        async with self._sessionmaker() as db:
            return await self._engine.finalize(
                db, state, domain=session.domain, campaign=session.campaign
            )

    async def _persist_terminal(
        self, session: CallSession, state: ConversationState, *, status: str, summary: str
    ) -> None:
        """Persist a compliance record for a call that did not finish normally."""
        async with self._sessionmaker() as db:
            await persist_call(
                db, campaign_name=session.campaign, domain=session.domain,
                state=state, notes=None, summary=summary, status=status,
            )

    def _complete(self, session: CallSession, *, status: str) -> None:
        session.status = status
        session.ended_at = _now()
        self._hub.publish(session.call_id, "status", {"status": status}, terminal=True)
        log.info("call %s ended status=%s", session.call_id, status)

    def _fail(self, session: CallSession, message: str, *, persisted: bool = False) -> None:
        session.status = "failed"
        session.error = message
        session.ended_at = _now()
        self._hub.publish(
            session.call_id, "error", {"message": message, "persisted": persisted}, terminal=True
        )
