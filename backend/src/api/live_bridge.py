"""Bridge live-call events from Redis pub/sub onto the in-process hub (Sprint 8).

A call taken at the microphone runs in ``scripts/run_live.py`` — a separate process
that cannot touch this server's :class:`~src.api.events.CallEventHub`. With
``--broadcast`` that process publishes each event to a Redis channel; this bridge is
the API-side subscriber that reads the channel and:

1. republishes every event to the hub, so the dashboard WebSocket streams it, and
2. registers/updates the call in the :class:`~src.api.runner.CallManager`, so it is
   discoverable — it shows in ``GET /calls`` (top of the list) and ``GET /calls/live``,
   and the WebSocket accepts subscribers for it.

The subscriber is resilient: a Redis blip is logged and retried with a short backoff,
never crashing the API. It is a no-op unless Redis is the configured state backend.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from src.api.events import CallEventHub
from src.api.runner import CallManager

log = logging.getLogger("echoassist.api.live_bridge")

_RETRY_SECONDS = 2.0


class LiveCallBridge:
    def __init__(
        self,
        *,
        hub: CallEventHub,
        call_manager: CallManager,
        redis_client,
        channel: str,
        default_domain: str,
        default_campaign: str,
    ) -> None:
        self._hub = hub
        self._call_manager = call_manager
        self._redis = redis_client
        self._channel = channel
        self._default_domain = default_domain
        self._default_campaign = default_campaign
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Launch the subscriber loop as a background task (idempotent)."""
        if self._task is None:
            self._task = asyncio.create_task(self._run_forever())

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        with contextlib.suppress(Exception):
            await self._redis.aclose()

    async def _run_forever(self) -> None:
        while True:
            try:
                await self._consume()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — a Redis blip must not kill discovery
                log.warning("live-call bridge error (%s); retrying in %ss", exc, _RETRY_SECONDS)
                await asyncio.sleep(_RETRY_SECONDS)

    async def _consume(self) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._channel)
        log.info("live-call bridge subscribed to %s", self._channel)
        try:
            # Poll rather than block: get_message(timeout) returns None on an idle channel
            # (no exception), so the subscription stays continuously alive between calls.
            # A blocking listen() would raise on the socket read timeout, and tearing the
            # subscription down to resubscribe leaves a window where published events are
            # lost (Redis pub/sub does not buffer for absent subscribers).
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is not None:
                    self.dispatch(message.get("data"))
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(self._channel)
                await pubsub.aclose()

    def dispatch(self, raw: str | bytes | None) -> None:
        """Route one raw Redis message: register the call, then re-fan to the hub."""
        if raw is None:
            return
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        try:
            event = json.loads(raw)
        except (ValueError, TypeError):
            log.debug("dropping malformed call-event frame")
            return

        call_id = event.get("call_id")
        type_ = event.get("type")
        if not isinstance(call_id, str) or not isinstance(type_, str):
            return
        data = event.get("data") or {}
        terminal = bool(event.get("terminal", False))
        domain = data.get("domain") or self._default_domain

        # Discovery: make the mic call visible + WebSocket-addressable, then update it.
        if self._call_manager.get(call_id) is None:
            log.info("bridging live call %s (domain=%s)", call_id, domain)
        self._call_manager.register_external(
            call_id=call_id, domain=domain, campaign=self._default_campaign
        )
        self._call_manager.note_external_event(call_id, type_, data, terminal=terminal)
        # Live fan-out to the dashboard WebSocket.
        self._hub.publish(call_id, type_, data, terminal=terminal)
