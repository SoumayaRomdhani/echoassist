"""Observability: OpenTelemetry tracing (Sprint 6, ARCHITECTURE.md §6/§9)."""

from src.observability.tracing import configure_tracing, span, trace_async

__all__ = ["configure_tracing", "span", "trace_async"]
