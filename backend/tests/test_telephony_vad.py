"""Energy endpointing logic (pure, hardware-free)."""

from __future__ import annotations

import numpy as np
import pytest

from src.telephony.vad import EndpointConfig, Endpointer, watch_for_barge_in

_FRAME = 320  # samples per frame (size is irrelevant to RMS; kept realistic for 16 kHz/20 ms)


def _speech(n: int = _FRAME) -> np.ndarray:
    return np.full(n, 0.2, dtype=np.float32)   # RMS 0.2 >> default threshold (0.015)


def _silence(n: int = _FRAME) -> np.ndarray:
    return np.zeros(n, dtype=np.float32)


def test_silence_before_speech_never_ends_and_never_starts() -> None:
    ep = Endpointer()
    for _ in range(100):
        assert ep.update(_silence()) is False
    assert ep.started is False


def test_onset_requires_consecutive_speech_frames() -> None:
    ep = Endpointer(EndpointConfig(onset_frames=3))
    assert ep.update(_speech()) is False
    assert ep.started is False          # one frame is not enough
    ep.update(_speech())
    assert ep.update(_speech()) is False
    assert ep.started is True           # three consecutive speech frames confirm onset


def test_trailing_silence_ends_the_utterance() -> None:
    cfg = EndpointConfig(frame_ms=20, silence_ms=700, onset_frames=3)
    ep = Endpointer(cfg)
    for _ in range(3):
        ep.update(_speech())
    assert ep.started is True

    needed = cfg.silence_ms // cfg.frame_ms          # 35 silent frames
    for _ in range(needed - 1):
        assert ep.update(_silence()) is False
    assert ep.update(_silence()) is True


def test_brief_pause_does_not_end_the_utterance() -> None:
    cfg = EndpointConfig(frame_ms=20, silence_ms=700, onset_frames=3)
    ep = Endpointer(cfg)
    for _ in range(3):
        ep.update(_speech())

    for _ in range(10):                              # 200 ms < 700 ms: just a breath
        assert ep.update(_silence()) is False
    ep.update(_speech())                             # speech resets the silence run
    for _ in range(34):
        assert ep.update(_silence()) is False
    assert ep.update(_silence()) is True             # now the full silence run elapses


def test_max_utterance_caps_continuous_speech() -> None:
    cfg = EndpointConfig(frame_ms=20, max_utterance_ms=100, silence_ms=10_000, onset_frames=1)
    ep = Endpointer(cfg)
    ep.update(_speech())                             # onset frame (started; not yet counted)
    results = [ep.update(_speech()) for _ in range(5)]   # elapsed 20,40,60,80,100 ms
    assert results == [False, False, False, False, True]


def _adaptive_cfg(**overrides) -> EndpointConfig:
    base = dict(
        frame_ms=20, silence_ms=600, min_silence_ms=400,
        long_utterance_ms=1000, onset_frames=1, adaptive=True,
    )
    return EndpointConfig(**{**base, **overrides})


def test_long_utterance_ends_at_the_shorter_adaptive_endpoint() -> None:
    cfg = _adaptive_cfg()
    ep = Endpointer(cfg)
    ep.update(_speech())                                 # onset
    for _ in range(50):                                  # 1000 ms of speech -> "a full thought"
        ep.update(_speech())

    needed = cfg.min_silence_ms // cfg.frame_ms          # 20 silent frames -> 400 ms
    for _ in range(needed - 1):
        assert ep.update(_silence()) is False
    assert ep.update(_silence()) is True                 # ended early at min_silence_ms


def test_short_utterance_holds_the_longer_endpoint() -> None:
    cfg = _adaptive_cfg()
    ep = Endpointer(cfg)
    ep.update(_speech())                                 # onset
    for _ in range(10):                                  # only 200 ms -> a short reply/hesitation
        ep.update(_speech())

    # 400 ms of silence is NOT enough for a short utterance — it waits the full silence_ms.
    for _ in range(cfg.silence_ms // cfg.frame_ms - 1):  # 29 silent frames -> 580 ms
        assert ep.update(_silence()) is False
    assert ep.update(_silence()) is True                 # ends only at the full 600 ms


def test_adaptive_off_keeps_the_fixed_endpoint_after_a_long_utterance() -> None:
    cfg = _adaptive_cfg(adaptive=False)
    ep = Endpointer(cfg)
    ep.update(_speech())                                 # onset
    for _ in range(50):                                  # long utterance, but adaptivity is off
        ep.update(_speech())

    for _ in range(cfg.silence_ms // cfg.frame_ms - 1):  # full 600 ms required despite the length
        assert ep.update(_silence()) is False
    assert ep.update(_silence()) is True


@pytest.mark.asyncio
async def test_barge_in_detected_when_caller_speaks_over_playback() -> None:
    monitor = Endpointer(EndpointConfig(onset_frames=2))
    frames = iter([_silence(), _speech(), _speech(), _speech()])

    async def _next() -> np.ndarray:
        return next(frames)

    # is_playing stays True; the caller speaks, so onset is reached mid-playback.
    assert await watch_for_barge_in(_next, lambda: True, monitor) is True


@pytest.mark.asyncio
async def test_no_barge_in_when_playback_finishes_during_silence() -> None:
    monitor = Endpointer()
    ticks = {"n": 0}

    async def _next() -> np.ndarray:
        return _silence()

    def _is_playing() -> bool:                       # playback runs for five frames, then ends
        ticks["n"] += 1
        return ticks["n"] <= 5

    assert await watch_for_barge_in(_next, _is_playing, monitor) is False
