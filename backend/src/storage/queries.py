"""Read queries and consent logging for the API layer.

Kept separate from ``db.py`` (which owns the engine/session helpers and the
write path ``persist_call``) so the REST routes have a small, explicit data
access surface. Every relationship the API serializes is eager-loaded here:
async SQLAlchemy cannot lazy-load a relationship outside an awaited query, so
loading it up front is both correct and a single round trip.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from src.storage.db import _get_or_create_campaign
from src.storage.models import Call, Campaign, ConsentLog, JobPosting


# --- Campaigns ------------------------------------------------------------- #
async def list_campaigns(session: AsyncSession) -> list[Campaign]:
    result = await session.scalars(select(Campaign).order_by(Campaign.created_at.desc()))
    return list(result)


async def get_campaign(session: AsyncSession, campaign_id: int) -> Campaign | None:
    return await session.get(Campaign, campaign_id)


async def create_campaign(session: AsyncSession, *, name: str, domain: str) -> Campaign:
    """Create a campaign, or return the existing one with the same name (idempotent)."""
    campaign = await _get_or_create_campaign(session, name, domain)
    await session.commit()
    return campaign


# --- Calls ----------------------------------------------------------------- #
async def list_calls(
    session: AsyncSession,
    *,
    campaign_id: int | None = None,
    domain: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Call]:
    """List calls (newest first), optionally filtered, with relationships loaded.

    note/summary are eager-loaded because the list DTO reports their presence and
    the ORM objects are read after the session closes (async cannot lazy-load).
    """
    stmt = (
        select(Call)
        .options(
            joinedload(Call.campaign),
            selectinload(Call.note),
            selectinload(Call.summary),
        )
        .order_by(Call.created_at.desc())
    )
    if campaign_id is not None:
        stmt = stmt.where(Call.campaign_id == campaign_id)
    if domain is not None:
        stmt = stmt.where(Call.domain == domain)
    stmt = stmt.limit(limit).offset(offset)
    return list(await session.scalars(stmt))


async def count_calls(
    session: AsyncSession, *, campaign_id: int | None = None, domain: str | None = None
) -> int:
    stmt = select(func.count()).select_from(Call)
    if campaign_id is not None:
        stmt = stmt.where(Call.campaign_id == campaign_id)
    if domain is not None:
        stmt = stmt.where(Call.domain == domain)
    return int(await session.scalar(stmt) or 0)


async def get_call(session: AsyncSession, call_id: str) -> Call | None:
    """Fetch one call by its conversation ``call_id`` with everything the API serializes."""
    stmt = (
        select(Call)
        .where(Call.call_id == call_id)
        .options(
            joinedload(Call.campaign),
            selectinload(Call.transcript),
            selectinload(Call.note),
            selectinload(Call.summary),
        )
    )
    return await session.scalar(stmt)


# --- Job postings ---------------------------------------------------------- #
async def create_job_posting(
    session: AsyncSession, *, title: str, domain: str, description: str, questions: list[dict]
) -> JobPosting:
    posting = JobPosting(title=title, domain=domain, description=description, questions=questions)
    session.add(posting)
    await session.commit()
    return posting


async def get_job_posting(session: AsyncSession, job_id: int) -> JobPosting | None:
    return await session.get(JobPosting, job_id)


async def list_job_postings(session: AsyncSession) -> list[JobPosting]:
    result = await session.scalars(
        select(JobPosting).order_by(JobPosting.created_at.desc())
    )
    return list(result)


async def update_job_posting(
    session: AsyncSession,
    job_id: int,
    *,
    title: str | None = None,
    questions: list[dict] | None = None,
    status: str | None = None,
) -> JobPosting | None:
    """Apply the provided fields (each optional) and commit. None if not found."""
    posting = await session.get(JobPosting, job_id)
    if posting is None:
        return None
    if title is not None:
        posting.title = title
    if questions is not None:
        posting.questions = questions
    if status is not None:
        posting.status = status
    await session.commit()
    return posting


# --- Consent log (ARCHITECTURE.md §10) ------------------------------------- #
async def log_consent(
    session: AsyncSession,
    *,
    call_id: str,
    domain: str,
    decision: str,
    granted: bool,
    disclosure_hash: str | None = None,
) -> ConsentLog:
    """Append an immutable consent record and commit it immediately."""
    entry = ConsentLog(
        call_id=call_id, domain=domain, decision=decision, granted=granted,
        disclosure_hash=disclosure_hash,
    )
    session.add(entry)
    await session.commit()
    return entry


async def list_consent(session: AsyncSession, call_id: str) -> list[ConsentLog]:
    result = await session.scalars(
        select(ConsentLog).where(ConsentLog.call_id == call_id).order_by(ConsentLog.created_at)
    )
    return list(result)
