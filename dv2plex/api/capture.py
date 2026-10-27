"""Capture: start, stop, camera control, live preview, status and the merge queue."""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dv2plex import web_app as state

router = APIRouter()
logger = logging.getLogger("dv2plex.web_app")


class CaptureStartRequest(BaseModel):
    title: str
    year: str
    auto_rewind_play: bool = True


def preview_callback(image: bytes) -> None:
    """Sends a preview frame (raw JPEG bytes) to every browser."""
    if isinstance(image, (bytes, bytearray)):
        try:
            state.broadcast_message_sync({
                "type": "preview_frame",
                "data": "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii"),
            })
        except Exception:
            pass


def _capture_service():
    if not state.capture_service:
        raise HTTPException(status_code=500, detail="Capture service not initialized")
    return state.capture_service


@router.get("/api/status")
def get_status():
    """Current state; runs in a worker thread because device detection reads the file system."""
    capture = state.capture_service
    return {
        "capture_running": capture.is_capturing() if capture else False,
        "postprocessing_running": state.postprocessing_service.is_running() if state.postprocessing_service else False,
        "postprocessing_current": state.postprocessing_service.current() if state.postprocessing_service else None,
        "postprocessing_queued": state.postprocessing_service.queued_count() if state.postprocessing_service else 0,
        "device_available": capture.get_device() is not None if capture else False,
        "rewind_block_seconds": capture.capture_engine.get_rewind_block_remaining() if capture else 0,
        "active_capture": state.active_capture,
    }


@router.post("/api/capture/start")
async def start_capture(request: CaptureStartRequest):
    """Starts a capture; dvgrab's start takes a second, so it runs outside the event loop."""
    capture = _capture_service()
    if capture.is_capturing():
        raise HTTPException(status_code=400, detail="A capture is already running.")
    try:
        success, error = await asyncio.to_thread(
            capture.start_capture,
            request.title,
            request.year,
            preview_callback=preview_callback,
            auto_rewind_play=request.auto_rewind_play,
        )
    except Exception as e:
        logger.exception("Fehler in start_capture")
        raise HTTPException(status_code=500, detail=f"Unexpected error starting the capture: {e}")
    if not success:
        error_msg = error or "Capture could not be started; see the log."
        logger.error(f"Capture-Fehler: {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)

    state.active_capture = {
        "title": request.title,
        "year": request.year,
        "started_at": datetime.now().isoformat(),
    }
    await state.broadcast_message({"type": "status", "status": "capture_started", "data": state.active_capture})
    return {"success": True, "message": "Capture gestartet"}


@router.post("/api/capture/stop")
async def stop_capture():
    """Stops the capture in the background; the merge follows by itself."""
    capture = _capture_service()
    if not capture.is_capturing():
        raise HTTPException(status_code=400, detail="No capture is running.")
    if state.active_capture_stop_task and not state.active_capture_stop_task.done():
        return {"success": True, "message": "Stop/Merge läuft bereits im Hintergrund"}

    async def stop_and_broadcast():
        success = await asyncio.to_thread(capture.stop_capture)
        if success:
            state.active_capture = None
            await state.broadcast_message({"type": "status", "status": "capture_stopped"})
        else:
            logger.error("Capture konnte nicht gestoppt werden (Hintergrund-Task).")

    state.active_capture_stop_task = asyncio.create_task(stop_and_broadcast())
    return {"success": True, "message": "Capture-Stop/Merge läuft im Hintergrund; Web-UI bleibt erreichbar."}


async def _control(action: str):
    capture = _capture_service()
    ok = await asyncio.to_thread(getattr(capture, f"{action}_camera"))
    if not ok:
        engine = capture.capture_engine
        remaining = engine.get_rewind_block_remaining()
        detail = (f"The tape is still rewinding for {remaining} seconds." if remaining
                  else engine.last_dvgrab_error or "The camera did not respond; see the log.")
        raise HTTPException(status_code=409, detail=detail)
    return {"success": True}


@router.post("/api/capture/rewind")
async def rewind_camera():
    return await _control("rewind")


@router.post("/api/capture/play")
async def play_camera():
    return await _control("play")


@router.post("/api/capture/pause")
async def pause_camera():
    return await _control("pause")


@router.get("/api/merge/queue")
def get_merge_queue():
    """Merge jobs: the current one, waiting ones, the last ten."""
    if not state.capture_service:
        return {"pending_count": 0, "current_job": None, "completed_count": 0, "jobs": []}
    return state.capture_service.capture_engine.get_merge_queue_status()
