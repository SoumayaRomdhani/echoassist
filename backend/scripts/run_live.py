"""Talk to the EchoAssist agent live through your microphone (Sprint 8).

Two modes, both driven by a real microphone + speakers instead of replayed WAVs —
the file source/sink is swapped for :class:`LocalAudioTransport` and nothing in the
pipeline changes (ARCHITECTURE.md §2, §4):

    python scripts/run_live.py                 # free conversation (STT -> LLM -> TTS)
    python scripts/run_live.py --interview     # the full structured screening interview
    python scripts/run_live.py --lang en       # pin the STT language (avoids mis-detection)
    python scripts/run_live.py --rate 48000    # if your mic rejects 16 kHz
    python scripts/run_live.py --device "USB"  # pick an input device by name/index

Speak after each "listening…" prompt; pause when you're done and the agent replies.
Talk over the agent to cut it off (barge-in). Press Ctrl-C to hang up.
Headphones REQUIRED — there is no echo cancellation, so on open speakers the mic
hears the agent and trips a false barge-in.

Modes:
  • default        — a plain conversational loop. Needs no Qdrant/Redis/Postgres;
                     good for validating the live transport quickly.
  • --interview    — the real screening flow (YAML states, slot filling, RAG-grounded
                     answers with citations, then notes + summary persisted to
                     Postgres). Needs Qdrant + Redis + Postgres up and the domain
                     ingested (docker compose up -d qdrant redis postgres; ingest_docs).

Compliance: both modes speak the AI disclosure, capture spoken consent, and persist
the immutable consent audit (disclosure_hash) before the interview proceeds.

Honesty note: on CPU (this machine's default) a turn takes ~15-30 s, STT-dominated;
the goal here is the live chain, not latency. Sub-second turns need a GPU or cloud
STT/TTS (a config-only provider swap).
"""

from __future__ import annotations

import argparse
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
    get_settings,
)
from src.agent.consent import disclosure_hash
from src.agent.dialogue import DialogueManager, LLMTurnClassifier
from src.agent.domain import DomainConfig, load_domain_config
from src.agent.finalize import finalize_call
from src.agent.grounding import GroundedResponder
from src.agent.notes import load_notes_schema
from src.agent.orchestrator import ConsentTurn, VoicePipeline
from src.agent.state import ConversationState, StateStore
from src.console import FAIL, WARN, bold, dim, init_console
from src.log import setup_logging
from src.providers.errors import ProviderError
from src.providers.llm.base import LLMProvider
from src.runtime import use_selector_event_loop
from src.storage.db import init_db, make_sessionmaker
from src.storage.queries import log_consent
from src.telephony.local_audio import LocalAudioTransport

log = logging.getLogger("echoassist.live")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Talk to the EchoAssist agent live via microphone."
    )
    parser.add_argument(
        "--interview", action="store_true",
        help="Run the full structured screening interview (needs Qdrant + Redis + Postgres).",
    )
    parser.add_argument(
        "--rate", type=int, default=16000,
        help="Microphone capture sample rate (try 48000 if 16000 is rejected).",
    )
    parser.add_argument(
        "--device", default=None,
        help="Input device index or name substring (default: system default).",
    )
    parser.add_argument(
        "--lang", default=None,
        help="Pin the STT language, e.g. 'en' or 'fr' (default: WHISPER_LANGUAGE / auto-detect). "
             "Pinning avoids whisper mis-detecting the language on short utterances.",
    )
    return parser.parse_args()


async def _say(transport: LocalAudioTransport, label: str, text: str, audio) -> bool:
    """Speak an agent line, interruptibly. Returns True if the caller barged in."""
    print(f"\n{bold(label)} {text}")
    barged = await transport.send_interruptible(audio)
    if barged:
        print(dim("  [barge-in — you talked over the agent]"))
    return barged


