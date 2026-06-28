"""WebSocket: live call status + transcript (Sprint 6).

A client connects to ``/ws/calls/{call_id}`` and receives every event for that
call as JSON — the buffered events first (so a client that joins a beat late sees
the whole call), then live updates, until the terminal event closes the stream.
The socket is read-only from the client's side: the server only pushes.
"""

from __future__ import annotations

import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger("echoassist.api.ws")

router = APIRouter(tags=["ws"])


@router.websocket("/ws/calls/{call_id}")
async def call_events(websocket: WebSocket, call_id: str) -> None:
    resources = websocket.app.state.resources
    settings = resources.settings
    hub = resources.hub
    known = resources.call_manager.get(call_id) is not None or bool(hub.history(call_id))

    await websocket.accept()

    # Shared-secret gate (Sprint 8), stand-in for ACTEEK SSO: when API_AUTH_TOKEN is
    # set, the client must present a matching ?access_token=. Unset => open (dev).
    token = websocket.query_params.get("access_token")
    if settings.api_auth_token and token != settings.api_auth_token:
        await websocket.send_json(
            {"type": "error", "data": {"message": "unauthorized: invalid or missing access_token"}}
        )
        await websocket.close(code=4401)
        return

    if not known:
        await websocket.send_json({"type": "error", "data": {"message": f"unknown call {call_id}"}})
        await websocket.close(code=4404)
        return

    subscription = hub.subscribe(call_id)
    try:
        async for event in subscription:
            await websocket.send_json(event.to_dict())
    except WebSocketDisconnect:
        log.debug("ws client disconnected from call %s", call_id)
    except Exception as exc:  # noqa: BLE001 - never let a socket error escape the handler
        log.debug("ws stream for call %s ended: %s", call_id, exc)
    finally:
        await subscription.aclose()
        with contextlib.suppress(Exception):
            await websocket.close()
