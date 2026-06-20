"""Local audio playback for the dev replay harness.

Playback is best-effort: on a headless machine or one without an output device,
it degrades gracefully (the caller still has the saved WAV).
"""

from __future__ import annotations

import asyncio
import logging

from src.audio.io import chunk_to_float
from src.providers.types import AudioChunk

log = logging.getLogger("echoassist.audio.playback")


def _play_sync(chunk: AudioChunk) -> None:
    import sounddevice as sd

    samples = chunk_to_float(chunk)
    sd.play(samples, chunk.fmt.sample_rate)
    sd.wait()


async def play(chunk: AudioChunk) -> bool:
    """Play an audio chunk on the default output device. Returns ``False`` if unavailable."""
    if not chunk.data:
        return True
    try:
        await asyncio.to_thread(_play_sync, chunk)
        return True
    except Exception as exc:  # noqa: BLE001 — no device / driver issue is non-fatal in dev
        log.warning("Audio playback unavailable (%s); skipping playback.", exc)
        return False
