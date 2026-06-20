"""Audio helpers shared by providers and dev scripts.

Conversions between WAV files, float32 numpy arrays (the model-facing
representation), and PCM16 :class:`AudioChunk` (the transport representation).
Resampling uses ``soxr`` (high quality, light wheel).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

from src.providers.types import AudioChunk, AudioFormat

_PCM16_PEAK = 32767


# --------------------------------------------------------------------------- #
# WAV I/O                                                                     #
# --------------------------------------------------------------------------- #
def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Read a WAV file as mono float32 in [-1, 1]. Returns (samples, sample_rate)."""
    samples, sample_rate = sf.read(str(path), dtype="float32", always_2d=False)
    if samples.ndim > 1:  # down-mix to mono
        samples = samples.mean(axis=1)
    return np.ascontiguousarray(samples, dtype=np.float32), int(sample_rate)


def write_wav(path: str | Path, samples: np.ndarray, sample_rate: int) -> None:
    """Write a mono float32 array to a 16-bit PCM WAV file."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.asarray(samples, dtype=np.float32), sample_rate, subtype="PCM_16")


# --------------------------------------------------------------------------- #
# Conversions                                                                 #
# --------------------------------------------------------------------------- #
def float_to_pcm16(samples: np.ndarray) -> bytes:
    """Convert float32 [-1, 1] samples to little-endian PCM16 bytes."""
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * _PCM16_PEAK).astype("<i2").tobytes()


def pcm16_to_float(data: bytes) -> np.ndarray:
    """Convert little-endian PCM16 bytes to float32 [-1, 1] samples."""
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / _PCM16_PEAK


def resample(samples: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Resample mono float32 audio. No-op when rates already match."""
    if sr_in == sr_out:
        return np.asarray(samples, dtype=np.float32)
    return soxr.resample(samples, sr_in, sr_out).astype(np.float32)


def chunk_from_float(samples: np.ndarray, sample_rate: int) -> AudioChunk:
    """Wrap float32 samples as a PCM16 :class:`AudioChunk`."""
    return AudioChunk(data=float_to_pcm16(samples), fmt=AudioFormat(sample_rate=sample_rate))


def chunk_to_float(chunk: AudioChunk) -> np.ndarray:
    """Decode an :class:`AudioChunk` to float32 samples."""
    return pcm16_to_float(chunk.data)


# --------------------------------------------------------------------------- #
# Streaming a file as if live                                                 #
# --------------------------------------------------------------------------- #
async def stream_wav(
    path: str | Path,
    *,
    chunk_ms: int = 20,
    target_sr: int = 16000,
    realtime: bool = True,
) -> AsyncIterator[AudioChunk]:
    """Yield a WAV file as fixed-size PCM16 chunks, optionally paced in real time.

    This is the dev replay harness's audio source: it makes a file behave like a
    live microphone feed so the pipeline sees the same streaming shape it will in
    production (ARCHITECTURE.md §2 — "dev uses replayed audio").
    """
    samples, sample_rate = read_wav(path)
    samples = resample(samples, sample_rate, target_sr)
    chunk_size = max(1, int(target_sr * chunk_ms / 1000))
    for start in range(0, len(samples), chunk_size):
        yield chunk_from_float(samples[start : start + chunk_size], target_sr)
        if realtime:
            await asyncio.sleep(chunk_ms / 1000)
