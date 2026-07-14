"""The Redis bridge that puts a terminal-run mic call onto the dashboard.

Covers the three pieces of the Sprint 8 discovery path, all without a real Redis:
the :class:`RedisCallEventSink` (publishes event JSON), the API-side
:class:`LiveCallBridge` (republishes to the hub + registers the call so it is
discoverable), and the routes that surface a live call (``GET /calls`` merge +
``GET /calls/live``).
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from src.api.events import CallEventHub
from src.api.live_bridge import LiveCallBridge
from src.api.runner import CallManager, _now
from src.telephony.events import RedisCallEventSink


class _FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))

    async def aclose(self) -> None:
        pass


def _manager() -> tuple[CallEventHub, CallManager]:
    hub = CallEventHub()
    manager = CallManager(
        engine=None, sessionmaker=None, state_store=None, hub=hub, default_campaign="camp"
    )
    return hub, manager


@pytest.mark.asyncio
async def test_redis_sink_publishes_event_json() -> None:
    fake = _FakeRedis()
    sink = RedisCallEventSink(fake, "chan", "call9")

    sink.emit("agent_state", {"state": "listening"})
    sink.emit("status", {"status": "completed"}, terminal=True)
    await sink.aclose()  # drains the fire-and-forget publish tasks

    assert len(fake.published) == 2
    assert all(chan == "chan" for chan, _ in fake.published)
    payloads = [json.loads(p) for _, p in fake.published]
    assert {
        "call_id": "call9",
        "type": "agent_state",
        "data": {"state": "listening"},
        "terminal": False,
    } in payloads
    assert any(p["type"] == "status" and p["terminal"] for p in payloads)


def test_bridge_registers_call_and_refans_to_hub() -> None:
    hub, manager = _manager()
    bridge = LiveCallBridge(
        hub=hub, call_manager=manager, redis_client=_FakeRedis(), channel="ch",
        default_domain="screening", default_campaign="camp",
    )

    bridge.dispatch(
        json.dumps(
            {
                "call_id": "m1",
                "type": "status",
                "data": {"status": "started", "domain": "screening"},
                "terminal": False,
            }
        )
    )

    # Registered as a live call (discoverable), and the event is on the hub for the WS.
    session = manager.get("m1")
    assert session is not None
    assert session.status == "started"
    assert session.domain == "screening"
    assert session in manager.live()
    assert hub.history("m1") and hub.history("m1")[0].type == "status"

    # A consent event updates the tracked session and is re-fanned.
    bridge.dispatch(json.dumps({"call_id": "m1", "type": "consent", "data": {"granted": True}}))
    assert manager.get("m1").consent_granted is True

    # The terminal status ends the call → it drops out of the live list.
    bridge.dispatch(
        json.dumps({"call_id": "m1", "type": "status", "data": {"status": "completed"},
                    "terminal": True})
    )
    assert manager.get("m1") not in manager.live()


def test_bridge_ignores_malformed_frames() -> None:
    hub, manager = _manager()
    bridge = LiveCallBridge(
        hub=hub, call_manager=manager, redis_client=_FakeRedis(), channel="ch",
        default_domain="screening", default_campaign="camp",
    )
    # None, non-JSON, and JSON missing call_id/type must all be dropped silently.
    bridge.dispatch(None)
    bridge.dispatch("not json")
    bridge.dispatch(json.dumps({"type": "status"}))
    bridge.dispatch(json.dumps({"call_id": "x"}))
    assert manager.live() == []


def test_stale_bridged_call_drops_out_of_live() -> None:
    _, manager = _manager()
    manager.register_external(call_id="ghost", domain="screening", campaign="camp")
    manager.register_external(call_id="fresh", domain="screening", campaign="camp")

    # A bridged call whose terminal event was lost (hard-killed mic process) goes silent.
    manager.get("ghost").last_event_at = _now() - timedelta(seconds=999)

    live_ids = [s.call_id for s in manager.live()]
    assert "fresh" in live_ids
    assert "ghost" not in live_ids  # aged out despite no terminal event


@pytest.mark.asyncio
async def test_live_call_surfaces_in_list_and_live_endpoint(client, resources) -> None:
    resources.call_manager.register_external(call_id="mic1", domain="screening", campaign="camp")
    resources.call_manager.note_external_event(
        "mic1", "status", {"status": "interviewing"}, terminal=False
    )

    live = (await client.get("/calls/live?domain=screening")).json()
    assert [c["call_id"] for c in live] == ["mic1"]
    assert live[0]["status"] == "interviewing"

    listed = (await client.get("/calls?domain=screening")).json()
    assert listed["items"][0]["call_id"] == "mic1"  # the live call sits on top

    # A different domain excludes it.
    assert (await client.get("/calls/live?domain=helpdesk")).json() == []

    # Once it ends it drops out of the live surfaces.
    resources.call_manager.note_external_event(
        "mic1", "status", {"status": "completed"}, terminal=True
    )
    assert (await client.get("/calls/live")).json() == []
