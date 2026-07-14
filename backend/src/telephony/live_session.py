"""Transport-agnostic live screening session — shared by the mic and LiveKit runners.

This is the body of a live call once a :class:`~src.telephony.transport.Transport`
is open: speak the AI disclosure, capture spoken consent + persist the immutable
audit, then run either the free conversational loop or the full structured
screening interview (slots → RAG-grounded answers → notes + summary persisted).

Because it depends only on the ``Transport`` interface, the *same* session runs at
the local microphone (``scripts/run_live.py`` → ``LocalAudioTransport``) or over a
real phone number (``scripts/run_livekit.py`` → ``LiveKitTransport``). The caller
owns the transport lifecycle (``start()`` with a transport-specific error message,
then ``aclose()``); this module owns the pipeline + state it builds here.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING

from config.settings import (
    Settings,
    build_engine,
    build_llm_with_failover,
    build_retriever,
    build_state_store,
    build_stt,
    build_tts,
)
from src.agent.consent import disclosure_hash
from src.agent.conversation import ConversationAgent
from src.agent.dialogue import DialogueManager, LLMTurnClassifier
from src.agent.domain import DomainConfig, load_domain_config
from src.agent.finalize import finalize_call
from src.agent.grounding import GroundedResponder
from src.agent.notes import load_notes_schema
from src.agent.orchestrator import ConsentTurn, VoicePipeline
from src.agent.state import ConversationState, StateStore
from src.agent.streaming import resolve_chunk_policy
from src.console import WARN, bold, dim
from src.observability import latency
from src.providers.llm.base import LLMProvider
from src.providers.tts.base import TTSProvider
from src.providers.types import AudioChunk
from src.storage.db import init_db, make_sessionmaker
from src.storage.queries import log_consent
from src.telephony.events import NULL_SINK, CallEventSink
from src.telephony.transport import Transport

if TYPE_CHECKING:
    from src.rag.retriever import Retriever

log = logging.getLogger("echoassist.live")


class _Filler:
    """Short, professional, pre-synthesized acknowledgements for slow grounded turns.

    A small pool is synthesized once in the background at session start (off the critical path)
    and cached as :class:`AudioChunk`\\ s — never a per-turn TTS call. :meth:`next_chunk` cycles
    through them for variety. Honest, not human mimicry (no "uhm"/breaths).
    """

    def __init__(self, tts: TTSProvider, phrases: list[str], delay_ms: int) -> None:
        self._tts = tts
        self._phrases = phrases
        self.delay_s = max(0.0, delay_ms / 1000.0)
        self._chunks: list[AudioChunk] = []
        self._next = 0

    async def prepare(self) -> None:
        for phrase in self._phrases:
            try:
                self._chunks.append(await self._tts.synthesize(phrase))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — best-effort; a failed phrase is skipped
                log.warning("filler prep failed for %r (%s)", phrase, exc)
        if self._chunks:
            log.info("fillers ready: %d phrase(s)", len(self._chunks))
        else:
            log.warning("no fillers synthesized; slow RAG turns won't be covered.")

    @property
    def ready(self) -> bool:
        return bool(self._chunks)

    def next_chunk(self) -> AudioChunk:
        """The next filler audio, cycling through the pool so it isn't always the same phrase."""
        chunk = self._chunks[self._next % len(self._chunks)]
        self._next += 1
        return chunk


async def _play_with_filler(
    transport: Transport,
    audio_stream: AsyncIterator[AudioChunk],
    pick_filler: Callable[[], AudioChunk],
    delay_s: float,
) -> bool:
    """Play a grounded answer, covering a slow start with a cached filler; return barge-in.

    The real answer keeps preparing in a background task, so RAG never blocks on the filler.
    If no real audio chunk is ready within ``delay_s``, one filler (picked by ``pick_filler``,
    so it rotates) plays; then the real audio plays through the transport's continuous stream
    (same gap-free path as usual). The answer stream is always drained to the end, so the
    assistant turn is recorded/persisted exactly as without a filler.
    """
    queue: asyncio.Queue = asyncio.Queue()
    end = object()

    async def _produce() -> None:
        try:
            async for chunk in audio_stream:
                queue.put_nowait(chunk)   # unbounded -> never blocks the RAG producer
        finally:
            queue.put_nowait(end)

    producer = asyncio.create_task(_produce())
    try:
        try:
            first = await asyncio.wait_for(queue.get(), timeout=delay_s)
        except TimeoutError:
            # Real audio is slow -> honest filler (rotated) while the answer keeps buffering.
            if await transport.send_interruptible(pick_filler()):
                return True                       # caller barged during the filler
            first = await queue.get()

        async def _real_audio() -> AsyncIterator[AudioChunk]:
            item = first
            while item is not end:
                yield item
                item = await queue.get()

        return await transport.send_stream_interruptible(_real_audio())
    finally:
        await producer   # drain the answer fully -> assistant turn recorded + state persisted


