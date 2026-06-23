"""OpenTelemetry tracing: no-op safety, per-stage span names, and PII-free attributes."""

from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from src.agent.state import ConversationState  # noqa: E402
from src.observability.tracing import configure_tracing, span  # noqa: E402
from src.storage.db import make_sessionmaker, persist_call  # noqa: E402
from tests.conftest import FakeSTT, FakeTTS, audio, make_settings  # noqa: E402

# One in-memory provider for the whole module; installed once (the global provider
# can only be set once per process). API tests disable tracing, so nothing competes.
_EXPORTER = InMemorySpanExporter()
_PROVIDER = TracerProvider()
_PROVIDER.add_span_processor(SimpleSpanProcessor(_EXPORTER))


def _use_exporter() -> bool:
    """Make our in-memory provider active and clear it; False if another owns the global."""
    current = trace.get_tracer_provider()
    if current is _PROVIDER:
        _EXPORTER.clear()
        return True
    if isinstance(current, TracerProvider):
        return False
    trace.set_tracer_provider(_PROVIDER)
    _EXPORTER.clear()
    return True


def test_span_is_safe_to_use_without_attributes_error() -> None:
    with span("noop.span", call_id="c1", count=3):
        pass


def test_span_records_into_active_provider() -> None:
    if not _use_exporter():
        pytest.skip("another tracer provider is installed")
    with span("call.turn", call_id="abc", domain="screening"):
        pass
    spans = {s.name: s for s in _EXPORTER.get_finished_spans()}
    assert "call.turn" in spans
    assert spans["call.turn"].attributes["call_id"] == "abc"


@pytest.mark.asyncio
async def test_stage_spans_are_named_per_stage(sqlite_engine) -> None:
    if not _use_exporter():
        pytest.skip("another tracer provider is installed")
    await FakeSTT().transcribe(audio("hello"))
    await FakeTTS().synthesize("hello")
    async with make_sessionmaker(sqlite_engine)() as db:
        state = ConversationState(call_id="t1")
        state.add_turn("user", "hi")
        await persist_call(db, campaign_name="C", domain="screening",
                           state=state, notes={"x": 1}, summary="s")

    names = {s.name for s in _EXPORTER.get_finished_spans()}
    assert {"stt.transcribe", "tts.synthesize", "db.persist"} <= names


@pytest.mark.asyncio
async def test_no_pii_in_span_attributes(sqlite_engine) -> None:
    if not _use_exporter():
        pytest.skip("another tracer provider is installed")
    secret = "leak@example.com"
    await FakeSTT().transcribe(audio(f"my email is {secret}"))
    await FakeTTS().synthesize(f"call {secret}")
    async with make_sessionmaker(sqlite_engine)() as db:
        state = ConversationState(call_id="t2")
        state.add_turn("user", secret)
        await persist_call(db, campaign_name="C2", domain="screening",
                           state=state, notes={}, summary=secret)

    for finished in _EXPORTER.get_finished_spans():
        for value in (finished.attributes or {}).values():
            assert secret not in str(value)   # transcript/email never leaks into attributes


def test_configure_tracing_disabled_is_a_noop() -> None:
    assert configure_tracing(make_settings()) is False
