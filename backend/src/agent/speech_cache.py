"""Static-line TTS cache — synthesize the deterministic spoken lines once (L5).

The screening flow is deterministic: the greeting, consent re-prompt/decline,
every interview question, the transition acknowledgement and the closing line are
*fixed strings* known before the call. Re-synthesizing them on every turn wastes
the TTS budget — and AMELIORATIONS.md (Axe 1, L5) notes that ~60 % of agent turns
speak a static line, so caching their audio takes their TTS cost to ~0 ms.

:class:`StaticSpeechCache` decorates any :class:`TTSProvider`: it memoizes
``synthesize`` by exact text, so a warmed line is served straight from memory.
:meth:`warm` is run in the background during the disclosure (3-4 free seconds of
playback) to fill the cache off the critical path. Dynamic lines (grounded
answers) are simply forwarded to the inner provider — they are never cached here.

Caching is transparent: a cached line is byte-for-byte what the inner provider
would have produced, so this never changes what the caller hears, only when the
audio is ready.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable

from src.providers.tts.base import TTSProvider
from src.providers.types import AudioChunk, AudioFormat

log = logging.getLogger("echoassist.agent.speech_cache")


class StaticSpeechCache(TTSProvider):
    """A :class:`TTSProvider` that memoizes whole-line synthesis by exact text."""

    def __init__(self, inner: TTSProvider) -> None:
        self._inner = inner
        # text -> in-flight/finished synthesis. A Task (not a stored AudioChunk) so
        # concurrent requests for the same line share one synthesis instead of racing.
        self._tasks: dict[str, asyncio.Task[AudioChunk]] = {}

    @property
    def output_format(self) -> AudioFormat:
        return self._inner.output_format

    async def synthesize(self, text: str) -> AudioChunk:
        """Return the line's audio, synthesizing once and caching by exact text."""
        key = text.strip()
        if not key:
            return await self._inner.synthesize(text)
        task = self._tasks.get(key)
        # (Re)synthesize when unseen, or when a previous attempt failed — never serve
        # (or re-raise) a cached failure, so a transient TTS error can recover.
        if task is None or (task.done() and task.exception() is not None):
            task = asyncio.ensure_future(self._inner.synthesize(text))
            self._tasks[key] = task
        # Shield so a cancelled caller (e.g. a barge-in) does not cancel the shared
        # synthesis other callers — and the cache — are still waiting on.
        return await asyncio.shield(task)

    async def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
        """Yield the line's audio: one cached chunk if warmed, else stream through.

        Static lines are short and played as a single chunk, so a cache hit yields
        one concatenated chunk. Unseen (dynamic) text streams straight from the inner
        provider — preserving its low time-to-first-audio — and is not cached.
        """
        if not text.strip():
            return
        if text.strip() in self._tasks:
            yield await self.synthesize(text)
            return
        async for chunk in self._inner.synthesize_stream(text):
            yield chunk

    async def warm(self, texts: Iterable[str]) -> None:
        """Pre-synthesize ``texts`` (best-effort, off the critical path).

        Concurrency follows the inner provider: a cloud HTTP TTS
        (``concurrent_warm=True``) warms all lines in parallel, so the cache is ready
        after ~one network round-trip instead of one-per-line — the difference between
        the cache being warm or not by the time the first questions are asked. A local
        single-model provider keeps it sequential (overlapping inference only thrashes
        one CPU pipeline). A synthesis failure is logged and skipped — warming must
        never break the call.
        """
        lines = [text for text in texts if text and text.strip()]
        # Bounded so a long flow cannot open dozens of sockets at once; 1 == sequential.
        limit = 8 if getattr(self._inner, "concurrent_warm", False) else 1
        sem = asyncio.Semaphore(limit)
        warmed = 0

        async def _warm_one(text: str) -> None:
            nonlocal warmed
            async with sem:
                try:
                    await self.synthesize(text)
                    warmed += 1
                except asyncio.CancelledError:
                    raise  # the session is shutting down — propagate so warming stops
                except Exception as exc:  # noqa: BLE001 — warming is best-effort
                    log.warning("static-line warm failed (%s); will synthesize on demand.", exc)

        # Semaphore acquisition is FIFO, so even sequential warming keeps soonest-first order.
        await asyncio.gather(*(_warm_one(text) for text in lines))
        log.info("static speech cache warmed: %d line(s)", warmed)

    async def aclose(self) -> None:
        await self._inner.aclose()
