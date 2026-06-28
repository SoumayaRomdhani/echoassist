"""WebSocket live updates — uses the sync TestClient (runs lifespan + supports WS)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from src.api.app import create_app  # noqa: E402
from tests.conftest import make_resources, make_settings  # noqa: E402


def _app():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    return create_app(make_resources(engine))


def _app_with_auth(token: str):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    settings = make_settings().model_copy(update={"api_auth_token": token})
    return create_app(make_resources(engine, settings=settings))


def test_ws_streams_live_call_events_then_serves_result() -> None:
    with TestClient(_app()) as client:
        started = client.post("/calls", json={"consent": True})
        assert started.status_code == 202
        call_id = started.json()["call_id"]

        events = []
        with client.websocket_connect(f"/ws/calls/{call_id}") as ws:
            while True:
                event = ws.receive_json()
                events.append(event)
                if event.get("terminal"):
                    break

        types = [e["type"] for e in events]
        assert types[0] == "status"                       # call started
        assert "consent" in types and "transcript" in types
        assert any(e["type"] == "transcript" and e["data"]["role"] == "caller" for e in events)
        assert events[-1]["data"]["status"] == "completed"

        # The call is fully persisted by the time the terminal event arrives.
        detail = client.get(f"/calls/{call_id}").json()
        assert detail["status"] == "completed"
        assert detail["notes"]["years_experience"] == "6 years"


def test_ws_rejects_unknown_call() -> None:
    with TestClient(_app()) as client, client.websocket_connect("/ws/calls/nope") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"


def test_ws_rejects_missing_or_wrong_token_when_auth_enabled() -> None:
    with TestClient(_app_with_auth("s3cret")) as client:
        call_id = client.post("/calls", json={"consent": True}).json()["call_id"]
        for url in (f"/ws/calls/{call_id}", f"/ws/calls/{call_id}?access_token=wrong"):
            with client.websocket_connect(url) as ws:
                message = ws.receive_json()
                assert message["type"] == "error"
                assert "unauthorized" in message["data"]["message"]


def test_ws_accepts_correct_token_when_auth_enabled() -> None:
    with TestClient(_app_with_auth("s3cret")) as client:
        call_id = client.post("/calls", json={"consent": True}).json()["call_id"]
        with client.websocket_connect(f"/ws/calls/{call_id}?access_token=s3cret") as ws:
            assert ws.receive_json()["type"] == "status"
