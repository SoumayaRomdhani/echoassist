"""LiveKit transport — the same :class:`Transport` over WebRTC/SIP instead of a mic.

This is Path B's telephony brick (Sprint 8): it carries a call's audio over a
LiveKit room — a browser participant for the WebRTC loopback, or a PSTN caller
bridged in via LiveKit SIP (Twilio) for a real phone number. It implements the
**exact same** :class:`~src.telephony.transport.Transport` interface as
:class:`~src.telephony.local_audio.LocalAudioTransport`, so swapping the mic for a
real number changes only which transport the runner constructs — nothing in the
voice pipeline (ARCHITECTURE.md §2, §4). The structure deliberately mirrors
``LocalAudioTransport`` so the two are easy to compare:

  capture   : a frame reader pulls the caller's track frames (``rtc.AudioStream``,
              resampled to 16 kHz mono, fixed 20 ms frames) into an asyncio queue;
  listen()  : the *same* energy :class:`~src.telephony.vad.Endpointer` loop ends
              the stream at the utterance endpoint;
  send()    : agent ``AudioChunk`` is resampled and pushed to an ``rtc.AudioSource``
              feeding a published audio track;
  barge-in  : ``send_interruptible`` watches the inbound queue with the shared
              :func:`~src.telephony.vad.watch_for_barge_in`. Unlike open speakers,
              WebRTC/SIP does echo cancellation, so barge-in needs no headphones.

``livekit`` / ``livekit-api`` are imported lazily, only after the config check, so
importing this module (tests, the doctor) never requires the SDK to be installed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import numpy as np

from src.audio.io import chunk_from_float, chunk_to_float, float_to_pcm16, pcm16_to_float, resample
from src.providers.errors import ProviderConfigError
from src.providers.types import AudioChunk
from src.telephony.transport import Transport
from src.telephony.vad import EndpointConfig, Endpointer, watch_for_barge_in

if TYPE_CHECKING:  # typing only — never import the SDK at module load
    from livekit import rtc

log = logging.getLogger("echoassist.telephony.livekit")

_CAPTURE_SR = 16000   # inbound: matches WhisperLocalSTT / declared to Deepgram (no resample)
_PLAYBACK_SR = 48000  # outbound: LiveKit's native rate; agent audio is resampled to it
# Outbound playout buffer. LiveKit's AudioSource default is 1000 ms, which starves on the
# real-time SIP/PSTN leg: whenever the single asyncio loop is busy (STT, resample, RAG) it
# can't refill the 1 s buffer in time, so the phone hears silence *inside* an utterance even
# though the audio/transcript is complete (the dashboard, which isn't real-time, never shows
# it). A generous buffer hands each whole utterance to LiveKit's own playout up front, immune
# to loop stalls. Barge-in is unaffected: clear_queue() flushes it instantly on interruption.
_PLAYBACK_QUEUE_MS = 30_000


def _join_token(api_key: str, api_secret: str, *, identity: str, room: str) -> str:
    """A LiveKit JWT granting join + publish + subscribe in ``room`` (lazy SDK import)."""
    from livekit import api

    grants = api.VideoGrants(
        room_join=True, room=room, can_publish=True, can_subscribe=True
    )
    return (
        api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(grants)
        .to_jwt()
    )


def guest_meet_url(
    *, url: str, api_key: str, api_secret: str, room: str, identity: str = "caller"
) -> str:
    """A meet.livekit.io URL a human can open to join ``room`` and talk to the agent.

    The safe first step before any phone number: the WebRTC *loopback*. Start the
    agent (it joins ``room`` and waits), open this URL in a browser, allow the mic,
    and you are the caller — same screening session, no Twilio.
    """
    token = _join_token(api_key, api_secret, identity=identity, room=room)
    return f"https://meet.livekit.io/custom?liveKitUrl={url}&token={token}"


class LiveKitTransport(Transport):
    """A :class:`Transport` backed by a LiveKit room (WebRTC loopback or SIP/PSTN)."""

    def __init__(
        self,
        *,
        url: str | None,
        api_key: str | None,
        api_secret: str | None,
        room: str = "echoassist",
        identity: str = "agent",
        endpoint: EndpointConfig | None = None,
        join_timeout: float = 120.0,
        barge_in_threshold: float = 0.02,
        barge_in_onset_frames: int = 5,
        audio_debug: bool = False,
    ) -> None:
        missing = [
            name
            for name, value in (
                ("LIVEKIT_URL", url),
                ("LIVEKIT_API_KEY", api_key),
                ("LIVEKIT_API_SECRET", api_secret),
            )
            if not value
        ]
        if missing:
            raise ProviderConfigError(
                f"LiveKit transport is missing {', '.join(missing)}. Set them in backend/.env "
                "(LiveKit Cloud dashboard, or a self-hosted server)."
            )
        self._url = url
        self._api_key = api_key
        self._api_secret = api_secret
        self._room_name = room
        self._identity = identity
        self._cfg = endpoint or EndpointConfig()
        self._join_timeout = join_timeout
        self._audio_debug = audio_debug
        # Barge-in uses a higher bar than endpointing (a louder, slightly longer run of
        # speech) so a stray noise on the line does not cut the agent off mid-sentence.
        self._barge_cfg = EndpointConfig(
            frame_ms=self._cfg.frame_ms,
            energy_threshold=barge_in_threshold,
            onset_frames=barge_in_onset_frames,
        )
        self._endpointer = Endpointer(self._cfg)
        self._queue: asyncio.Queue[np.ndarray] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._room: rtc.Room | None = None
        self._source: rtc.AudioSource | None = None
        self._audio_stream: rtc.AudioStream | None = None
        self._audio_track: rtc.Track | None = None
        self._audio_track_ready: asyncio.Event | None = None
        self._reader: asyncio.Task[None] | None = None
        self._caller_ready: asyncio.Event | None = None
        self._caller: rtc.RemoteParticipant | None = None
        self._frames_seen = 0
        self._last_frame_at: float | None = None
        self._last_rms = 0.0
        self._reader_stopped: str | None = None

    # --- token ------------------------------------------------------------- #
    def _build_token(self) -> str:
        return _join_token(
            self._api_key, self._api_secret, identity=self._identity, room=self._room_name
        )

    # --- lifecycle --------------------------------------------------------- #
    async def start(self) -> None:
        from livekit import rtc

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._caller_ready = asyncio.Event()
        self._audio_track_ready = asyncio.Event()

        self._room = rtc.Room()

        @self._room.on("participant_connected")
        def _on_participant(participant: rtc.RemoteParticipant) -> None:  # event-loop thread
            if self._caller is None:
                self._caller = participant
                assert self._caller_ready is not None
                self._caller_ready.set()

        @self._room.on("track_published")
        def _on_track_published(
            publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant
        ) -> None:
            if publication.kind == rtc.TrackKind.KIND_AUDIO:
                log.info(
                    "caller %r published audio track source=%s subscribed=%s",
                    getattr(participant, "identity", "?"),
                    getattr(publication, "source", "?"),
                    getattr(publication, "subscribed", "?"),
                )
                publication.set_subscribed(True)

        @self._room.on("track_subscribed")
        def _on_track_subscribed(
            track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if publication.kind != rtc.TrackKind.KIND_AUDIO:
                return
            if publication.source not in (
                rtc.TrackSource.SOURCE_MICROPHONE,
                rtc.TrackSource.SOURCE_UNKNOWN,
            ):
                return
            if self._caller is None:
                self._caller = participant
                assert self._caller_ready is not None
                self._caller_ready.set()
            if self._audio_track is None:
                self._audio_track = track
                assert self._audio_track_ready is not None
                self._audio_track_ready.set()
                log.info(
                    "subscribed to caller %r audio track %r",
                    getattr(participant, "identity", "?"),
                    getattr(track, "sid", "?"),
                )

        await self._room.connect(
            self._url, self._build_token(), options=rtc.RoomOptions(auto_subscribe=True)
        )
        log.info("connected to LiveKit room %r as %r", self._room_name, self._identity)

        # Publish the agent's audio track so it can speak into the room.
        self._source = rtc.AudioSource(_PLAYBACK_SR, 1, queue_size_ms=_PLAYBACK_QUEUE_MS)
        track = rtc.LocalAudioTrack.create_audio_track("agent-voice", self._source)
        await self._room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )

        # A caller may already be in the room; otherwise wait for one to join.
        if self._caller is None and self._room.remote_participants:
            self._caller = next(iter(self._room.remote_participants.values()))
            self._caller_ready.set()
        for participant in self._room.remote_participants.values():
            for publication in participant.track_publications.values():
                if publication.kind != rtc.TrackKind.KIND_AUDIO:
                    continue
                publication.set_subscribed(True)
                if publication.track is not None and self._audio_track is None:
                    self._audio_track = publication.track
                    self._audio_track_ready.set()
        log.info("waiting up to %.0fs for a caller to join…", self._join_timeout)
        await asyncio.wait_for(self._caller_ready.wait(), timeout=self._join_timeout)
        log.info("waiting for caller microphone track…")
        await asyncio.wait_for(self._audio_track_ready.wait(), timeout=self._join_timeout)

        # Follow the caller's microphone track at 16 kHz mono, in 20 ms frames so the
        # energy endpointer sees the frame size its timing assumes.
        assert self._audio_track is not None
        self._audio_stream = rtc.AudioStream.from_track(
            track=self._audio_track,
            sample_rate=_CAPTURE_SR,
            num_channels=1,
            frame_size_ms=self._cfg.frame_ms,
        )
        self._reader = asyncio.create_task(self._read_frames())
        log.info("caller %r joined; capturing audio", getattr(self._caller, "identity", "?"))

    async def _read_frames(self) -> None:
        assert self._audio_stream is not None and self._queue is not None
        try:
            async for event in self._audio_stream:
                # LiveKit frames are 16-bit PCM; decode to float32 for the endpointer.
                samples = pcm16_to_float(bytes(event.frame.data))
                self._frames_seen += 1
                self._last_frame_at = time.monotonic()
                self._last_rms = (
                    float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0
                )
                if self._frames_seen == 1:
                    log.info(
                        "first inbound LiveKit audio frame received: samples=%d rms=%.4f",
                        len(samples),
                        self._last_rms,
                    )
                elif self._audio_debug and self._frames_seen % 250 == 0:
                    log.info(
                        "inbound LiveKit audio: frames=%d latest_rms=%.4f queue=%d",
                        self._frames_seen,
                        self._last_rms,
                        self._queue.qsize(),
                    )
                self._queue.put_nowait(samples)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the stream ends when the caller leaves; not fatal
            self._reader_stopped = f"{type(exc).__name__}: {exc}"
            log.warning("LiveKit audio stream reader stopped: %s", self._reader_stopped)
        else:
            self._reader_stopped = "stream ended"
            log.warning("LiveKit audio stream reader ended after %d frame(s)", self._frames_seen)

    # --- listen ------------------------------------------------------------ #
    async def listen(self) -> AsyncIterator[AudioChunk]:
        if self._queue is None:
            raise RuntimeError("LiveKitTransport.start() must be called before listen()")
        self._drain()
        self._endpointer.reset()
        # Hold pre-onset frames so the start of speech is not clipped; flush them once
        # the caller is committed to speaking.
        preroll: deque[np.ndarray] = deque(maxlen=self._cfg.onset_frames)
        waiting_ms = 0
        while True:
            try:
                frame = await asyncio.wait_for(self._queue.get(), timeout=5.0)
            except TimeoutError:
                reader_state = ""
                if self._reader is not None and self._reader.done():
                    reader_state = f" reader_stopped={self._reader_stopped or 'done'}."
                if self._frames_seen == 0:
                    log.warning(
                        "still waiting for caller audio frames from LiveKit. "
                        "Check the browser mic permission/mute state and close old meet tabs.%s",
                        reader_state,
                    )
                else:
                    log.warning(
                        "no new LiveKit audio frame for 5s (frames_seen=%d last_rms=%.4f).%s",
                        self._frames_seen,
                        self._last_rms,
                        reader_state,
                    )
                continue
            ended = self._endpointer.update(frame)
            if self._endpointer.started:
                while preroll:
                    yield chunk_from_float(preroll.popleft(), _CAPTURE_SR)
                yield chunk_from_float(frame, _CAPTURE_SR)
            else:
                waiting_ms += self._cfg.frame_ms
                if waiting_ms >= 5000:
                    log.info(
                        "waiting for speech onset: latest_rms=%.4f threshold=%.4f "
                        "(speak louder or lower --vad-threshold).",
                        self._last_rms,
                        self._cfg.energy_threshold,
                    )
                    waiting_ms = 0
                preroll.append(frame)
            if ended:
                return

    # --- send -------------------------------------------------------------- #
    async def _capture(self, audio: AudioChunk) -> None:
        from livekit import rtc

        assert self._source is not None
        samples = resample(chunk_to_float(audio), audio.fmt.sample_rate, _PLAYBACK_SR)
        frame = rtc.AudioFrame(
            data=float_to_pcm16(samples),
            sample_rate=_PLAYBACK_SR,
            num_channels=1,
            samples_per_channel=len(samples),
        )
        await self._source.capture_frame(frame)

    async def send(self, audio: AudioChunk) -> None:
        if self._source is None:
            raise RuntimeError("LiveKitTransport.start() must be called before send()")
        await self._capture(audio)

    async def send_interruptible(self, audio: AudioChunk) -> bool:
        """Play agent audio while listening for the caller to barge in.

        Returns ``True`` (and clears the playout queue) the instant the caller talks
        over the agent, else ``False`` when the line finishes. WebRTC/SIP does echo
        cancellation, so — unlike local open speakers — the agent's own voice does
        not trip a false barge-in.
        """
        if self._source is None or self._queue is None:
            raise RuntimeError("start() must be called before send_interruptible()")
        self._drain()
        await self._capture(audio)

        finished = asyncio.Event()

        async def _await_playout() -> None:
            assert self._source is not None
            await self._source.wait_for_playout()
            finished.set()

        async def _next_frame() -> np.ndarray | None:
            assert self._queue is not None
            try:
                return self._queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(self._cfg.frame_ms / 1000)
                return None

        waiter = asyncio.create_task(_await_playout())
        try:
            barged = await watch_for_barge_in(
                _next_frame, lambda: not finished.is_set(), Endpointer(self._barge_cfg)
            )
            if barged:
                self._source.clear_queue()
        finally:
            await waiter
        return barged

    async def send_stream_interruptible(self, audio: AsyncIterator[AudioChunk]) -> bool:
        """Play a *live* (token-streamed) TTS reply gap-free, while watching for barge-in.

        The base implementation plays each chunk then **waits for its playout** before
        capturing the next — which leaves LiveKit's playout buffer momentarily EMPTY
        between chunks. On the real-time SIP/PSTN leg that empty window is audible
        silence, so a streamed reply comes out chopped, even inside a word
        ("p-r-o-c-e-d…"). Pre-synthesized lines (disclosure/greeting/fillers) are sent
        as one chunk via :meth:`send_interruptible`, so they never hit this and sound
        fine — which is exactly the symptom this fixes.

        Here we instead pour every chunk into the buffer **as soon as it arrives**
        (``_capture`` queues it; we do NOT wait for it to finish), so the buffer plays
        the chunks back-to-back with no gap. The generous ``_PLAYBACK_QUEUE_MS`` buffer
        absorbs jitter in the LLM->TTS stream.

        Barge-in still works: on interruption we clear the buffer at once and stop
        capturing. The stream is always drained to exhaustion so its producer (the
        dialogue's streaming turn) records the spoken turn even when the caller cuts in.
        Returns ``True`` if the caller barged in.
        """
        if self._source is None or self._queue is None:
            raise RuntimeError("start() must be called before send_stream_interruptible()")
        self._drain()

        barged = asyncio.Event()
        fed = asyncio.Event()       # the whole stream has been consumed
        finished = asyncio.Event()  # fed AND the buffer has fully played out

        async def _feed() -> None:
            # Pour chunks into the buffer as they arrive. After a barge-in, keep pulling
            # from the iterator (without capturing) so the producer finishes bookkeeping.
            try:
                async for chunk in audio:
                    if not barged.is_set():
                        await self._capture(chunk)
            finally:
                fed.set()

        async def _await_done() -> None:
            assert self._source is not None
            await fed.wait()
            if not barged.is_set():
                await self._source.wait_for_playout()
            finished.set()

        async def _next_frame() -> np.ndarray | None:
            assert self._queue is not None
            try:
                return self._queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(self._cfg.frame_ms / 1000)
                return None

        feeder = asyncio.create_task(_feed())
        done_waiter = asyncio.create_task(_await_done())
        try:
            if await watch_for_barge_in(
                _next_frame, lambda: not finished.is_set(), Endpointer(self._barge_cfg)
            ):
                barged.set()
                self._source.clear_queue()
        finally:
            await feeder
            await done_waiter
        return barged.is_set()

    def _drain(self) -> None:
        # Discard frames captured between turns so the next utterance starts clean.
        assert self._queue is not None
        while not self._queue.empty():
            self._queue.get_nowait()

    async def aclose(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
            self._reader = None
        if self._audio_stream is not None:
            await self._audio_stream.aclose()
            self._audio_stream = None
        if self._source is not None:
            await self._source.aclose()
            self._source = None
        if self._room is not None:
            await self._room.disconnect()
            self._room = None
