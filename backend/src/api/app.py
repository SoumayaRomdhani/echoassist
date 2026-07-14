"""FastAPI application factory (Sprint 6).

``create_app()`` builds the production app (real :class:`AppResources`); tests
call ``create_app(resources=...)`` with fakes. Run it with::

    uvicorn src.api.app:create_app --factory --reload
    # or: python scripts/serve.py

The factory wires the lifespan (configure tracing, create tables on startup;
release resources on shutdown), CORS for the dashboard, a per-request trace span,
the REST routers, the WebSocket route, and provider-error handlers so an upstream
outage degrades to a clean HTTP status instead of a 500.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.settings import get_settings
from src.api.context import AppResources, build_resources
from src.api.routes import ROUTERS
from src.api.ws import router as ws_router
from src.log import setup_logging
from src.observability.tracing import configure_tracing, span
from src.providers.errors import ProviderError, ProviderQuotaError
from src.storage.db import init_db

log = logging.getLogger("echoassist.api")

API_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    resources: AppResources = app.state.resources
    configure_tracing(resources.settings)
    await init_db(resources.engine)
    # Subscribe to mic/LiveKit call events (Redis) so a call taken in a terminal shows
    # live on the dashboard. No-op when there is no bridge (in-memory state backend).
    if resources.live_bridge is not None:
        resources.live_bridge.start()
    log.info("EchoAssist API ready (domain=%s)", resources.settings.domain)
    try:
        yield
    finally:
        await resources.aclose()


def create_app(resources: AppResources | None = None) -> FastAPI:
    settings = resources.settings if resources is not None else get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(title="EchoAssist API", version=API_VERSION, lifespan=lifespan)
    app.state.resources = resources if resources is not None else build_resources(settings)

    # Dev defaults: CORS is open and there is no auth. ACTEEK SSO is integrated in
    # Sprint 7 (ARCHITECTURE.md §2 — do not rebuild auth); do not expose this publicly as-is.
    origins = [o.strip() for o in settings.api_cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def trace_requests(request: Request, call_next):
        attrs = {"http.method": request.method, "http.target": request.url.path}
        with span("http.request", **attrs):
            return await call_next(request)

    @app.exception_handler(ProviderQuotaError)
    async def _quota_handler(_: Request, exc: ProviderQuotaError) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": f"provider quota exceeded: {exc}"})

    @app.exception_handler(ProviderError)
    async def _provider_handler(_: Request, exc: ProviderError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": f"provider error: {exc}"})

    @app.get("/", tags=["health"])
    async def root() -> dict:
        return {"service": settings.otel_service_name, "version": API_VERSION, "docs": "/docs"}

    for router in ROUTERS:
        app.include_router(router)
    app.include_router(ws_router)
    return app
