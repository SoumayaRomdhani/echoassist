"""Call endpoints: start a call, list/inspect calls, notes, summary, consent log."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.context import AppResources, get_resources
from src.api.schemas import (
    CallDetailOut,
    CallListOut,
    CallOut,
    CallStatusOut,
    ConsentLogOut,
    NotesOut,
    StartCallRequest,
    StartCallResponse,
    SummaryOut,
)
from src.storage import queries

router = APIRouter(prefix="/calls", tags=["calls"])


@router.post("", response_model=StartCallResponse, status_code=202)
async def start_call(
    body: StartCallRequest, resources: AppResources = Depends(get_resources)
) -> StartCallResponse:
    """Start a screening call in the background; subscribe to ``ws_url`` for live updates."""
    session = resources.call_manager.start(
        domain=body.domain, campaign=body.campaign, consent=body.consent
    )
    return StartCallResponse(
        call_id=session.call_id, status=session.status, ws_url=f"/ws/calls/{session.call_id}"
    )


@router.get("", response_model=CallListOut)
async def list_calls(
    domain: str | None = Query(default=None),
    campaign_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    resources: AppResources = Depends(get_resources),
) -> CallListOut:
    async with resources.sessionmaker() as db:
        calls = await queries.list_calls(
            db, campaign_id=campaign_id, domain=domain, limit=limit, offset=offset
        )
        total = await queries.count_calls(db, campaign_id=campaign_id, domain=domain)
    return CallListOut(
        items=[CallOut.from_orm_model(c) for c in calls], total=total, limit=limit, offset=offset
    )


@router.get("/{call_id}/status", response_model=CallStatusOut)
async def get_call_status(
    call_id: str, resources: AppResources = Depends(get_resources)
) -> CallStatusOut:
    """Live status from the in-memory registry, falling back to the persisted record."""
    session = resources.call_manager.get(call_id)
    if session is not None:
        return CallStatusOut(
            call_id=session.call_id, domain=session.domain, campaign=session.campaign,
            status=session.status, consent_granted=session.consent_granted,
            started_at=session.started_at, ended_at=session.ended_at,
        )
    async with resources.sessionmaker() as db:
        call = await queries.get_call(db, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail=f"call {call_id} not found")
    return CallStatusOut(
        call_id=call.call_id, domain=call.domain, campaign=call.campaign.name,
        status=call.status, consent_granted=call.consent_granted,
        started_at=call.created_at, ended_at=call.created_at,
    )


@router.get("/{call_id}", response_model=CallDetailOut)
async def get_call(call_id: str, resources: AppResources = Depends(get_resources)) -> CallDetailOut:
    async with resources.sessionmaker() as db:
        call = await queries.get_call(db, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail=f"call {call_id} not found")
    return CallDetailOut.from_orm_model(call)


@router.get("/{call_id}/notes", response_model=NotesOut)
async def get_call_notes(
    call_id: str, resources: AppResources = Depends(get_resources)
) -> NotesOut:
    async with resources.sessionmaker() as db:
        call = await queries.get_call(db, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail=f"call {call_id} not found")
    if call.note is None:
        raise HTTPException(status_code=404, detail=f"call {call_id} has no notes")
    return NotesOut(call_id=call_id, notes=call.note.data)


@router.get("/{call_id}/summary", response_model=SummaryOut)
async def get_call_summary(
    call_id: str, resources: AppResources = Depends(get_resources)
) -> SummaryOut:
    async with resources.sessionmaker() as db:
        call = await queries.get_call(db, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail=f"call {call_id} not found")
    if call.summary is None:
        raise HTTPException(status_code=404, detail=f"call {call_id} has no summary")
    return SummaryOut(call_id=call_id, summary=call.summary.text)


@router.get("/{call_id}/consent", response_model=list[ConsentLogOut])
async def get_call_consent(
    call_id: str, resources: AppResources = Depends(get_resources)
) -> list[ConsentLogOut]:
    """The immutable consent audit trail for a call (ARCHITECTURE.md §10)."""
    async with resources.sessionmaker() as db:
        entries = await queries.list_consent(db, call_id)
    return [ConsentLogOut.from_orm_model(e) for e in entries]
