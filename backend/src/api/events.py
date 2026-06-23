"""In-process pub/sub hub for live call events (WebSocket fan-out).

A running call publishes events (status changes, transcript turns, consent,
degradation); WebSocket clients subscribe per ``call_id`` and stream them. This
is deliberately in-process: Sprint 6 is single-instance. Multi-instance fan-out
(Redis pub/sub) is a scale concern for later — the publish/subscribe surface
here is what a Redis-backed hub would re-implement.

A small per-call replay buffer means a client that connects a beat after the
call starts still receives the events it missed, then live updates, with no gap
and no duplicates (subscribe snapshots the buffer and registers its queue in one
synchronous step — no ``await`` between, so no interleaving with a publisher).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field

log = logging.getLogger("echoassist.api.events")

_REPLAY_LIMIT = 500   # max events retained per call for late subscribers


@dataclass(frozen=True, slots=True)
class CallEvent:
    """One live update about a call. ``terminal`` marks the last event of the call."""

    call_id: str
    type: str                 # status | transcript | consent | degraded | error
    seq: int                  # 1-based, monotonic per call
    ts: float
    data: dict = field(default_factory=dict)
    terminal: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class _Subscription:
    """An async iterator over one subscriber's events: buffered replay, then live."""

    def __init__(self, hub: CallEventHub, call_id: str, replay: list[CallEvent]) -> None:
        self._hub = hub
        self._call_id = call_id
        self._queue: asyncio.Queue[CallEvent | None] = asyncio.Queue()
        self._replay = replay
        self._closed = False

    def __aiter__(self) -> AsyncIterator[CallEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[CallEvent]:
        for event in self._replay:
            yield event
            if event.terminal:
                return
        while True:
            event = await self._queue.get()
            if event is None:    # hub closed the subscription
                return
            yield event
            if event.terminal:
                return

    def _put(self, event: CallEvent | None) -> None:
        if not self._closed:
            self._queue.put_nowait(event)

    async def aclose(self) -> None:
        self._closed = True
        self._hub._unsubscribe(self._call_id, self)


class CallEventHub:
    def __init__(self, *, replay_limit: int = _REPLAY_LIMIT) -> None:
        self._subscribers: dict[str, set[_Subscription]] = defaultdict(set)
        self._buffer: dict[str, list[CallEvent]] = defaultdict(list)
        self._seq: dict[str, int] = defaultdict(int)
        self._replay_limit = replay_limit

    def publish(self, call_id: str, type: str, data: dict, *, terminal: bool = False) -> CallEvent:
        """Build, buffer, and fan out one event. Returns the created event."""
        self._seq[call_id] += 1
        event = CallEvent(
            call_id=call_id,
            type=type,
            seq=self._seq[call_id],
            ts=time.time(),
            data=data,
            terminal=terminal,
        )
        buffer = self._buffer[call_id]
        buffer.append(event)
        if len(buffer) > self._replay_limit:
            del buffer[: len(buffer) - self._replay_limit]
        for subscription in self._subscribers[call_id]:
            subscription._put(event)
            if terminal:
                subscription._put(None)   # end the iterator after the final event
        return event

    def subscribe(self, call_id: str) -> _Subscription:
        """Subscribe to a call's events, replaying anything already buffered."""
        subscription = _Subscription(self, call_id, list(self._buffer[call_id]))
        self._subscribers[call_id].add(subscription)
        return subscription

    def _unsubscribe(self, call_id: str, subscription: _Subscription) -> None:
        self._subscribers[call_id].discard(subscription)
        if not self._subscribers[call_id]:
            del self._subscribers[call_id]

    def history(self, call_id: str) -> list[CallEvent]:
        """The buffered events for a call (most a late/replaying client could see)."""
        return list(self._buffer[call_id])

    def forget(self, call_id: str) -> None:
        """Drop a finished call's buffer and seq counter (bounds memory)."""
        self._buffer.pop(call_id, None)
        self._seq.pop(call_id, None)
