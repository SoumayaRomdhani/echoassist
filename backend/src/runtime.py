"""Process-level runtime setup."""

from __future__ import annotations

import asyncio
import sys


def use_selector_event_loop() -> None:
    """Use the Selector event loop on Windows.

    psycopg's async driver cannot run on Windows' default ProactorEventLoop, so
    any entry point that talks to Postgres must select the Selector loop before
    ``asyncio.run``. No-op on non-Windows platforms.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
