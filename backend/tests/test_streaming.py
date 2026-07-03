"""Sentence-streaming TTS: sentence splitting + early time-to-first-audio."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from src.agent.streaming import (
    ChunkPolicy,
    resolve_chunk_policy,
    split_complete_sentences,
    synthesize_streaming,
)
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


class ChunkyTTS(TTSProvider):
    """Streams one audio chunk per character — like a cloud TTS emitting many chunks."""

    @property
    def output_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=24000)

    async def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
        for ch in text:
            yield AudioChunk(data=ch.encode("utf-8"), fmt=self.output_format)


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


@pytest.mark.asyncio
async def test_true_streaming_yields_each_tts_chunk_immediately() -> None:
    # Default: a sentence that streams N audio chunks is forwarded as N chunks (low TTFA).
    async def stream() -> AsyncIterator[str]:
        yield "Hi there."

    chunks = [c async for c in synthesize_streaming(stream(), ChunkyTTS())]

    assert len(chunks) == len("Hi there.")                 # not buffered into one
    assert b"".join(c.data for c in chunks) == b"Hi there."


@pytest.mark.asyncio
async def test_coalesce_flag_merges_a_sentence_into_one_chunk() -> None:
    # Opt-in local-playback smoothing: the sentence's audio is buffered into one chunk.
    async def stream() -> AsyncIterator[str]:
        yield "Hi there."

    chunks = [
        c async for c in synthesize_streaming(stream(), ChunkyTTS(), coalesce_sentences=True)
    ]

    assert len(chunks) == 1
    assert chunks[0].data == b"Hi there."


# --- Phase B: low-latency chunk policy --------------------------------------- #
async def _three_deltas() -> AsyncIterator[str]:
    for delta in ["Our company is remote-first, ", "with a flexible schedule ",
                  "and great benefits for all."]:
        yield delta


@pytest.mark.asyncio
async def test_policy_flushes_at_a_comma_before_the_sentence_ends() -> None:
    tts = RecordingTTS()
    policy = ChunkPolicy(min_words=3, max_words=6, max_delay_ms=1_000_000)

    _ = [c async for c in synthesize_streaming(_three_deltas(), tts, policy=policy)]

    # First chunk was flushed at the comma (4 words >= min_words) — not at the sentence end.
    assert tts.spoken[0] == "Our company is remote-first,"
    assert len(tts.spoken) > 1                                  # more chunks, not one big sentence
    full = "Our company is remote-first, with a flexible schedule and great benefits for all."
    assert " ".join(tts.spoken).split() == full.split()        # no text lost across the chunks


@pytest.mark.asyncio
async def test_policy_none_falls_back_to_whole_sentences() -> None:
    tts = RecordingTTS()

    _ = [c async for c in synthesize_streaming(_three_deltas(), tts, policy=None)]

    # The whole thing is one sentence, so the fallback emits exactly one chunk (high TTFA).
    assert len(tts.spoken) == 1
    assert tts.spoken[0].startswith("Our company is remote-first,")


@pytest.mark.asyncio
async def test_policy_does_not_flush_a_tiny_sub_min_words_fragment() -> None:
    tts = RecordingTTS()
    policy = ChunkPolicy(min_words=3, max_words=20, max_delay_ms=1_000_000)

    async def stream() -> AsyncIterator[str]:
        yield "Well, the company is remote."

    _ = [c async for c in synthesize_streaming(stream(), tts, policy=policy)]

    # "Well," (1 word) is NOT flushed alone — it stays until the sentence completes.
    assert tts.spoken == ["Well, the company is remote."]


def _domain(flow: dict):
    from src.agent.domain import DomainConfig
    return DomainConfig(
        name="x", language="en", disclosure="d", greeting="g", system_prompt="s",
        consent_reprompt="r", consent_decline="c", flow=flow,
    )


def test_resolve_chunk_policy_reads_settings_and_domain_override() -> None:
    from config.settings import Settings

    settings = Settings(
        tts_stream_min_words=3, tts_stream_max_words=10, tts_stream_max_delay_ms=400
    )
    assert resolve_chunk_policy(settings, _domain({})) == ChunkPolicy(3, 10, 400)

    # A domain may override any subset under `tts_stream:`; the rest come from settings.
    over = _domain({"tts_stream": {"min_words": 5, "max_words": 15}})
    policy = resolve_chunk_policy(settings, over)
    assert (policy.min_words, policy.max_words, policy.max_delay_ms) == (5, 15, 400)

    # Disabled -> None -> caller uses the sentence-only fallback.
    assert resolve_chunk_policy(Settings(tts_stream_early_chunking=False), _domain({})) is None