async def _say(transport: Transport, label: str, text: str, audio: AudioChunk) -> bool:
    """Speak an agent line, interruptibly. Returns True if the caller barged in."""
    print(f"\n{bold(label)} {text}")
    barged = await transport.send_interruptible(audio)
    if barged:
        print(dim("  [barge-in — the caller talked over the agent]"))
    return barged


def _emit_transcript(
    sink: CallEventSink, role: str, text: str, *, citations: list[str] | None = None
) -> None:
    """Broadcast one transcript turn (empty turns are skipped, matching the API runner)."""
    if not text:
        return
    data: dict = {"role": role, "text": text}
    if citations:
        data["citations"] = citations
    sink.emit("transcript", data)


def _partial_emitter(sink: CallEventSink):
    """A per-turn ``on_partial`` callback: broadcast the caller's words *as they speak*.

    Streaming STT (Deepgram) reports interim hypotheses that grow as the caller talks;
    forwarding them as ``partial_transcript`` events lets the dashboard type the line out
    live, so the wait never looks frozen. Consecutive duplicates are dropped. The final
    ``transcript`` turn supersedes the partial on the UI side.
    """
    last = ""

    def on_partial(text: str) -> None:
        nonlocal last
        text = text.strip()
        if text and text != last:
            last = text
            sink.emit("partial_transcript", {"role": "caller", "text": text})

    return on_partial


def _progress(index: int, total: int) -> dict:
    """Question-progress fields for an ``agent_state`` event (omitted when total unknown)."""
    if total > 0:
        return {"question_index": index, "question_total": total}
    return {"question_index": index}


def _question_total(domain: DomainConfig | None) -> int:
    """How many questions the interview flow asks — the denominator for the progress bar."""
    states = domain.flow.get("states", []) if domain is not None else []
    return sum(1 for s in states if isinstance(s, dict) and s.get("type") == "question")


async def _record_consent(
    settings: Settings, *, call_id: str, disclosure_text: str, consent: ConsentTurn
) -> None:
    """Persist the immutable consent audit record (decision + disclosure_hash).

    Compliance is mandatory for a real call (ARCHITECTURE.md §10), so every live
    path logs consent the same way the API runner does. Best-effort here: a dev run
    without Postgres warns and continues; a real call must have the DB up.
    """
    engine = build_engine(settings)
    try:
        await init_db(engine)
        async with make_sessionmaker(engine)() as session:
            await log_consent(
                session,
                call_id=call_id,
                domain=settings.domain,
                decision=consent.decision.value,
                granted=consent.proceed,
                disclosure_hash=disclosure_hash(disclosure_text),
            )
        print(dim(f"consent logged (audit): {consent.decision.value}, call_id={call_id}"))
    except Exception as exc:  # noqa: BLE001 — no DB in a dev run is non-fatal (warned)
        print(f"{WARN} compliance audit NOT persisted ({exc}). "
              "DEV ONLY — a real call must log consent.")
    finally:
        await engine.dispose()


async def _greet_and_consent(
    pipeline: VoicePipeline,
    transport: Transport,
    settings: Settings,
    call_id: str,
    sink: CallEventSink = NULL_SINK,
) -> bool:
    """Disclosure → spoken consent → audit log. Returns True if the call may proceed."""
    disclosure_text, audio = await pipeline.speak_disclosure()
    sink.emit("agent_state", {"state": "speaking"})
    await _say(transport, "AGENT (disclosure):", disclosure_text, audio)
    _emit_transcript(sink, "assistant", disclosure_text)

    print(dim("\n[listening — the caller answers the consent question, then pauses]"))
    sink.emit("agent_state", {"state": "listening"})
    consent = await pipeline.handle_consent(transport.listen(), on_partial=_partial_emitter(sink))
    print(
        f"\n{bold('CALLER:')} {consent.transcript or '(silence)'}  "
        f"{dim('[' + consent.decision.value + ']')}"
    )
    _emit_transcript(sink, "caller", consent.transcript)
    sink.emit("agent_state", {"state": "thinking"})
    sink.emit("agent_state", {"state": "speaking"})
    await _say(transport, "AGENT:", consent.reply, consent.audio)
    _emit_transcript(sink, "assistant", consent.reply)
    await _record_consent(
        settings, call_id=call_id, disclosure_text=disclosure_text, consent=consent
    )
    sink.emit("consent", {"decision": consent.decision.value, "granted": consent.proceed})
    if consent.ended or not consent.proceed:
        print(dim("\nCall ended."))
        return False
    return True


