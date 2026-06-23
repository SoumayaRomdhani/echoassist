"""Call event hub: fan-out, buffered replay for late subscribers, terminal close."""

from __future__ import annotations

import asyncio

import pytest

from src.api.events import CallEventHub


async def _collect(subscription) -> list:
    return [event async for event in subscription]


@pytest.mark.asyncio
async def test_subscriber_receives_live_events_until_terminal() -> None:
    hub = CallEventHub()
    sub = hub.subscribe("c1")
    collector = asyncio.create_task(_collect(sub))
    await asyncio.sleep(0)   # let the iterator start

    hub.publish("c1", "status", {"status": "started"})
    hub.publish("c1", "transcript", {"role": "assistant", "text": "hi"})
    hub.publish("c1", "status", {"status": "completed"}, terminal=True)

    events = await asyncio.wait_for(collector, timeout=1)
    assert [e.type for e in events] == ["status", "transcript", "status"]
    assert [e.seq for e in events] == [1, 2, 3]      # monotonic per call
    assert events[-1].terminal is True


@pytest.mark.asyncio
async def test_late_subscriber_replays_buffer_then_ends() -> None:
    hub = CallEventHub()
    hub.publish("c1", "status", {"status": "started"})
    hub.publish("c1", "transcript", {"role": "caller", "text": "yes"})
    hub.publish("c1", "status", {"status": "completed"}, terminal=True)

    # Subscribing after the call finished still yields the full history.
    events = await asyncio.wait_for(_collect(hub.subscribe("c1")), timeout=1)
    assert [e.type for e in events] == ["status", "transcript", "status"]
    assert events[-1].terminal is True


@pytest.mark.asyncio
async def test_two_subscribers_both_receive_events() -> None:
    hub = CallEventHub()
    sub1, sub2 = hub.subscribe("c1"), hub.subscribe("c1")
    t1 = asyncio.create_task(_collect(sub1))
    t2 = asyncio.create_task(_collect(sub2))
    await asyncio.sleep(0)

    hub.publish("c1", "status", {"status": "started"})
    hub.publish("c1", "status", {"status": "completed"}, terminal=True)

    got1, got2 = await asyncio.wait_for(asyncio.gather(t1, t2), timeout=1)
    assert len(got1) == len(got2) == 2


@pytest.mark.asyncio
async def test_events_are_isolated_per_call() -> None:
    hub = CallEventHub()
    hub.publish("c1", "status", {"status": "started"}, terminal=True)
    hub.publish("c2", "status", {"status": "started"}, terminal=True)

    c1 = await asyncio.wait_for(_collect(hub.subscribe("c1")), timeout=1)
    c2 = await asyncio.wait_for(_collect(hub.subscribe("c2")), timeout=1)
    assert all(e.call_id == "c1" for e in c1)
    assert all(e.call_id == "c2" for e in c2)


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery() -> None:
    hub = CallEventHub()
    sub = hub.subscribe("c1")
    await sub.aclose()
    assert hub._subscribers.get("c1") in (None, set())   # registry cleaned up


def test_event_serializes_to_dict() -> None:
    hub = CallEventHub()
    event = hub.publish("c1", "consent", {"granted": True})
    payload = event.to_dict()
    assert payload["call_id"] == "c1"
    assert payload["type"] == "consent"
    assert payload["data"] == {"granted": True}
    assert payload["terminal"] is False


def test_forget_clears_buffer() -> None:
    hub = CallEventHub()
    hub.publish("c1", "status", {"status": "started"})
    assert hub.history("c1")
    hub.forget("c1")
    assert hub.history("c1") == []
