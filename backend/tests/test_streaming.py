"""Sentence-streaming TTS: sentence splitting + early time-to-first-audio."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from src.agent.streaming import split_complete_sentences, synthesize_streaming
from src.providers.tts.base import TTSProvider
from src.providers.types import AudioChunk, AudioFormat


class RecordingTTS(TTSProvider):
    """Yields one chunk per call and records the text it was asked to speak."""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    @property
    def output_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=24000)

    async def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
        self.spoken.append(text)
        yield AudioChunk(data=text.encode("utf-8"), fmt=self.output_format)


def test_split_complete_sentences() -> None:
    assert split_complete_sentences("Hello world. How are you?") == (
        ["Hello world.", "How are you?"], "",
    )
    assert split_complete_sentences("No terminator yet") == ([], "No terminator yet")
    assert split_complete_sentences("One. Two. three") == (["One.", "Two."], "three")


@pytest.mark.asyncio
async def test_streaming_synthesizes_each_sentence_in_order() -> None:
    async def stream() -> AsyncIterator[str]:
        for delta in ["The cat ", "sat. ", "The dog ran."]:
            yield delta

    tts = RecordingTTS()
    chunks = [chunk async for chunk in synthesize_streaming(stream(), tts)]

    assert tts.spoken == ["The cat sat.", "The dog ran."]
    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_first_audio_is_ready_before_input_is_fully_consumed() -> None:
    pulled: list[int] = []

    async def stream() -> AsyncIterator[str]:
        pulled.append(1)
        yield "First sentence. "
        pulled.append(2)
        yield "Second sentence."

    agen = synthesize_streaming(stream(), RecordingTTS())
    await agen.__anext__()  # first audio chunk

    assert pulled == [1]  # the 2nd delta has NOT been pulled yet -> low TTFA

    async for _ in agen:  # drain the rest
        pass
    assert pulled == [1, 2]