async def _record_consent(
    settings: Settings, *, call_id: str, disclosure_text: str, consent: ConsentTurn
) -> None:
    """Persist the immutable consent audit record (decision + disclosure_hash).

    Compliance is mandatory for a real call (ARCHITECTURE.md §10), so the live path
    logs consent exactly like the API runner does. Best-effort here: a dev transport
    test without Postgres warns and continues; a real call must have the DB up.
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
    except Exception as exc:  # noqa: BLE001 — no DB in a dev transport test is non-fatal (warned)
        print(f"{WARN} compliance audit NOT persisted ({exc}). "
              "DEV ONLY — a real call must log consent.")
    finally:
        await engine.dispose()


async def _greet_and_consent(
    pipeline: VoicePipeline, transport: LocalAudioTransport, settings: Settings, call_id: str
) -> bool:
    """Disclosure → spoken consent → audit log. Returns True if the call may proceed."""
    disclosure_text, audio = await pipeline.speak_disclosure()
    await _say(transport, "AGENT (disclosure):", disclosure_text, audio)

    print(dim("\n[listening — answer the consent question, then pause]"))
    consent = await pipeline.handle_consent(transport.listen())
    print(
        f"\n{bold('YOU:')} {consent.transcript or '(silence)'}  "
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


async def _run_conversation(pipeline: VoicePipeline, transport: LocalAudioTransport) -> None:
    """Free conversational loop (no structured flow, no services needed)."""
    print(dim("\n--- consent granted — start talking (Ctrl-C to hang up) ---"))
    while True:
        print(dim("\n[listening…]"))
        result = await pipeline.run_turn(transport.listen())
        print(f"\n{bold('YOU:')} {result.transcript or '(silence)'}")
        await _say(transport, "AGENT:", result.reply, result.audio)
        t = result.timings
        print(dim(
            f"latency  stt={t.stt_ms:.0f}ms  llm={t.llm_ms:.0f}ms  "
            f"tts={t.tts_ms:.0f}ms  total={t.total_ms:.0f}ms"
        ))


async def _run_interview(
    pipeline: VoicePipeline,
    transport: LocalAudioTransport,
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
        # Non-streaming turn so each agent line is one chunk and barge-in composes.
        turn = await pipeline.interview_turn(transport.listen())
        print(f"\n{bold('YOU:')} {turn.transcript or '(silence)'}")
        await _say(transport, "AGENT:", turn.reply, turn.audio)
        if turn.citations:
            print(dim(f"  sources: {', '.join(turn.citations)}"))
        if turn.ended:
            break

    await _finalize(settings, llm, state)


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
        ),
        domain=domain,
        state=state,
        store=store,
        redact=settings.redact_pii,
    )
    return dialogue, store


async def main() -> None:
    args = _parse_args()
    settings = get_settings()
    if args.lang:  # pin the STT language for this run (overrides WHISPER_LANGUAGE)
        settings = settings.model_copy(update={"whisper_language": args.lang})
    init_console()
    setup_logging(settings.log_level)

    device: int | str | None = args.device
    if isinstance(device, str) and device.isdigit():
        device = int(device)

    log.info(
        "Providers: STT=%s LLM=%s TTS=%s | domain=%s | mode=%s",
        settings.stt_provider.value,
        settings.llm_provider.value,
        settings.tts_provider.value,
        settings.domain,
        "interview" if args.interview else "conversation",
    )

    domain = load_domain_config(settings.domain, settings.config_dir)
    call_id = uuid.uuid4().hex
    llm = build_llm_with_failover(settings)
    transport = LocalAudioTransport(sample_rate=args.rate, input_device=device)

    # Interview mode wires the dialogue manager (RAG + state); both share one llm.
    state: ConversationState | None = None
    store = None
    if args.interview:
        state = ConversationState(call_id=call_id)
        dialogue, store = _build_dialogue(settings, domain, llm, state)
        pipeline = VoicePipeline(build_stt(settings), llm, build_tts(settings), domain,
                                 dialogue=dialogue)
    else:
        pipeline = VoicePipeline(build_stt(settings), llm, build_tts(settings), domain)

    try:
        await transport.start()
    except Exception as exc:  # noqa: BLE001 — no mic / unsupported rate is a clean exit, not a crash
        raise SystemExit(
            f"{FAIL} Could not open the microphone ({exc}).\n"
            "Check your input device, or pass --rate 48000 / --device <name>."
        ) from exc

    try:
        if not await _greet_and_consent(pipeline, transport, settings, call_id):
            return
        if args.interview:
            assert state is not None
            await _run_interview(pipeline, transport, settings=settings, llm=llm, state=state)
        else:
            await _run_conversation(pipeline, transport)
    finally:
        await transport.aclose()
        await pipeline.aclose()
        if store is not None:
            await store.aclose()


if __name__ == "__main__":
    use_selector_event_loop()  # Selector loop: psycopg async (consent log / finalize) on Windows
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n" + dim("Hung up."))
    except ProviderError as exc:
        raise SystemExit(f"{FAIL} {exc}") from exc
