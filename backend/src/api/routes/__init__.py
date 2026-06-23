"""REST route modules, aggregated for mounting in :func:`src.api.app.create_app`."""

from src.api.routes.calls import router as calls_router
from src.api.routes.campaigns import router as campaigns_router
from src.api.routes.documents import router as documents_router
from src.api.routes.domains import router as domains_router
from src.api.routes.health import router as health_router

ROUTERS = (
    health_router,
    domains_router,
    campaigns_router,
    calls_router,
    documents_router,
)

__all__ = ["ROUTERS"]
