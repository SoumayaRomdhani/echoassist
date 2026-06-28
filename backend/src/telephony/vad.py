"""Energy-based utterance endpointing for live transports.

A transport reading a continuous microphone feed needs to know when the caller has
*finished* a turn so the pipeline can respond. This module answers exactly that
with a dependency-free RMS energy detector: feed it consecutive fixed-size frames
and it reports utterance onset and the endpoint (a run of trailing silence after
speech).

Why energy and not ``webrtcvad``: the latter is a C extension that needs a build
toolchain on Windows and adds a dependency for a job a few lines of NumPy do well
enough for turn-taking. faster-whisper still runs its own ``vad_filter`` when it
transcribes the buffered utterance, so this detector only has to decide *turn
boundaries*, not clean the audio.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class EndpointConfig:
    """Tunables for :class:`Endpointer` (defaults suit a 16 kHz, 20 ms-frame mic)."""

    frame_ms: int = 20
    energy_threshold: float = 0.015   # RMS over [-1, 1]; a frame at/above this is speech
    onset_frames: int = 3             # consecutive speech frames that confirm speech started
    silence_ms: int = 700             # trailing silence after speech that ends the utterance
    max_utterance_ms: int = 15000     # hard cap so a noisy line can't listen forever


class Endpointer:
    """Decides when a caller's utterance has ended, from a stream of audio frames.

    Stateful and single-utterance: feed frames via :meth:`update`; call
    :meth:`reset` before each new turn. Silence *before* onset is ignored (we wait
    for the caller to start); once speaking, ``silence_ms`` of trailing silence —
    or hitting ``max_utterance_ms`` — ends the turn.
    """

    def __init__(self, config: EndpointConfig | None = None) -> None:
        self._cfg = config or EndpointConfig()
        self.reset()

    def reset(self) -> None:
        """Clear all state so the endpointer can track a fresh utterance."""
        self._onset_run = 0
        self._silence_run = 0
        self._started = False
        self._elapsed_ms = 0

    @property
    def started(self) -> bool:
        """Whether speech onset has been detected for the current utterance."""
        return self._started

    def update(self, samples: np.ndarray) -> bool:
        """Feed one frame of float32 samples. Return ``True`` once the utterance ends."""
        rms = float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0
        is_speech = rms >= self._cfg.energy_threshold

        if not self._started:
            # Wait for a short run of speech before committing — ignores stray clicks.
            self._onset_run = self._onset_run + 1 if is_speech else 0
            if self._onset_run >= self._cfg.onset_frames:
                self._started = True
            return False

        self._elapsed_ms += self._cfg.frame_ms
        self._silence_run = 0 if is_speech else self._silence_run + 1
        if self._silence_run * self._cfg.frame_ms >= self._cfg.silence_ms:
            return True
        return self._elapsed_ms >= self._cfg.max_utterance_ms


async def watch_for_barge_in(
    next_frame: Callable[[], Awaitable[np.ndarray | None]],
    is_playing: Callable[[], bool],
    monitor: Endpointer,
) -> bool:
    """Report a caller barge-in while the agent is speaking.

    Pulls microphone frames via ``next_frame`` (which may return ``None`` when no
    frame is ready yet) and feeds them to ``monitor`` for as long as ``is_playing``
    stays true. Returns ``True`` the instant speech onset is detected — the caller
    spoke over the agent — or ``False`` if playback finishes first. The decision is
    deliberately transport-free (it knows nothing of sounddevice) so it is
    unit-tested without an audio device; the live transport supplies ``next_frame``
    from its mic queue and ``is_playing`` from the playback state.
    """
    monitor.reset()
    while is_playing():
        frame = await next_frame()
        if frame is None:
            continue
        monitor.update(frame)
        if monitor.started:
            return True
    return False
