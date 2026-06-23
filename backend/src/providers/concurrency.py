"""Concurrency guards for shared, non-reentrant CPU providers.

The local Whisper (STT) and Kokoro (TTS) models are single instances shared
across calls and are *not* safe to invoke concurrently — and on a small CPU box
overlapping inference only thrashes memory. These thin wrappers serialize model
access behind an :class:`asyncio.Lock` while preserving the provider interfaces,
so the orchestrator stays unaware that providers are shared.

Pass one lock to all guards that wrap the same hardware so model work across
concurrent calls runs one at a time (Sprint 6 concurrency requirement; the
Sprint 8 live-duplex path will revisit this with per-call workers / a pool).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from src.providers.stt.base import STTProvider
from src.providers.tts.base import TTSProvider
from src.providers.types import AudioChunk, AudioFormat, Transcript


class SerializedSTT(STTProvider):
    """Wrap an STT provider so only one transcription runs at a time."""

    def __init__(self, inner: STTProvider, lock: asyncio.Lock) -> None:
        self._inner = inner
        self._lock = lock

    async def transcribe_stream(
        self, audio: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[Transcript]:
        async with self._lock:
            async for transcript in self._inner.transcribe_stream(audio):
                yield transcript

    async def aclose(self) -> None:
        await self._inner.aclose()


class SerializedTTS(TTSProvider):
    """Wrap a TTS provider so only one synthesis runs at a time."""

    def __init__(self, inner: TTSProvider, lock: asyncio.Lock) -> None:
        self._inner = inner
        self._lock = lock

    @property
    def output_format(self) -> AudioFormat:
        return self._inner.output_format

    async def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
        async with self._lock:
            async for chunk in self._inner.synthesize_stream(text):
                yield chunk

    async def aclose(self) -> None:
        await self._inner.aclose()
