"""faster-whisper speech-to-text (open-source default).

ARCHITECTURE.md §6: faster-whisper (large-v3 in production; a smaller model is a
fine dev default). The model is loaded lazily on first use and reused; the
blocking transcribe call runs in a worker thread so it never stalls the loop.

Device handling: ``device=auto`` prefers CUDA when a GPU is present but falls
back to CPU if CUDA inference fails at runtime (e.g. the CUDA/cuBLAS runtime
libraries are missing, or the card is too small) — so it never hard-crashes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from src.audio.io import pcm16_to_float, resample
from src.providers.stt.base import STTProvider
from src.providers.types import AudioChunk, Transcript

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

log = logging.getLogger("echoassist.stt.whisper")

_TARGET_SR = 16000  # Whisper operates at 16 kHz mono.


class WhisperLocalSTT(STTProvider):
    def __init__(
        self,
        *,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "int8",
        language: str | None = None,
        beam_size: int = 5,
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language = language
        self._beam_size = beam_size
        self._model: WhisperModel | None = None
        self._active_device: str | None = None

    # --- model lifecycle ---------------------------------------------------
    def _resolve_device(self) -> str:
        if self._device != "auto":
            return self._device
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                return "cuda"
        except Exception:  # noqa: BLE001 — any failure means fall back to CPU
            pass
        return "cpu"

    def _build_model(self, device: str) -> WhisperModel:
        from faster_whisper import WhisperModel

        log.info(
            "Loading faster-whisper model=%s device=%s compute=%s",
            self._model_size,
            device,
            self._compute_type,
        )
        model = WhisperModel(self._model_size, device=device, compute_type=self._compute_type)
        self._active_device = device
        return model

    def _ensure_model(self) -> WhisperModel:
        if self._model is None:
            self._model = self._build_model(self._resolve_device())
        return self._model

    # --- inference ---------------------------------------------------------
    def _decode(self, model: WhisperModel, samples) -> Transcript:
        segments, info = model.transcribe(
            samples,
            language=self._language,
            beam_size=self._beam_size,
            vad_filter=True,
        )
        text = "".join(segment.text for segment in segments).strip()
        return Transcript(
            text=text,
            is_final=True,
            language=getattr(info, "language", None),
            confidence=getattr(info, "language_probability", None),
        )

    def _transcribe_sync(self, samples) -> Transcript:
        model = self._ensure_model()
        try:
            return self._decode(model, samples)
        except Exception as exc:  # noqa: BLE001 — degrade to CPU rather than crash the call
            if self._active_device == "cpu":
                raise
            log.warning("Whisper on %s failed (%s); falling back to CPU.", self._active_device, exc)
            self._model = self._build_model("cpu")
            return self._decode(self._model, samples)

    async def transcribe_stream(
        self, audio: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[Transcript]:
        # faster-whisper is not incremental: buffer the utterance, then decode once.
        buffer = bytearray()
        sample_rate = _TARGET_SR
        async for chunk in audio:
            buffer.extend(chunk.data)
            sample_rate = chunk.fmt.sample_rate

        if not buffer:
            yield Transcript(text="", is_final=True)
            return

        samples = pcm16_to_float(bytes(buffer))
        samples = resample(samples, sample_rate, _TARGET_SR)
        yield await asyncio.to_thread(self._transcribe_sync, samples)