async def _run_conversation(
    pipeline: VoicePipeline, transport: Transport, *, sink: CallEventSink = NULL_SINK
) -> None:
    """Free conversational loop (no structured flow, no services needed)."""
    print(dim("\n--- consent granted — start talking (Ctrl-C to hang up) ---"))
    while True:
        print(dim("\n[listening…]"))
        sink.emit("agent_state", {"state": "listening"})
        result = await pipeline.run_turn(transport.listen(), on_partial=_partial_emitter(sink))
        print(f"\n{bold('CALLER:')} {result.transcript or '(silence)'}")
        _emit_transcript(sink, "caller", result.transcript)
        sink.emit("agent_state", {"state": "thinking"})
        sink.emit("agent_state", {"state": "speaking"})
        await _say(transport, "AGENT:", result.reply, result.audio)
        _emit_transcript(sink, "assistant", result.reply)
        t = result.timings
        print(dim(
            f"latency  stt={t.stt_ms:.0f}ms  llm={t.llm_ms:.0f}ms  "
            f"tts={t.tts_ms:.0f}ms  total={t.total_ms:.0f}ms"
        ))


async def _run_interview(
    pipeline: VoicePipeline,
    transport: Transport,
    *,
    settings: Settings,
    llm: LLMProvider,
    state: ConversationState,
    filler: _Filler | None = None,
    sink: CallEventSink = NULL_SINK,
    call_id: str = "",
    domain: DomainConfig | None = None,
) -> None:
    """The full structured screening interview, live, then notes + summary persisted."""
    print(dim("\n--- consent granted — the interview begins (Ctrl-C to hang up) ---"))
    total = _question_total(domain)
    sink.emit("status", {"status": "interviewing"})
    question_index = 1
    question_text, question_audio = await pipeline.begin_interview()
    sink.emit("agent_state", {"state": "speaking", **_progress(question_index, total)})
    await _say(transport, "AGENT:", question_text, question_audio)
    _emit_transcript(sink, "assistant", question_text)

    turn_id = 0
    try:
        while True:
            turn_id += 1
            print(dim("\n[listening…]"))
            sink.emit("agent_state", {"state": "listening", **_progress(question_index, total)})
            # record_turn is a no-op unless LATENCY_LOGGING=true (adds nothing otherwise).
            with latency.record_turn(
                settings.data_dir, turn_id=turn_id, **latency.config_fields(settings)
            ):
                # Streaming turn (LLM->TTS): the agent starts speaking at the first chunk instead
                # of after the whole reply. send_stream_interruptible keeps barge-in working and
                # drains the stream so the turn is recorded even when interrupted. (Citations are
                # stripped before TTS; the answer is still grounded — sources live in the notes.)
                transcript, is_rag, audio_stream = await pipeline.interview_turn_streaming(
                    transport.listen(), on_partial=_partial_emitter(sink)
                )
                print(f"\n{bold('CALLER:')} {transcript or '(silence)'}")
                _emit_transcript(sink, "caller", transcript)
                sink.emit("agent_state", {"state": "thinking", **_progress(question_index, total)})
                # Cover a slow *grounded* turn with a filler; slot answers / meta go straight thru.
                use_filler = (
                    filler is not None and filler.ready
                    and (is_rag or not settings.filler_only_for_rag)
                )
                sink.emit("agent_state", {"state": "speaking", **_progress(question_index, total)})
                if use_filler:
                    barged = await _play_with_filler(
                        transport, audio_stream, filler.next_chunk, filler.delay_s
                    )
                else:
                    barged = await transport.send_stream_interruptible(audio_stream)
                agent_line = _last_agent_line(state)
                print(f"{bold('AGENT:')} {agent_line}")
                _emit_transcript(sink, "assistant", agent_line)
                # The agent's reply typically poses the next question — advance the counter.
                question_index = min(question_index + 1, total) if total else question_index + 1
                if barged:
                    print(dim("  [barge-in — the caller talked over the agent]"))
            if pipeline.interview_finished:
                break
    finally:
        # Persist on *any* end of call, not just a deterministic close. A caller-led
        # (help-desk) call usually ends by hanging up — Ctrl-C, a dropped line — rather
        # than a recognised closing phrase, and a slot flow can be abandoned mid-way; in
        # both cases the loop exits without `interview_finished`. Finalizing here (instead
        # of only after a clean break) is what makes those calls reach the dashboard.
        sink.emit("agent_state", {"state": "idle"})
        await _finalize(
            settings, llm, state, completed=pipeline.interview_finished, sink=sink, call_id=call_id
        )


