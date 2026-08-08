"""Persistence layer, validated against in-memory SQLite (no Postgres needed)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from src.agent.state import ConversationState
from src.storage.db import init_db, make_sessionmaker, persist_call
from src.storage.models import Call, Campaign, JobPosting, Note, Summary, TranscriptTurn


async def _engine():
    # Shared in-memory DB across sessions (StaticPool keeps a single connection).
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    await init_db(engine)
    return engine


def _state(call_id: str = "c1") -> ConversationState:
    state = ConversationState(call_id=call_id, consent_granted=True)
    state.add_turn("assistant", "How many years of experience?")
    state.add_turn("user", "Six years.")
    return state


@pytest.mark.asyncio
async def test_persist_call_writes_all_rows() -> None:
    engine = await _engine()
    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as session:
        await persist_call(
            session, campaign_name="Camp", domain="screening", state=_state(),
            notes={"years_experience": "6 years", "overall_fit": "strong"},
            summary="Strong candidate with six years of experience.",
        )

    async with sessionmaker() as session:
        call = await session.scalar(select(Call).where(Call.call_id == "c1"))
        assert call is not None and call.consent_granted is True and call.status == "completed"

        turns = (await session.scalars(
            select(TranscriptTurn).where(TranscriptTurn.call_id == call.id)
            .order_by(TranscriptTurn.ordinal)
        )).all()
        assert [t.role for t in turns] == ["assistant", "user"]

        note = await session.scalar(select(Note).where(Note.call_id == call.id))
        assert note.data["years_experience"] == "6 years"

        summary = await session.scalar(select(Summary).where(Summary.call_id == call.id))
        assert "six years" in summary.text

    await engine.dispose()


@pytest.mark.asyncio
async def test_job_posting_round_trips() -> None:
    engine = await _engine()  # init_db must auto-create the new job_postings table
    sessionmaker = make_sessionmaker(engine)
    questions = [
        {"id": "q1", "text": "Years of Python experience?", "slot": "years_python",
         "enabled": True},
        {"id": "q2", "text": "Comfortable with on-call?", "slot": "on_call", "enabled": False},
    ]
    async with sessionmaker() as session:
        session.add(JobPosting(
            title="Senior Backend Engineer", description="We are hiring...", questions=questions,
        ))
        await session.commit()

    async with sessionmaker() as session:
        posting = await session.scalar(select(JobPosting))
        assert posting.title == "Senior Backend Engineer"
        assert posting.domain == "screening"   # default
        assert posting.status == "draft"        # default
        assert posting.questions[0]["slot"] == "years_python"
        assert posting.questions[1]["enabled"] is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_campaign_is_reused_across_calls() -> None:
    engine = await _engine()
    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as session:
        await persist_call(session, campaign_name="Camp", domain="screening",
                           state=_state("c1"), notes={}, summary="a")
        await persist_call(session, campaign_name="Camp", domain="screening",
                           state=_state("c2"), notes={}, summary="b")

    async with sessionmaker() as session:
        campaigns = (await session.scalars(select(Campaign))).all()
        calls = (await session.scalars(select(Call))).all()
        assert len(campaigns) == 1   # same campaign reused
        assert len(calls) == 2

    await engine.dispose()
