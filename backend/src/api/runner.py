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
from src.agent.domain import DomainConfig, with_question_flow
from src.agent.finalize import FinalizedCall
from src.agent.grounding import Citation
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

# A bridged mic/LiveKit call silent longer than this is treated as ended, so a lost
# terminal event (hard-killed mic process) can't leave a call stuck "live" forever.
# Generous because CPU turns are slow (STT ~15-30 s) — this only catches true drops.
_LIVE_STALE_SECONDS = 180.0


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
    job_posting_id: int | None = None  # set => tailored interview from a job posting
    started_at: datetime = field(default_factory=_now)
    ended_at: datetime | None = None
    error: str | None = None
    external: bool = False           # driven from another process via the Redis bridge
    last_event_at: datetime | None = None  # last bridged event (staleness safety net)


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

    def live(self) -> list[CallSession]:
        """The calls running *right now* (server-started or mic/LiveKit), newest first.

        A bridged (external) call whose terminal event was lost — e.g. the mic process
        was hard-killed before the ``completed`` event flushed — would otherwise linger
        as "live" forever, so one that has gone silent past ``_LIVE_STALE_SECONDS`` is
        treated as ended. Server-started calls are owned by their task and end cleanly.
        """
        now = _now()
        alive: list[CallSession] = []
        for s in self.list():
            if s.ended_at is not None:
                continue
            stale = (
                s.external
                and s.last_event_at is not None
                and (now - s.last_event_at).total_seconds() > _LIVE_STALE_SECONDS
            )
            if stale:
                continue
            alive.append(s)
        return alive

    # --- externally-driven sessions (the mic/LiveKit bridge) ---------------
    def register_external(self, *, call_id: str, domain: str, campaign: str) -> CallSession:
        """Track a live call driven from another process (its events arrive via Redis).

        Idempotent: the first event for a call registers it so it appears in the live
        list and the WebSocket accepts subscribers; later events just update it.
        """
        session = self._sessions.get(call_id)
        if session is None:
            session = CallSession(
                call_id=call_id, domain=domain, campaign=campaign,
                external=True, last_event_at=_now(),
            )
            self._sessions[call_id] = session
        return session

    def note_external_event(
        self, call_id: str, event_type: str, data: dict, *, terminal: bool
    ) -> None:
        """Fold one bridged event into the tracked session (status, consent, end-of-call)."""
        session = self._sessions.get(call_id)
        if session is None:
            return
        session.last_event_at = _now()
        if event_type == "status":
            status = data.get("status")
            if isinstance(status, str):
                session.status = status
            # The 'started' event carries the call's real domain — adopt it, so the call
            # lists under the right domain even if it first registered under the default.
            domain = data.get("domain")
            if isinstance(domain, str) and domain:
                session.domain = domain
        elif event_type == "consent":
            session.consent_granted = bool(data.get("granted"))
        if terminal:
            session.ended_at = _now()

    def preflight(self) -> None:
        """Verify a call can run here (voice models installed); raises VoiceUnavailable."""
        self._engine.preflight()

    # --- lifecycle ---------------------------------------------------------
    def start(self, *, domain: str | None = None, campaign: str | None = None,
              consent: bool = True, job_posting_id: int | None = None) -> CallSession:
        """Register a call and launch its background task; returns immediately."""
        session = CallSession(
            call_id=uuid4().hex,
            domain=domain or self._engine.default_domain(),
            campaign=campaign or self._default_campaign,
            job_posting_id=job_posting_id,
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

        if session.job_posting_id is not None:
            try:
                domain_cfg = await self._tailored_domain(domain_cfg, session.job_posting_id)
            except (LookupError, ValueError) as exc:
                self._fail(session, f"cannot build tailored interview: {exc}")
                return

        state = ConversationState(call_id=call_id)
        # Build off the event loop: a real engine loads heavy models here (FastEmbed
        # retriever, Whisper, Kokoro), which must never block the API while a call starts.
        pipeline = await asyncio.to_thread(
            self._engine.build_pipeline, session.domain, domain_cfg, state, self._state_store
        )

        try:
            with span("call.run", call_id=call_id, domain=session.domain):
                await self._drive(session, pipeline, state, domain_cfg, consent=consent)
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

    async def _tailored_domain(self, base: DomainConfig, job_posting_id: int) -> DomainConfig:
        """Overlay a job posting's confirmed questions onto the base domain flow."""
        from src.storage.queries import get_job_posting

        async with self._sessionmaker() as db:
            posting = await get_job_posting(db, job_posting_id)
        if posting is None:
            raise LookupError(f"job posting {job_posting_id} not found")
        return with_question_flow(base, posting.questions)

    async def _drive(
        self, session: CallSession, pipeline: VoicePipeline, state: ConversationState,
        domain_cfg: DomainConfig, *, consent: bool,
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

        for audio in self._engine.answer_audios(domain_cfg):
            with span("call.turn"):
                turn = await pipeline.interview_turn(audio)
            self._emit_transcript(call_id, "caller", turn.transcript)
            self._emit_transcript(
                call_id, "assistant", turn.reply,
                citations=turn.citations, details=turn.details,
            )
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
        self,
        call_id: str,
        role: str,
        text: str,
        *,
        citations: list[str] | None = None,
        details: list[Citation] | None = None,
    ) -> None:
        if not text:
            return
        data: dict = {"role": role, "text": text}
        if details:
            # Show the rich provenance (source — heading (p17)); keep the structured
            # form too for a future citations UI. Falls back to bare sources.
            data["citations"] = [d.label() for d in details]
            data["citations_detail"] = [d.to_dict() for d in details]
        elif citations:
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
