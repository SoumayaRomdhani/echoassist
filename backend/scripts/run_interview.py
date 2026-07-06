"""Run a full screening interview end-to-end from replayed audio.

This is the Sprint 3 Definition of Done: disclosure -> consent -> the agent
leads the structured interview (filling slots), answers the caller's own
questions from the knowledge base, and closes — all from replayed WAVs.

    python scripts/run_interview.py            # uses the generated interview clips
    python scripts/run_interview.py --no-play --no-realtime

Requires Qdrant + Redis running and the domain ingested:
    docker compose -f ../docker-compose.yml up -d qdrant redis
    python scripts/ingest_docs.py
    python scripts/gen_sample_audio.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from pathlib import Path

from config.settings import (
    build_engine,
    build_llm,
    build_retriever,
    build_state_store,
    build_stt,
    build_tts,
    get_settings,
)
from src.agent.dialogue import DialogueManager, LLMTurnClassifier
from src.agent.domain import load_domain_config
from src.agent.finalize import finalize_call
from src.agent.grounding import GroundedResponder
from src.agent.notes import load_notes_schema
from src.agent.orchestrator import VoicePipeline
from src.agent.state import ConversationState
from src.agent.streaming import resolve_chunk_policy
from src.audio.io import stream_wav
from src.audio.playback import play
from src.console import FAIL, bold, dim, init_console
from src.log import setup_logging
from src.observability import latency
from src.providers.errors import ProviderError
from src.runtime import use_selector_event_loop
from src.storage.db import init_db, make_sessionmaker
from src.telephony.live_session import _warm_retriever

log = logging.getLogger("echoassist.interview")

# Caller turns, in order: four answers, a mid-question detour (RAG) during the salary
# question, then salary + "done". The detour sits late on purpose so the background RAG
# warm (see run_live_session) has time to finish before the only turn that needs it —
# letting you observe the cold-load moving to startup without a microphone.
_DEFAULT_ANSWERS = [
    "interview_experience.wav",
    "interview_stack.wav",
    "interview_availability.wav",
    "interview_remote.wav",
    "interview_question.wav",
    "interview_salary.wav",
    "interview_done.wav",
]


def _parse_args(data_dir: Path) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a full screening interview from audio.")
    parser.add_argument("--consent", type=Path, default=data_dir / "sample_consent.wav")
    parser.add_argument("--no-play", action="store_true", help="Do not play audio (save only).")
    parser.add_argument("--no-realtime", action="store_true", help="Feed audio without pacing.")
    return parser.parse_args()


async def _emit(label: str, text: str, audio, *, play_audio: bool) -> None:
    print(f"\n{bold(label)} {text}")
    if play_audio:
        await play(audio)


async def main() -> None:
    settings = get_settings()
    init_console()
    setup_logging(settings.log_level)
    data_dir = settings.data_dir / "test_audio"
    args = _parse_args(data_dir)

    answer_paths = [data_dir / name for name in _DEFAULT_ANSWERS]
    for path in (args.consent, *answer_paths):
        if not path.exists():
            raise SystemExit(f"Audio not found: {path}\nRun: python scripts/gen_sample_audio.py")

    domain = load_domain_config(settings.domain, settings.config_dir)
    llm = build_llm(settings)
    retriever = build_retriever(settings)
    # Warm the RAG models in the background at startup (same fix as the live path), so the
    # candidate-question turn doesn't pay their cold load. Watch: with realtime pacing the
    # "Loading FastEmbed…" lines appear now, not on the RAG turn.
    rag_warm_task = asyncio.create_task(_warm_retriever(retriever))
    store = build_state_store(settings)
    state = ConversationState(call_id=uuid.uuid4().hex)
    dialogue = DialogueManager(
        classifier=LLMTurnClassifier(llm),
        responder=GroundedResponder(
            llm, retriever, system_prompt=domain.system_prompt,
            min_confidence=settings.grounding_min_confidence,
            fallback_message=domain.fallback_prompt or None,
        ),
        domain=domain,
        state=state,
        store=store,
        redact=settings.redact_pii,
    )
    pipeline = VoicePipeline(
        build_stt(settings), llm, build_tts(settings), domain, dialogue=dialogue,
        stream_coalesce=settings.tts_local_smoothing,
        chunk_policy=resolve_chunk_policy(settings, domain),
    )

    play_audio = not args.no_play
    realtime = not args.no_realtime
    log.info("call_id=%s | state backend=%s", state.call_id, settings.state_backend.value)

    try:
        disclosure_text, disclosure_audio = await pipeline.speak_disclosure()
        await _emit("AGENT (disclosure):", disclosure_text, disclosure_audio, play_audio=play_audio)

        consent = await pipeline.handle_consent(stream_wav(args.consent, realtime=realtime))
        tag = dim(f"[{consent.decision.value}]")
        print(f"\n{bold('CALLER:')} {consent.transcript}  {tag}")
        await _emit("AGENT:", consent.reply, consent.audio, play_audio=play_audio)
        if not consent.proceed:
            print(dim("\nCall ended — consent not given."))
            return
        # consent_granted is persisted to the call state by the pipeline (handle_consent).

        question_text, question_audio = await pipeline.begin_interview()
        await _emit("AGENT (question):", question_text, question_audio, play_audio=play_audio)

        for turn_id, path in enumerate(answer_paths, start=1):
            # Streaming turn: audio starts at the first sentence (grounded answers
            # stream from the LLM), instead of waiting for the whole reply. The whole
            # turn (through consuming the audio stream) runs inside record_turn so the
            # deep pipeline spans land on this turn (no-op unless LATENCY_LOGGING=true).
            with latency.record_turn(
                settings.data_dir, turn_id=turn_id, **latency.config_fields(settings)
            ):
                caller_text, _is_rag, audio_stream = await pipeline.interview_turn_streaming(
                    stream_wav(path, realtime=realtime)
                )
                print(f"\n{bold('CALLER:')} {caller_text}")
                async for chunk in audio_stream:  # consume as it streams
                    if play_audio:
                        await play(chunk)
                reply_text = state.transcript[-1]["text"] if state.transcript else ""
                print(f"{bold('AGENT:')} {reply_text}")
            if dialogue.finished:
                break

        print(bold("\n\n--- Interview complete ---"))
        print(f"{bold('Filled slots:')}")
        for slot, value in state.slots.items():
            print(f"  {slot}: {value}")

        # Sprint 4: extract structured notes + summary and persist to Postgres.
        engine = build_engine(settings)
        await init_db(engine)
        schema = load_notes_schema(settings.domain, settings.config_dir)
        try:
            async with make_sessionmaker(engine)() as session:
                final = await finalize_call(
                    session, state, llm=llm, schema=schema,
                    campaign_name=settings.default_campaign, domain=settings.domain,
                    redact=settings.redact_pii,
                )
        finally:
            await engine.dispose()

        print(f"\n{bold('Notes (persisted):')}")
        for key, value in final.notes.items():
            print(f"  {key}: {value}")
        print(f"\n{bold('Summary:')} {final.summary}")
        print(dim(f"\npersisted to Postgres: campaign='{settings.default_campaign}' "
                  f"call db id={final.call.id} (status={final.call.status})"))
    finally:
        if not rag_warm_task.done():
            rag_warm_task.cancel()
        await pipeline.aclose()
        await store.aclose()


if __name__ == "__main__":
    use_selector_event_loop()
    try:
        asyncio.run(main())
    except ProviderError as exc:
        raise SystemExit(f"{FAIL} {exc}") from exc
