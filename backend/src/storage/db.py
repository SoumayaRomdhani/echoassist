"""Async database engine/session helpers + call persistence.

Postgres in production (``postgresql+psycopg://``); tests use in-memory SQLite
(``sqlite+aiosqlite://``). The models are DB-agnostic, so the same code path runs
against both.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.agent.state import ConversationState
from src.observability.tracing import span
from src.storage.models import Base, Call, Campaign, Note, Summary, TranscriptTurn

log = logging.getLogger("echoassist.storage")


def make_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    return create_async_engine(url, echo=echo)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# Additive, idempotent schema patches for tables that already exist from an earlier
# version (create_all only CREATEs missing tables, it never ALTERs). This is a
# lightweight stand-in for a migration tool — a real deployment should adopt Alembic.
# Each entry: (table, column, "TYPE" used in ADD COLUMN).
_ADDITIVE_COLUMNS = (
    ("consent_log", "disclosure_hash", "VARCHAR(64)"),
)


def _apply_additive_migrations(conn) -> None:
    inspector = inspect(conn)
    for table, column, coltype in _ADDITIVE_COLUMNS:
        if not inspector.has_table(table):
            continue   # create_all just made it (with the column) — nothing to patch
        columns = {c["name"] for c in inspector.get_columns(table)}
        if column not in columns:
            log.info("migrating: ADD COLUMN %s.%s", table, column)
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))


async def init_db(engine: AsyncEngine) -> None:
    """Create missing tables, then apply additive column migrations to existing ones."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_additive_migrations)


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
    notes: dict | None,
    summary: str | None,
    status: str = "completed",
) -> Call:
    """Persist a call: the call row, its transcript, and (when present) notes + summary.

    ``notes``/``summary`` may be ``None`` for a call that did not finish normally
    (e.g. consent declined) — the compliance record is still written, just without
    interview output.

    Concurrency-safe: when two calls create the same (new) campaign at once, the
    loser hits a unique-constraint violation, rolls back, and finds the committed
    campaign on the retry.
    """
    # Stage span — call_id is a uuid and domain an enum value; neither is PII.
    with span("db.persist", **{"db.call_id": state.call_id, "db.domain": domain}):
        for attempt in range(2):
            try:
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
                )
                if notes is not None:
                    call.note = Note(data=notes)
                if summary is not None:
                    call.summary = Summary(text=summary)
                session.add(call)
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if attempt == 1:
                    raise
                log.debug("persist_call retrying after campaign creation race")
                continue
            log.info(
                "persisted call_id=%s (%d turns) to campaign '%s'",
                state.call_id, len(state.transcript), campaign_name,
            )
            return call
    raise AssertionError("unreachable")  # the loop returns or raises
