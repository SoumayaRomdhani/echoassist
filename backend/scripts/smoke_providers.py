"""Smoke-test the configured STT + TTS providers end to end — no microphone, no phone.

Round-trips one line of text: the **TTS** synthesizes it to PCM audio, then the
**STT** transcribes that audio back to text. This validates real provider keys
(Deepgram / Cartesia / ElevenLabs, or the local whisper/kokoro defaults) and prints
per-stage latency, so the cloud-vs-CPU difference is visible without a mic or a call.

    python scripts/smoke_providers.py
    python scripts/smoke_providers.py --text "Bonjour, je suis le candidat." --lang fr
    python scripts/smoke_providers.py --keep            # keep the generated wav

Providers come from .env (STT_PROVIDER / TTS_PROVIDER + keys). Override per-run from
the shell to test a specific combo without editing .env, e.g. (PowerShell):

    $env:STT_PROVIDER="deepgram"; $env:TTS_PROVIDER="cartesia"; python scripts/smoke_providers.py

A misconfigured provider (missing key / voice id) exits with a clean message, not a
traceback. Note: with the local defaults the STT step is slow (CPU whisper); cloud
providers return in well under a second.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import tempfile
import time
from pathlib import Path

from config.settings import Settings, build_stt, build_tts, get_settings
from src.audio.io import chunk_to_float, stream_wav, write_wav
from src.console import FAIL, OK, bold, dim, init_console
from src.log import setup_logging
from src.providers.errors import ProviderError

log = logging.getLogger("echoassist.smoke")

_DEFAULT_TEXT = (
    "Hello, I have five years of experience with Python, "
    "and I am available to start in two weeks."
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Round-trip the configured TTS + STT providers (no mic, no phone)."
    )
    parser.add_argument("--text", default=_DEFAULT_TEXT, help="Line to speak then transcribe.")
    parser.add_argument(
        "--lang", default=None,
        help="Pin the STT language, e.g. 'en' or 'fr' (sets WHISPER_LANGUAGE + DEEPGRAM_LANGUAGE).",
    )
    parser.add_argument(
        "--keep", action="store_true",
        help="Keep the generated wav (default: delete it on exit).",
    )
    return parser.parse_args()


def _apply_lang(settings: Settings, lang: str | None) -> Settings:
    if not lang:
        return settings
    return settings.model_copy(update={"whisper_language": lang, "deepgram_language": lang})


async def main() -> None:
    args = _parse_args()
    init_console()
    settings = _apply_lang(get_settings(), args.lang)
    setup_logging(settings.log_level)

    print(
        bold("Providers: ")
        + f"STT={settings.stt_provider.value}  TTS={settings.tts_provider.value}"
    )

    tts = build_tts(settings)
    stt = build_stt(settings)
    out = Path(tempfile.gettempdir()) / "echoassist_smoke.wav"
    try:
        t0 = time.perf_counter()
        spoken = await tts.synthesize(args.text)
        tts_ms = (time.perf_counter() - t0) * 1000
        write_wav(out, chunk_to_float(spoken), spoken.fmt.sample_rate)
        print(
            f"  TTS  {spoken.duration_s:5.1f}s audio @ {spoken.fmt.sample_rate} Hz "
            f"in {tts_ms:7.0f} ms  -> {out.name}"
        )

        t1 = time.perf_counter()
        heard = await stt.transcribe(stream_wav(out, realtime=False))
        stt_ms = (time.perf_counter() - t1) * 1000
        print(f"  STT  transcribed in {stt_ms:7.0f} ms")

        print(bold("\n  said : ") + args.text)
        print(bold("  heard: ") + (heard.text or dim("(empty)")))
        print(f"\n{OK} round-trip complete "
              + dim("(heard ≈ said means both providers work end to end)"))
    finally:
        await tts.aclose()
        await stt.aclose()
        if not args.keep:
            out.unlink(missing_ok=True)
        elif out.exists():
            print(dim(f"kept {out}"))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n" + dim("aborted."))
    except ProviderError as exc:
        raise SystemExit(f"{FAIL} {exc}") from exc
