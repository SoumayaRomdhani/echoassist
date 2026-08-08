"""Call endpoints: start a call, list/inspect calls, notes, summary, consent log."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.context import AppResources, get_resources
from src.api.runner import VoiceUnavailable
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


def _live_call_out(session) -> CallOut:
    """A list-row for a call running right now (not yet a persisted record)."""
    return CallOut(
        call_id=session.call_id,
        campaign_id=0,  # placeholder — a live call has no campaign row until it persists
        domain=session.domain,
        status=session.status,
        consent_granted=session.consent_granted,
        created_at=session.started_at,
        has_notes=False,
        has_summary=False,
    )


async def _validate_job_posting(resources: AppResources, job_posting_id: int) -> None:
    """Ensure a tailored interview can run: posting exists, confirmed, has ≥1 enabled question."""
    async with resources.sessionmaker() as db:
        posting = await queries.get_job_posting(db, job_posting_id)
    if posting is None:
        raise HTTPException(status_code=404, detail=f"job posting {job_posting_id} not found")
    if posting.status != "confirmed":
        raise HTTPException(
            status_code=409, detail="job posting must be confirmed before starting a call"
        )
    if not any(
        q.get("enabled", True) and str(q.get("text", "")).strip() for q in posting.questions
    ):
        raise HTTPException(status_code=422, detail="job posting has no enabled questions")


@router.post("", response_model=StartCallResponse, status_code=202)
async def start_call(
    body: StartCallRequest, resources: AppResources = Depends(get_resources)
) -> StartCallResponse:
    """Start a screening call in the background; subscribe to ``ws_url`` for live updates."""
    try:
        resources.call_manager.preflight()   # voice models present? (light image → 503)
    except VoiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if body.job_posting_id is not None:
        await _validate_job_posting(resources, body.job_posting_id)
    session = resources.call_manager.start(
        domain=body.domain, campaign=body.campaign, consent=body.consent,
        job_posting_id=body.job_posting_id,
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

    # Surface calls running right now (mic/LiveKit + server-started) at the top of the
    # first page, so a live call is discoverable before it is persisted. Deduped against
    # the persisted rows; campaign filtering excludes them (a live call has no campaign row).
    live_items: list[CallOut] = []
    if offset == 0 and campaign_id is None:
        persisted_ids = {c.call_id for c in calls}
        live = [
            s
            for s in resources.call_manager.live()
            if s.call_id not in persisted_ids and (domain is None or s.domain == domain)
        ]
        live_items = [_live_call_out(s) for s in live]

    items = live_items + [CallOut.from_orm_model(c) for c in calls]
    return CallListOut(items=items, total=total + len(live_items), limit=limit, offset=offset)


@router.get("/live", response_model=list[CallOut])
async def list_live_calls(
    domain: str | None = Query(default=None),
    resources: AppResources = Depends(get_resources),
) -> list[CallOut]:
    """Calls in progress right now — powers the dashboard's live banner. Newest first."""
    live = resources.call_manager.live()
    if domain is not None:
        live = [s for s in live if s.domain == domain]
    return [_live_call_out(s) for s in live]


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
