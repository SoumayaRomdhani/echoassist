"""Run the EchoAssist backend API (Sprint 6).

    python scripts/serve.py            # http://localhost:8000  (docs at /docs)

On Windows this must run on the Selector event loop, because psycopg's async
driver cannot use the default ProactorEventLoop (see src/runtime.py). ``uvicorn``
installs its own loop and would override the policy, so on Windows we set the
Selector policy and run the server inside our own ``asyncio.run`` (which bypasses
uvicorn's loop setup). On other platforms we use ``uvicorn.run`` directly (so it
can pick up uvloop). For the same reason, prefer this script over
``uvicorn ... --reload`` on Windows.

Requires Postgres (and, for live calls / RAG, Redis + Qdrant) running:
    docker compose -f ../docker-compose.yml up -d postgres redis qdrant
"""

from __future__ import annotations

import asyncio
import sys

import uvicorn

from config.settings import get_settings
from src.console import init_console
from src.runtime import use_selector_event_loop

_APP = "src.api.app:create_app"


def main() -> None:
    init_console()
    settings = get_settings()
    kwargs = dict(
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )
    if sys.platform == "win32":
        # Set the Selector policy, then drive the server on a loop we control so
        # uvicorn cannot swap in the (psycopg-incompatible) ProactorEventLoop.
        use_selector_event_loop()
        config = uvicorn.Config(_APP, **kwargs)
        asyncio.run(uvicorn.Server(config).serve())
    else:
        uvicorn.run(_APP, **kwargs)


if __name__ == "__main__":
    main()
