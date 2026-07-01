"""Deepgram streaming speech-to-text (paid drop-in, Sprint 8 Path B).

A config-only swap for the open-source default (``whisper_local``): set
``STT_PROVIDER=deepgram`` + ``DEEPGRAM_API_KEY`` and nothing in the pipeline
changes (ARCHITECTURE.md §2, §5). Deepgram transcribes *while* the caller speaks
over a websocket, so the final transcript is ready within ~hundreds of ms of the
endpoint — the latency win over CPU whisper (~15-30 s/turn on the MX350).

Streaming model (``deepgram-sdk`` v7, the ``listen.v1`` async socket): we open a
connection declaring the incoming PCM16 format, push each :class:`AudioChunk` as
it arrives via ``send_media``, and ``send_close_stream`` once the utterance ends;
Deepgram then flushes its final segments and closes. We consume the socket's typed
events directly (no thread bridge needed — it is already an async iterator).

Contract note: Deepgram emits one ``is_final`` event *per finalized segment*, but
the orchestrator consumes :meth:`STTProvider.transcribe` which keeps the **last**
final. So, like ``whisper_local`` (one final for the whole utterance), we surface
each Deepgram segment as a non-final *liveness* update and emit a single cumulative
``is_final=True`` transcript (all segments joined) when the stream ends.

The vendor SDK is imported lazily, only after the API-key check, so importing this
module (tests, the doctor) never requires ``deepgram-sdk`` to be installed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from src.providers.errors import ProviderConfigError, ProviderError, ProviderQuotaError
from src.providers.stt.base import STTProvider
from src.providers.types import AudioChunk, Transcript

if TYPE_CHECKING:
    from deepgram import AsyncDeepgramClient

log = logging.getLogger("echoassist.stt.deepgram")

# Our wire format (providers/types.py): raw PCM, signed 16-bit, little-endian, mono.
_ENCODING = "linear16"


def _to_transcript(result: Any, *, language: str | None) -> Transcript | None:
    """Map a Deepgram streaming ``Results`` event to a :class:`Transcript`.

    Pure and SDK-agnostic: duck-typed on the documented shape
    (``result.channel.alternatives[0].transcript`` + ``result.is_final``), so it
    unit-tests with a lightweight fake and survives SDK-internal renames. Returns
    ``None`` for an empty hypothesis (nothing to surface yet).
    """
    channel = getattr(result, "channel", None)
    alternatives = getattr(channel, "alternatives", None) or []
    if not alternatives:
        return None
    alt = alternatives[0]
    text = (getattr(alt, "transcript", "") or "").strip()
    if not text:
        return None
    return Transcript(
        text=text,
        is_final=bool(getattr(result, "is_final", False)),
        confidence=getattr(alt, "confidence", None),
        language=language,
    )


def _log_finalize_timing(marks: dict[str, float]) -> None:
    """DIAGNOSTIC: log where the post-speech STT latency goes (one line per turn).

    ``close→final`` is Deepgram's real finalize (server-side); ``final→socket_end`` is
    time we spend *waiting for the websocket to close* after the transcript is already in
    hand — pure waste if it's large (would justify returning on the final instead).
    """
    start = marks.get("start")
    if start is None:
        return

    def since(name: str) -> float:
        return (marks[name] - start) * 1000 if name in marks else -1.0

    def delta(a: str, b: str) -> float:
        return (marks[b] - marks[a]) * 1000 if a in marks and b in marks else -1.0

    log.info(
        "deepgram finalize: connect=%.0fms audio_sent=%.0fms close_sent=%.0fms "
        "last_final=%.0fms socket_end=%.0fms | close→final=%.0fms final→socket_end=%.0fms",
        since("connected"), since("audio_sent"), since("close_sent"),
        since("last_final"), since("socket_end"),
        delta("close_sent", "last_final"), delta("last_final", "socket_end"),
    )


def _to_provider_error(exc: Exception) -> ProviderError:
    """Map a Deepgram/transport error to a clean ProviderError (no raw traceback)."""
    text = str(exc).lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status in (401, 403) or "unauthor" in text or "forbidden" in text or "invalid auth" in text:
        return ProviderConfigError(
            "Deepgram rejected the API key (401/403). Check DEEPGRAM_API_KEY in backend/.env "
            "(get one at https://console.deepgram.com)."
        )
    if status == 429 or "rate limit" in text or "quota" in text or "too many requests" in text:
        return ProviderQuotaError(
            "Deepgram rate limit / quota exceeded. Wait and retry, or fall back with "
            "STT_PROVIDER=whisper_local in backend/.env."
        )
    return ProviderError(f"Deepgram streaming error: {str(exc)[:200]} — please retry in a moment.")


class DeepgramSTT(STTProvider):
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "nova-2",
        language: str | None = None,
        interim_results: bool = True,
        smart_format: bool = True,
    ) -> None:
        if not api_key:
            raise ProviderConfigError(
                "DEEPGRAM_API_KEY is not set. Get a key at https://console.deepgram.com "
                "and add it to backend/.env (or set STT_PROVIDER=whisper_local for the default)."
            )
        from deepgram import AsyncDeepgramClient

        self._client: AsyncDeepgramClient = AsyncDeepgramClient(api_key=api_key)
        self._model = model
        self._language = language
        self._interim_results = interim_results
        self._smart_format = smart_format

    def _connect_options(self, *, sample_rate: int, channels: int) -> dict[str, Any]:
        options: dict[str, Any] = {
            "model": self._model,
            "encoding": _ENCODING,
            "sample_rate": sample_rate,
            "channels": channels,
            "interim_results": self._interim_results,
            "smart_format": self._smart_format,
        }
        if self._language:
            options["language"] = self._language
        return options

    async def transcribe_stream(
        self, audio: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[Transcript]:
        # Peek the first chunk to learn the PCM format we must declare to Deepgram.
        audio_iter = audio.__aiter__()
        try:
            first = await audio_iter.__anext__()
        except StopAsyncIteration:
            yield Transcript(text="", is_final=True)
            return

        segments: list[str] = []
        last_confidence: float | None = None
        # DIAGNOSTIC: timestamp the finalize path to see where post-speech latency goes.
        marks: dict[str, float] = {"start": time.perf_counter()}
        try:
            connection = self._client.listen.v1.connect(
                **self._connect_options(
                    sample_rate=first.fmt.sample_rate, channels=first.fmt.channels
                )
            )
            async with connection as socket:
                marks["connected"] = time.perf_counter()

                async def _pump() -> None:
                    # Stream the utterance, then signal end-of-stream so Deepgram
                    # flushes its final segments and closes the socket.
                    await socket.send_media(first.data)
                    async for chunk in audio_iter:
                        if chunk.data:
                            await socket.send_media(chunk.data)
                    marks["audio_sent"] = time.perf_counter()
                    await socket.send_close_stream()
                    marks["close_sent"] = time.perf_counter()

                pump = asyncio.create_task(_pump())
                try:
                    async for message in socket:
                        transcript = _to_transcript(message, language=self._language)
                        if transcript is None:
                            continue
                        if transcript.is_final:
                            marks["last_final"] = time.perf_counter()
                            segments.append(transcript.text)
                            last_confidence = transcript.confidence
                            # Surface the finalized segment as liveness; the single
                            # cumulative final is emitted once the stream ends.
                            yield Transcript(
                                text=transcript.text,
                                is_final=False,
                                confidence=transcript.confidence,
                                language=transcript.language,
                            )
                        else:
                            yield transcript
                finally:
                    await pump
            marks["socket_end"] = time.perf_counter()
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — map any SDK/transport error to a clean ProviderError
            raise _to_provider_error(exc) from exc

        _log_finalize_timing(marks)

        yield Transcript(
            text=" ".join(s for s in segments if s).strip(),
            is_final=True,
            confidence=last_confidence,
            language=self._language,
        )
