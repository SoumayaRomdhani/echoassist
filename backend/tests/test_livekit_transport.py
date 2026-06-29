"""LiveKitTransport: the same Transport seam over WebRTC/SIP.

Runs with **no LiveKit account and no SDK for the core paths**:
  1. missing config -> ProviderConfigError (validation precedes the lazy SDK import);
  2. listen() endpointing over a fed frame queue — one utterance per call, ends at
     the endpoint — exactly like the local transport, with no audio hardware;
  3. join-token building via livekit-api (``importorskip``), asserting the room grant
     — no network.
"""

from __future__ import annotations

import asyncio
import base64
import json

import numpy as np
import pytest

from src.providers.errors import ProviderConfigError
from src.providers.types import AudioChunk
from src.telephony.livekit_transport import LiveKitTransport
from src.telephony.vad import EndpointConfig

_DUMMY = {"url": "ws://localhost:7880", "api_key": "devkey", "api_secret": "secret"}


def test_livekit_missing_config_raises_config_error() -> None:
    with pytest.raises(ProviderConfigError):
        LiveKitTransport(url=None, api_key="k", api_secret="s")
    with pytest.raises(ProviderConfigError):
        LiveKitTransport(url="ws://x", api_key=None, api_secret="s")
    with pytest.raises(ProviderConfigError):
        LiveKitTransport(url="ws://x", api_key="k", api_secret=None)


def _loud(samples: int = 320) -> np.ndarray:
    return np.full(samples, 0.5, dtype=np.float32)


def _silent(samples: int = 320) -> np.ndarray:
    return np.zeros(samples, dtype=np.float32)


@pytest.mark.asyncio
async def test_listen_yields_one_utterance_and_ends_at_endpoint() -> None:
    # Fast endpointing so the test is small: onset after 2 speech frames, end after 40 ms silence.
    transport = LiveKitTransport(
        **_DUMMY,
        endpoint=EndpointConfig(frame_ms=20, energy_threshold=0.01, onset_frames=2, silence_ms=40),
    )
    transport._queue = asyncio.Queue()  # normally created in start(); injected to skip the SDK

    frames = [_loud(), _loud(), _loud(), _silent(), _silent()]

    async def _feed() -> None:
        # Runs after listen() drains the (empty) queue and awaits the first frame.
        for frame in frames:
            transport._queue.put_nowait(frame)

    feeder = asyncio.create_task(_feed())
    chunks: list[AudioChunk] = [chunk async for chunk in transport.listen()]
    await feeder

    # The utterance was captured (onset preroll flushed) and listen() returned at the endpoint.
    assert len(chunks) >= 3
    assert all(isinstance(c, AudioChunk) and c.fmt.sample_rate == 16000 for c in chunks)

    # A second call is independent and also terminates.
    async def _feed2() -> None:
        for frame in (_loud(), _loud(), _silent(), _silent()):
            transport._queue.put_nowait(frame)

    feeder2 = asyncio.create_task(_feed2())
    second = [chunk async for chunk in transport.listen()]
    await feeder2
    assert len(second) >= 2


def test_listen_before_start_raises() -> None:
    transport = LiveKitTransport(**_DUMMY)

    async def _drive() -> None:
        async for _ in transport.listen():
            pass

    with pytest.raises(RuntimeError):
        asyncio.run(_drive())


def test_join_token_carries_room_grant() -> None:
    pytest.importorskip("livekit.api")
    transport = LiveKitTransport(
        url="ws://localhost:7880", api_key="devkey",
        api_secret="a-test-secret-at-least-32-bytes-long!!",
        room="room-42", identity="agent-1",
    )
    jwt = transport._build_token()

    assert jwt.count(".") == 2  # header.payload.signature
    payload_b64 = jwt.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)  # pad for urlsafe_b64decode
    claims = json.loads(base64.urlsafe_b64decode(payload_b64))

    assert claims["sub"] == "agent-1"
    assert claims["video"]["room"] == "room-42"
    assert claims["video"]["roomJoin"] is True
