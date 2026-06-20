"""Replay caller WAVs through the voice pipeline as if it were a live call.

This is the Sprint 1 Definition of Done, run as two distinct turns:
  1. disclosure  -> caller consent audio -> greeting (or decline + end the call)
  2. candidate answer audio -> agent reply

    python scripts/replay_audio.py
    python scripts/replay_audio.py --consent data/test_audio/sample_decline.wav   # refusal demo

Options:
    --consent <wav>   caller's answer to the consent question (default: sample_consent.wav)
    --answer  <wav>   candidate's interview answer            (default: sample_answer.wav)
    --out <wav>       where to save the spoken reply
    --no-play         do not play audio (save only)
    --no-realtime     feed files as fast as possible instead of pacing them live
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from config.settings import build_llm, build_stt, build_tts, get_settings
from src.agent.domain import load_domain_config
from src.agent.orchestrator import VoicePipeline
from src.audio.io import chunk_to_float, stream_wav, write_wav
from src.audio.playback import play
from src.console import bold, dim, init_console
from src.log import setup_logging

log = logging.getLogger("echoassist.replay")


def _parse_args() -> argparse.Namespace:
    data = get_settings().data_dir / "test_audio"
    parser = argparse.ArgumentParser(description="Replay a call through the EchoAssist pipeline.")
    parser.add_argument("--consent", type=Path, default=data / "sample_consent.wav",
                        help="Caller's answer to the consent question.")
    parser.add_argument("--answer", type=Path, default=data / "sample_answer.wav",
                        help="Candidate's interview answer (used only if consent is granted).")
    parser.add_argument("--out", type=Path, default=None, help="Where to save the reply WAV.")
    parser.add_argument("--no-play", action="store_true", help="Do not play audio (save only).")
    parser.add_argument("--no-realtime", action="store_true",
                        help="Feed files as fast as possible instead of pacing them in real time.")
    return parser.parse_args()


async def _emit(label: str, text: str, audio, *, play_audio: bool) -> None:
    print(f"\n{bold(label)} {text}")
    if play_audio:
        await play(audio)


async def main() -> None:
    args = _parse_args()
    settings = get_settings()
    init_console()
    setup_logging(settings.log_level)

    for path in (args.consent, args.answer):
        if not path.exists():
            raise SystemExit(f"Audio not found: {path}\nRun: python scripts/gen_sample_audio.py")

    log.info(
        "Providers: STT=%s LLM=%s TTS=%s | domain=%s",
        settings.stt_provider.value,
        settings.llm_provider.value,
        settings.tts_provider.value,
        settings.domain,
    )

    domain = load_domain_config(settings.domain, settings.config_dir)
    pipeline = VoicePipeline(build_stt(settings), build_llm(settings), build_tts(settings), domain)
    play_audio = not args.no_play
    realtime = not args.no_realtime

    try:
        # Turn 1 — disclosure, then gate on spoken consent.
        disclosure_text, disclosure_audio = await pipeline.speak_disclosure()
        await _emit("AGENT (disclosure):", disclosure_text, disclosure_audio, play_audio=play_audio)

        consent = await pipeline.handle_consent(stream_wav(args.consent, realtime=realtime))
        print(f"\n{bold('CALLER (consent):')} {consent.transcript or '(silence)'}  "
              f"{dim('[' + consent.decision.value + ']')}")
        await _emit("AGENT:", consent.reply, consent.audio, play_audio=play_audio)

        if consent.ended:
            print(dim("\nCall ended — consent not given. The interview was not conducted."))
            return
        if not consent.proceed:
            print(dim("\nConsent unclear — re-asked. Provide a clearer consent clip to continue."))
            return

        # Turn 2 — the interview answer (only reached once consent is granted).
        result = await pipeline.run_turn(stream_wav(args.answer, realtime=realtime))
        print(f"\n{bold('CALLER (answer):')} {result.transcript or '(silence)'}")
        await _emit("AGENT (reply):", result.reply, result.audio, play_audio=play_audio)

        t = result.timings
        print(dim(
            f"\nlatency  stt={t.stt_ms:.0f}ms  llm={t.llm_ms:.0f}ms  "
            f"tts={t.tts_ms:.0f}ms  total={t.total_ms:.0f}ms"
        ))

        out_path = args.out or (settings.data_dir / "test_audio" / "reply.wav")
        write_wav(out_path, chunk_to_float(result.audio), result.audio.fmt.sample_rate)
        print(dim(f"saved reply -> {out_path}"))
    finally:
        await pipeline.aclose()


if __name__ == "__main__":
    asyncio.run(main())
