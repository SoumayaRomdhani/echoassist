"""OpenTelemetry tracing helpers: no-op safety + real span capture."""

from __future__ import annotations

import pytest

from src.observability.tracing import configure_tracing, span
from tests.conftest import make_settings

# These exercise the real SDK; skip cleanly when the observability extra is absent.
pytest.importorskip("opentelemetry.sdk")


def test_span_is_safe_to_use_without_a_provider() -> None:
    # No provider configured: span() must still be a valid context manager and
    # accept attributes without raising.
    with span("noop.span", call_id="c1", count=3):
        pass


def test_span_records_into_an_active_provider() -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    if isinstance(trace.get_tracer_provider(), TracerProvider):
        pytest.skip("a tracer provider is already installed in this session")

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    with span("call.turn", call_id="abc", domain="screening"):
        pass

    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["call.turn"]
    assert spans[0].attributes["call_id"] == "abc"
    assert spans[0].attributes["domain"] == "screening"


def test_configure_tracing_disabled_is_a_noop() -> None:
    settings = make_settings()   # otel_enabled=False
    assert configure_tracing(settings) is False
    assert configure_tracing(settings) is False   # idempotent, no side effects
