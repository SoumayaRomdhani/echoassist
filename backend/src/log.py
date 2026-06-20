"""Minimal structured logging setup.

A thin wrapper now; replaced/augmented by OpenTelemetry in Sprint 6. Kept here
so every entry point configures logging the same way.
"""

from __future__ import annotations

import logging


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging once, idempotently."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Silence noisy third-party loggers that would drown the speaking loop.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
