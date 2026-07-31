"""Deepgram (Aura) text-to-speech (paid drop-in, Sprint 8 Path B).

A config-only swap for the open-source default (``kokoro``): set
``TTS_PROVIDER=deepgram`` + ``DEEPGRAM_TTS_API_KEY`` and nothing in the pipeline
changes (ARCHITECTURE.md §2, §5). The TTS key is **separate** from STT's
``DEEPGRAM_API_KEY`` so text-to-speech credits stay on their own billing line (it
falls back to ``DEEPGRAM_API_KEY`` only when the TTS key is unset). Aura streams
audio with very low time-to-first-audio, the low-latency complement to Deepgram STT.

Unlike Cartesia/ElevenLabs, the *voice* is the model (``aura-2-thalia-en`` …), so
there is no separate voice id to configure.

Language mirroring (FR/EN): an Aura voice speaks ONE language — the language is baked
into the model name (``…-en`` vs ``…-fr``) and there is no single Aura model that
auto-switches between English and French. So, like Kokoro, this provider keeps a
default (English) model and a French model and picks per utterance: it detects whether
the reply is French and, if so, synthesizes with the French voice; otherwise the
default. That lets the agent open in English and speak French once the caller does.

We request **raw ``linear16``** (``container="none"``) at the configured sample
rate, which is exactly our wire format (providers/types.py: PCM16 mono LE), so each
streamed chunk is wrapped in an :class:`AudioChunk` with no re-encoding. The async
``generate`` call yields bytes as the server produces them (low TTFA), driven by the
sentence-streamer in ``src/agent/streaming.py``.

The vendor SDK is imported lazily, only after the API-key check, so importing this
module (tests, the doctor) never requires ``deepgram-sdk`` to be installed.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from src.providers.errors import ProviderConfigError, ProviderError, ProviderQuotaError
from src.providers.tts.base import TTSProvider, aligned_pcm16
from src.providers.tts.language import looks_french
from src.providers.types import AudioChunk, AudioFormat

if TYPE_CHECKING:  # typing only — never import the SDK at module load
    from deepgram import AsyncDeepgramClient

log = logging.getLogger("echoassist.tts.deepgram")

# Our wire format (providers/types.py): raw PCM, signed 16-bit, little-endian, mono.
# container="none" strips the WAV header linear16 carries by default.
_ENCODING = "linear16"
_CONTAINER = "none"
# Sample rates Deepgram Aura supports for linear16 output.
_VALID_SAMPLE_RATES = (8000, 16000, 24000, 32000, 48000)


def _to_provider_error(exc: Exception) -> ProviderError:
    """Map a Deepgram/transport error to a clean ProviderError (no raw traceback)."""
    text = str(exc).lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status in (401, 403) or "unauthor" in text or "forbidden" in text or "invalid auth" in text:
        return ProviderConfigError(
            "Deepgram rejected the API key (401/403). Check DEEPGRAM_TTS_API_KEY in backend/.env "
            "(get one at https://console.deepgram.com), or set TTS_PROVIDER=kokoro for the default."
        )
    if status == 429 or "rate limit" in text or "quota" in text or "too many requests" in text:
        return ProviderQuotaError(
            "Deepgram rate limit / quota exceeded. Wait and retry, or fall back with "
            "TTS_PROVIDER=kokoro in backend/.env."
        )
    return ProviderError(f"Deepgram TTS error: {str(exc)[:200]} — please retry in a moment.")


class DeepgramTTS(TTSProvider):
    concurrent_warm = True  # cloud HTTP: warm the static-line cache in parallel

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "aura-2-thalia-en",
        model_fr: str | None = "aura-2-agathe-fr",
        sample_rate: int = 24000,
    ) -> None:
        if not api_key:
            raise ProviderConfigError(
                "DEEPGRAM_TTS_API_KEY is not set. Get a key at https://console.deepgram.com "
                "and add it to backend/.env (or set TTS_PROVIDER=kokoro for the default)."
            )
        if sample_rate not in _VALID_SAMPLE_RATES:
            raise ProviderConfigError(
                f"DEEPGRAM_TTS_SAMPLE_RATE={sample_rate} is unsupported; "
                f"choose one of {_VALID_SAMPLE_RATES}."
            )
        from deepgram import AsyncDeepgramClient

        self._client: AsyncDeepgramClient = AsyncDeepgramClient(api_key=api_key)
        self._model = model            # default / English voice
        # French voice, used only when a reply is French. Blank => stay on the default
        # voice for every reply (French text would then be read by the English voice).
        self._model_fr = model_fr or model
        self._sample_rate = sample_rate

    @property
    def output_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=self._sample_rate)

    def _select_model(self, text: str) -> str:
        """The Aura model (voice) for ``text`` — the French voice when French, else default."""
        return self._model_fr if looks_french(text) else self._model

    async def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return
        try:
            # generate() is an async-generator function (yields bytes as the server
            # produces them) — iterate it directly, do not await it. Its HTTP chunks
            # can split a 16-bit sample, so re-align before yielding (aligned_pcm16).
            byte_stream = self._client.speak.v1.audio.generate(
                text=text,
                model=self._select_model(text),
                encoding=_ENCODING,
                sample_rate=self._sample_rate,
                container=_CONTAINER,
            )
            async for chunk in aligned_pcm16(byte_stream, self.output_format):
                yield chunk
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — map any SDK/transport error to a clean ProviderError
            raise _to_provider_error(exc) from exc
