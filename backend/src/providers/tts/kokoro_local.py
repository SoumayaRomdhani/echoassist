"""Kokoro text-to-speech (open-source default).

Kokoro outputs 24 kHz mono float32 audio. The pipeline is loaded lazily and the
blocking synthesis runs in a worker thread. Kokoro segments long text on its
own; each segment is yielded as it is produced so the transport can start
playback early (ARCHITECTURE.md §9 — TTS first audio ~150 ms).

Language mirroring (Sprint 8, FR/EN): a Kokoro voice speaks ONE language (it is
tied to an espeak-ng ``lang_code`` bound when the pipeline is built), so a fixed
English voice cannot pronounce a French reply. Instead of pinning one language,
this provider keeps a default (English) voice and a French voice and picks per
utterance: it detects whether the text is French and, if so, synthesizes with the
French pipeline + voice; otherwise it uses the default. This lets the offline path
mirror the caller's language — English opening, French once the caller speaks
French — the same way the cloud providers do. One :class:`KPipeline` is cached
per ``lang_code`` (each is heavy), built lazily on first use of that language.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import numpy as np

from src.audio.io import chunk_from_float
from src.providers.tts.base import TTSProvider
from src.providers.tts.language import looks_french
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
        lang_code_fr: str = "f",
        voice_fr: str = "ff_siwis",
        speed: float = 1.0,
    ) -> None:
        self._lang_code = lang_code
        self._voice = voice
        self._lang_code_fr = lang_code_fr
        self._voice_fr = voice_fr
        self._speed = speed
        # One heavy KPipeline per lang_code, built lazily on first use of that language.
        self._pipelines: dict[str, KPipeline] = {}

    @property
    def output_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=_SAMPLE_RATE)

    def _select(self, text: str) -> tuple[str, str]:
        """Return the (lang_code, voice) to use for ``text`` — French when detected, else default."""
        if looks_french(text):
            return self._lang_code_fr, self._voice_fr
        return self._lang_code, self._voice

    def _ensure_pipeline(self, lang_code: str) -> KPipeline:
        pipeline = self._pipelines.get(lang_code)
        if pipeline is None:
            from kokoro import KPipeline

            log.info("Loading Kokoro pipeline lang_code=%s", lang_code)
            pipeline = KPipeline(lang_code=lang_code)
            self._pipelines[lang_code] = pipeline
        return pipeline

    @staticmethod
    def _to_float32(audio) -> np.ndarray:
        # Kokoro returns a torch tensor or numpy array depending on version.
        array = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
        return array.astype(np.float32)

    async def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return
        lang_code, voice = self._select(text)
        # Bridge Kokoro's blocking per-segment generator (worker thread) to async via
        # a queue, so the FIRST segment is yielded as soon as it's ready — not after
        # the whole text is synthesized. This is what improves time-to-first-audio.
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        sentinel = object()

        def produce() -> None:
            try:
                pipeline = self._ensure_pipeline(lang_code)
                segments = pipeline(text, voice=voice, speed=self._speed)
                for _graphemes, _phonemes, audio in segments:
                    loop.call_soon_threadsafe(queue.put_nowait, self._to_float32(audio))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, sentinel)

        worker = loop.run_in_executor(None, produce)
        try:
            while True:
                item = await queue.get()
                if item is sentinel:
                    break
                yield chunk_from_float(item, _SAMPLE_RATE)
        finally:
            await worker
