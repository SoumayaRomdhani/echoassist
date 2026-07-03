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
from src.providers.types import AudioChunk

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
) -> AsyncIterator[AudioChunk]:
    """Synthesize each sentence of a text stream as soon as it completes.

    ``clean`` is applied to each complete sentence before synthesis (e.g. to strip
    ``[source]`` citations from a grounded answer so they are not spoken).
    """
    got_audio = False

    def _mark_first_audio(started: float) -> None:
        # First audio chunk of the turn: mark TTFA and the TTS' own time-to-first-audio.
        nonlocal got_audio
        if not got_audio:
            latency.event("first_audio")
            latency.observe(tts_ttfa_ms=(time.perf_counter() - started) * 1000.0)
            got_audio = True

    buffer = ""
    async for delta in text_stream:
        buffer += delta
        sentences, buffer = split_complete_sentences(buffer)
        for sentence in sentences:
            spoken = clean(sentence)
            if spoken:
                tts_start = time.perf_counter()
                async for chunk in tts.synthesize_stream(spoken):
                    _mark_first_audio(tts_start)
                    yield chunk
    remainder = clean(buffer.strip())
    if remainder:
        tts_start = time.perf_counter()
        async for chunk in tts.synthesize_stream(remainder):
            _mark_first_audio(tts_start)
            yield chunk
