"""ElevenLabs text-to-speech (paid drop-in, Sprint 8 Path B).

A config-only swap for the open-source default (``kokoro``): set
``TTS_PROVIDER=elevenlabs`` + ``ELEVENLABS_API_KEY`` and nothing in the pipeline
changes (ARCHITECTURE.md §2, §5). ElevenLabs is the *naturalness* alternative on
the paid path (Cartesia is the lowest-latency one).

We request raw ``pcm_<rate>`` output, which ElevenLabs returns as PCM16 mono LE —
exactly our wire format (providers/types.py) — over the streaming endpoint, so the
first bytes arrive as the server produces them (low TTFA), driven by the
sentence-streamer in ``src/agent/streaming.py``.

The vendor SDK is imported lazily, only after the API-key check, so importing this
module never requires ``elevenlabs`` to be installed.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from src.providers.errors import ProviderConfigError, ProviderError, ProviderQuotaError
from src.providers.tts.base import TTSProvider, aligned_pcm16
from src.providers.types import AudioChunk, AudioFormat

if TYPE_CHECKING:  # typing only — never import the SDK at module load
    from elevenlabs.client import AsyncElevenLabs

log = logging.getLogger("echoassist.tts.elevenlabs")

# ElevenLabs raw PCM only accepts this discrete set of sample rates (pcm_<rate>).
_VALID_SAMPLE_RATES = (8000, 16000, 22050, 24000, 32000, 44100, 48000)


def _to_provider_error(exc: Exception) -> ProviderError:
    """Map an ElevenLabs API error to a clean ProviderError (no raw traceback)."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()
    is_auth = name in ("UnauthorizedError", "ForbiddenError") or status in (401, 403)
    if is_auth or "unauthor" in text:
        return ProviderConfigError(
            "ElevenLabs rejected the API key. Check ELEVENLABS_API_KEY in backend/.env "
            "(get one at https://elevenlabs.io), or set TTS_PROVIDER=kokoro for the default."
        )
    if status == 429 or "rate limit" in text or "quota" in text:
        return ProviderQuotaError(
            "ElevenLabs rate limit / quota exceeded. Wait and retry, or fall back with "
            "TTS_PROVIDER=kokoro in backend/.env."
        )
    return ProviderError(f"ElevenLabs TTS error: {str(exc)[:200]} — please retry in a moment.")


class ElevenLabsTTS(TTSProvider):
    concurrent_warm = True  # cloud HTTP: warm the static-line cache in parallel

    def __init__(
        self,
        *,
        api_key: str | None,
        voice_id: str | None = None,
        model: str = "eleven_turbo_v2_5",
        sample_rate: int = 24000,
    ) -> None:
        if not api_key:
            raise ProviderConfigError(
                "ELEVENLABS_API_KEY is not set. Get a key at https://elevenlabs.io "
                "and add it to backend/.env (or set TTS_PROVIDER=kokoro for the default)."
            )
        if not voice_id:
            raise ProviderConfigError(
                "ELEVENLABS_VOICE_ID is not set. Pick a voice id at https://elevenlabs.io "
                "and add it to backend/.env."
            )
        if sample_rate not in _VALID_SAMPLE_RATES:
            raise ProviderConfigError(
                f"ELEVENLABS_SAMPLE_RATE={sample_rate} is unsupported; "
                f"choose one of {_VALID_SAMPLE_RATES}."
            )
        from elevenlabs.client import AsyncElevenLabs

        self._client: AsyncElevenLabs = AsyncElevenLabs(api_key=api_key)
        self._voice_id = voice_id
        self._model = model
        self._sample_rate = sample_rate
        self._output_format = f"pcm_{sample_rate}"

    @property
    def output_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=self._sample_rate)

    async def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return
        try:
            stream = self._client.text_to_speech.stream(
                self._voice_id,
                text=text,
                model_id=self._model,
                output_format=self._output_format,
            )
            # HTTP chunks can split a 16-bit sample → re-align before yielding.
            async for chunk in aligned_pcm16(stream, self.output_format):
                yield chunk
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — map any SDK/transport error to a clean ProviderError
            raise _to_provider_error(exc) from exc
