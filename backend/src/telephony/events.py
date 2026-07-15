"""A tiny event seam for the live (mic / LiveKit) call path.

The live session runs in its **own process** — the terminal you launch
``scripts/run_live.py`` in — with its own event loop, separate from the API
server that owns the :class:`~src.api.events.CallEventHub` and the dashboard
WebSocket. To put a live call on the dashboard we therefore *ship* its events
across that process boundary rather than call the hub directly.

:class:`CallEventSink` is the seam. The live session emits the same event
vocabulary the API runner publishes (``status`` / ``transcript`` / ``consent`` /
``agent_state`` / ``notes`` / ``summary``); a sink decides where they go:

* :class:`NullSink` — the default. Emits nothing, so a plain terminal run is
  byte-for-byte what it always was (the console ``print``\\s are untouched).
* ``RedisCallEventSink`` (Sprint 8, added alongside the API-side subscriber) —
  publishes each event to Redis pub/sub, where the API server re-fans it to the
  hub and out to the dashboard.

Emitting is deliberately **fire-and-forget and never-raising**: a sink must not
add latency to, or fail, a live call. A broken sink degrades to "the dashboard
doesn't update", never "the call broke".
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from config.settings import Settings

log = logging.getLogger("echoassist.telephony.events")


@runtime_checkable
class CallEventSink(Protocol):
    """Where a live call sends its events. Implementations must never raise."""

    def emit(self, type_: str, data: dict, *, terminal: bool = False) -> None:
        """Publish one event. ``terminal=True`` marks the last event of the call."""


class NullSink:
    """The default sink: drops every event (a terminal-only run broadcasts nothing)."""

    def emit(self, type_: str, data: dict, *, terminal: bool = False) -> None:  # noqa: D102
        return None


NULL_SINK: CallEventSink = NullSink()


class RedisCallEventSink:
    """Publishes each call event to a Redis pub/sub channel (the cross-process bridge).

    The live call runs in the terminal process; the API server subscribes to the same
    channel (:class:`~src.api.live_bridge.LiveCallBridge`) and re-fans the events to its
    hub, so the dashboard sees the call live.

    ``emit`` is non-blocking: it enqueues the event and returns immediately, so it never
    adds latency to the call. A single background worker drains the queue and publishes
    **in order** — ordering matters (the ``started`` event carries the call's domain, and
    transcript turns must arrive in sequence), so publishes are serialized rather than
    fired concurrently. A failed publish is logged, never raised, so a Redis blip can't
    break the call.
    """

    def __init__(self, redis_client, channel: str, call_id: str) -> None:
        self._redis = redis_client
        self._channel = channel
        self._call_id = call_id
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    def emit(self, type_: str, data: dict, *, terminal: bool = False) -> None:
        payload = json.dumps(
            {"call_id": self._call_id, "type": type_, "data": data, "terminal": terminal}
        )
        if self._worker is None or self._worker.done():
            try:
                self._worker = asyncio.ensure_future(self._run())
            except RuntimeError:  # no running loop — nothing to publish onto
                return
        self._queue.put_nowait(payload)

    async def _run(self) -> None:
        while True:
            payload = await self._queue.get()
            try:
                await self._redis.publish(self._channel, payload)
            except Exception as exc:  # noqa: BLE001 — a broken sink must never break the call
                log.debug("call-event publish failed: %s", exc)
            finally:
                self._queue.task_done()

    async def aclose(self) -> None:
        """Flush every queued event (incl. the terminal one), then close the client."""
        if self._worker is not None and not self._worker.done():
            with contextlib.suppress(Exception):
                await self._queue.join()   # wait until all queued publishes have completed
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._worker
        with contextlib.suppress(Exception):
            await self._redis.aclose()


def event_channel(settings: Settings) -> str:
    """The Redis pub/sub channel live-call events flow through (sink → API bridge)."""
    return f"{settings.redis_key_prefix}events"


def build_redis_event_sink(settings: Settings, call_id: str) -> RedisCallEventSink:
    """Build a Redis-backed sink for one call (used by ``run_live.py --broadcast``)."""
    from redis import asyncio as redis_asyncio

    client = redis_asyncio.from_url(settings.redis_url)
    return RedisCallEventSink(client, event_channel(settings), call_id)
