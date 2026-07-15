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
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.observability import latency
from src.providers.tts.base import TTSProvider
from src.providers.types import AudioChunk, AudioFormat

if TYPE_CHECKING:
    from config.settings import Settings
    from src.agent.domain import DomainConfig

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


# --------------------------------------------------------------------------- #
# Low-latency, domain-agnostic text chunking for TTS (Phase B)                #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ChunkPolicy:
    """When to flush buffered LLM text to TTS — earlier than a full sentence, for low TTFA.

    Domain-agnostic: no hardcoded phrases, no slot/recruiting assumptions. Tuned globally
    in settings and optionally overridden per domain (``tts_stream:`` in the domain YAML).
    """

    min_words: int = 3       # never flush a soft/stale chunk shorter than this (avoid tiny bits)
    max_words: int = 10      # force a flush after this many words if no punctuation appeared
    max_delay_ms: int = 400  # once a chunk is >= min_words, flush it if text stalls this long


_SENTENCE_BOUNDARY = re.compile(r"[.!?]+(?=\s)")   # sentence punctuation followed by space
_SOFT_BOUNDARY = re.compile(r"[,;:]+(?=\s)")        # comma / semicolon / colon followed by space
_COMPLETE_WORD = re.compile(r"\S+(?=\s)")   # a fully-arrived word (has trailing whitespace)


def _word_count(text: str) -> int:
    return len(text.split())


def _next_chunk(buffer: str, policy: ChunkPolicy, *, stale: bool) -> tuple[str | None, str]:
    """Take the next flushable chunk from ``buffer`` per ``policy``; else ``(None, buffer)``."""
    # 1. Sentence boundary -> always flush (a natural, complete unit of any length).
    match = _SENTENCE_BOUNDARY.search(buffer)
    if match:
        cut = match.end()
        return buffer[:cut].strip(), buffer[cut:]
    # 2. Soft boundary -> flush the earliest comma/;/: that already has >= min_words before it.
    for soft in _SOFT_BOUNDARY.finditer(buffer):
        if _word_count(buffer[: soft.end()]) >= policy.min_words:
            cut = soft.end()
            return buffer[:cut].strip(), buffer[cut:]
    # 3. Word cap -> a clause is dragging with no punctuation: flush max_words whole words.
    words = list(_COMPLETE_WORD.finditer(buffer))
    if len(words) >= policy.max_words:
        cut = words[policy.max_words - 1].end()
        return buffer[:cut].strip(), buffer[cut:]
    # 4. Stalled (no new text for max_delay) and we already have a speakable chunk -> flush it.
    if stale and len(words) >= policy.min_words:
        cut = words[-1].end()
        return buffer[:cut].strip(), buffer[cut:]
    return None, buffer


def _flush_chunks(buffer: str, policy: ChunkPolicy, *, stale: bool) -> tuple[list[str], str]:
    chunks: list[str] = []
    while True:
        chunk, buffer = _next_chunk(buffer, policy, stale=stale)
        if chunk is None:
            break
        if chunk:
            chunks.append(chunk)
    return chunks, buffer


def resolve_chunk_policy(settings: Settings, domain: DomainConfig | None) -> ChunkPolicy | None:
    """Build the chunk policy from settings, with an optional per-domain YAML override.

    Returns ``None`` when early chunking is disabled — the caller then falls back to the
    original sentence-only streaming. The domain override lives under ``tts_stream:`` in the
    interview flow YAML, so tuning a domain needs no code change.
    """
    if not settings.tts_stream_early_chunking:
        return None
    override = (domain.flow.get("tts_stream") or {}) if domain is not None else {}
    return ChunkPolicy(
        min_words=int(override.get("min_words", settings.tts_stream_min_words)),
        max_words=int(override.get("max_words", settings.tts_stream_max_words)),
        max_delay_ms=int(override.get("max_delay_ms", settings.tts_stream_max_delay_ms)),
    )


async def synthesize_streaming(
    text_stream: AsyncIterator[str],
    tts: TTSProvider,
    *,
    clean: Callable[[str], str] = _identity,
    coalesce_sentences: bool = False,
    policy: ChunkPolicy | None = None,
    on_text: Callable[[str], None] | None = None,
) -> AsyncIterator[AudioChunk]:
    """True LLM->TTS streaming: yield each TTS audio chunk **as soon as the provider
    returns it** (lowest time-to-first-audio).

    Text chunking: with a :class:`ChunkPolicy` (``policy``), text is flushed to TTS early —
    on sentence punctuation, on a comma/;/: once it holds ``min_words``, after ``max_words``,
    or when it stalls for ``max_delay_ms`` — so the agent starts speaking a clause into a
    long reply instead of after the whole sentence. With ``policy=None`` it falls back to the
    original sentence-only splitting.

    ``clean`` is applied to each chunk before synthesis (e.g. to strip ``[source]`` citations
    so they are not spoken). ``coalesce_sentences=True`` buffers a chunk's audio into one
    :class:`AudioChunk` before yielding — a *local-playback smoothing* option that trades TTFA
    for gap-free playback on the ``sd.play`` mic transport; **off by default**.

    Records per-turn metrics (no-op unless LATENCY_LOGGING): ``tts_first_byte_ms``,
    ``sentence_tts_total_ms`` (first flushed chunk), ``tts_chunks_count``, and the
    ``first_audio`` event that drives ``ttfa_ms``.
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
    last_flush = time.perf_counter()
    async for delta in text_stream:
        buffer += delta
        if on_text is not None and delta:
            # Forward the raw reply delta for a live "typewriter" transcript (dashboard).
            # Fires as the LLM generates, independent of the (sentence-buffered) TTS flush.
            on_text(delta)
        if policy is None:
            texts, buffer = split_complete_sentences(buffer)   # fallback: whole sentences
        else:
            stale = (time.perf_counter() - last_flush) * 1000.0 >= policy.max_delay_ms
            texts, buffer = _flush_chunks(buffer, policy, stale=stale)
        for text in texts:
            spoken = clean(text)
            if spoken:
                async for chunk in _speak(spoken):
                    yield chunk
                last_flush = time.perf_counter()
    remainder = clean(buffer.strip())
    if remainder:
        async for chunk in _speak(remainder):
            yield chunk
    latency.observe(tts_chunks_count=chunk_count)
