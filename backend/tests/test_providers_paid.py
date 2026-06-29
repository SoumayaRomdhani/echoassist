"""Paid drop-in providers (Sprint 8 Path B): Deepgram STT, Cartesia/ElevenLabs TTS.

These run with **no API key and no network**. Three layers of coverage:
  1. missing-key -> ProviderConfigError (the key check precedes the lazy SDK import,
     so it holds even when the vendor SDK is not installed);
  2. pure mapping helpers (parsing / output-format) tested with lightweight fakes;
  3. a fake-SDK bridge test per provider (``importorskip`` the SDK, monkeypatch its
     client) that drives the streaming glue end-to-end without a socket.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest

from src.providers.errors import ProviderConfigError
from src.providers.types import AudioChunk, AudioFormat


async def _audio_stream(
    datas: list[bytes], *, sample_rate: int = 16000
) -> AsyncIterator[AudioChunk]:
    for data in datas:
        yield AudioChunk(data=data, fmt=AudioFormat(sample_rate=sample_rate))


# --------------------------------------------------------------------------- #
# Deepgram STT                                                                #
# --------------------------------------------------------------------------- #
def _dg_result(text: str, *, is_final: bool, confidence: float | None = None) -> SimpleNamespace:
    """A Deepgram ``Results`` event, duck-typed the way ``_to_transcript`` reads it."""
    alt = SimpleNamespace(transcript=text, confidence=confidence)
    return SimpleNamespace(channel=SimpleNamespace(alternatives=[alt]), is_final=is_final)


def test_deepgram_missing_key_raises_config_error() -> None:
    from src.providers.stt.deepgram import DeepgramSTT

    with pytest.raises(ProviderConfigError):
        DeepgramSTT(api_key=None)


def test_deepgram_to_transcript_parses_and_skips_empty() -> None:
    from src.providers.stt.deepgram import _to_transcript

    final = _to_transcript(_dg_result("Bonjour", is_final=True, confidence=0.95), language="fr")
    assert final is not None
    assert (final.text, final.is_final, final.confidence, final.language) == (
        "Bonjour", True, 0.95, "fr",
    )

    interim = _to_transcript(_dg_result("bon", is_final=False), language=None)
    assert interim is not None and interim.is_final is False

    # whitespace-only hypothesis -> nothing to surface
    assert _to_transcript(_dg_result("   ", is_final=False), language=None) is None
    # a non-Results event (Metadata/UtteranceEnd) has no channel -> ignored
    assert _to_transcript(SimpleNamespace(is_final=True), language=None) is None


class _FakeDeepgramSocket:
    """Records sent audio + close, and yields scripted ``Results`` events."""

    def __init__(self, messages: list[SimpleNamespace]) -> None:
        self._messages = messages
        self.sent: list[bytes] = []
        self.closed = False

    async def send_media(self, data: bytes) -> None:
        self.sent.append(data)

    async def send_close_stream(self) -> None:
        self.closed = True

    async def __aiter__(self) -> AsyncIterator[SimpleNamespace]:
        for message in self._messages:
            await asyncio.sleep(0)  # let the concurrent sender task interleave
            yield message


class _FakeDeepgramConnect:
    def __init__(self, socket: _FakeDeepgramSocket) -> None:
        self._socket = socket

    async def __aenter__(self) -> _FakeDeepgramSocket:
        return self._socket

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _fake_deepgram_client(socket: _FakeDeepgramSocket):
    connect_calls: dict = {}

    def connect(**options):
        connect_calls.update(options)
        return _FakeDeepgramConnect(socket)

    listen = SimpleNamespace(v1=SimpleNamespace(connect=connect))
    return SimpleNamespace(listen=listen, _connect_calls=connect_calls)


@pytest.mark.asyncio
async def test_deepgram_bridge_emits_single_cumulative_final(monkeypatch) -> None:
    pytest.importorskip("deepgram")
    socket = _FakeDeepgramSocket(
        [
            _dg_result("hello", is_final=False),
            _dg_result("hello world", is_final=True, confidence=0.9),
            _dg_result("how are you", is_final=True, confidence=0.8),
        ]
    )
    client = _fake_deepgram_client(socket)
    monkeypatch.setattr("deepgram.AsyncDeepgramClient", lambda **_kw: client)

    from src.providers.stt.deepgram import DeepgramSTT

    stt = DeepgramSTT(api_key="x", language="en")
    final = await stt.transcribe(_audio_stream([b"\x00\x01", b"\x02\x03"]))

    # The orchestrator keeps the last is_final: one cumulative transcript, all segments joined.
    assert final.is_final is True
    assert final.text == "hello world how are you"
    assert socket.closed is True          # close_stream was sent after the audio
    assert socket.sent == [b"\x00\x01", b"\x02\x03"]
    # format was declared from the first chunk
    assert client._connect_calls["encoding"] == "linear16"
    assert client._connect_calls["sample_rate"] == 16000


@pytest.mark.asyncio
async def test_deepgram_empty_utterance_yields_empty_final() -> None:
    pytest.importorskip("deepgram")
    from src.providers.stt.deepgram import DeepgramSTT

    stt = DeepgramSTT(api_key="x")
    final = await stt.transcribe(_audio_stream([]))
    assert final.text == "" and final.is_final is True


# --------------------------------------------------------------------------- #
# Cartesia TTS                                                                #
# --------------------------------------------------------------------------- #
def test_cartesia_missing_key_and_voice_raise_config_error() -> None:
    from src.providers.tts.cartesia import CartesiaTTS

    with pytest.raises(ProviderConfigError):
        CartesiaTTS(api_key=None, voice_id="v")
    with pytest.raises(ProviderConfigError):
        CartesiaTTS(api_key="x", voice_id=None)
    with pytest.raises(ProviderConfigError):  # unsupported raw sample rate
        CartesiaTTS(api_key="x", voice_id="v", sample_rate=12345)


class _FakeCartesiaResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aenter__(self) -> _FakeCartesiaResponse:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            await asyncio.sleep(0)
            yield chunk


def _fake_cartesia_client(chunks: list[bytes]):
    calls: list[dict] = []

    def generate(**kwargs):
        calls.append(kwargs)
        return _FakeCartesiaResponse(chunks)

    tts = SimpleNamespace(with_streaming_response=SimpleNamespace(generate=generate))
    return SimpleNamespace(tts=tts, _calls=calls, close=_aclose_noop)


async def _aclose_noop() -> None:
    return None


@pytest.mark.asyncio
async def test_cartesia_streams_raw_pcm(monkeypatch) -> None:
    pytest.importorskip("cartesia")
    client = _fake_cartesia_client([b"\x01\x02", b"\x03\x04"])
    monkeypatch.setattr("cartesia.AsyncCartesia", lambda **_kw: client)

    from src.providers.tts.cartesia import CartesiaTTS

    tts = CartesiaTTS(api_key="x", voice_id="voice-1", sample_rate=24000)
    chunk = await tts.synthesize("Hello there.")

    assert chunk.data == b"\x01\x02\x03\x04"
    assert chunk.fmt.sample_rate == 24000
    # raw pcm_s16le was requested for our wire format, addressed to the configured voice
    fmt = client._calls[0]["output_format"]
    assert fmt == {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000}
    assert client._calls[0]["voice"] == {"id": "voice-1", "mode": "id"}


@pytest.mark.asyncio
async def test_cartesia_blank_text_yields_nothing(monkeypatch) -> None:
    pytest.importorskip("cartesia")
    client = _fake_cartesia_client([b"\x01"])
    monkeypatch.setattr("cartesia.AsyncCartesia", lambda **_kw: client)

    from src.providers.tts.cartesia import CartesiaTTS

    tts = CartesiaTTS(api_key="x", voice_id="v")
    chunks = [c async for c in tts.synthesize_stream("   ")]
    assert chunks == []
    assert client._calls == []  # no API call for blank text


# --------------------------------------------------------------------------- #
# ElevenLabs TTS                                                              #
# --------------------------------------------------------------------------- #
def test_elevenlabs_missing_key_and_voice_raise_config_error() -> None:
    from src.providers.tts.elevenlabs import ElevenLabsTTS

    with pytest.raises(ProviderConfigError):
        ElevenLabsTTS(api_key=None, voice_id="v")
    with pytest.raises(ProviderConfigError):
        ElevenLabsTTS(api_key="x", voice_id=None)
    with pytest.raises(ProviderConfigError):  # unsupported raw sample rate
        ElevenLabsTTS(api_key="x", voice_id="v", sample_rate=12345)


async def _eleven_bytes(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        await asyncio.sleep(0)
        yield chunk


def _fake_eleven_client(chunks: list[bytes]):
    calls: list[tuple[str, dict]] = []

    def stream(voice_id: str, **kwargs):
        calls.append((voice_id, kwargs))
        return _eleven_bytes(chunks)

    tts = SimpleNamespace(stream=stream)
    return SimpleNamespace(text_to_speech=tts, _calls=calls)


@pytest.mark.asyncio
async def test_elevenlabs_streams_raw_pcm(monkeypatch) -> None:
    pytest.importorskip("elevenlabs")
    client = _fake_eleven_client([b"\xaa", b"\xbb"])
    monkeypatch.setattr("elevenlabs.client.AsyncElevenLabs", lambda **_kw: client)

    from src.providers.tts.elevenlabs import ElevenLabsTTS

    tts = ElevenLabsTTS(api_key="x", voice_id="voice-1", sample_rate=24000)
    chunk = await tts.synthesize("Hello.")

    assert chunk.data == b"\xaa\xbb"
    assert chunk.fmt.sample_rate == 24000
    voice_id, kwargs = client._calls[0]
    assert voice_id == "voice-1"
    assert kwargs["output_format"] == "pcm_24000"  # raw PCM16 at our wire rate
