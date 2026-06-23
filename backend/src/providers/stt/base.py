"""Speech-to-text provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from src.observability.tracing import span
from src.providers.types import AudioChunk, Transcript


async def _as_stream(chunk: AudioChunk) -> AsyncIterator[AudioChunk]:
    yield chunk


class STTProvider(ABC):
    """Streaming speech-to-text.

    Implementations consume an async stream of :class:`AudioChunk` and yield
    :class:`Transcript` objects. Interim results may be yielded with
    ``is_final=False``; at least one ``is_final=True`` transcript is expected
    once the input stream ends.
    """

    @abstractmethod
    def transcribe_stream(
        self, audio: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[Transcript]:
        """Transcribe a live audio stream. Returns an async iterator of transcripts."""
        raise NotImplementedError

    async def transcribe(self, audio: AudioChunk | AsyncIterator[AudioChunk]) -> Transcript:
        """Convenience: transcribe a whole utterance and return the final transcript."""
        stream = audio.__aiter__() if hasattr(audio, "__aiter__") else _as_stream(audio)  # type: ignore[arg-type]
        # Stage span — no transcript text in attributes (it is PII).
        with span("stt.transcribe"):
            final = Transcript(text="")
            async for t in self.transcribe_stream(stream):  # type: ignore[arg-type]
                if t.is_final:
                    final = t
            return final

    async def aclose(self) -> None:  # noqa: B027 — optional override hook, default no-op
        """Release any held resources. Override if needed."""
