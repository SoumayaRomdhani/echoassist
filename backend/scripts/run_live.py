"""Talk to the agent live through your microphone (Sprint 8 — first live transport).

The Sprint 1 speaking loop and the consent gate, driven by a real microphone and
speakers instead of replayed WAVs. It swaps the file source/sink for
:class:`LocalAudioTransport` and changes nothing in the pipeline — the same
``VoicePipeline`` the replay harness uses (ARCHITECTURE.md §2, §4).

    python scripts/run_live.py
    python scripts/run_live.py --rate 48000      # if your mic rejects 16 kHz
    python scripts/run_live.py --device "USB"    # pick an input device by name/index

Speak after each "listening…" prompt; pause when you're done and the agent
replies. Talk over the agent to cut it off (barge-in). Press Ctrl-C to hang up.
Headphones REQUIRED — there is no echo cancellation, so on open speakers the mic
hears the agent and trips a false barge-in.

Scope: this validates the live *duplex turn loop*, barge-in, and the consent gate
with the local providers — a plain conversational loop (STT -> LLM -> TTS), so it
needs no Qdrant/Redis/Postgres. The grounded screening interview is the same wiring
as ``run_interview.py`` with ``transport.listen()`` in place of ``stream_wav``;
live telephony (LiveKit + SIP) is the next step.

Honesty note: on CPU (this machine's default) a turn takes ~20-30 s, STT-dominated;
the goal here is the live chain, not latency. Sub-second turns need a GPU or cloud
STT/TTS (a config-only provider swap).
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from config.settings import build_llm_with_failover, build_stt, build_tts, get_settings
from src.agent.domain import load_domain_config
from src.agent.orchestrator import VoicePipeline
from src.console import FAIL, bold, dim, init_console
from src.log import setup_logging
from src.providers.errors import ProviderError
from src.telephony.local_audio import LocalAudioTransport

log = logging.getLogger("echoassist.live")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Talk to the EchoAssist agent live via microphone."
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
    print(f"\n{bold(label)} {text}")
    barged = await transport.send_interruptible(audio)
    if barged:
        print(dim("  [barge-in — you talked over the agent]"))
    return barged


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
        "Providers: STT=%s LLM=%s TTS=%s | domain=%s",
        settings.stt_provider.value,
        settings.llm_provider.value,
        settings.tts_provider.value,
        settings.domain,
    )

    domain = load_domain_config(settings.domain, settings.config_dir)
    pipeline = VoicePipeline(
        build_stt(settings), build_llm_with_failover(settings), build_tts(settings), domain
    )
    transport = LocalAudioTransport(sample_rate=args.rate, input_device=device)

    try:
        await transport.start()
    except Exception as exc:  # noqa: BLE001 — no mic / unsupported rate is a clean exit, not a crash
        raise SystemExit(
            f"{FAIL} Could not open the microphone ({exc}).\n"
            "Check your input device, or pass --rate 48000 / --device <name>."
        ) from exc

    try:
        text, audio = await pipeline.speak_disclosure()
        await _say(transport, "AGENT (disclosure):", text, audio)

        print(dim("\n[listening — answer the consent question, then pause]"))
        consent = await pipeline.handle_consent(transport.listen())
        print(
            f"\n{bold('YOU:')} {consent.transcript or '(silence)'}  "
            f"{dim('[' + consent.decision.value + ']')}"
        )
        await _say(transport, "AGENT:", consent.reply, consent.audio)
        if consent.ended or not consent.proceed:
            print(dim("\nCall ended."))
            return

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
    finally:
        await transport.aclose()
        await pipeline.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n" + dim("Hung up."))
    except ProviderError as exc:
        raise SystemExit(f"{FAIL} {exc}") from exc
