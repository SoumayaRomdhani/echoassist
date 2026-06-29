"""Run the EchoAssist agent over a LiveKit room — WebRTC loopback, then real PSTN.

Same live screening session as ``scripts/run_live.py``, but the caller's audio
arrives over a LiveKit room instead of the local microphone. Only the Transport
differs (``LiveKitTransport`` vs ``LocalAudioTransport``); the disclosure→consent→
conversation/interview body is the shared ``src.telephony.live_session`` and the
voice pipeline is untouched (ARCHITECTURE.md §2, §4 — the whole point of the seam).

    python scripts/run_livekit.py                 # free conversation over WebRTC
    python scripts/run_livekit.py --interview     # the full structured screening
    python scripts/run_livekit.py --lang en       # pin the STT language
    python scripts/run_livekit.py --room demo-1   # override LIVEKIT_ROOM

Two-step rollout (see backend/docs/demo_screening.md):
  1. SAFE FIRST — WebRTC loopback, no phone number: start this script; it joins the
     room and waits. Open the printed meet.livekit.io URL in a browser, allow the
     mic, and you are the caller. WebRTC does echo cancellation, so barge-in works
     without headphones.
  2. PSTN — wire a LiveKit SIP inbound trunk + dispatch rule to a Twilio number that
     routes calls into the same room. The caller is then just another participant →
     this script is UNCHANGED; you dial the number instead of opening a browser.

Config: set LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET in backend/.env
(LiveKit Cloud dashboard or a self-hosted server). Without them this exits with a
clear message — no account, no run.

Honesty note: latency is dominated by the STT/LLM/TTS providers, not the transport.
On the CPU defaults a turn is ~15-30 s; cloud providers (STT_PROVIDER=deepgram,
TTS_PROVIDER=cartesia) bring it to interactive speed — a config-only swap.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from config.settings import get_settings
from src.console import FAIL, bold, dim, init_console
from src.log import setup_logging
from src.providers.errors import ProviderConfigError, ProviderError
from src.runtime import use_selector_event_loop
from src.telephony.live_session import run_live_session
from src.telephony.livekit_transport import LiveKitTransport, guest_meet_url
from src.telephony.vad import EndpointConfig

log = logging.getLogger("echoassist.live")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the EchoAssist agent over a LiveKit room (WebRTC loopback / SIP)."
    )
    parser.add_argument(
        "--interview", action="store_true",
        help="Run the full structured screening interview (needs Qdrant + Redis + Postgres).",
    )
    parser.add_argument(
        "--lang", default=None,
        help="Pin the STT language, e.g. 'en' or 'fr' (default: WHISPER_LANGUAGE / auto-detect).",
    )
    parser.add_argument(
        "--room", default=None,
        help="Override LIVEKIT_ROOM for this run.",
    )
    parser.add_argument(
        "--vad-threshold",
        type=float,
        default=0.015,
        help="Speech energy threshold for LiveKit inbound audio (lower if mic is quiet).",
    )
    parser.add_argument(
        "--audio-debug",
        action="store_true",
        help="Log inbound LiveKit audio frame/RMS diagnostics.",
    )
    return parser.parse_args()


def _print_join_hint(settings) -> None:
    """Print the browser URL a human opens to join as the caller (WebRTC loopback)."""
    print(bold("\nLiveKit room: ") + settings.livekit_room)
    print(dim("Open this URL in a browser to join as the caller (then allow the mic):"))
    print(
        "  "
        + guest_meet_url(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
            room=settings.livekit_room,
        )
    )
    print(dim("(Or dial the SIP/PSTN number once telephony is wired — see the runbook.)\n"))


async def main() -> None:
    args = _parse_args()
    settings = get_settings()
    overrides: dict[str, object] = {}
    if args.lang:
        overrides["whisper_language"] = args.lang
    if args.room:
        overrides["livekit_room"] = args.room
    if overrides:
        settings = settings.model_copy(update=overrides)
    init_console()
    setup_logging(settings.log_level)

    try:
        transport = LiveKitTransport(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
            room=settings.livekit_room,
            identity=settings.livekit_identity,
            endpoint=EndpointConfig(energy_threshold=args.vad_threshold),
            audio_debug=args.audio_debug,
        )
    except ProviderConfigError as exc:
        raise SystemExit(f"{FAIL} {exc}") from exc

    _print_join_hint(settings)

    try:
        await transport.start()  # connect, publish the agent track, wait for the caller
    except Exception as exc:  # noqa: BLE001 — bad creds / no caller joined is a clean exit
        raise SystemExit(
            f"{FAIL} Could not start the LiveKit call ({exc}).\n"
            "Check LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET, and that a caller joined."
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
