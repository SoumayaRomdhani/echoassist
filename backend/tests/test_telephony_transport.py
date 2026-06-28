"""The Transport seam: per-utterance streams plug in where the replay source does."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from src.providers.stt.base import STTProvider
from src.providers.types import AudioChunk, AudioFormat, Transcript
from src.telephony.transport import Transport

_FMT = AudioFormat(sample_rate=16000)


def _chunk(text: str) -> AudioChunk:
    return AudioChunk(data=text.encode("utf-8"), fmt=_FMT)


class _FakeTransport(Transport):
    """Scripted utterances in, sent audio recorded — no hardware."""

    def __init__(self, utterances: list[list[AudioChunk]]) -> None:
        self._utterances = [list(u) for u in utterances]
        self._turn = 0
        self.sent: list[AudioChunk] = []

    async def listen(self) -> AsyncIterator[AudioChunk]:
        utterance = self._utterances[self._turn]
        self._turn += 1
        for chunk in utterance:
            yield chunk

    async def send(self, audio: AudioChunk) -> None:
        self.sent.append(audio)


class _DecodingSTT(STTProvider):
    """Concatenates chunk bytes and decodes them — the test STT used elsewhere."""

    async def transcribe_stream(
        self, audio: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[Transcript]:
        buffer = bytearray()
        async for chunk in audio:
            buffer.extend(chunk.data)
        yield Transcript(text=buffer.decode("utf-8"), is_final=True)


@pytest.mark.asyncio
async def test_listen_returns_one_utterance_per_call() -> None:
    transport = _FakeTransport([[_chunk("a"), _chunk("b")], [_chunk("c")]])
    first = [c async for c in transport.listen()]
    second = [c async for c in transport.listen()]
    assert [c.data for c in first] == [b"a", b"b"]
    assert [c.data for c in second] == [b"c"]


@pytest.mark.asyncio
async def test_listen_stream_feeds_an_stt_provider_like_the_replay_source() -> None:
    # The seam: transport.listen() is consumable exactly where stream_wav(path) is.
    transport = _FakeTransport([[_chunk("hel"), _chunk("lo")]])
    transcript = await _DecodingSTT().transcribe(transport.listen())
    assert transcript.text == "hello"


@pytest.mark.asyncio
async def test_send_stream_forwards_each_chunk_to_send() -> None:
    transport = _FakeTransport([])

    async def _stream() -> AsyncIterator[AudioChunk]:
        for text in ("one", "two", "three"):
            yield _chunk(text)

    await transport.send_stream(_stream())
    assert [c.data for c in transport.sent] == [b"one", b"two", b"three"]


@pytest.mark.asyncio
async def test_send_interruptible_default_plays_fully_and_reports_no_barge_in() -> None:
    # A transport without duplex (the default) plays the whole chunk, no barge-in.
    transport = _FakeTransport([])
    barged = await transport.send_interruptible(_chunk("hello"))
    assert barged is False
    assert [c.data for c in transport.sent] == [b"hello"]
