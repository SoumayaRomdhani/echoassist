"""OpenTelemetry tracing — per-stage spans for the voice pipeline + API.

Design goals:

- **Optional dependency.** If ``opentelemetry`` is not installed (e.g. the
  Sprint 1–5 install), every helper degrades to a no-op so business logic and
  the test suite run unchanged. Instrumentation is therefore safe to sprinkle
  through the pipeline (STT/LLM/TTS/retrieve) without a hard dependency.
- **Delegates to the global API.** :func:`span` always calls the OpenTelemetry
  API's global tracer. Until :func:`configure_tracing` installs a real provider
  the global default is a no-op (spans cost almost nothing); afterwards the same
  call sites emit real spans. Tests can install an in-memory provider and see
  exactly the spans the code produced.
- **Light by default (ARCHITECTURE.md §6).** Export to an OTLP collector/Tempo
  when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, to the console when explicitly
  asked, otherwise drop spans. No collector is required to run the service.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Iterator

    from config.settings import Settings

log = logging.getLogger("echoassist.observability")

try:  # OpenTelemetry is an optional extra (`pip install -e ".[observability]"`).
    from opentelemetry import trace as _otel_trace

    _OTEL = True
except ImportError:  # pragma: no cover - exercised only without the extra installed
    _OTEL = False

_TRACER_NAME = "echoassist"
_configured = False

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def configure_tracing(settings: Settings) -> bool:
    """Install a tracer provider once. Returns True if real tracing is active.

    Idempotent: safe to call from every entry point (API, scripts). A no-op when
    tracing is disabled or the OpenTelemetry SDK is not installed.
    """
    global _configured
    if _configured or not settings.otel_enabled or not _OTEL:
        return _configured

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )
    except ImportError:  # SDK missing — API present but cannot export; stay no-op.
        log.warning("opentelemetry-sdk not installed; tracing disabled")
        return False

    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.otel_service_name})
    )
    if settings.otel_exporter_otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError:
            log.warning(
                "OTLP endpoint set but the exporter is not installed; "
                "run pip install -e \".[observability-otlp]\". Tracing stays local."
            )
        else:
            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
                )
            )
            log.info("tracing -> OTLP %s", settings.otel_exporter_otlp_endpoint)
    elif settings.otel_console_export:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        log.info("tracing -> console")
    else:
        log.info("tracing enabled (no exporter; set OTEL_EXPORTER_OTLP_ENDPOINT to export)")

    _otel_trace.set_tracer_provider(provider)
    _configured = True
    return True


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Start a span named ``name`` with optional attributes; a no-op without OTel.

    Usage::

        with span("stt.transcribe", call_id=call_id):
            ...
    """
    if not _OTEL:
        yield None
        return
    tracer = _otel_trace.get_tracer(_TRACER_NAME)
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        yield current


def trace_async(name: str) -> Callable[[F], F]:
    """Decorator: wrap an async function body in a span named ``name``."""

    def decorate(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            with span(name):
                return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorate
