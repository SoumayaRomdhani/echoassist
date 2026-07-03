"""Streaming reply synthesis.

Bridges an LLM text stream (``chat_stream``) to TTS (``synthesize_stream``): as
soon as a full sentence is available it is synthesized and its audio yielded —
the agent starts speaking before the LLM has finished writing. This is what cuts
time-to-first-audio; total compute is unchanged. The non-streaming path
(``LLMProvider.chat`` + ``TTSProvider.synthesize``) is preserved.
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator, Callable

from src.observability import latency
from src.providers.tts.base import TTSProvider
from src.providers.types import AudioChunk, AudioFormat

_SENTENCE_END = re.compile(r"[.!?](\s+|$)")


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
    coalesce_sentences: bool = False,
) -> AsyncIterator[AudioChunk]:
    """True LLM->TTS streaming: yield each TTS audio chunk **as soon as the provider
    returns it** (lowest time-to-first-audio). Text is still chunked by sentence.

    ``clean`` is applied to each complete sentence before synthesis (e.g. to strip
    ``[source]`` citations so they are not spoken). ``coalesce_sentences=True`` buffers a
    sentence's audio into one chunk before yielding — a *local-playback smoothing* option
    that trades TTFA for gap-free playback on the ``sd.play`` mic transport; **off by
    default** so we stream truly.

    Records per-turn metrics (no-op unless LATENCY_LOGGING): ``tts_first_byte_ms`` (first
    sentence), ``sentence_tts_total_ms`` (first sentence full synth), ``tts_chunks_count``,
    and the ``first_audio`` event that drives ``ttfa_ms``.
    """
    got_first = False
    chunk_count = 0
    first_sentence_recorded = False

    async def _speak(spoken: str) -> AsyncIterator[AudioChunk]:
        nonlocal got_first, chunk_count, first_sentence_recorded
        started = time.perf_counter()
        coalesced = bytearray()
        fmt: AudioFormat | None = None
        sentence_first = True
        async for chunk in tts.synthesize_stream(spoken):
            chunk_count += 1
            if sentence_first:
                sentence_first = False
                if not got_first:  # the turn's first audio -> TTFA + TTS first-byte
                    latency.event("first_audio")
                    latency.observe(tts_first_byte_ms=(time.perf_counter() - started) * 1000.0)
                    got_first = True
            if coalesce_sentences:
                coalesced.extend(chunk.data)
                fmt = chunk.fmt
            else:
                yield chunk  # emit immediately — do NOT wait for the whole sentence
        if coalesce_sentences and coalesced and fmt is not None:
            yield AudioChunk(bytes(coalesced), fmt)
        if not first_sentence_recorded:
            latency.observe(sentence_tts_total_ms=(time.perf_counter() - started) * 1000.0)
            first_sentence_recorded = True

    buffer = ""
    async for delta in text_stream:
        buffer += delta
        sentences, buffer = split_complete_sentences(buffer)
        for sentence in sentences:
            spoken = clean(sentence)
            if spoken:
                async for chunk in _speak(spoken):
                    yield chunk
    remainder = clean(buffer.strip())
    if remainder:
        async for chunk in _speak(remainder):
            yield chunk
    latency.observe(tts_chunks_count=chunk_count)
