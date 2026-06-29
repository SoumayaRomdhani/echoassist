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
        self._reader: asyncio.Task[None] | None = None
        self._caller_ready: asyncio.Event | None = None
        self._caller: rtc.RemoteParticipant | None = None

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

        self._room = rtc.Room()

        @self._room.on("participant_connected")
        def _on_participant(participant: rtc.RemoteParticipant) -> None:  # event-loop thread
            if self._caller is None:
                self._caller = participant
                assert self._caller_ready is not None
                self._caller_ready.set()

        await self._room.connect(
            self._url, self._build_token(), options=rtc.RoomOptions(auto_subscribe=True)
        )
        log.info("connected to LiveKit room %r as %r", self._room_name, self._identity)

        # Publish the agent's audio track so it can speak into the room.
        self._source = rtc.AudioSource(_PLAYBACK_SR, 1)
        track = rtc.LocalAudioTrack.create_audio_track("agent-voice", self._source)
        await self._room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )

        # A caller may already be in the room; otherwise wait for one to join.
        if self._caller is None and self._room.remote_participants:
            self._caller = next(iter(self._room.remote_participants.values()))
            self._caller_ready.set()
        log.info("waiting up to %.0fs for a caller to join…", self._join_timeout)
        await asyncio.wait_for(self._caller_ready.wait(), timeout=self._join_timeout)

        # Follow the caller's microphone track at 16 kHz mono, in 20 ms frames so the
        # energy endpointer sees the frame size its timing assumes.
        self._audio_stream = rtc.AudioStream.from_participant(
            participant=self._caller,
            track_source=rtc.TrackSource.SOURCE_MICROPHONE,
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
                self._queue.put_nowait(pcm16_to_float(bytes(event.frame.data)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the stream ends when the caller leaves; not fatal
            log.debug("audio stream reader stopped: %s", exc)

    # --- listen ------------------------------------------------------------ #
    async def listen(self) -> AsyncIterator[AudioChunk]:
        if self._queue is None:
            raise RuntimeError("LiveKitTransport.start() must be called before listen()")
        self._drain()
        self._endpointer.reset()
        # Hold pre-onset frames so the start of speech is not clipped; flush them once
        # the caller is committed to speaking.
        preroll: deque[np.ndarray] = deque(maxlen=self._cfg.onset_frames)
        while True:
            frame = await self._queue.get()
            ended = self._endpointer.update(frame)
            if self._endpointer.started:
                while preroll:
                    yield chunk_from_float(preroll.popleft(), _CAPTURE_SR)
                yield chunk_from_float(frame, _CAPTURE_SR)
            else:
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