def _last_agent_line(state: ConversationState) -> str:
    """The most recent assistant line recorded on the call state (for the console log)."""
    for turn in reversed(state.transcript):
        if turn["role"] == "assistant":
            return turn["text"]
    return ""


async def _finalize(
    settings: Settings,
    llm: LLMProvider,
    state: ConversationState,
    *,
    completed: bool,
    sink: CallEventSink = NULL_SINK,
    call_id: str = "",
) -> None:
    """Extract structured notes + a grounded summary and persist them to Postgres.

    ``completed`` says whether the call reached a deterministic close (all slots filled
    or a recognised closing phrase) or ended early (hang-up / abandoned); it becomes the
    persisted call ``status``. A call where the caller never spoke has nothing worth
    persisting, so it's skipped.

    A terminal ``status`` event is always broadcast so the dashboard settles the call,
    even when there is nothing to persist or Postgres is down (the live transcript stays).
    """
    print(bold("\n--- Interview complete ---" if completed else "\n--- Call ended ---"))
    if not any(turn["role"] == "user" for turn in state.transcript):
        print(dim("Nothing to persist — no caller turns recorded."))
        return
    print(f"{bold('Filled slots:')}")
    for slot, value in state.slots.items():
        print(f"  {slot}: {value}")

    engine = build_engine(settings)
    try:
        await init_db(engine)
        schema = load_notes_schema(settings.domain, settings.config_dir)
        async with make_sessionmaker(engine)() as session:
            final = await finalize_call(
                session, state, llm=llm, schema=schema,
                campaign_name=settings.default_campaign, domain=settings.domain,
                status="completed" if completed else "incomplete",
                redact=settings.redact_pii,
            )
        print(f"\n{bold('Notes (persisted):')}")
        for key, value in final.notes.items():
            print(f"  {key}: {value}")
        print(f"\n{bold('Summary:')} {final.summary}")
        print(dim(f"persisted to Postgres: call id={final.call.id} ({final.call.status})"))
        sink.emit("notes", {"notes": final.notes})
        sink.emit("summary", {"summary": final.summary})
    except Exception as exc:  # noqa: BLE001 — finalize needs Postgres; warn rather than crash the demo
        print(f"{WARN} notes/summary NOT persisted ({exc}). Needs Postgres up.")
    finally:
        await engine.dispose()
        # The terminal status is emitted once by run_live_session on any exit path.


async def _warm_retriever(retriever: Retriever) -> None:
    """Load the RAG models (dense/sparse embedder + reranker) off the critical path.

    They otherwise load lazily on the *first* candidate question — a ~30 s cold start at
    the worst moment, mid-call. Running one throwaway retrieval in the background at
    session start moves that cost into the disclosure + early slot questions (which never
    hit RAG), so the first real question finds the stack hot. Runs the sync retrieve in a
    worker thread (as the live path does) and is best-effort: a failure (e.g. Qdrant down)
    is logged and the models simply load on demand.
    """
    try:
        await asyncio.to_thread(retriever.retrieve, "warmup")
        log.info("RAG stack warmed (embedder + reranker loaded)")
    except asyncio.CancelledError:
        raise  # the session is shutting down — stop warming
    except Exception as exc:  # noqa: BLE001 — warming is best-effort, never break the call
        log.warning("RAG warm failed (%s); models will load on the first question.", exc)


def _filler_phrases(domain: DomainConfig, settings: Settings) -> list[str]:
    """The filler pool: a domain YAML ``filler:`` (a string or a list) overrides the default."""
    override = domain.flow.get("filler")
    if isinstance(override, str):
        return [override.strip()] if override.strip() else []
    if isinstance(override, list):
        return [str(p).strip() for p in override if str(p).strip()]
    return list(settings.filler_phrases)


