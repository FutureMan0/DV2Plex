"""The WebSocket: live log, progress and preview frames for every open page."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from dv2plex import web_app as state
from dv2plex.access import host_allowed, origin_allowed, requires_token, token_from_request, token_matches

router = APIRouter()
logger = logging.getLogger("dv2plex.web_app")


# WebSocket endpoint
@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket-Endpoint für Live-Updates"""
    host_header = websocket.headers.get("host")
    if not host_allowed(host_header, not state.token_required_everywhere, state._allowed_hosts()) or not origin_allowed(
        websocket.headers.get("origin"), host_header
    ):
        # Another web page must not read the live log and preview
        await websocket.close(code=1008)
        return
    if requires_token("/ws", state.token_required_everywhere):
        given = token_from_request(websocket.headers, websocket.query_params)
        if not token_matches(state.api_token, given):
            await websocket.close(code=1008)
            return
    await websocket.accept()
    state.websocket_connections.append(websocket)
    
    # Beim Verbinden aktuellen Status pushen, damit Buttons/Titel/Jahr sofort stimmen
    try:
        await websocket.send_json({
            "type": "status",
            "status": "capture_started" if (state.capture_service and state.capture_service.is_capturing()) else "capture_stopped",
            "data": state.active_capture
        })
    except Exception as e:
        logger.error(f"WebSocket-Initstatus konnte nicht gesendet werden: {e}")
    
    try:
        while True:
            # Keep connection alive and wait for messages
            data = await websocket.receive_text()
            # Echo back or handle commands
            await websocket.send_json({"type": "pong", "data": data})
    except WebSocketDisconnect:
        if websocket in state.websocket_connections:
            state.websocket_connections.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket-Fehler: {e}")
        if websocket in state.websocket_connections:
            state.websocket_connections.remove(websocket)
    finally:
        if websocket in state.websocket_connections:
            state.websocket_connections.remove(websocket)


