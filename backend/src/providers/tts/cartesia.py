"""Cartesia text-to-speech (paid drop-in, Sprint 8 Path B).

A config-only swap for the open-source default (``kokoro``): set
``TTS_PROVIDER=cartesia`` + ``CARTESIA_API_KEY`` and nothing in the pipeline
changes (ARCHITECTURE.md §2, §5). Cartesia (Sonic) streams audio with very low
time-to-first-audio — the natural-voice, low-latency complement to Deepgram STT
on the paid path.

We request **raw ``pcm_s16le``** at the configured sample rate, which is exactly
our wire format (providers/types.py: PCM16 mono LE), so each streamed chunk is
wrapped in an :class:`AudioChunk` with no re-encoding. Streaming uses the SDK's
``with_streaming_response`` so the first bytes are yielded as the server produces
them (low TTFA), driven by the sentence-streamer in ``src/agent/streaming.py``.

The vendor SDK is imported lazily, only after the API-key check, so importing this
module never requires ``cartesia`` to be installed.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from src.providers.errors import ProviderConfigError, ProviderError, ProviderQuotaError
from src.providers.tts.base import TTSProvider
from src.providers.types import AudioChunk, AudioFormat

if TYPE_CHECKING:
    from cartesia import AsyncCartesia

log = logging.getLogger("echoassist.tts.cartesia")

# Cartesia raw PCM only accepts this discrete set of sample rates.
_VALID_SAMPLE_RATES = (8000, 16000, 22050, 24000, 44100, 48000)


def _to_provider_error(exc: Exception) -> ProviderError:
    """Map a Cartesia API error to a clean ProviderError (no raw traceback)."""
    name = type(exc).__name__
    text = str(exc).lower()
    if name == "AuthenticationError" or "unauthor" in text or "api key" in text:
        return ProviderConfigError(
            "Cartesia rejected the API key. Check CARTESIA_API_KEY in backend/.env "
            "(get one at https://play.cartesia.ai), or set TTS_PROVIDER=kokoro for the default."
        )
    if name == "RateLimitError" or "rate limit" in text or "quota" in text:
        return ProviderQuotaError(
            "Cartesia rate limit / quota exceeded. Wait and retry, or fall back with "
            "TTS_PROVIDER=kokoro in backend/.env."
        )
    return ProviderError(f"Cartesia TTS error: {str(exc)[:200]} — please retry in a moment.")


class CartesiaTTS(TTSProvider):
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "sonic-2",
        voice_id: str | None = None,
        sample_rate: int = 24000,
        language: str | None = None,
    ) -> None:
        if not api_key:
            raise ProviderConfigError(
                "CARTESIA_API_KEY is not set. Get a key at https://play.cartesia.ai "
                "and add it to backend/.env (or set TTS_PROVIDER=kokoro for the default)."
            )
        if not voice_id:
            raise ProviderConfigError(
                "CARTESIA_VOICE_ID is not set. Pick a voice id at https://play.cartesia.ai "
                "and add it to backend/.env."
            )
        if sample_rate not in _VALID_SAMPLE_RATES:
            raise ProviderConfigError(
                f"CARTESIA_SAMPLE_RATE={sample_rate} is unsupported; "
                f"choose one of {_VALID_SAMPLE_RATES}."
            )
        from cartesia import AsyncCartesia

        self._client: AsyncCartesia = AsyncCartesia(api_key=api_key)
        self._model = model
        self._voice_id = voice_id
        self._sample_rate = sample_rate
        self._language = language

    @property
    def output_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=self._sample_rate)

    def _request_kwargs(self, text: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model_id": self._model,
            "transcript": text,
            "voice": {"id": self._voice_id, "mode": "id"},
            "output_format": {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": self._sample_rate,
            },
        }
        if self._language:
            kwargs["language"] = self._language
        return kwargs

    async def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return
        try:
            response_ctx = self._client.tts.with_streaming_response.generate(
                **self._request_kwargs(text)
            )
            async with response_ctx as response:
                async for chunk in response.iter_bytes():
                    if chunk:
                        yield AudioChunk(data=chunk, fmt=self.output_format)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — map any SDK/transport error to a clean ProviderError
            raise _to_provider_error(exc) from exc

    async def aclose(self) -> None:
        await self._client.close()
