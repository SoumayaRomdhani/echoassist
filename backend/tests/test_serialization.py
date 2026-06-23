"""Serialized CPU-provider wrappers enforce one-at-a-time model access."""

from __future__ import annotations

import asyncio

import pytest

from src.providers.concurrency import SerializedSTT, SerializedTTS
from tests.conftest import FakeSTT, FakeTTS, Probe, audio


async def _drain_stt(stt, text: str) -> str:
    transcript = await stt.transcribe(audio(text))
    return transcript.text


@pytest.mark.asyncio
async def test_serialized_stt_never_overlaps() -> None:
    probe = Probe()
    stt = SerializedSTT(FakeSTT(probe), asyncio.Lock())

    results = await asyncio.gather(*[_drain_stt(stt, f"turn {i}") for i in range(6)])

    assert probe.max_active == 1                 # the lock serialized every call
    assert sorted(results) == sorted(f"turn {i}" for i in range(6))


@pytest.mark.asyncio
async def test_serialized_tts_never_overlaps() -> None:
    probe = Probe()
    tts = SerializedTTS(FakeTTS(probe), asyncio.Lock())

    async def synth(text: str) -> bytes:
        chunk = await tts.synthesize(text)
        return chunk.data

    out = await asyncio.gather(*[synth(f"line {i}") for i in range(6)])

    assert probe.max_active == 1
    assert {b.decode() for b in out} == {f"line {i}" for i in range(6)}


@pytest.mark.asyncio
async def test_one_lock_serializes_stt_and_tts_together() -> None:
    # Sharing a single lock across the wrappers prevents STT and TTS overlapping
    # too — the right policy for one shared CPU/box.
    probe = Probe()
    lock = asyncio.Lock()
    stt = SerializedSTT(FakeSTT(probe), lock)
    tts = SerializedTTS(FakeTTS(probe), lock)

    await asyncio.gather(
        _drain_stt(stt, "hello"),
        tts.synthesize("world"),
        _drain_stt(stt, "again"),
    )
    assert probe.max_active == 1


@pytest.mark.asyncio
async def test_serialized_tts_preserves_output_format() -> None:
    tts = SerializedTTS(FakeTTS(), asyncio.Lock())
    assert tts.output_format.sample_rate == 24000
