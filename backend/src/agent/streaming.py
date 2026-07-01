"""Streaming reply synthesis.

Bridges an LLM text stream (``chat_stream``) to TTS (``synthesize_stream``): as
soon as a full sentence is available it is synthesized and its audio yielded —
the agent starts speaking before the LLM has finished writing. This is what cuts
time-to-first-audio; total compute is unchanged. The non-streaming path
(``LLMProvider.chat`` + ``TTSProvider.synthesize``) is preserved.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from time import perf_counter

from src.providers.tts.base import TTSProvider
from src.providers.types import AudioChunk

_SENTENCE_END = re.compile(r"[.!?](\s+|$)")


@dataclass
class StreamTimings:
    """Per-turn latency for a streaming reply, in milliseconds.

    A live turn's wall-clock is dominated by *human* time — the caller thinking before
    they speak (``wait_ms``) and speaking, plus the VAD's trailing-silence timeout
    (``speech_ms``). Those are not machine latency. The latency the caller *feels* is
    ``ttfa_ms``: from the moment they stop talking to the agent's first sound, which is
    ``stt_ms + llm_ms + tts_ms`` — so the largest of those three is the real bottleneck.
    """

    wait_ms: float = 0.0    # (human) turn start -> caller starts speaking
    speech_ms: float = 0.0  # (human) caller speaking + the VAD trailing-silence timeout
    stt_ms: float = 0.0     # caller stops -> transcript ready (STT finalize only)
    llm_ms: float = 0.0     # transcript ready -> first agent text (Groq turn-classify / RAG)
    tts_ms: float = 0.0     # first agent text -> first audio (first-sentence synthesis)
    ttfa_ms: float = 0.0    # caller stops -> first audio: the latency the caller actually feels
    total_ms: float = 0.0   # caller stops -> all audio produced (also spans playback)


def _identity(text: str) -> str:
    return text


def split_complete_sentences(buffer: str) -> tuple[list[str], str]:
    """Split off complete sentences; return (sentences, remaining buffer)."""
    sentences: list[str] = []
    last = 0
    for match in _SENTENCE_END.finditer(buffer):
        sentence = buffer[last : match.start() + 1].strip()
        if sentence:
            sentences.append(sentence)
        last = match.end()
    return sentences, buffer[last:]


async def synthesize_streaming(
    text_stream: AsyncIterator[str],
    tts: TTSProvider,
    *,
    clean: Callable[[str], str] = _identity,
    timings: StreamTimings | None = None,
    start: float | None = None,
) -> AsyncIterator[AudioChunk]:
    """Synthesize each sentence of a text stream as soon as it completes.

    ``clean`` is applied to each complete sentence before synthesis (e.g. to strip
    ``[source]`` citations from a grounded answer so they are not spoken).

    When ``timings`` and ``start`` (a ``perf_counter()`` reference at turn start, with
    ``timings.stt_ms`` already filled) are given, per-turn latency is recorded as the
    stream is consumed: ``llm_ms`` at the first text delta, ``ttfa_ms``/``tts_ms`` at
    the first audio chunk, and ``total_ms`` at the end.
    """
    record = timings is not None and start is not None
    got_text = got_audio = False

    def _mark_first_audio() -> None:
        nonlocal got_audio
        if record and not got_audio:
            timings.ttfa_ms = (perf_counter() - start) * 1000
            timings.tts_ms = timings.ttfa_ms - timings.stt_ms - timings.llm_ms
            got_audio = True

    buffer = ""
    async for delta in text_stream:
        if record and not got_text:
            timings.llm_ms = (perf_counter() - start) * 1000 - timings.stt_ms
            got_text = True
        buffer += delta
        sentences, buffer = split_complete_sentences(buffer)
        for sentence in sentences:
            spoken = clean(sentence)
            if spoken:
                async for chunk in tts.synthesize_stream(spoken):
                    _mark_first_audio()
                    yield chunk
    remainder = clean(buffer.strip())
    if remainder:
        async for chunk in tts.synthesize_stream(remainder):
            _mark_first_audio()
            yield chunk
    if record:
        timings.total_ms = (perf_counter() - start) * 1000
