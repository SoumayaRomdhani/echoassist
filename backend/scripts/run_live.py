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

The live-session body (disclosure→consent→conversation/interview) is the shared,
transport-agnostic ``src.telephony.live_session`` — the same code runs over a real
phone number in ``scripts/run_livekit.py``; only the Transport differs.

Honesty note: on CPU (this machine's default) a turn takes ~15-30 s, STT-dominated;
the goal here is the live chain, not latency. Sub-second turns need a GPU or cloud
STT/TTS (a config-only provider swap — STT_PROVIDER=deepgram / TTS_PROVIDER=cartesia).
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from config.settings import get_settings
from src.console import FAIL, dim, init_console
from src.log import setup_logging
from src.providers.errors import ProviderError
from src.runtime import use_selector_event_loop
from src.telephony.live_session import run_live_session
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

    transport = LocalAudioTransport(sample_rate=args.rate, input_device=device)
    try:
        await transport.start()
    except Exception as exc:  # noqa: BLE001 — no mic / unsupported rate is a clean exit, not a crash
        raise SystemExit(
            f"{FAIL} Could not open the microphone ({exc}).\n"
            "Check your input device, or pass --rate 48000 / --device <name>."
        ) from exc

    try:
        await run_live_session(transport, settings, interview=args.interview)
    finally:
        await transport.aclose()


if __name__ == "__main__":
    use_selector_event_loop()  # Selector loop: psycopg async (consent log / finalize) on Windows
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n" + dim("Hung up."))
    except ProviderError as exc:
        raise SystemExit(f"{FAIL} {exc}") from exc
