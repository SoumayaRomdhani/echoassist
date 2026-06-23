"""Text-to-speech provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from src.observability.tracing import span
from src.providers.types import AudioChunk, AudioFormat


class TTSProvider(ABC):
    """Streaming text-to-speech.

    Implementations synthesize ``text`` into a stream of :class:`AudioChunk`,
    all sharing :attr:`output_format`. Streaming lets the transport start
    playback before synthesis finishes.
    """

    @property
    @abstractmethod
    def output_format(self) -> AudioFormat:
        """The format of every chunk produced by :meth:`synthesize_stream`."""
        raise NotImplementedError

    @abstractmethod
    def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
        """Synthesize ``text``; yields audio chunks in :attr:`output_format`."""
        raise NotImplementedError

    async def synthesize(self, text: str) -> AudioChunk:
        """Convenience: synthesize the whole text into a single concatenated chunk."""
        # Stage span — no spoken text in attributes (it can carry PII).
        with span("tts.synthesize"):
            buffer = bytearray()
            async for chunk in self.synthesize_stream(text):
                buffer.extend(chunk.data)
            return AudioChunk(data=bytes(buffer), fmt=self.output_format)

    async def aclose(self) -> None:  # noqa: B027 — optional override hook, default no-op
        """Release any held resources. Override if needed."""
