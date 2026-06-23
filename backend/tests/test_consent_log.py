"""Consent audit logging (ARCHITECTURE.md §10), validated against in-memory SQLite."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from src.storage.db import init_db, make_sessionmaker
from src.storage.queries import list_consent, log_consent


async def _sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    await init_db(engine)
    return make_sessionmaker(engine), engine


@pytest.mark.asyncio
async def test_consent_is_logged_and_retrievable() -> None:
    sessionmaker, engine = await _sessionmaker()
    async with sessionmaker() as db:
        entry = await log_consent(
            db, call_id="c1", domain="screening", decision="accepted", granted=True
        )
        assert entry.id is not None

    async with sessionmaker() as db:
        entries = await list_consent(db, "c1")
    assert len(entries) == 1
    assert entries[0].decision == "accepted" and entries[0].granted is True
    assert entries[0].created_at is not None
    await engine.dispose()


@pytest.mark.asyncio
async def test_consent_log_records_disclosure_hash() -> None:
    sessionmaker, engine = await _sessionmaker()
    async with sessionmaker() as db:
        await log_consent(
            db, call_id="c1", domain="screening", decision="accepted", granted=True,
            disclosure_hash="a" * 64,
        )
    async with sessionmaker() as db:
        entries = await list_consent(db, "c1")
    assert entries[0].disclosure_hash == "a" * 64
    await engine.dispose()


@pytest.mark.asyncio
async def test_consent_log_is_append_only_and_ordered() -> None:
    sessionmaker, engine = await _sessionmaker()
    async with sessionmaker() as db:
        await log_consent(db, call_id="c1", domain="screening", decision="ambiguous", granted=False)
        await log_consent(db, call_id="c1", domain="screening", decision="refused", granted=False)

    async with sessionmaker() as db:
        entries = await list_consent(db, "c1")
    assert [e.decision for e in entries] == ["ambiguous", "refused"]   # both kept, in order
    await engine.dispose()


@pytest.mark.asyncio
async def test_consent_log_is_isolated_per_call() -> None:
    sessionmaker, engine = await _sessionmaker()
    async with sessionmaker() as db:
        await log_consent(db, call_id="a", domain="screening", decision="accepted", granted=True)
        await log_consent(db, call_id="b", domain="screening", decision="refused", granted=False)

    async with sessionmaker() as db:
        assert len(await list_consent(db, "a")) == 1
        assert len(await list_consent(db, "b")) == 1
    await engine.dispose()
