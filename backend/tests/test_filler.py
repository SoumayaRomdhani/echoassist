"""Perceived-latency filler for slow grounded turns (no hardware, no models)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from src.providers.types import AudioChunk, AudioFormat
from src.telephony.live_session import _play_with_filler
from src.telephony.transport import Transport

_FMT = AudioFormat(sample_rate=24000)


def _chunk(text: str) -> AudioChunk:
    return AudioChunk(data=text.encode("utf-8"), fmt=_FMT)


class _RecordTransport(Transport):
    """Records the single-chunk plays (filler) separately from the streamed real audio."""

    def __init__(self) -> None:
        self.played: list[AudioChunk] = []      # via send_interruptible (the filler)
        self.streamed: list[AudioChunk] = []    # via send_stream_interruptible (the answer)

    async def listen(self) -> AsyncIterator[AudioChunk]:
        for _ in ():
            yield _

    async def send(self, audio: AudioChunk) -> None:
        self.streamed.append(audio)

    async def send_interruptible(self, audio: AudioChunk) -> bool:
        self.played.append(audio)
        return False

    async def send_stream_interruptible(self, audio: AsyncIterator[AudioChunk]) -> bool:
        async for chunk in audio:
            self.streamed.append(chunk)
        return False


async def _answer(*, warmup: float) -> AsyncIterator[AudioChunk]:
    await asyncio.sleep(warmup)   # time before the first real audio chunk is ready
    for text in ("real-1", "real-2"):
        yield _chunk(text)


@pytest.mark.asyncio
async def test_filler_plays_when_the_answer_is_slow_then_the_real_audio() -> None:
    transport = _RecordTransport()
    filler = _chunk("Let me check that.")

    barged = await _play_with_filler(transport, _answer(warmup=0.05), lambda: filler, delay_s=0.01)

    assert barged is False
    assert transport.played == [filler]                                 # filler covered the wait
    assert [c.data for c in transport.streamed] == [b"real-1", b"real-2"]  # then the real answer


@pytest.mark.asyncio
async def test_no_filler_when_the_answer_is_fast() -> None:
    transport = _RecordTransport()
    filler = _chunk("Let me check that.")

    barged = await _play_with_filler(transport, _answer(warmup=0.0), lambda: filler, delay_s=1.0)

    assert barged is False
    assert transport.played == []                                       # answer was ready in time
    assert [c.data for c in transport.streamed] == [b"real-1", b"real-2"]


@pytest.mark.asyncio
async def test_filler_drains_the_answer_even_on_barge_in() -> None:
    drained: list[str] = []

    async def _answer_tracked() -> AsyncIterator[AudioChunk]:
        await asyncio.sleep(0.05)
        for text in ("real-1", "real-2"):
            drained.append(text)
            yield _chunk(text)

    class _BargeTransport(_RecordTransport):
        async def send_interruptible(self, audio: AudioChunk) -> bool:
            self.played.append(audio)
            return True   # caller barges during the filler

    transport = _BargeTransport()
    filler = _chunk("filler")
    barged = await _play_with_filler(transport, _answer_tracked(), lambda: filler, delay_s=0.01)

    assert barged is True
    assert drained == ["real-1", "real-2"]   # answer still fully drained -> turn recorded/persisted


@pytest.mark.asyncio
async def test_filler_rotates_through_the_phrase_pool() -> None:
    from src.providers.tts.base import TTSProvider
    from src.telephony.live_session import _Filler

    class _EchoTTS(TTSProvider):
        @property
        def output_format(self) -> AudioFormat:
            return _FMT

        async def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
            yield _chunk(text)

    filler = _Filler(_EchoTTS(), ["a", "b", "c"], delay_ms=800)
    await filler.prepare()

    assert filler.ready
    picked = [filler.next_chunk().data.decode() for _ in range(5)]
    assert picked == ["a", "b", "c", "a", "b"]   # cycles through the pool, no immediate repeats
