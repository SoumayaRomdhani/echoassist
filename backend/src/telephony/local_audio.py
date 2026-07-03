"""Local microphone + speaker transport — the first live (non-file) transport.

The smallest "live" brick for Sprint 8: you talk into the laptop mic and the agent
answers on the speakers, exercising the full *turn* loop with no telephony
infrastructure, no cloud account and no Docker. It implements the same
:class:`~src.telephony.transport.Transport` interface a LiveKit/SIP transport will,
so moving to a real phone number later swaps this class out and touches nothing in
the pipeline.

Capture: a sounddevice ``InputStream`` callback (PortAudio thread) hands frames to
the asyncio loop via ``call_soon_threadsafe``; :meth:`listen` runs them through an
energy :class:`~src.telephony.vad.Endpointer` and ends the stream at the utterance
endpoint. Frames are yielded at the capture sample rate — ``WhisperLocalSTT``
resamples to 16 kHz itself — so no resampling happens here.

Playback reuses :func:`src.audio.playback.play`. It is half-duplex by design (the
pipeline is turn-based); the mic queue is drained before each turn so the agent
never transcribes its own voice. Acoustic echo is not cancelled — use headphones,
or a real carrier's echo control once telephony lands.

``sounddevice`` is imported lazily so importing this module (e.g. in tests) never
requires an audio backend.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import AsyncIterator

import numpy as np

from src.audio.io import chunk_from_float, chunk_to_float
from src.audio.playback import play
from src.providers.types import AudioChunk
from src.telephony.transport import Transport
from src.telephony.vad import EndpointConfig, Endpointer, watch_for_barge_in

log = logging.getLogger("echoassist.telephony.local")


class LocalAudioTransport(Transport):
    """A :class:`Transport` backed by the default microphone and speaker."""

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        endpoint: EndpointConfig | None = None,
        input_device: int | str | None = None,
        barge_in_threshold: float = 0.02,
        barge_in_onset_frames: int = 5,
    ) -> None:
        self._sr = sample_rate
        self._cfg = endpoint or EndpointConfig()
        self._frame_size = max(1, int(sample_rate * self._cfg.frame_ms / 1000))
        self._input_device = input_device
        self._endpointer = Endpointer(self._cfg)
        # Barge-in uses a higher bar than endpointing: a louder, slightly longer run
        # of speech, so speaker bleed or a stray cough does not cut the agent off.
        self._barge_cfg = EndpointConfig(
            frame_ms=self._cfg.frame_ms,
            energy_threshold=barge_in_threshold,
            onset_frames=barge_in_onset_frames,
        )
        self._queue: asyncio.Queue[np.ndarray] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stream: object | None = None

    async def start(self) -> None:
        import sounddevice as sd

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()

        def _callback(indata, _frames, _time, status) -> None:  # PortAudio thread
            if status:
                log.debug("input stream status: %s", status)
            # Copy: sounddevice reuses the buffer after the callback returns.
            frame = np.array(indata[:, 0], dtype=np.float32)
            assert self._loop is not None and self._queue is not None
            self._loop.call_soon_threadsafe(self._queue.put_nowait, frame)

        self._stream = sd.InputStream(
            samplerate=self._sr,
            channels=1,
            dtype="float32",
            blocksize=self._frame_size,
            device=self._input_device,
            callback=_callback,
        )
        self._stream.start()
        log.info("microphone open: %d Hz, %d-sample frames", self._sr, self._frame_size)

    async def listen(self) -> AsyncIterator[AudioChunk]:
        if self._queue is None:
            raise RuntimeError("LocalAudioTransport.start() must be called before listen()")
        self._drain()
        self._endpointer.reset()
        # Hold the frames seen before onset is confirmed so the start of speech is
        # not clipped; flush them once the caller is committed to speaking.
        preroll: deque[np.ndarray] = deque(maxlen=self._cfg.onset_frames)
        while True:
            frame = await self._queue.get()
            ended = self._endpointer.update(frame)
            if self._endpointer.started:
                while preroll:
                    yield chunk_from_float(preroll.popleft(), self._sr)
                yield chunk_from_float(frame, self._sr)
            else:
                preroll.append(frame)
            if ended:
                return

    async def send(self, audio: AudioChunk) -> None:
        await play(audio)

    async def send_interruptible(self, audio: AudioChunk) -> bool:
        """Play agent audio while listening for the caller to barge in.

        Returns ``True`` (and stops playback) the instant the caller talks over the
        agent, else ``False`` when the line finishes. Requires headphones: there is
        no echo cancellation, so on open speakers the mic hears the agent and would
        trip an immediate false barge-in (a real carrier / Pipecat handles echo once
        telephony lands).
        """
        import sounddevice as sd

        if self._queue is None:
            raise RuntimeError("start() must be called before send_interruptible()")
        self._drain()
        sd.play(chunk_to_float(audio), audio.fmt.sample_rate)

        finished = asyncio.Event()

        async def _await_playback() -> None:
            await asyncio.to_thread(sd.wait)
            finished.set()

        async def _next_frame() -> np.ndarray | None:
            assert self._queue is not None
            try:
                return self._queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(self._cfg.frame_ms / 1000)
                return None

        waiter = asyncio.create_task(_await_playback())
        try:
            barged = await watch_for_barge_in(
                _next_frame, lambda: not finished.is_set(), Endpointer(self._barge_cfg)
            )
            if barged:
                sd.stop()
        finally:
            await waiter
        return barged

    async def send_stream_interruptible(self, audio: AsyncIterator[AudioChunk]) -> bool:
        """Play a stream of agent audio through ONE continuous output stream.

        The base default plays one ``sd.play`` per chunk — catastrophic when a cloud TTS
        emits 100+ tiny chunks per reply (each ``sd.play``/``sd.wait`` has fixed overhead,
        so a 5 s reply can take ~50 s and it throttles the TTS). Here every chunk is written
        into a single persistent :class:`sounddevice.OutputStream`, so playback is gap-free
        and real-time and never gates synthesis. Barge-in is checked between chunk writes.

        Headphones required (no echo cancellation), same as :meth:`send_interruptible`.
        """
        import sounddevice as sd

        if self._queue is None:
            raise RuntimeError("start() must be called before send_stream_interruptible()")
        self._drain()
        monitor = Endpointer(self._barge_cfg)
        monitor.reset()
        stream: sd.OutputStream | None = None
        barged = False
        try:
            async for chunk in audio:
                if barged or not chunk.data:
                    continue  # drain remaining audio so the producer records the turn
                if stream is None:
                    stream = sd.OutputStream(
                        samplerate=chunk.fmt.sample_rate,
                        channels=chunk.fmt.channels,
                        dtype="float32",
                    )
                    stream.start()
                # Blocking write (waits only when the device buffer is full = real-time);
                # offload so the event loop stays free for the mic callback. Shape as
                # (frames, channels) — what OutputStream.write expects.
                samples = chunk_to_float(chunk).reshape(-1, chunk.fmt.channels)
                await asyncio.to_thread(stream.write, samples)
                if self._barge_in_pending(monitor):
                    barged = True
                    stream.abort()
        finally:
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.stop()
                    stream.close()
        return barged

    def _barge_in_pending(self, monitor: Endpointer) -> bool:
        """Feed mic frames captured during playback to the barge monitor; True on onset."""
        assert self._queue is not None
        while not self._queue.empty():
            monitor.update(self._queue.get_nowait())
            if monitor.started:
                return True
        return False

    def _drain(self) -> None:
        # Discard frames captured between turns (e.g. the agent's own audio leaking
        # back through the speakers) so the next utterance starts clean.
        assert self._queue is not None
        while not self._queue.empty():
            self._queue.get_nowait()

    async def aclose(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
