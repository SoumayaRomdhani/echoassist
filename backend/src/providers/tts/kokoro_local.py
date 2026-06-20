"""Kokoro text-to-speech (open-source default).

Kokoro outputs 24 kHz mono float32 audio. The pipeline is loaded lazily and the
blocking synthesis runs in a worker thread. Kokoro segments long text on its
own; each segment is yielded as it is produced so the transport can start
playback early (ARCHITECTURE.md §9 — TTS first audio ~150 ms).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import numpy as np

from src.audio.io import chunk_from_float
from src.providers.tts.base import TTSProvider
from src.providers.types import AudioChunk, AudioFormat

if TYPE_CHECKING:
    from kokoro import KPipeline

log = logging.getLogger("echoassist.tts.kokoro")

_SAMPLE_RATE = 24000


class KokoroTTS(TTSProvider):
    def __init__(
        self,
        *,
        lang_code: str = "a",
        voice: str = "af_heart",
        speed: float = 1.0,
    ) -> None:
        self._lang_code = lang_code
        self._voice = voice
        self._speed = speed
        self._pipeline: KPipeline | None = None

    @property
    def output_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=_SAMPLE_RATE)

    def _ensure_pipeline(self) -> KPipeline:
        if self._pipeline is None:
            from kokoro import KPipeline

            log.info("Loading Kokoro pipeline lang_code=%s voice=%s", self._lang_code, self._voice)
            self._pipeline = KPipeline(lang_code=self._lang_code)
        return self._pipeline

    def _synthesize_sync(self, text: str) -> list[np.ndarray]:
        pipeline = self._ensure_pipeline()
        segments: list[np.ndarray] = []
        for _graphemes, _phonemes, audio in pipeline(text, voice=self._voice, speed=self._speed):
            # Kokoro returns a torch tensor or numpy array depending on version.
            array = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            segments.append(array.astype(np.float32))
        return segments

    async def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return
        segments = await asyncio.to_thread(self._synthesize_sync, text)
        for segment in segments:
            yield chunk_from_float(segment, _SAMPLE_RATE)
