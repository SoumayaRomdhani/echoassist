"""Async database engine/session helpers + call persistence.

Postgres in production (``postgresql+psycopg://``); tests use in-memory SQLite
(``sqlite+aiosqlite://``). The models are DB-agnostic, so the same code path runs
against both.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.agent.state import ConversationState
from src.storage.models import Base, Call, Campaign, Note, Summary, TranscriptTurn

log = logging.getLogger("echoassist.storage")


def make_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    return create_async_engine(url, echo=echo)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    """Create tables if they do not exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _get_or_create_campaign(session: AsyncSession, name: str, domain: str) -> Campaign:
    existing = await session.scalar(select(Campaign).where(Campaign.name == name))
    if existing is not None:
        return existing
    campaign = Campaign(name=name, domain=domain)
    session.add(campaign)
    await session.flush()
    return campaign


async def persist_call(
    session: AsyncSession,
    *,
    campaign_name: str,
    domain: str,
    state: ConversationState,
    notes: dict,
    summary: str,
    status: str = "completed",
) -> Call:
    """Persist a completed call: the call row, its transcript, notes, and summary."""
    campaign = await _get_or_create_campaign(session, campaign_name, domain)
    call = Call(
        campaign_id=campaign.id,
        call_id=state.call_id,
        domain=domain,
        consent_granted=state.consent_granted,
        status=status,
        transcript=[
            TranscriptTurn(ordinal=i, role=turn["role"], text=turn["text"])
            for i, turn in enumerate(state.transcript)
        ],
        note=Note(data=notes),
        summary=Summary(text=summary),
    )
    session.add(call)
    await session.commit()
    log.info(
        "persisted call_id=%s (%d turns) to campaign '%s'",
        state.call_id, len(state.transcript), campaign_name,
    )
    return call
