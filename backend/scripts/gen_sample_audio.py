"""Generate sample caller WAVs using the configured TTS provider.

Gives the replay harness separate clips per turn (the consent gate means consent
and the interview answer must be distinct turns, not one audio):

  - sample_consent.wav  : a clear "yes" to the consent question
  - sample_decline.wav  : a clear "no" (to demo the refusal path)
  - sample_answer.wav   : the candidate's answer (interview turn)

All clips are saved at 16 kHz mono (microphone-like), ready for `replay_audio.py`
or `telephonize.py`.

Usage:
    python scripts/gen_sample_audio.py                       # generate the clip set
    python scripts/gen_sample_audio.py --text "..." --out data/test_audio/custom.wav
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from config.settings import build_tts, get_settings
from src.audio.io import chunk_to_float, resample, write_wav
from src.console import init_console
from src.log import setup_logging
from src.providers.tts.base import TTSProvider

_OUTPUT_SR = 16000  # microphone-like input rate for STT

_CLIPS = {
    # Consent gate (Sprint 1)
    "sample_consent.wav": "Yes, that's fine, you can continue.",
    "sample_decline.wav": "No, I'd rather not. Please don't continue.",
    "sample_answer.wav": (
        "I have about five years of experience as a backend Python developer, "
        "mostly building APIs with FastAPI and Postgres. "
        "I'm available to start within a month, and I'm comfortable working remotely."
    ),
    # Full screening interview (Sprint 3) — one caller turn per clip, in order
    "interview_question.wav": "Actually, before that — is this role fully remote?",
    "interview_experience.wav": (
        "Sure. I have about six years of professional software experience, mostly with Python."
    ),
    "interview_stack.wav": "My main stack is Python with FastAPI, and PostgreSQL for the database.",
    "interview_availability.wav": "I could start in about three weeks.",
    "interview_remote.wav": (
        "Yes, I'm comfortable working remotely. I'm based in Tunis, in Central European Time."
    ),
    "interview_salary.wav": "I'm looking for around seventy-five thousand euros per year.",
    "interview_done.wav": "No, that's all from me. Thank you.",
}


async def _synthesize_to(tts: TTSProvider, text: str, path: Path) -> None:
    chunk = await tts.synthesize(text)
    samples = resample(chunk_to_float(chunk), chunk.fmt.sample_rate, _OUTPUT_SR)
    write_wav(path, samples, _OUTPUT_SR)
    print(f"wrote {path.name:<20} ({len(samples) / _OUTPUT_SR:.1f}s @ {_OUTPUT_SR}Hz)")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize sample caller WAVs via TTS.")
    parser.add_argument("--text", default=None, help="Synthesize a single custom clip.")
    parser.add_argument("--out", type=Path, default=None, help="Output path for --text.")
    args = parser.parse_args()

    settings = get_settings()
    init_console()
    setup_logging(settings.log_level)

    tts = build_tts(settings)
    out_dir = settings.data_dir / "test_audio"

    if args.text:
        await _synthesize_to(tts, args.text, args.out or (out_dir / "sample.wav"))
        return

    for name, text in _CLIPS.items():
        await _synthesize_to(tts, text, out_dir / name)


if __name__ == "__main__":
    asyncio.run(main())
