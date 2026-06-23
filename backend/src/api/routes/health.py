"""Liveness and readiness probes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text

from src.api.context import AppResources, get_resources
from src.api.schemas import HealthOut

log = logging.getLogger("echoassist.api.health")

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health(resources: AppResources = Depends(get_resources)) -> HealthOut:
    """Liveness: the process is up and serving (no external dependencies checked)."""
    return HealthOut(status="ok", service=resources.settings.otel_service_name, components={})


@router.get("/ready", response_model=HealthOut)
async def ready(resources: AppResources = Depends(get_resources)) -> HealthOut:
    """Readiness: the database is reachable (used by orchestrators before routing traffic)."""
    components: dict[str, str] = {}
    try:
        async with resources.sessionmaker() as db:
            await db.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report, do not raise, from a probe
        log.warning("readiness: database unreachable: %s", exc)
        components["database"] = "unreachable"

    status = "ok" if all(v == "ok" for v in components.values()) else "degraded"
    return HealthOut(status=status, service=resources.settings.otel_service_name,
                     components=components)
