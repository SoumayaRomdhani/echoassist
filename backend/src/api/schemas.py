"""Pydantic request/response models for the REST API.

These DTOs are the API's stable contract — deliberately separate from the
SQLAlchemy models so the database schema can evolve without breaking clients.
The ``from_orm_*`` constructors do the (small, explicit) mapping.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.agent.question_gen import DEFAULT_MAX_QUESTIONS, MAX_QUESTIONS_LIMIT
from src.storage.models import Call, Campaign, ConsentLog, JobPosting


# --- Domains --------------------------------------------------------------- #
class DomainOut(BaseModel):
    name: str
    language: str
    disclosure: str
    greeting: str
    question_count: int
    slots: list[str]
    indexed: bool | None = Field(
        default=None, description="Whether a vector collection exists for this domain."
    )


# --- Campaigns ------------------------------------------------------------- #
class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str = "screening"


class CampaignOut(BaseModel):
    id: int
    name: str
    domain: str
    created_at: datetime

    @classmethod
    def from_orm_model(cls, campaign: Campaign) -> CampaignOut:
        return cls(
            id=campaign.id,
            name=campaign.name,
            domain=campaign.domain,
            created_at=campaign.created_at,
        )


# --- Job postings ---------------------------------------------------------- #
class QuestionModel(BaseModel):
    """One interview question. ``id``/``slot`` are server-assigned (optional on input)."""

    id: str | None = None
    text: str = Field(min_length=1, max_length=300)
    slot: str | None = None
    enabled: bool = True


class JobPostingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, description="The job description (fiche de poste).")
    domain: str = "screening"
    max_questions: int = Field(default=DEFAULT_MAX_QUESTIONS, ge=1, le=MAX_QUESTIONS_LIMIT)


class JobPostingUpdate(BaseModel):
    """Recruiter edits: any subset. ``questions`` replaces the whole set (re-normalized)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    questions: list[QuestionModel] | None = None
    status: Literal["draft", "confirmed"] | None = None


class JobPostingOut(BaseModel):
    id: int
    title: str
    domain: str
    description: str
    questions: list[QuestionModel]
    status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, posting: JobPosting) -> JobPostingOut:
        return cls(
            id=posting.id,
            title=posting.title,
            domain=posting.domain,
            description=posting.description,
            questions=[QuestionModel(**q) for q in posting.questions],
            status=posting.status,
            created_at=posting.created_at,
            updated_at=posting.updated_at,
        )


# --- Calls ----------------------------------------------------------------- #
class TranscriptTurnOut(BaseModel):
    ordinal: int
    role: str
    text: str


class CallOut(BaseModel):
    """List-view of a call (no transcript/notes body)."""

    call_id: str
    campaign_id: int
    domain: str
    status: str
    consent_granted: bool
    created_at: datetime
    has_notes: bool
    has_summary: bool

    @classmethod
    def from_orm_model(cls, call: Call) -> CallOut:
        return cls(
            call_id=call.call_id,
            campaign_id=call.campaign_id,
            domain=call.domain,
            status=call.status,
            consent_granted=call.consent_granted,
            created_at=call.created_at,
            has_notes=call.note is not None,
            has_summary=call.summary is not None,
        )


class CallDetailOut(CallOut):
    """Full call: list fields + transcript, notes, and summary."""

    campaign_name: str
    transcript: list[TranscriptTurnOut]
    notes: dict | None
    summary: str | None

    @classmethod
    def from_orm_model(cls, call: Call) -> CallDetailOut:
        return cls(
            call_id=call.call_id,
            campaign_id=call.campaign_id,
            campaign_name=call.campaign.name,
            domain=call.domain,
            status=call.status,
            consent_granted=call.consent_granted,
            created_at=call.created_at,
            has_notes=call.note is not None,
            has_summary=call.summary is not None,
            transcript=[
                TranscriptTurnOut(ordinal=t.ordinal, role=t.role, text=t.text)
                for t in call.transcript
            ],
            notes=call.note.data if call.note is not None else None,
            summary=call.summary.text if call.summary is not None else None,
        )


class CallListOut(BaseModel):
    items: list[CallOut]
    total: int
    limit: int
    offset: int


class NotesOut(BaseModel):
    call_id: str
    notes: dict


class SummaryOut(BaseModel):
    call_id: str
    summary: str


class ConsentLogOut(BaseModel):
    call_id: str
    domain: str
    decision: str
    granted: bool
    disclosure_hash: str | None
    created_at: datetime

    @classmethod
    def from_orm_model(cls, entry: ConsentLog) -> ConsentLogOut:
        return cls(
            call_id=entry.call_id,
            domain=entry.domain,
            decision=entry.decision,
            granted=entry.granted,
            disclosure_hash=entry.disclosure_hash,
            created_at=entry.created_at,
        )


# --- Call runner ----------------------------------------------------------- #
class StartCallRequest(BaseModel):
    domain: str | None = Field(default=None, description="Defaults to the configured DOMAIN.")
    campaign: str | None = Field(default=None, description="Defaults to DEFAULT_CAMPAIGN.")
    consent: bool = Field(
        default=True, description="Whether the simulated caller consents to the recording."
    )
    job_posting_id: int | None = Field(
        default=None,
        description="Run a tailored interview from this confirmed job posting (else the "
        "static domain flow).",
    )


class StartCallResponse(BaseModel):
    call_id: str
    status: str
    ws_url: str


class CallStatusOut(BaseModel):
    call_id: str
    domain: str
    campaign: str
    status: str
    consent_granted: bool
    started_at: datetime
    ended_at: datetime | None


# --- Documents ------------------------------------------------------------- #
class SkippedDocumentOut(BaseModel):
    source: str
    reason: str


class DocumentUploadOut(BaseModel):
    domain: str
    filename: str
    documents: int
    chunks: int
    collection_count: int
    skipped: list[SkippedDocumentOut] = []


class DocumentDeleteOut(BaseModel):
    domain: str
    filename: str
    file_removed: bool
    chunks_removed: int


class DomainReindexOut(BaseModel):
    domain: str
    documents: int
    chunks: int
    collection_count: int
    skipped: list[SkippedDocumentOut] = []


class DocumentInfoOut(BaseModel):
    source: str
    size_bytes: int
    modified_at: str
    chunks: int | None = None


class DocumentListOut(BaseModel):
    domain: str
    documents: list[DocumentInfoOut]


class SearchPreviewIn(BaseModel):
    query: str
    limit: int = 6


class RetrievedChunkOut(BaseModel):
    source: str
    score: float
    page: int | None = None
    heading: str | None = None
    snippet: str


class SearchPreviewOut(BaseModel):
    domain: str
    query: str
    results: list[RetrievedChunkOut]


# --- Health ---------------------------------------------------------------- #
class HealthOut(BaseModel):
    status: str               # "ok" | "degraded"
    service: str
    components: dict[str, str]
