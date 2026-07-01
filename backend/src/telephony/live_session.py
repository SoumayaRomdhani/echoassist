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
from src.agent.dialogue import DialogueManager, LLMTurnClassifier, static_lines
from src.agent.domain import DomainConfig, load_domain_config
from src.agent.finalize import finalize_call
from src.agent.grounding import GroundedResponder
from src.agent.notes import load_notes_schema
from src.agent.orchestrator import ConsentTurn, VoicePipeline
from src.agent.speech_cache import StaticSpeechCache
from src.agent.state import ConversationState, StateStore
from src.console import WARN, bold, dim
from src.providers.llm.base import LLMProvider
from src.providers.types import AudioChunk
from src.storage.db import init_db, make_sessionmaker
from src.storage.queries import log_consent
from src.telephony.transport import Transport

log = logging.getLogger("echoassist.live")


async def _say(transport: Transport, label: str, text: str, audio: AudioChunk) -> bool:
    """Speak an agent line, interruptibly. Returns True if the caller barged in."""
    print(f"\n{bold(label)} {text}")
    barged = await transport.send_interruptible(audio)
    if barged:
        print(dim("  [barge-in — the caller talked over the agent]"))
    return barged


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
    pipeline: VoicePipeline, transport: Transport, settings: Settings, call_id: str
) -> bool:
    """Disclosure → spoken consent → audit log. Returns True if the call may proceed."""
    disclosure_text, audio = await pipeline.speak_disclosure()
    await _say(transport, "AGENT (disclosure):", disclosure_text, audio)

    print(dim("\n[listening — the caller answers the consent question, then pauses]"))
    consent = await pipeline.handle_consent(transport.listen())
    print(
        f"\n{bold('CALLER:')} {consent.transcript or '(silence)'}  "
        f"{dim('[' + consent.decision.value + ']')}"
    )
    await _say(transport, "AGENT:", consent.reply, consent.audio)
    await _record_consent(
        settings, call_id=call_id, disclosure_text=disclosure_text, consent=consent
    )
    if consent.ended or not consent.proceed:
        print(dim("\nCall ended."))
        return False
    return True


async def _run_conversation(pipeline: VoicePipeline, transport: Transport) -> None:
    """Free conversational loop (no structured flow, no services needed)."""
    print(dim("\n--- consent granted — start talking (Ctrl-C to hang up) ---"))
    while True:
        print(dim("\n[listening…]"))
        result = await pipeline.run_turn(transport.listen())
        print(f"\n{bold('CALLER:')} {result.transcript or '(silence)'}")
        await _say(transport, "AGENT:", result.reply, result.audio)
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
) -> None:
    """The full structured screening interview, live, then notes + summary persisted."""
    print(dim("\n--- consent granted — the interview begins (Ctrl-C to hang up) ---"))
    question_text, question_audio = await pipeline.begin_interview()
    await _say(transport, "AGENT:", question_text, question_audio)

    while True:
        print(dim("\n[listening…]"))
        # Streaming turn (L2): the agent's audio starts at the first sentence (low TTFA),
        # grounded answers stream from the LLM. send_stream_interruptible keeps barge-in
        # working and drains the stream so the turn is recorded even when interrupted.
        # (Citations are stripped before TTS and not echoed here; the answer is still
        # grounded — sources live in the persisted notes.)
        transcript, audio_stream, timings = await pipeline.interview_turn_streaming(
            transport.listen()
        )
        print(f"\n{bold('CALLER:')} {transcript or '(silence)'}")
        barged = await transport.send_stream_interruptible(audio_stream)
        print(f"{bold('AGENT:')} {_last_agent_line(state)}")
        # Machine latency (stt+llm+tts = the pause after you stop talking) vs human time
        # (you thinking + speaking + the VAD silence tail). The big numbers are usually human.
        print(dim(
            f"latency  stt={timings.stt_ms:.0f}ms  llm={timings.llm_ms:.0f}ms  "
            f"tts={timings.tts_ms:.0f}ms  →  reply {timings.ttfa_ms:.0f}ms after you stop"
            f"   (you: wait {timings.wait_ms/1000:.1f}s + speech {timings.speech_ms/1000:.1f}s)"
        ))
        if barged:
            print(dim("  [barge-in — the caller talked over the agent]"))
        if pipeline.interview_finished:
            break

    await _finalize(settings, llm, state)


def _last_agent_line(state: ConversationState) -> str:
    """The most recent assistant line recorded on the call state (for the console log)."""
    for turn in reversed(state.transcript):
        if turn["role"] == "assistant":
            return turn["text"]
    return ""


async def _finalize(settings: Settings, llm: LLMProvider, state: ConversationState) -> None:
    """Extract structured notes + a grounded summary and persist them to Postgres."""
    print(bold("\n--- Interview complete ---"))
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
                redact=settings.redact_pii,
            )
        print(f"\n{bold('Notes (persisted):')}")
        for key, value in final.notes.items():
            print(f"  {key}: {value}")
        print(f"\n{bold('Summary:')} {final.summary}")
        print(dim(f"persisted to Postgres: call id={final.call.id} ({final.call.status})"))
    except Exception as exc:  # noqa: BLE001 — finalize needs Postgres; warn rather than crash the demo
        print(f"{WARN} notes/summary NOT persisted ({exc}). Needs Postgres up.")
    finally:
        await engine.dispose()


def _build_dialogue(
    settings: Settings, domain: DomainConfig, llm: LLMProvider, state: ConversationState
) -> tuple[DialogueManager, StateStore]:
    """Wire the dialogue manager (classifier + grounded responder + Redis state)."""
    store = build_state_store(settings)
    dialogue = DialogueManager(
        classifier=LLMTurnClassifier(llm),
        responder=GroundedResponder(
            llm, build_retriever(settings), system_prompt=domain.system_prompt,
            min_confidence=settings.grounding_min_confidence,
            retrieve_then_read=settings.grounding_retrieve_then_read,
        ),
        domain=domain,
        state=state,
        store=store,
        redact=settings.redact_pii,
    )
    return dialogue, store


async def run_live_session(
    transport: Transport, settings: Settings, *, interview: bool
) -> None:
    """Run one live call on an already-started ``transport``.

    The caller owns the transport (``start()`` / ``aclose()``); this owns the
    pipeline + conversation state it builds and tears them down on the way out.
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
    call_id = uuid.uuid4().hex
    llm = build_llm_with_failover(settings)

    # Pre-synthesize the deterministic lines (greeting, questions, close…) in the
    # background during the disclosure, so most agent turns spend ~0 ms on TTS (L5).
    tts = build_tts(settings)
    warm_task: asyncio.Task[None] | None = None
    if settings.tts_cache_static:
        cache = StaticSpeechCache(tts)
        tts = cache
        warm_task = asyncio.create_task(cache.warm(static_lines(domain)))

    state: ConversationState | None = None
    store: StateStore | None = None
    if interview:
        state = ConversationState(call_id=call_id)
        dialogue, store = _build_dialogue(settings, domain, llm, state)
        pipeline = VoicePipeline(build_stt(settings), llm, tts, domain, dialogue=dialogue)
    else:
        pipeline = VoicePipeline(build_stt(settings), llm, tts, domain)

    try:
        if not await _greet_and_consent(pipeline, transport, settings, call_id):
            return
        if interview:
            assert state is not None
            await _run_interview(pipeline, transport, settings=settings, llm=llm, state=state)
        else:
            await _run_conversation(pipeline, transport)
    finally:
        if warm_task is not None and not warm_task.done():
            warm_task.cancel()
        await pipeline.aclose()
        if store is not None:
            await store.aclose()
