"""Domain endpoints — a domain is config (interview flow + KB + notes schema)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from src.agent.domain import list_available_domains, load_domain_config
from src.api.context import AppResources, get_resources
from src.api.schemas import DomainOut

log = logging.getLogger("echoassist.api.domains")

router = APIRouter(prefix="/domains", tags=["domains"])


def _indexed(resources: AppResources, domain: str) -> bool | None:
    """Best-effort: does a non-empty vector collection exist for this domain?

    Returns None when it cannot be determined (no provider pool, or Qdrant down) —
    a metadata endpoint must never fail because the vector store is unreachable.
    """
    if resources.pool is None:
        return None
    try:
        return resources.pool.vector_store(domain).count() > 0
    except Exception as exc:  # noqa: BLE001
        log.debug("indexed check failed for %s: %s", domain, exc)
        return None


def _domain_out(resources: AppResources, domain: str) -> DomainOut:
    cfg = load_domain_config(domain, resources.settings.config_dir)
    states = cfg.flow.get("states", [])
    return DomainOut(
        name=cfg.name,
        language=cfg.language,
        disclosure=cfg.disclosure,
        greeting=cfg.greeting,
        question_count=sum(1 for s in states if s.get("type") == "question"),
        slots=[s["slot"] for s in states if s.get("slot")],
        indexed=_indexed(resources, domain),
    )


@router.get("", response_model=list[DomainOut])
async def list_domains(resources: AppResources = Depends(get_resources)) -> list[DomainOut]:
    return [
        _domain_out(resources, domain)
        for domain in list_available_domains(resources.settings.config_dir)
    ]


@router.get("/{domain}", response_model=DomainOut)
async def get_domain(
    domain: str, resources: AppResources = Depends(get_resources)
) -> DomainOut:
    if domain not in list_available_domains(resources.settings.config_dir):
        raise HTTPException(status_code=404, detail=f"domain '{domain}' not found")
    return _domain_out(resources, domain)
