"""The live (mic / LiveKit) call path broadcasts its events to a sink.

Guards the Sprint 8 dashboard bridge: the same session that prints to the terminal
also emits ``status`` / ``agent_state`` / ``transcript`` / ``consent`` / ``notes`` /
``summary`` through a :class:`~src.telephony.events.CallEventSink`, so a call taken
at the microphone shows up live on the dashboard. No hardware, models, or Postgres —
a recording sink captures what would be published.
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


class RecordingSink:
    """A test :class:`CallEventSink` that records every emitted event."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict, bool]] = []

    def emit(self, type_: str, data: dict, *, terminal: bool = False) -> None:
        self.events.append((type_, data, terminal))

    def types(self) -> list[str]:
        return [t for t, _, _ in self.events]

    def of(self, type_: str) -> list[dict]:
        return [d for t, d, _ in self.events if t == type_]

    def agent_states(self) -> list[str]:
        return [d["state"] for t, d, _ in self.events if t == "agent_state"]


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
    def __init__(self, state: ConversationState, *, turns: int) -> None:
        self._state = state
        self._turns = turns
        self._n = 0
        self.interview_finished = False

    async def begin_interview(self) -> tuple[str, AudioChunk]:
        self._state.add_turn("assistant", "First question?")
        return "First question?", _chunk()

    async def interview_turn_streaming(
        self, audio: AsyncIterator[AudioChunk]
    ) -> tuple[str, bool, AsyncIterator[AudioChunk]]:
        self._n += 1
        self._state.add_turn("user", f"turn {self._n}")
        self._state.add_turn("assistant", f"answer {self._n}")
        if self._n >= self._turns:
            self.interview_finished = True

        async def _audio() -> AsyncIterator[AudioChunk]:
            yield _chunk()

        return f"turn {self._n}", False, _audio()


async def _noop_finalize(settings, llm, state, *, completed, **_kw):
    return None


@pytest.mark.asyncio
async def test_interview_broadcasts_states_progress_and_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Isolate the interview loop from persistence (finalize has its own test below).
    monkeypatch.setattr(live_session, "_finalize", _noop_finalize)

    sink = RecordingSink()
    state = ConversationState(call_id="c1")
    pipe = _FakePipeline(state, turns=2)
    domain = SimpleNamespace(
        flow={"states": [{"type": "question"}, {"type": "question"}, {"type": "closing"}]}
    )

    await _run_interview(
        pipe, _FakeTransport(), settings=make_settings(), llm=None, state=state,
        sink=sink, call_id="c1", domain=domain,
    )

    # The interview is announced, and the orb moves through every phase, settling idle.
    assert ("status", {"status": "interviewing"}, False) in sink.events
    states = sink.agent_states()
    assert {"speaking", "listening", "thinking"} <= set(states)
    assert states[-1] == "idle"  # settled before finalize runs

    # Progress carries the flow's question count (2 questions, not the closing state).
    with_total = [d for d in sink.of("agent_state") if "question_total" in d]
    assert with_total and all(d["question_total"] == 2 for d in with_total)

    # Both sides of the conversation are broadcast.
    transcripts = sink.of("transcript")
    assert {"role": "assistant", "text": "First question?"} in transcripts
    assert any(t["role"] == "caller" for t in transcripts)


@pytest.mark.asyncio
async def test_progress_omitted_when_flow_size_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_session, "_finalize", _noop_finalize)
    sink = RecordingSink()
    state = ConversationState(call_id="c2")

    await _run_interview(
        _FakePipeline(state, turns=1), _FakeTransport(), settings=make_settings(),
        llm=None, state=state, sink=sink, call_id="c2", domain=None,
    )

    # Without a domain the total is unknown, so no event carries question_total.
    assert all("question_total" not in d for d in sink.of("agent_state"))


@pytest.mark.asyncio
async def test_finalize_broadcasts_notes_summary_and_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Engine:
        async def dispose(self) -> None:
            pass

    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *_exc) -> bool:
            return False

    async def _fake_finalize_call(session, state, *, status, **_kw):
        return SimpleNamespace(
            notes={"name": "X"}, summary="a summary", call=SimpleNamespace(id=1, status=status)
        )

    monkeypatch.setattr(live_session, "build_engine", lambda _s: _Engine())
    monkeypatch.setattr(live_session, "init_db", _noop_engine)
    monkeypatch.setattr(live_session, "load_notes_schema", lambda _d, _c: {})
    monkeypatch.setattr(live_session, "make_sessionmaker", lambda _e: (lambda: _Session()))
    monkeypatch.setattr(live_session, "finalize_call", _fake_finalize_call)

    sink = RecordingSink()
    state = ConversationState(call_id="c3")
    state.add_turn("user", "hello")
    await _finalize(make_settings(), None, state, completed=True, sink=sink, call_id="c3")

    assert ("notes", {"notes": {"name": "X"}}, False) in sink.events
    assert ("summary", {"summary": "a summary"}, False) in sink.events
    # The terminal status is always the last event and settles the dashboard.
    assert sink.events[-1] == ("status", {"status": "completed"}, True)


@pytest.mark.asyncio
async def test_finalize_empty_call_still_settles_dashboard() -> None:
    sink = RecordingSink()
    state = ConversationState(call_id="c4")  # no caller turns → nothing to persist
    await _finalize(make_settings(), None, state, completed=False, sink=sink)
    assert sink.events == [("status", {"status": "completed"}, True)]


async def _noop_engine(_engine) -> None:
    pass
