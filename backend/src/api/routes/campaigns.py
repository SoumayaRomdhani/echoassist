"""Campaign endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.context import AppResources, get_resources
from src.api.schemas import CallListOut, CallOut, CampaignCreate, CampaignOut
from src.storage import queries

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(resources: AppResources = Depends(get_resources)) -> list[CampaignOut]:
    async with resources.sessionmaker() as db:
        campaigns = await queries.list_campaigns(db)
    return [CampaignOut.from_orm_model(c) for c in campaigns]


@router.post("", response_model=CampaignOut, status_code=201)
async def create_campaign(
    body: CampaignCreate, resources: AppResources = Depends(get_resources)
) -> CampaignOut:
    async with resources.sessionmaker() as db:
        campaign = await queries.create_campaign(db, name=body.name, domain=body.domain)
    return CampaignOut.from_orm_model(campaign)


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    campaign_id: int, resources: AppResources = Depends(get_resources)
) -> CampaignOut:
    async with resources.sessionmaker() as db:
        campaign = await queries.get_campaign(db, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=f"campaign {campaign_id} not found")
    return CampaignOut.from_orm_model(campaign)


@router.get("/{campaign_id}/calls", response_model=CallListOut)
async def list_campaign_calls(
    campaign_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    resources: AppResources = Depends(get_resources),
) -> CallListOut:
    async with resources.sessionmaker() as db:
        campaign = await queries.get_campaign(db, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail=f"campaign {campaign_id} not found")
        calls = await queries.list_calls(db, campaign_id=campaign_id, limit=limit, offset=offset)
        total = await queries.count_calls(db, campaign_id=campaign_id)
    return CallListOut(
        items=[CallOut.from_orm_model(c) for c in calls], total=total, limit=limit, offset=offset
    )
