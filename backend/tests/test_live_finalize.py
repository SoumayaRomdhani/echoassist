"""End-of-call finalization runs on *any* exit — a clean close or a hang-up.

Regression guard for the bug where a caller-led (help-desk) call ended by hanging up
(Ctrl-C / dropped line) instead of a recognised closing phrase was never persisted, so
it never reached the dashboard. No hardware, no models, no Postgres.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest

from src.agent.state import ConversationState
from src.providers.types import AudioChunk, AudioFormat
from src.telephony import live_session
from src.telephony.live_session import _finalize, _run_interview
from tests.conftest import make_settings

_FMT = AudioFormat(sample_rate=24000)


def _chunk(text: str = "x") -> AudioChunk:
    return AudioChunk(data=text.encode(), fmt=_FMT)


class _FakeTransport:
    async def listen(self) -> AsyncIterator[AudioChunk]:
        for _ in ():
            yield _

    async def send_interruptible(self, audio: AudioChunk) -> bool:
        return False

    async def send_stream_interruptible(self, audio: AsyncIterator[AudioChunk]) -> bool:
        async for _ in audio:
            pass
        return False


class _FakePipeline:
    """Feeds a fixed number of turns; finishes cleanly or hangs up (raises) mid-call."""

    def __init__(
        self, state: ConversationState, *, turns: int, hangup_at: int | None = None
    ) -> None:
        self._state = state
        self._turns = turns
        self._hangup_at = hangup_at
        self._n = 0
        self.interview_finished = False

    async def begin_interview(self) -> tuple[str, AudioChunk]:
        self._state.add_turn("assistant", "First question?")
        return "First question?", _chunk()

    async def interview_turn_streaming(
        self, audio: AsyncIterator[AudioChunk], *, on_partial=None
    ) -> tuple[str, bool, AsyncIterator[AudioChunk]]:
        self._n += 1
        if self._hangup_at is not None and self._n >= self._hangup_at:
            raise KeyboardInterrupt  # the caller hung up (Ctrl-C) mid-call
        self._state.add_turn("user", f"turn {self._n}")
        self._state.add_turn("assistant", f"answer {self._n}")
        if self._n >= self._turns:
            self.interview_finished = True

        async def _audio() -> AsyncIterator[AudioChunk]:
            yield _chunk()

        return f"turn {self._n}", False, _audio()


def _spy_finalize(record: list[bool]):
    async def _spy(settings, llm, state, *, completed: bool, **_kw) -> None:
        record.append(completed)

    return _spy


@pytest.mark.asyncio
async def test_finalizes_on_clean_close(monkeypatch: pytest.MonkeyPatch) -> None:
    completed: list[bool] = []
    monkeypatch.setattr(live_session, "_finalize", _spy_finalize(completed))

    state = ConversationState(call_id="c1")
    pipe = _FakePipeline(state, turns=2)
    await _run_interview(pipe, _FakeTransport(), settings=make_settings(), llm=None, state=state)

    assert completed == [True]  # finalized once, marked completed


@pytest.mark.asyncio
async def test_finalizes_on_hangup(monkeypatch: pytest.MonkeyPatch) -> None:
    completed: list[bool] = []
    monkeypatch.setattr(live_session, "_finalize", _spy_finalize(completed))

    state = ConversationState(call_id="c2")
    pipe = _FakePipeline(state, turns=5, hangup_at=2)  # never reaches a clean close
    with pytest.raises(KeyboardInterrupt):
        await _run_interview(
            pipe, _FakeTransport(), settings=make_settings(), llm=None, state=state
        )

    assert completed == [False]  # still finalized despite the hang-up, marked not-completed


@pytest.mark.asyncio
async def test_finalize_skips_a_call_with_no_caller_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_settings):  # pragma: no cover - only runs if the guard fails
        raise AssertionError("must not touch the database for an empty call")

    monkeypatch.setattr(live_session, "build_engine", _boom)

    state = ConversationState(call_id="c3")  # only the opening question, no caller turn
    state.add_turn("assistant", "First question?")
    await _finalize(make_settings(), None, state, completed=False)  # returns without persisting


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("completed", "expected"), [(True, "completed"), (False, "incomplete")]
)
async def test_finalize_maps_completed_flag_to_status(
    monkeypatch: pytest.MonkeyPatch, completed: bool, expected: str
) -> None:
    class _Engine:
        async def dispose(self) -> None:
            pass

    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *_exc) -> bool:
            return False

    seen: dict[str, str] = {}

    async def _fake_finalize_call(session, state, *, status, **_kw):
        seen["status"] = status
        return SimpleNamespace(notes={}, summary="s", call=SimpleNamespace(id=1, status=status))

    monkeypatch.setattr(live_session, "build_engine", lambda _s: _Engine())
    monkeypatch.setattr(live_session, "init_db", _noop)
    monkeypatch.setattr(live_session, "load_notes_schema", lambda _d, _c: {})
    monkeypatch.setattr(live_session, "make_sessionmaker", lambda _e: (lambda: _Session()))
    monkeypatch.setattr(live_session, "finalize_call", _fake_finalize_call)

    state = ConversationState(call_id="c4")
    state.add_turn("user", "hello")
    await _finalize(make_settings(), None, state, completed=completed)

    assert seen["status"] == expected


async def _noop(_engine) -> None:
    pass