def _build_dialogue(
    settings: Settings, domain: DomainConfig, llm: LLMProvider, state: ConversationState
) -> tuple[DialogueManager, StateStore, Retriever]:
    """Wire the dialogue manager (classifier + grounded responder + Redis state).

    Also returns the retriever so the caller can warm its models off the critical path.
    """
    store = build_state_store(settings)
    retriever = build_retriever(settings)
    dialogue = DialogueManager(
        classifier=LLMTurnClassifier(llm),
        responder=GroundedResponder(
            llm, retriever, system_prompt=domain.system_prompt,
            min_confidence=settings.grounding_min_confidence,
            fallback_message=domain.fallback_prompt or None,
        ),
        agent=ConversationAgent(
            llm, retriever, system_prompt=domain.system_prompt,
            min_confidence=settings.grounding_min_confidence,
            fallback_message=domain.fallback_prompt or None,
        ),
        domain=domain,
        state=state,
        store=store,
        redact=settings.redact_pii,
    )
    return dialogue, store, retriever


async def run_live_session(
    transport: Transport,
    settings: Settings,
    *,
    interview: bool,
    sink: CallEventSink = NULL_SINK,
    call_id: str | None = None,
) -> None:
    """Run one live call on an already-started ``transport``.

    The caller owns the transport (``start()`` / ``aclose()``); this owns the
    pipeline + conversation state it builds and tears them down on the way out.

    ``sink`` receives the call's live events (status / transcript / consent /
    agent_state / notes / summary) for the dashboard; it defaults to :data:`NULL_SINK`
    so a plain terminal run broadcasts nothing and its console output is unchanged.
    The caller may pass ``call_id`` so it can address the same call on the sink's
    transport (Redis channel) — otherwise a fresh id is generated here.
    """
    log.info(
        "Providers: STT=%s LLM=%s TTS=%s | domain=%s | mode=%s",
        settings.stt_provider.value,
        settings.llm_provider.value,
        settings.tts_provider.value,
        settings.domain,
        "interview" if interview else "conversation",
    )

    domain = load_domain_config(settings.domain, settings.config_dir)
    call_id = call_id or uuid.uuid4().hex
    llm = build_llm_with_failover(settings)
    tts = build_tts(settings)   # shared by the pipeline and the filler

    state: ConversationState | None = None
    store: StateStore | None = None
    rag_warm_task: asyncio.Task[None] | None = None
    filler: _Filler | None = None
    filler_task: asyncio.Task[None] | None = None
    if interview:
        state = ConversationState(call_id=call_id)
        dialogue, store, retriever = _build_dialogue(settings, domain, llm, state)
        # Warm the RAG models in the background now, so the first candidate question
        # doesn't pay their ~30 s cold load mid-call.
        rag_warm_task = asyncio.create_task(_warm_retriever(retriever))
        # Pre-synthesize the perceived-latency filler pool in the background (off the critical
        # path), so a phrase is ready to cover a slow grounded turn. Domain YAML may override it.
        if settings.filler_enabled:
            phrases = _filler_phrases(domain, settings)
            if phrases:
                filler = _Filler(tts, phrases, settings.filler_delay_ms)
                filler_task = asyncio.create_task(filler.prepare())
        pipeline = VoicePipeline(
            build_stt(settings), llm, tts, domain, dialogue=dialogue,
            stream_coalesce=settings.tts_local_smoothing,
            chunk_policy=resolve_chunk_policy(settings, domain),
        )
    else:
        pipeline = VoicePipeline(build_stt(settings), llm, tts, domain)

    terminal_status = "completed"
    try:
        # The domain rides along on the first event so the API-side bridge can register
        # this call under the right domain (that's what makes it show in the dashboard list).
        sink.emit("status", {"status": "started", "domain": settings.domain})
        if not await _greet_and_consent(pipeline, transport, settings, call_id, sink):
            terminal_status = "declined"
            return
        if interview:
            assert state is not None
            await _run_interview(
                pipeline, transport, settings=settings, llm=llm, state=state,
                filler=filler, sink=sink, call_id=call_id, domain=domain,
            )
        else:
            await _run_conversation(pipeline, transport, sink=sink)
    finally:
        # Emit exactly one terminal event on EVERY exit — normal end, provider error, or
        # Ctrl-C — so the dashboard never shows a call stuck "live". Emitted before the
        # awaited cleanup below, which gives the loop a chance to flush the publish; the
        # caller's sink.aclose() then drains it (see run_live.py).
        sink.emit("status", {"status": terminal_status}, terminal=True)
        for task in (rag_warm_task, filler_task):
            if task is not None and not task.done():
                task.cancel()
        await pipeline.aclose()
        if store is not None:
            await store.aclose()
