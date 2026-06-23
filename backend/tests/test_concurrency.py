"""Concurrency DoD: the system survives N concurrent calls + requests, and the
shared CPU models are never used by two calls at once.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from src.providers.concurrency import SerializedSTT, SerializedTTS
from src.storage.db import init_db
from src.storage.models import Call
from tests.conftest import FakeSTT, FakeTTS, Probe, make_resources

pytestmark = pytest.mark.asyncio

_N = 5


async def _collect(subscription) -> list:
    return [event async for event in subscription]


async def _file_engine():
    # A real connection pool over a file DB — concurrent calls each get their own
    # connection (in-memory StaticPool shares one, which Postgres would not).
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", connect_args={"timeout": 30})
    await init_db(engine)
    return engine, path


async def test_concurrent_calls_complete_and_serialize_models() -> None:
    engine, path = await _file_engine()

    # One shared probe + lock behind shared serialized providers — exactly the
    # production wiring (providers built once, CPU access serialized).
    probe = Probe()
    lock = asyncio.Lock()
    resources = make_resources(
        engine,
        stt=SerializedSTT(FakeSTT(probe), lock),
        tts=SerializedTTS(FakeTTS(probe), lock),
    )

    try:
        # Start N calls and subscribe before yielding, so every event is observed.
        sessions = [resources.call_manager.start(consent=True) for _ in range(_N)]
        collectors = [
            asyncio.create_task(_collect(resources.hub.subscribe(s.call_id))) for s in sessions
        ]
        events_per_call = await asyncio.wait_for(asyncio.gather(*collectors), timeout=20)

        # Every call finished cleanly.
        assert all(s.status == "completed" for s in sessions)

        # The CPU models were never used by two calls at once.
        assert probe.max_active == 1

        # Each subscriber saw a terminal "completed" status and live transcript.
        for events in events_per_call:
            assert events[-1].terminal is True
            assert events[-1].data["status"] == "completed"
            assert any(e.type == "transcript" for e in events)

        # All N calls were persisted.
        async with resources.sessionmaker() as db:
            total = await db.scalar(select(func.count()).select_from(Call))
        assert total == _N
    finally:
        await resources.call_manager.aclose()
        await engine.dispose()
        with contextlib.suppress(OSError):  # Windows may still hold the file handle briefly
            os.remove(path)


async def test_api_survives_concurrent_requests(client) -> None:
    responses = await asyncio.gather(*[client.get("/health") for _ in range(20)])
    assert all(r.status_code == 200 for r in responses)
