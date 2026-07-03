"""Optional per-turn latency instrumentation for the voice interview pipeline.

Turn on with ``LATENCY_LOGGING=true``. When off, every helper is a cheap no-op (the
context var is ``None``), so it neither changes behaviour nor adds measurable latency.
When on, each turn's timings are collected in a context-local :class:`TurnRecorder`,
logged as one readable line, and appended as one JSON object to
``backend/data/latency_runs/latency_<timestamp>.jsonl`` (one file per process/run).

Design: a :class:`contextvars.ContextVar` holds the current turn's recorder, so deep
pipeline code (retriever, dialogue, grounding, providers) records spans via
:func:`span` / :func:`event` / :func:`observe` **without any signature change** — and
``asyncio.to_thread`` copies the context, so retrieval timing recorded in a worker
thread still lands on the right turn. All timing uses ``time.perf_counter`` (monotonic).

Instrumentation must never affect the call: writes are wrapped so a logging failure is
swallowed, and the whole module is inert unless the env flag is set.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.settings import Settings

log = logging.getLogger("echoassist.latency")

_ENV_FLAG = "LATENCY_LOGGING"

_current: contextvars.ContextVar[TurnRecorder | None] = contextvars.ContextVar(
    "echoassist_latency_turn", default=None
)
_run_path: Path | None = None


def is_enabled() -> bool:
    """Whether latency logging is on (``LATENCY_LOGGING=true|1|yes|on``)."""
    return os.getenv(_ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


class TurnRecorder:
    """Collects one turn's timings/values. Durations accumulate; events keep the first."""

    def __init__(self, fields: dict) -> None:
        self._t0 = time.perf_counter()
        self._events: dict[str, float] = {}
        self.data: dict = dict(fields)

    def _elapsed_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0

    def event(self, name: str) -> None:
        """Record the time of a one-off event (ms since turn start); keeps the first."""
        self._events.setdefault(name, self._elapsed_ms())

    def add(self, field: str, ms: float) -> None:
        """Accumulate a duration (repeated calls sum — e.g. the tool loop's LLM calls)."""
        self.data[field] = self.data.get(field, 0.0) + ms

    def observe(self, **fields: object) -> None:
        self.data.update(fields)

    def finalize(self) -> dict:
        """Compute derived fields (total_turn, TTFA) and round floats for readability."""
        self.data["total_turn_ms"] = self._elapsed_ms()
        stt_done = self._events.get("stt_done")
        first_audio = self._events.get("first_audio")
        if first_audio is not None:
            self.data["first_audio_event_ms"] = first_audio   # turn-relative, ms
        if stt_done is not None and first_audio is not None:
            # TTFA: from the transcript being ready to the agent's first audio chunk.
            self.data["ttfa_ms"] = first_audio - stt_done
        for key, value in list(self.data.items()):
            if isinstance(value, float):
                self.data[key] = round(value, 1)
        return self.data


def current() -> TurnRecorder | None:
    return _current.get()


@contextmanager
def span(field: str) -> Iterator[None]:
    """Time a block and accumulate it into ``<field>`` of the current turn (no-op if off)."""
    rec = _current.get()
    if rec is None:
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        rec.add(field, (time.perf_counter() - start) * 1000.0)


def event(name: str) -> None:
    """Timestamp a one-off event (e.g. ``stt_done``, ``first_audio``) on the current turn."""
    rec = _current.get()
    if rec is not None:
        rec.event(name)


def observe(**fields: object) -> None:
    """Attach arbitrary values (intent, counts, config) to the current turn."""
    rec = _current.get()
    if rec is not None:
        rec.observe(**fields)


def config_fields(settings: Settings) -> dict:
    """The run's config + provider names/models, embedded in every turn's JSON for comparison."""
    tts_model = {
        "deepgram": getattr(settings, "deepgram_tts_model", ""),
        "cartesia": getattr(settings, "cartesia_model", ""),
        "elevenlabs": getattr(settings, "elevenlabs_model", ""),
        "kokoro": getattr(settings, "kokoro_voice", ""),
    }.get(settings.tts_provider.value, "")
    return {
        "domain": settings.domain,
        "stt_provider": settings.stt_provider.value,
        "llm_provider": settings.llm_provider.value,
        "tts_provider": settings.tts_provider.value,
        "tts_model": tts_model,
        "embeddings_provider": settings.embeddings_provider.value,
        "reranker_provider": settings.reranker_provider.value,
        "rag_candidates": settings.rag_candidates,
        "rag_top_k": settings.rag_top_k,
        "grounding_min_confidence": settings.grounding_min_confidence,
    }


@contextmanager
def record_turn(data_dir: Path, **fields: object) -> Iterator[TurnRecorder | None]:
    """Record one turn: bind the context var, then log + append one JSONL line on exit.

    Always usable — yields ``None`` (and does nothing) when ``LATENCY_LOGGING`` is off, so
    the call sites stay clean and add no latency in the default configuration.
    """
    if not is_enabled():
        yield None
        return
    rec = TurnRecorder(fields)
    token = _current.set(rec)
    try:
        yield rec
    finally:
        _current.reset(token)
        data = rec.finalize()
        _append_jsonl(data_dir, data)
        _log_summary(data)


def _run_file(data_dir: Path) -> Path:
    global _run_path
    if _run_path is None:
        runs = data_dir / "latency_runs"
        runs.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        _run_path = runs / f"latency_{stamp}.jsonl"
        log.info("latency logging on -> %s", _run_path)
    return _run_path


def _append_jsonl(data_dir: Path, data: dict) -> None:
    try:
        with _run_file(data_dir).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:  # noqa: BLE001 — instrumentation must never break the call
        log.warning("latency JSONL write failed (%s)", exc)


def _log_summary(d: dict) -> None:
    def num(key: str) -> str:
        value = d.get(key)
        return f"{value:.0f}" if isinstance(value, (int, float)) else "-"

    log.info(
        "latency turn=%s intent=%s rag=%s tts=%s/%s | ttfa=%sms total=%sms | stt=%s classify=%s "
        "rag=%s(embed=%s qdrant=%s rerank=%s) llm=%s(ttft=%s) | "
        "tts_first_byte=%s sent_total=%s chunks=%s first_audio_at=%s | retrieved=%s confident=%s",
        d.get("turn_id"), d.get("intent"), d.get("is_rag"),
        d.get("tts_provider"), d.get("tts_model"),
        num("ttfa_ms"), num("total_turn_ms"), num("stt_ms"), num("classifier_ms"),
        num("rag_total_ms"), num("rag_embed_ms"), num("rag_qdrant_ms"), num("rag_rerank_ms"),
        num("llm_total_ms"), num("llm_ttft_ms"),
        num("tts_first_byte_ms"), num("sentence_tts_total_ms"), d.get("tts_chunks_count", "-"),
        num("first_audio_event_ms"),
        d.get("retrieved_chunks_count", "-"), d.get("confident_chunks_count", "-"),
    )
