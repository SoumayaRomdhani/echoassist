"""SQLAlchemy models for call data (campaigns, calls, transcripts, notes, summaries)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    domain: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    calls: Mapped[list[Call]] = relationship(back_populates="campaign")


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    call_id: Mapped[str] = mapped_column(String(64), unique=True)  # conversation uuid
    domain: Mapped[str] = mapped_column(String(64))
    consent_granted: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    campaign: Mapped[Campaign] = relationship(back_populates="calls")
    transcript: Mapped[list[TranscriptTurn]] = relationship(
        back_populates="call", cascade="all, delete-orphan", order_by="TranscriptTurn.ordinal"
    )
    note: Mapped[Note | None] = relationship(
        back_populates="call", cascade="all, delete-orphan", uselist=False
    )
    summary: Mapped[Summary | None] = relationship(
        back_populates="call", cascade="all, delete-orphan", uselist=False
    )


class TranscriptTurn(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"))
    ordinal: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)

    call: Mapped[Call] = relationship(back_populates="transcript")


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), unique=True)
    data: Mapped[dict] = mapped_column(JSON)  # structured notes (config/schemas/{domain}.json)

    call: Mapped[Call] = relationship(back_populates="note")


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), unique=True)
    text: Mapped[str] = mapped_column(Text)

    call: Mapped[Call] = relationship(back_populates="summary")


class ConsentLog(Base):
    """Immutable audit trail of consent decisions (ARCHITECTURE.md §10).

    Written the moment consent is captured — before any persistence — and never
    updated, so the compliance record stands independently of how (or whether) the
    call row is later finalized. Keyed by the conversation ``call_id`` string (the
    call row may not exist yet when consent is logged).
    """

    __tablename__ = "consent_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[str] = mapped_column(String(64))   # conversation uuid (not the FK)
    domain: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))  # accepted | refused | ambiguous
    granted: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_consent_log_call_id", "call_id"),)
