"""Liveness and readiness probes."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text

from config.settings import Settings, StateBackendName
from src.api.context import AppResources, get_resources
from src.api.schemas import HealthOut

log = logging.getLogger("echoassist.api.health")

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health(resources: AppResources = Depends(get_resources)) -> HealthOut:
    """Liveness: the process is up and serving (no external dependencies checked)."""
    return HealthOut(status="ok", service=resources.settings.otel_service_name, components={})


async def _check_database(resources: AppResources) -> str:
    try:
        async with resources.sessionmaker() as db:
            await db.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 - a probe reports, never raises
        log.warning("readiness: database unreachable: %s", exc)
        return "unreachable"


async def _check_redis(settings: Settings) -> str | None:
    if settings.state_backend is not StateBackendName.redis:
        return None   # not applicable (in-memory state backend)
    try:
        from redis import asyncio as redis_asyncio

        client = redis_asyncio.from_url(settings.redis_url)
        try:
            await client.ping()
        finally:
            await client.aclose()
        return "ok"
    except Exception as exc:  # noqa: BLE001
        log.warning("readiness: redis unreachable: %s", exc)
        return "unreachable"


async def _check_qdrant(settings: Settings) -> str:
    def _ping() -> None:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=settings.qdrant_url, timeout=2, check_compatibility=False)
        client.get_collections()

    try:
        await asyncio.to_thread(_ping)
        return "ok"
    except Exception as exc:  # noqa: BLE001
        log.warning("readiness: qdrant unreachable: %s", exc)
        return "unreachable"


@router.get("/ready", response_model=HealthOut)
async def ready(resources: AppResources = Depends(get_resources)) -> HealthOut:
    """Readiness: required backing services are reachable; ``degraded`` if any is down."""
    settings = resources.settings
    components: dict[str, str] = {"database": await _check_database(resources)}
    redis_status = await _check_redis(settings)
    if redis_status is not None:
        components["redis"] = redis_status
    components["qdrant"] = await _check_qdrant(settings)

    status = "ok" if all(v == "ok" for v in components.values()) else "degraded"
    return HealthOut(status=status, service=settings.otel_service_name, components=components)
