"""Static-line TTS cache: memoization, warming, dedup, and line enumeration (L5)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from src.agent.dialogue import static_lines
from src.agent.domain import DomainConfig
from src.agent.speech_cache import StaticSpeechCache
from src.providers.tts.base import TTSProvider
from src.providers.types import AudioChunk, AudioFormat


class CountingTTS(TTSProvider):
    """Records how many times each text was actually synthesized."""

    def __init__(self, *, fail_first: str | None = None) -> None:
        self.calls: list[str] = []
        self._fail_first = fail_first  # raise once for this text, then succeed

    @property
    def output_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=24000)

    async def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
        self.calls.append(text)
        await asyncio.sleep(0)  # let concurrent callers interleave before we "produce"
        if text == self._fail_first:
            self._fail_first = None
            raise RuntimeError("synthesis boom")
        # Two chunks so a "single concatenated chunk" cache hit is observable.
        for part in (text[: len(text) // 2], text[len(text) // 2 :]):
            yield AudioChunk(data=part.encode("utf-8"), fmt=self.output_format)

    def count(self, text: str) -> int:
        return self.calls.count(text)


def _domain() -> DomainConfig:
    flow = {
        "transition_ack": "Thanks.",
        "states": [
            {"id": "experience", "type": "question", "slot": "yoe", "prompt": "How many years?"},
            {"id": "qa", "type": "grounded_qa", "prompt": "Any questions for me?"},
            {"id": "close", "type": "close", "prompt": "Goodbye."},
        ],
    }
    return DomainConfig(
        name="screening", language="en", disclosure="This is an AI. OK to continue?",
        greeting="Great, thanks.", system_prompt="s",
        consent_reprompt="Please say yes or no.", consent_decline="No problem, goodbye.",
        flow=flow,
    )


@pytest.mark.asyncio
async def test_synthesize_caches_by_exact_text() -> None:
    inner = CountingTTS()
    cache = StaticSpeechCache(inner)

    first = await cache.synthesize("Hello there.")
    second = await cache.synthesize("Hello there.")

    assert first.data == second.data == b"Hello there."   # both chunks concatenated
    assert inner.count("Hello there.") == 1                # synthesized once, then cached


@pytest.mark.asyncio
async def test_warm_then_synthesize_is_free() -> None:
    inner = CountingTTS()
    cache = StaticSpeechCache(inner)

    await cache.warm(["Great, thanks.", "Goodbye.", "  ", ""])
    assert inner.count("Great, thanks.") == 1 and inner.count("Goodbye.") == 1

    await cache.synthesize("Great, thanks.")              # served from the warm cache
    assert inner.count("Great, thanks.") == 1


@pytest.mark.asyncio
async def test_synthesize_stream_yields_one_chunk_when_warmed() -> None:
    inner = CountingTTS()
    cache = StaticSpeechCache(inner)
    await cache.warm(["Any questions for me?"])

    chunks = [c async for c in cache.synthesize_stream("Any questions for me?")]

    assert len(chunks) == 1                                # one cached, concatenated chunk
    assert chunks[0].data == b"Any questions for me?"
    assert inner.count("Any questions for me?") == 1       # not re-synthesized for the stream


@pytest.mark.asyncio
async def test_uncached_stream_passes_through() -> None:
    inner = CountingTTS()
    cache = StaticSpeechCache(inner)

    chunks = [c async for c in cache.synthesize_stream("A dynamic grounded answer.")]

    assert len(chunks) == 2                                # inner's per-segment streaming preserved
    assert b"".join(c.data for c in chunks) == b"A dynamic grounded answer."


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_synthesis() -> None:
    inner = CountingTTS()
    cache = StaticSpeechCache(inner)

    results = await asyncio.gather(*(cache.synthesize("Shared line.") for _ in range(5)))

    assert all(r.data == b"Shared line." for r in results)
    assert inner.count("Shared line.") == 1               # deduped, not 5 syntheses


@pytest.mark.asyncio
async def test_failed_synthesis_is_not_cached() -> None:
    inner = CountingTTS(fail_first="flaky line")
    cache = StaticSpeechCache(inner)

    with pytest.raises(RuntimeError):
        await cache.synthesize("flaky line")
    recovered = await cache.synthesize("flaky line")      # retry must re-synthesize

    assert recovered.data == b"flaky line"
    assert inner.count("flaky line") == 2


class _PeakTrackingTTS(TTSProvider):
    """Records the peak number of syntheses running at once (to observe warm concurrency)."""

    def __init__(self, *, concurrent_warm: bool) -> None:
        self.concurrent_warm = concurrent_warm
        self._inflight = 0
        self.peak = 0

    @property
    def output_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=24000)

    async def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
        self._inflight += 1
        self.peak = max(self.peak, self._inflight)
        try:
            await asyncio.sleep(0.02)  # hold the "synthesis" open so overlap is observable
            yield AudioChunk(data=text.encode("utf-8"), fmt=self.output_format)
        finally:
            self._inflight -= 1


@pytest.mark.asyncio
async def test_warm_runs_in_parallel_for_cloud_providers() -> None:
    cloud = _PeakTrackingTTS(concurrent_warm=True)
    await StaticSpeechCache(cloud).warm(["a", "b", "c", "d"])
    assert cloud.peak > 1                                  # cloud lines warmed concurrently

    local = _PeakTrackingTTS(concurrent_warm=False)
    await StaticSpeechCache(local).warm(["a", "b", "c", "d"])
    assert local.peak == 1                                 # local single-pipeline stays serial


@pytest.mark.asyncio
async def test_warm_swallows_failures() -> None:
    inner = CountingTTS(fail_first="Great, thanks.")
    cache = StaticSpeechCache(inner)

    await cache.warm(["Great, thanks.", "Goodbye."])      # must not raise despite the failure
    assert inner.count("Goodbye.") == 1


def test_output_format_delegates_to_inner() -> None:
    inner = CountingTTS()
    assert StaticSpeechCache(inner).output_format == inner.output_format


def test_static_lines_covers_flow_and_excludes_disclosure() -> None:
    lines = static_lines(_domain())

    # Consent-phase lines are present; the disclosure is not (spoken once, up front).
    assert "Great, thanks." in lines
    assert "Please say yes or no." in lines
    assert "No problem, goodbye." in lines
    assert "This is an AI. OK to continue?" not in lines

    # Each state prompt, the bare transition ack, and the question re-ask.
    assert "How many years?" in lines
    assert "Sorry — How many years?" in lines               # unclear re-ask
    assert "Thanks." in lines                                # ack, spoken alone before each advance
    assert "Goodbye." in lines

    # Joined "ack + question" forms are NOT warmed: streaming splits them on the
    # sentence boundary, so only the bare ack + bare prompt are ever requested.
    assert "Thanks. How many years?" not in lines
    assert "Thanks. Any questions for me?" not in lines
    assert len(lines) == len(set(lines))                     # de-duplicated
