"""Audio conversion/resampling round-trips (no models, no I/O devices)."""

from __future__ import annotations

import numpy as np

from src.audio.io import (
    chunk_from_float,
    chunk_to_float,
    float_to_pcm16,
    pcm16_to_float,
    resample,
)
from src.providers.types import AudioFormat


def test_pcm16_float_roundtrip_is_lossless_enough() -> None:
    original = np.linspace(-1.0, 1.0, 2000, dtype=np.float32)
    restored = pcm16_to_float(float_to_pcm16(original))
    assert restored.shape == original.shape
    assert np.max(np.abs(restored - original)) < 1e-3  # PCM16 quantization step


def test_float_to_pcm16_clips_out_of_range() -> None:
    loud = np.array([2.0, -2.0], dtype=np.float32)
    restored = pcm16_to_float(float_to_pcm16(loud))
    assert np.all(np.abs(restored) <= 1.0)


def test_chunk_roundtrip_preserves_samples_and_format() -> None:
    samples = np.array([0.0, 0.25, -0.25, 0.5], dtype=np.float32)
    chunk = chunk_from_float(samples, 16000)
    assert chunk.fmt == AudioFormat(sample_rate=16000)
    assert chunk.num_samples == 4
    assert np.allclose(chunk_to_float(chunk), samples, atol=1e-3)


def test_resample_changes_length_proportionally() -> None:
    samples = np.zeros(16000, dtype=np.float32)  # 1 s @ 16 kHz
    out = resample(samples, 16000, 8000)
    assert abs(len(out) - 8000) <= 2


def test_resample_noop_when_rates_match() -> None:
    samples = np.ones(100, dtype=np.float32)
    assert np.array_equal(resample(samples, 16000, 16000), samples)
