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

    # Whether pre-synthesizing many static lines concurrently is safe/beneficial.
    # Cloud HTTP providers (Deepgram/Cartesia/ElevenLabs) set True so the static-line
    # cache warms in parallel (one RTT total instead of one-per-line). Local single-model
    # providers (Kokoro) keep False — overlapping inference only thrashes one CPU pipeline.
    concurrent_warm: bool = False

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


async def aligned_pcm16(
    byte_stream: AsyncIterator[bytes], fmt: AudioFormat
) -> AsyncIterator[AudioChunk]:
    """Re-chunk a raw little-endian PCM16 byte stream into sample-aligned AudioChunks.

    Cloud TTS streams raw ``pcm`` / ``linear16`` over HTTP chunks whose boundaries can
    fall *inside* a 16-bit sample (an odd byte count). Downstream playback decodes each
    chunk with ``np.frombuffer(..., '<i2')``, which requires whole samples — an odd-length
    chunk raises ``ValueError`` and crashes the turn. We carry the trailing partial sample
    to the next chunk and emit only sample-aligned blocks, so every :class:`AudioChunk` a
    streaming provider yields is safe to decode on its own. A leftover sub-sample tail at
    end-of-stream is incomplete audio and dropped (sub-millisecond).
    """
    width = fmt.sample_width * fmt.channels
    carry = b""
    async for data in byte_stream:
        if not data:
            continue
        carry += data
        cut = len(carry) - (len(carry) % width)
        if cut:
            yield AudioChunk(data=carry[:cut], fmt=fmt)
            carry = carry[cut:]
