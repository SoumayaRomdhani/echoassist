"""Transport abstraction — the boundary between a call and the voice pipeline.

A *transport* is whatever carries a call's audio: the dev replay harness (files),
a local microphone + speaker (this sprint's first live brick), or — later in
Sprint 8 — a LiveKit/SIP room bridged to the PSTN. Each one turns its medium into
the single streaming shape :class:`~src.agent.orchestrator.VoicePipeline` already
expects: an utterance of PCM16 :class:`AudioChunk` in, agent ``AudioChunk`` out.

Business logic depends only on this interface (ARCHITECTURE.md §2 — no vendor SDK
in business logic). Swapping local audio for LiveKit changes the implementation
here, never the pipeline: the pipeline consumes ``transport.listen()`` exactly as
it consumes ``stream_wav(path)`` today.

Turn model: one :meth:`listen` call == one caller utterance. The returned stream
ends when the caller stops speaking (endpoint detected) or the call ends — the
half-duplex turn loop the pipeline runs today. Full-duplex *barge-in* (letting
``listen`` and ``send`` overlap and cancelling playback on speech) is the next
telephony step, layered on this same interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from src.providers.types import AudioChunk


class Transport(ABC):
    """Carries one call's audio to and from the voice pipeline."""

    async def start(self) -> None:  # noqa: B027 — optional lifecycle hook, default no-op
        """Open the transport (acquire devices / connect). Override if needed."""

    @abstractmethod
    def listen(self) -> AsyncIterator[AudioChunk]:
        """Yield PCM16 chunks for the caller's next utterance.

        One call corresponds to one caller turn; the returned stream ends at the
        utterance endpoint (a run of trailing silence) or when the call ends.
        """
        raise NotImplementedError

    @abstractmethod
    async def send(self, audio: AudioChunk) -> None:
        """Emit one chunk of agent audio to the caller."""
        raise NotImplementedError

    async def send_interruptible(self, audio: AudioChunk) -> bool:
        """Play agent audio, letting the caller barge in. Return ``True`` if interrupted.

        Default: no duplex — play the whole chunk and report no barge-in. A live
        transport that can listen while it speaks overrides this to cut playback the
        moment the caller starts talking over the agent.
        """
        await self.send(audio)
        return False

    async def send_stream(self, audio: AsyncIterator[AudioChunk]) -> None:
        """Emit a stream of agent audio. Default: forward each chunk to :meth:`send`."""
        async for chunk in audio:
            await self.send(chunk)

    async def send_stream_interruptible(self, audio: AsyncIterator[AudioChunk]) -> bool:
        """Play a stream of agent audio chunk-by-chunk, letting the caller barge in.

        Each chunk is played via :meth:`send_interruptible`, so audio starts at the
        first sentence (low time-to-first-audio) instead of after the whole reply is
        synthesized — this is how streaming reaches the live path (L2). The per-chunk
        barge-in of any duplex transport composes for free; a non-duplex transport just
        plays every chunk and reports no barge-in.

        On a barge-in, playback stops at once but the stream is still **drained to
        exhaustion**: its producer (the dialogue's streaming turn) records the spoken
        turn and persists state only once fully consumed, so abandoning it early would
        drop that turn's slot/advance. Returns ``True`` if the caller interrupted.
        """
        barged = False
        async for chunk in audio:
            if barged:
                continue  # drain remaining audio so the producer finishes its bookkeeping
            barged = await self.send_interruptible(chunk)
        return barged

    async def aclose(self) -> None:  # noqa: B027 — optional lifecycle hook, default no-op
        """Release devices / connections. Override if needed."""
