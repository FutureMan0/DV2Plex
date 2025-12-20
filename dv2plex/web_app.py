"""
Web-App für DV2Plex - FastAPI-basierte Web-UI
"""

import sys
import logging
import base64
import asyncio
import threading
import mimetypes
import shutil
import os
import stat
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import uvicorn

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dv2plex.config import Config
from dv2plex.service import (
    PostprocessingService,
    CaptureService,
    MovieModeService,
    CoverService,
    find_pending_movies,
    find_upscaled_videos,
    find_available_videos,
    find_exported_plex_videos,
    parse_movie_folder_name
)
from dv2plex.update_manager import UpdateManager

QIMAGE_AVAILABLE = False


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# FastAPI app
app = FastAPI(title="DV2Plex Web Interface")

# Global state
config = Config()
capture_service: Optional[CaptureService] = None
postprocessing_service: Optional[PostprocessingService] = None
movie_mode_service: Optional[MovieModeService] = None
cover_service: Optional[CoverService] = None
update_manager: Optional[UpdateManager] = None
update_task: Optional[asyncio.Task] = None
main_event_loop: Optional[asyncio.AbstractEventLoop] = None

# WebSocket connections for broadcasting
websocket_connections: List[WebSocket] = []

# Active operations
active_capture: Optional[Dict[str, Any]] = None
active_postprocessing: Optional[Dict[str, Any]] = None
active_capture_stop_task: Optional[asyncio.Task] = None
active_export_all: Dict[str, Any] = {
    "running": False,
    "total": 0,
    "done": 0,
    "skipped": 0,
    "failed": 0,
    "current": None,
}
active_export_single: Dict[str, Any] = {
    "running": False,
    "current": None,
}
active_movie_merge: Dict[str, Any] = {
    "running": False,
    "current": None,
}

# Log-Speicher für Web-Interface (ringbuffer)
log_buffer: List[Dict[str, Any]] = []
LOG_BUFFER_MAX_SIZE = 500  # Maximale Anzahl Log-Einträge


def add_log_entry(msg: str, category: str = "general"):
    """Fügt einen Log-Eintrag zum Buffer hinzu"""
    global log_buffer
    
    # Ignoriere Preview-Logs (zu viele)
    if "Preview" in msg and category == "general":
        return
    
    entry = {
        "timestamp": datetime.now().isoformat(),
        "message": msg,
        "category": category
    }
    log_buffer.append(entry)
    
    # Ringbuffer: Entferne älteste Einträge wenn zu voll
    if len(log_buffer) > LOG_BUFFER_MAX_SIZE:
        log_buffer = log_buffer[-LOG_BUFFER_MAX_SIZE:]


def setup_services():
    """Initialisiert die Services"""
    global capture_service, postprocessing_service, movie_mode_service, cover_service, update_manager
    
    def log_callback(msg: str):
        logger.info(msg)
        add_log_entry(msg, "capture")
        broadcast_message_sync({"type": "log", "message": msg})
    
    def merge_progress_callback(job):
        """Callback für Merge-Progress-Updates"""
        add_log_entry(f"Merge [{job.status}]: {job.title} ({job.year}) - {job.message}", "merge")
        broadcast_message_sync({
            "type": "merge_progress",
            "job": {
                "title": job.title,
                "year": job.year,
                "status": job.status,
                "progress": job.progress,
                "message": job.message
            }
        })

    def capture_state_callback(state: str):
        if state == "stopped":
            broadcast_message_sync({
                "type": "status",
                "status": "capture_stopped",
                "data": None,
                "operation": "capture"
            })
    
    capture_service = CaptureService(
        config, 
        log_callback=log_callback,
        merge_progress_callback=merge_progress_callback,
        state_callback=capture_state_callback,
    )
    
    postprocessing_service = PostprocessingService(config, log_callback=log_callback)
    movie_mode_service = MovieModeService(config, log_callback=log_callback)
    cover_service = CoverService(config, log_callback=log_callback)
    update_manager = UpdateManager(
        project_root,
        config.get("update.branch", "master"),
        config.get("update.service_name", "dv2plex"),
        config,
        capture_service,
        log_callback=lambda msg: add_log_entry(msg, "update"),
    )


async def broadcast_message(message: Dict[str, Any]):
    """Sendet eine Nachricht an alle WebSocket-Verbindungen"""
    if websocket_connections:
        # Send to all connections
        disconnected = []
        for ws in websocket_connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.error(f"Fehler beim Senden an WebSocket: {e}")
                disconnected.append(ws)
        
        # Remove disconnected connections
        for ws in disconnected:
            if ws in websocket_connections:
                websocket_connections.remove(ws)


def broadcast_message_sync(message: Dict[str, Any]):
    """Synchroner Wrapper für broadcast_message (für Threads)"""
    if not websocket_connections:
        return
    
    # Nutze immer die Event-Loop des Servers, damit Futures nicht an falsche Loops gebunden werden.
    loop = main_event_loop
    if loop is None:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    
    if loop.is_running():
        for ws in websocket_connections[:]:
            try:
                asyncio.run_coroutine_threadsafe(ws.send_json(message), loop)
            except Exception as e:
                logger.error(f"Fehler beim Senden an WebSocket: {e}")
                if ws in websocket_connections:
                    websocket_connections.remove(ws)
    else:
        try:
            loop.run_until_complete(broadcast_message(message))
        except Exception as e:
            logger.error(f"Fehler bei WebSocket-Broadcast: {e}")


async def _start_update_scheduler():
    """Startet den periodischen Update-Check."""
    global update_task
    if update_task and not update_task.done():
        return
    if not update_manager:
        return

    async def _loop():
        await asyncio.sleep(5)
        while True:
            interval_minutes = int(config.get("update.interval_minutes", 60) or 60)
            interval_minutes = max(1, interval_minutes)
            if config.get("update.enabled", True):
                try:
                    result = await update_manager.check_and_update(auto=True)
                    if result.get("blocked"):
                        add_log_entry(f"Update übersprungen: {result.get('reason')}", "update")
                    elif result.get("updated"):
                        add_log_entry("Auto-Update erfolgreich ausgeführt", "update")
                    elif result.get("error"):
                        add_log_entry(f"Auto-Update Fehler: {result.get('error')}", "update")
                except Exception as e:
                    logger.error(f"Auto-Update Scheduler Fehler: {e}")
                    add_log_entry(f"Auto-Update Scheduler Fehler: {e}", "update")
            await asyncio.sleep(interval_minutes * 60)

    update_task = asyncio.create_task(_loop())


# Pydantic models for API
class CaptureStartRequest(BaseModel):
    title: str
    year: str
    auto_rewind_play: bool = True


class PostprocessRequest(BaseModel):
    movie_dir: str
    profile_name: str = "realesrgan_2x"


class MergeRequest(BaseModel):
    video_paths: List[str]
    title: str
    year: str


class ExportRequest(BaseModel):
    video_path: str
    title: Optional[str] = None
    year: Optional[str] = None


class ExportAllRequest(BaseModel):
    skip_existing: bool = True


class DeleteProjectsRequest(BaseModel):
    paths: List[str]


class CoverExtractRequest(BaseModel):
    video_path: str
    count: int = 4


class CoverGenerateRequest(BaseModel):
    frame_path: str
    title: str
    year: Optional[str] = None


class ChownRequest(BaseModel):
    path: str


# Preview callback for capture
def preview_callback(image):
    """Callback für Preview-Frames während Capture"""
    # Erwartet rohe JPEG-Bytes
    if isinstance(image, (bytes, bytearray)):
        try:
            base64_image = base64.b64encode(image).decode('utf-8')
            broadcast_message_sync({
                "type": "preview_frame",
                "data": f"data:image/jpeg;base64,{base64_image}"
            })
        except Exception:
            pass


# API Routes
@app.get("/", response_class=HTMLResponse)
async def root():
    """Hauptseite mit Web-Interface"""
    return get_html_interface()


@app.get("/api/status")
async def get_status():
    """Gibt den aktuellen Status zurück"""
    return {
        "capture_running": capture_service.is_capturing() if capture_service else False,
        "postprocessing_running": postprocessing_service.is_running() if postprocessing_service else False,
        "device_available": capture_service.get_device() is not None if capture_service else False,
        "active_capture": active_capture
    }


@app.get("/api/update/status")
async def get_update_status(refresh: bool = False):
    """Gibt den Update-Status zurück"""
    if not update_manager:
        raise HTTPException(status_code=500, detail="Update-Manager nicht initialisiert")
    status = await update_manager.get_status(refresh=refresh)
    busy_reason = update_manager.busy_reason()
    return {
        "status": {
            "local": status.local,
            "remote": status.remote,
            "ahead": status.ahead,
            "behind": status.behind,
            "fetched": status.fetched,
            "ok": status.ok,
            "error": status.error,
            "last_checked": status.last_checked,
            "blocked_reason": status.blocked_reason or busy_reason,
        },
        "last_result": update_manager.last_result,
    }


@app.post("/api/update/run")
async def trigger_update():
    """Löst ein manuelles Update aus (git pull + Restart)"""
    if not update_manager:
        raise HTTPException(status_code=500, detail="Update-Manager nicht initialisiert")
    result = await update_manager.check_and_update(auto=False)
    if result.get("blocked"):
        raise HTTPException(status_code=409, detail=result.get("reason") or "Update blockiert")
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return {
        "success": result.get("updated", False),
        "message": result.get("message")
        or ("Kein Update nötig" if not result.get("updated") else "Update ausgeführt"),
        "status": result.get("status"),
    }


@app.get("/api/upscaling/profiles")
async def get_upscaling_profiles():
    """Gibt alle verfügbaren Upscaling-Profile zurück"""
    profiles = config.get("upscaling.profiles", {})
    default_profile = config.get("upscaling.default_profile", "realesrgan_2x")
    return {
        "profiles": list(profiles.keys()),
        "default_profile": default_profile
    }


@app.get("/api/postprocess/list")
async def get_postprocess_list():
    """Gibt Liste der zu verarbeitenden Filme zurück"""
    pending = find_pending_movies(config)
    result = []
    for movie_dir in pending:
        title, year = parse_movie_folder_name(movie_dir.name)
        result.append({
            "path": str(movie_dir),
            "title": title,
            "year": year,
            "display": f"{title} ({year})" if year else movie_dir.name
        })
    return {"movies": result}


@app.get("/api/movie/list")
async def get_movie_list():
    """Gibt Liste der upscaled Videos zurück"""
    videos = find_upscaled_videos(config)
    result = []
    plex_root = config.get_plex_movies_root()

    # Speicherplatz am Ziel ermitteln (Filesystem von plex_root)
    total_bytes = used_bytes = free_bytes = None
    try:
        usage = shutil.disk_usage(str(plex_root))
        total_bytes = int(usage.total)
        used_bytes = int(usage.used)
        free_bytes = int(usage.free)
    except Exception as e:
        logger.warning(f"Konnte Disk-Usage nicht ermitteln für {plex_root}: {e}")

    required_bytes = 0
    required_count = 0
    for video_path, title, year in videos:
        movie_name = f"{title} ({year})" if year else title
        expected_target = plex_root / movie_name / f"{movie_name}.mp4"
        exported = expected_target.exists()
        # Größe der Quell-Datei (HighRes)
        size_bytes = None
        try:
            size_bytes = int(video_path.stat().st_size)
        except Exception:
            size_bytes = None

        if not exported and size_bytes is not None:
            required_bytes += size_bytes
            required_count += 1

        fits_now = True
        if not exported and free_bytes is not None and size_bytes is not None:
            fits_now = size_bytes <= free_bytes
        result.append({
            "path": str(video_path),
            "title": title,
            "year": year,
            "display": f"{title} ({year})" if year else f"{title} - {video_path.name}",
            "exported": exported,
            "expected_target": str(expected_target),
            "size_bytes": size_bytes,
            "fits_now": fits_now,
        })

    fits_all = True
    if free_bytes is not None:
        fits_all = required_bytes <= free_bytes

    return {
        "videos": result,
        "storage": {
            "plex_root": str(plex_root),
            "total_bytes": total_bytes,
            "used_bytes": used_bytes,
            "free_bytes": free_bytes,
            "required_bytes": int(required_bytes),
            "required_count": int(required_count),
            "fits_all": fits_all,
        }
    }


@app.get("/api/cover/videos")
async def get_cover_videos():
    """Gibt Liste der verfügbaren Videos für Cover-Generierung zurück"""
    # Cover-Generator soll nur Videos anzeigen, die bereits in PlexMovies exportiert wurden.
    videos = find_exported_plex_videos(config)
    result = []
    for video_path, title, year in videos:
        result.append({
            "path": str(video_path),
            "title": title,
            "year": year,
            "display": f"{title} ({year})" if year else f"{title} - {video_path.name}"
        })
    return {"videos": result}


@app.post("/api/capture/start")
async def start_capture(request: CaptureStartRequest):
    """Startet eine Capture-Session"""
    global active_capture
    
    if not capture_service:
        raise HTTPException(status_code=500, detail="Capture-Service nicht initialisiert")
    
    if capture_service.is_capturing():
        raise HTTPException(status_code=400, detail="Capture läuft bereits")
    
    try:
        success, error = capture_service.start_capture(
            request.title,
            request.year,
            preview_callback=preview_callback,
            auto_rewind_play=request.auto_rewind_play
        )
        
        if success:
            active_capture = {
                "title": request.title,
                "year": request.year,
                "started_at": datetime.now().isoformat()
            }
            await broadcast_message({
                "type": "status",
                "status": "capture_started",
                "data": active_capture
            })
            return {"success": True, "message": "Capture gestartet"}
        else:
            error_msg = error or "Capture konnte nicht gestartet werden"
            logger.error(f"Capture-Fehler: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
    except HTTPException:
        # Gewollte Fehler (z.B. Ordner existiert) ohne 500 weiterreichen
        raise
    except Exception as e:
        error_msg = f"Unerwarteter Fehler beim Starten der Aufnahme: {str(e)}"
        logger.exception("Fehler in start_capture")
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/api/capture/stop")
async def stop_capture():
    """Stoppt die laufende Capture-Session"""
    global active_capture, active_capture_stop_task
    
    if not capture_service:
        raise HTTPException(status_code=500, detail="Capture-Service nicht initialisiert")
    
    if not capture_service.is_capturing():
        raise HTTPException(status_code=400, detail="Kein Capture aktiv")
    
    # Wenn bereits ein Stop im Hintergrund läuft, nicht blockieren
    if active_capture_stop_task and not active_capture_stop_task.done():
        return {"success": True, "message": "Stop/Merge läuft bereits im Hintergrund"}
    
    async def _stop_and_broadcast():
        global active_capture
        success = await asyncio.to_thread(capture_service.stop_capture)
        if success:
            active_capture = None
            await broadcast_message({"type": "status", "status": "capture_stopped"})
        else:
            logger.error("Capture konnte nicht gestoppt werden (Hintergrund-Task).")
    
    active_capture_stop_task = asyncio.create_task(_stop_and_broadcast())
    
    return {"success": True, "message": "Capture-Stop/Merge läuft im Hintergrund; Web-UI bleibt erreichbar."}


@app.post("/api/capture/rewind")
async def rewind_camera():
    """Spult die Kamera zurück"""
    if not capture_service:
        raise HTTPException(status_code=500, detail="Capture-Service nicht initialisiert")
    
    capture_service.rewind_camera()
    return {"success": True}


@app.post("/api/capture/play")
async def play_camera():
    """Startet Wiedergabe auf der Kamera"""
    if not capture_service:
        raise HTTPException(status_code=500, detail="Capture-Service nicht initialisiert")
    
    capture_service.play_camera()
    return {"success": True}


@app.post("/api/capture/pause")
async def pause_camera():
    """Pausiert die Kamera"""
    if not capture_service:
        raise HTTPException(status_code=500, detail="Capture-Service nicht initialisiert")
    
    capture_service.pause_camera()
    return {"success": True}


def _ensure_in_dv_import_root(file_path: Path) -> Path:
    """Validiert, dass sich der Pfad innerhalb des DV_Import-Verzeichnisses befindet."""
    root = config.get_dv_import_root().resolve()
    try:
        resolved = file_path.resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Ungültiger Pfad")
    try:
        resolved.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Pfad liegt nicht im DV_Import-Ordner")
    return resolved


def _rmtree_force(path: Path) -> None:
    """
    Löscht ein Verzeichnis rekursiv und entfernt ggf. Readonly-Attribute (Windows).
    """

    def _onerror(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            raise

    shutil.rmtree(path, onerror=_onerror)


def _list_videos_in_folder(folder: Path) -> List[Dict[str, str]]:
    """Gibt alle Video-Dateien in einem Ordner zurück."""
    exts = {".mp4", ".avi", ".mkv", ".mov"}
    if not folder.exists() or not folder.is_dir():
        return []
    files = []
    for f in sorted(folder.iterdir()):
        if f.is_file() and f.suffix.lower() in exts:
            try:
                safe_path = _ensure_in_dv_import_root(f)
            except HTTPException:
                continue
            files.append({"name": f.name, "path": str(safe_path)})
    return files


@app.get("/api/player/projects")
async def list_player_projects():
    """Listet alle Projekte (LowRes/HighRes) im DV_Import-Ordner auf."""
    root = config.get_dv_import_root()
    projects = []
    if not root.exists():
        return {"projects": projects}

    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        lowres = _list_videos_in_folder(project_dir / "LowRes")
        highres = _list_videos_in_folder(project_dir / "HighRes")
        if not lowres and not highres:
            continue
        projects.append({
            "title": project_dir.name,
            "lowres": lowres,
            "highres": highres,
        })

    return {"projects": projects}


@app.get("/api/player/stream")
async def stream_video(path: str):
    """Spielt eine Videodatei aus dem DV_Import-Ordner ab."""
    if not path:
        raise HTTPException(status_code=400, detail="Pfad fehlt")
    file_path = _ensure_in_dv_import_root(Path(path))
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    mime_type, _ = mimetypes.guess_type(file_path.name)
    return FileResponse(file_path, media_type=mime_type or "video/mp4", filename=file_path.name)


@app.post("/api/postprocess/process")
async def process_movie(request: PostprocessRequest):
    """Startet Postprocessing für einen Film"""
    global active_postprocessing
    
    if not postprocessing_service:
        raise HTTPException(status_code=500, detail="Postprocessing-Service nicht initialisiert")
    
    movie_dir = Path(request.movie_dir)
    if not movie_dir.exists():
        raise HTTPException(status_code=404, detail=f"Film-Ordner nicht gefunden: {movie_dir}")
    
    # Run in background thread
    def run_postprocessing():
        global active_postprocessing
        active_postprocessing = {
            "movie_dir": str(movie_dir),
            "started_at": datetime.now().isoformat()
        }
        
        def progress_cb(value: int):
            broadcast_message_sync({"type": "progress", "value": value, "operation": "postprocessing"})
        
        def status_cb(status: str):
            broadcast_message_sync({"type": "status", "status": status, "operation": "postprocessing"})

        def finished_cb(success: bool, message: str):
            global active_postprocessing
            active_postprocessing = None
            broadcast_message_sync({
                "type": "postprocessing_finished",
                "success": success,
                "message": message
            })
        
        success, message = postprocessing_service.process_movie(
            movie_dir,
            request.profile_name,
            progress_callback=progress_cb,
            status_callback=status_cb,
            finished_callback=finished_cb,
        )
        # Wenn die Queue nur angenommen hat, nicht sofort abschließen; finished_cb macht das
        if not success:
            finished_cb(False, message)
    
    thread = threading.Thread(target=run_postprocessing, daemon=True)
    thread.start()
    
    return {"success": True, "message": "Postprocessing gestartet"}


@app.post("/api/movie/merge")
async def merge_videos(request: MergeRequest):
    """Merged mehrere Videos zu einem Film (läuft im Hintergrund)"""
    if not movie_mode_service:
        raise HTTPException(status_code=500, detail="Movie-Mode-Service nicht initialisiert")
    
    video_paths = [Path(p) for p in request.video_paths]

    global active_movie_merge
    if active_movie_merge.get("running"):
        raise HTTPException(status_code=409, detail="Merge läuft bereits")

    # Schnell validieren, damit wir sofort Fehler zurückgeben
    if len(video_paths) < 2:
        raise HTTPException(status_code=400, detail="Mindestens 2 Videos erforderlich")
    if not request.title or not request.year:
        raise HTTPException(status_code=400, detail="Titel und Jahr müssen angegeben werden")

    active_movie_merge = {"running": True, "current": f"{request.title} ({request.year})"}

    def run_merge():
        global active_movie_merge
        try:
            broadcast_message_sync({"type": "progress", "value": 0, "operation": "movie_merge"})
            broadcast_message_sync({
                "type": "status",
                "status": "movie_merge_started",
                "operation": "movie_merge",
                "data": {"title": request.title, "year": request.year, "count": len(video_paths)},
            })

            success, merged_file, error = movie_mode_service.merge_videos(
                video_paths,
                request.title,
                request.year
            )

            if not success or not merged_file:
                broadcast_message_sync({
                    "type": "status",
                    "status": "movie_merge_failed",
                    "operation": "movie_merge",
                    "data": {"error": error or "Merge fehlgeschlagen"},
                })
                return

            # Export to Plex
            export_success, exported_path, export_error = movie_mode_service.export_to_plex(
                merged_file,
                request.title,
                request.year
            )

            # Clean up temp file
            try:
                merged_file.unlink()
            except Exception:
                pass

            if export_success:
                broadcast_message_sync({"type": "progress", "value": 100, "operation": "movie_merge"})
                broadcast_message_sync({
                    "type": "status",
                    "status": "movie_merge_finished",
                    "operation": "movie_merge",
                    "data": {"exported_path": str(exported_path) if exported_path else None},
                })
            else:
                broadcast_message_sync({
                    "type": "status",
                    "status": "movie_merge_failed",
                    "operation": "movie_merge",
                    "data": {"error": export_error or "Export fehlgeschlagen"},
                })
        except Exception as e:
            logger.exception("Fehler beim Movie-Merge")
            broadcast_message_sync({
                "type": "status",
                "status": "movie_merge_failed",
                "operation": "movie_merge",
                "data": {"error": str(e)},
            })
        finally:
            active_movie_merge["running"] = False
            active_movie_merge["current"] = None

    threading.Thread(target=run_merge, daemon=True).start()
    return {"success": True, "message": "Merge gestartet (läuft im Hintergrund)."}


@app.post("/api/movie/export")
async def export_video(request: ExportRequest):
    """Exportiert ein einzelnes Video nach PlexMovies (läuft im Hintergrund)"""
    if not movie_mode_service:
        raise HTTPException(status_code=500, detail="Movie-Mode-Service nicht initialisiert")
    
    video_path = Path(request.video_path)

    global active_export_single
    if active_export_single.get("running"):
        raise HTTPException(status_code=409, detail="Export läuft bereits")

    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"Video nicht gefunden: {video_path}")

    active_export_single = {"running": True, "current": str(video_path)}

    def run_export_single():
        global active_export_single
        try:
            broadcast_message_sync({"type": "progress", "value": 0, "operation": "movie_export_single"})
            broadcast_message_sync({
                "type": "status",
                "status": "movie_export_single_started",
                "operation": "movie_export_single",
                "data": {"video_path": str(video_path)},
            })

            success, exported_path, error = movie_mode_service.export_to_plex(
                video_path,
                request.title,
                request.year
            )

            if success:
                broadcast_message_sync({"type": "progress", "value": 100, "operation": "movie_export_single"})
                broadcast_message_sync({
                    "type": "status",
                    "status": "movie_export_single_done",
                    "operation": "movie_export_single",
                    "data": {"video_path": str(video_path), "exported_path": str(exported_path) if exported_path else None},
                })
            else:
                broadcast_message_sync({
                    "type": "status",
                    "status": "movie_export_single_failed",
                    "operation": "movie_export_single",
                    "data": {"video_path": str(video_path), "error": error or "Export fehlgeschlagen"},
                })
        except Exception as e:
            logger.exception("Fehler beim Export (single)")
            broadcast_message_sync({
                "type": "status",
                "status": "movie_export_single_failed",
                "operation": "movie_export_single",
                "data": {"video_path": str(video_path), "error": str(e)},
            })
        finally:
            active_export_single["running"] = False
            active_export_single["current"] = None

    threading.Thread(target=run_export_single, daemon=True).start()
    return {"success": True, "message": "Export gestartet (läuft im Hintergrund)."}


@app.post("/api/movie/export-all")
async def export_all_videos(request: ExportAllRequest):
    """Exportiert alle upscaled (HighRes) Videos nach PlexMovies (läuft im Hintergrund)."""
    global active_export_all

    if not movie_mode_service:
        raise HTTPException(status_code=500, detail="Movie-Mode-Service nicht initialisiert")

    if active_export_all.get("running"):
        raise HTTPException(status_code=409, detail="Export-All läuft bereits")

    videos = find_upscaled_videos(config)
    total = len(videos)
    if total == 0:
        return {"success": True, "message": "Keine Videos zum Exportieren gefunden.", "total": 0}

    plex_root = config.get_plex_movies_root()

    # Init state
    active_export_all = {
        "running": True,
        "total": total,
        "done": 0,
        "skipped": 0,
        "failed": 0,
        "current": None,
    }

    def run_export_all():
        global active_export_all
        try:
            broadcast_message_sync({
                "type": "status",
                "status": "movie_export_all_started",
                "operation": "movie_export_all",
                "data": {"total": total},
            })
            broadcast_message_sync({"type": "progress", "value": 0, "operation": "movie_export_all"})

            for idx, (video_path, title, year) in enumerate(videos, start=1):
                movie_name = f"{title} ({year})" if year else title
                expected_target = plex_root / movie_name / f"{movie_name}.mp4"
                active_export_all["current"] = str(video_path)

                # Skip existing if requested
                if request.skip_existing and expected_target.exists():
                    active_export_all["skipped"] += 1
                    active_export_all["done"] += 1
                    percent = int(round(active_export_all["done"] * 100 / max(active_export_all["total"], 1)))
                    broadcast_message_sync({
                        "type": "status",
                        "status": "movie_export_item_skipped",
                        "operation": "movie_export_all",
                        "data": {
                            "video_path": str(video_path),
                            "title": title,
                            "year": year,
                            "expected_target": str(expected_target),
                            "index": idx,
                            "total": total,
                        },
                    })
                    broadcast_message_sync({"type": "progress", "value": percent, "operation": "movie_export_all"})
                    continue

                broadcast_message_sync({
                    "type": "status",
                    "status": "movie_export_item_started",
                    "operation": "movie_export_all",
                    "data": {
                        "video_path": str(video_path),
                        "title": title,
                        "year": year,
                        "expected_target": str(expected_target),
                        "index": idx,
                        "total": total,
                    },
                })

                success, exported_path, error = movie_mode_service.export_to_plex(
                    Path(video_path),
                    title,
                    year,
                    overwrite=True,
                )

                active_export_all["done"] += 1
                percent = int(round(active_export_all["done"] * 100 / max(active_export_all["total"], 1)))

                if success:
                    broadcast_message_sync({
                        "type": "status",
                        "status": "movie_export_item_done",
                        "operation": "movie_export_all",
                        "data": {
                            "video_path": str(video_path),
                            "title": title,
                            "year": year,
                            "exported_path": str(exported_path) if exported_path else None,
                            "expected_target": str(expected_target),
                            "index": idx,
                            "total": total,
                        },
                    })
                else:
                    active_export_all["failed"] += 1
                    broadcast_message_sync({
                        "type": "status",
                        "status": "movie_export_item_failed",
                        "operation": "movie_export_all",
                        "data": {
                            "video_path": str(video_path),
                            "title": title,
                            "year": year,
                            "error": error or "Export fehlgeschlagen",
                            "expected_target": str(expected_target),
                            "index": idx,
                            "total": total,
                        },
                    })

                broadcast_message_sync({"type": "progress", "value": percent, "operation": "movie_export_all"})

            broadcast_message_sync({
                "type": "status",
                "status": "movie_export_all_finished",
                "operation": "movie_export_all",
                "data": {
                    "total": total,
                    "skipped": active_export_all.get("skipped", 0),
                    "failed": active_export_all.get("failed", 0),
                },
            })
        except Exception as e:
            logger.exception("Fehler bei Export-All")
            broadcast_message_sync({
                "type": "status",
                "status": "movie_export_all_failed",
                "operation": "movie_export_all",
                "data": {"error": str(e)},
            })
        finally:
            active_export_all["running"] = False
            active_export_all["current"] = None

    thread = threading.Thread(target=run_export_all, daemon=True)
    thread.start()

    return {"success": True, "message": f"Export-All gestartet ({total} Videos).", "total": total}


@app.post("/api/project/delete")
async def delete_projects(request: DeleteProjectsRequest):
    """
    Löscht für ein oder mehrere DV_Import-Projekte die Ordner LowRes und HighRes.

    Akzeptiert als Input sowohl:
    - den Projektordner (DV_Import/<Projekt>)
    - einen Pfad zu einer Datei innerhalb LowRes/HighRes
    """
    if not request.paths:
        raise HTTPException(status_code=400, detail="paths darf nicht leer sein")

    dv_root = config.get_dv_import_root().resolve()

    def _delete_one(raw: str) -> Dict[str, Any]:
        p = Path(raw)

        # Erlaube sowohl Ordner als auch Datei; validiere immer gegen DV_Import
        resolved = _ensure_in_dv_import_root(p)

        # Projektordner ableiten
        project_dir = resolved
        if resolved.is_file():
            parent = resolved.parent
            if parent.name.lower() in ("lowres", "highres"):
                project_dir = parent.parent
            else:
                project_dir = parent
        else:
            # Wenn user direkt LowRes/HighRes gewählt hat -> Parent ist Projekt
            if resolved.name.lower() in ("lowres", "highres"):
                project_dir = resolved.parent
            else:
                project_dir = resolved

        # Safety: Projekt muss innerhalb DV_Import liegen
        _ensure_in_dv_import_root(project_dir)

        deleted = []
        for sub in ("LowRes", "HighRes"):
            d = project_dir / sub
            if d.exists() and d.is_dir():
                _rmtree_force(d)
                deleted.append(str(d))

        # Optional: Projektordner entfernen, falls jetzt leer
        try:
            if project_dir.exists() and project_dir.is_dir() and not any(project_dir.iterdir()):
                project_dir.rmdir()
        except Exception:
            pass

        return {"input": raw, "project_dir": str(project_dir), "deleted": deleted}

    try:
        results = await asyncio.to_thread(lambda: [_delete_one(p) for p in request.paths])
        add_log_entry(f"Projekt(e) gelöscht: {len(results)}", "movie")
        return {"success": True, "results": results}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Fehler beim Löschen von Projekten")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cover/extract")
async def extract_frames(request: CoverExtractRequest):
    """Extrahiert Frames aus einem Video"""
    if not cover_service:
        raise HTTPException(status_code=500, detail="Cover-Service nicht initialisiert")
    
    video_path = Path(request.video_path)
    
    success, frames, error = cover_service.extract_frames(video_path, request.count)
    
    if success:
        # Convert frames to base64
        frame_data = []
        for frame_path in frames:
            try:
                with open(frame_path, 'rb') as f:
                    frame_bytes = f.read()
                    base64_data = base64.b64encode(frame_bytes).decode('utf-8')
                    frame_data.append({
                        "path": str(frame_path),
                        "data": f"data:image/jpeg;base64,{base64_data}"
                    })
            except Exception as e:
                logger.error(f"Fehler beim Lesen von Frame {frame_path}: {e}")
        
        return {"success": True, "frames": frame_data}
    else:
        raise HTTPException(status_code=400, detail=error or "Frame-Extraktion fehlgeschlagen")


@app.post("/api/cover/generate")
async def generate_cover(request: CoverGenerateRequest):
    """Generiert ein Cover aus einem Frame"""
    if not cover_service:
        raise HTTPException(status_code=500, detail="Cover-Service nicht initialisiert")
    
    frame_path = Path(request.frame_path)
    
    # Run in background thread
    def run_generation():
        def progress_cb(value: int):
            broadcast_message_sync({"type": "progress", "value": value, "operation": "cover_generation"})
        
        def status_cb(status: str):
            broadcast_message_sync({"type": "status", "status": status, "operation": "cover_generation"})
        
        success, cover_path, error = cover_service.generate_cover(
            frame_path,
            request.title,
            request.year,
            progress_callback=progress_cb,
            status_callback=status_cb
        )
        
        broadcast_message_sync({
            "type": "cover_generation_finished",
            "success": success,
            "message": error if not success else f"Cover erfolgreich generiert: {cover_path}",
            "cover_path": str(cover_path) if cover_path else None
        })
    
    thread = threading.Thread(target=run_generation, daemon=True)
    thread.start()
    
    return {"success": True, "message": "Cover-Generierung gestartet"}


@app.get("/api/settings")
async def get_settings():
    """Gibt die aktuellen Einstellungen zurück"""
    return {
        "plex_movies_root": str(config.get_plex_movies_root()),
        "dv_import_root": str(config.get_dv_import_root()),
        "ffmpeg_path": str(config.get_ffmpeg_path()),
        "auto_postprocess": config.get("capture.auto_postprocess", False),
        "auto_upscale": config.get("capture.auto_upscale", True),
        "auto_export": config.get("capture.auto_export", False),
        "ui_theme": config.get("ui.theme", "plex"),
        "show_cover_tab": config.get("ui.show_cover_tab", True),
        "update_enabled": config.get("update.enabled", True),
        "update_interval_minutes": config.get("update.interval_minutes", 60),
    }


@app.post("/api/settings")
async def update_settings(settings: Dict[str, Any]):
    """Aktualisiert die Einstellungen"""
    if "plex_movies_root" in settings:
        config.set("paths.plex_movies_root", settings["plex_movies_root"])
    if "dv_import_root" in settings:
        config.set("paths.dv_import_root", settings["dv_import_root"])
    if "ffmpeg_path" in settings:
        config.set("paths.ffmpeg_path", settings["ffmpeg_path"])
    if "auto_postprocess" in settings:
        config.set("capture.auto_postprocess", settings["auto_postprocess"])
    if "auto_upscale" in settings:
        config.set("capture.auto_upscale", settings["auto_upscale"])
    if "auto_export" in settings:
        config.set("capture.auto_export", settings["auto_export"])
    if "ui_theme" in settings:
        config.set("ui.theme", settings["ui_theme"])
    if "show_cover_tab" in settings:
        config.set("ui.show_cover_tab", bool(settings["show_cover_tab"]))
    if "update_enabled" in settings:
        config.set("update.enabled", settings["update_enabled"])
    if "update_interval_minutes" in settings:
        config.set("update.interval_minutes", settings["update_interval_minutes"])
    
    config.save_config()
    return {"success": True, "message": "Einstellungen gespeichert"}


@app.post("/api/chown")
async def apply_chown(request: ChownRequest):
    """Führt sudo chown auf den angegebenen Pfad aus"""
    import subprocess
    import os
    import pwd
    
    path = Path(request.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Pfad nicht gefunden: {path}")
    
    try:
        # Aktuellen Benutzer ermitteln
        current_user = pwd.getpwuid(os.getuid()).pw_name
        
        # sudo chown -R ausführen
        result = subprocess.run(
            # -n: niemals interaktiv nach einem Passwort fragen (wichtig für systemd/Services)
            ["sudo", "-n", "chown", "-R", f"{current_user}:{current_user}", str(path)],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            logger.info(f"chown erfolgreich auf {path}")
            return {"success": True, "message": f"Berechtigungen für {path} geändert"}
        else:
            error_msg = (result.stderr or result.stdout or "Unbekannter Fehler").strip()
            if "password" in error_msg.lower() or "a password is required" in error_msg.lower():
                error_msg = (
                    f"{error_msg}\n"
                    "Hinweis: sudo benötigt ein Passwort. In der Web-UI/als Service geht das nicht interaktiv.\n"
                    "Lösung: sudoers passend konfigurieren oder Berechtigungen einmalig per Shell setzen."
                )
            logger.error(f"chown fehlgeschlagen: {error_msg}")
            raise HTTPException(status_code=500, detail=f"chown fehlgeschlagen: {error_msg}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Timeout bei chown-Ausführung")
    except Exception as e:
        logger.exception("Fehler bei chown")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/fix-config-permissions")
async def fix_config_permissions():
    """Korrigiert die Berechtigungen des Config-Ordners"""
    import subprocess
    import os
    import pwd
    
    try:
        config_dir = config.config_dir
        current_user = pwd.getpwuid(os.getuid()).pw_name
        
        # sudo chown -R auf config-Ordner ausführen
        result = subprocess.run(
            # -n: niemals interaktiv nach einem Passwort fragen (wichtig für systemd/Services)
            ["sudo", "-n", "chown", "-R", f"{current_user}:{current_user}", str(config_dir)],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            logger.info(f"Config-Berechtigungen korrigiert: {config_dir}")
            return {"success": True, "message": f"Berechtigungen für {config_dir} korrigiert"}
        else:
            error_msg = (result.stderr or result.stdout or "Unbekannter Fehler").strip()
            if "password" in error_msg.lower() or "a password is required" in error_msg.lower():
                error_msg = (
                    f"{error_msg}\n"
                    "Hinweis: sudo benötigt ein Passwort. In der Web-UI/als Service geht das nicht interaktiv.\n"
                    "Lösung: sudoers passend konfigurieren oder Berechtigungen einmalig per Shell setzen."
                )
            raise HTTPException(status_code=500, detail=f"chown fehlgeschlagen: {error_msg}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Timeout bei chown-Ausführung")
    except Exception as e:
        logger.exception("Fehler bei Config-Berechtigungen")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/browse")
async def browse_directory(path: str = "/"):
    """Listet Verzeichnisse auf für den Datei-Browser"""
    import os
    
    target_path = Path(path)
    
    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"Pfad nicht gefunden: {path}")
    
    if not target_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Kein Verzeichnis: {path}")
    
    entries = []
    try:
        for entry in sorted(target_path.iterdir()):
            try:
                is_dir = entry.is_dir()
                # Überspringe versteckte Dateien (optional)
                if entry.name.startswith('.'):
                    continue
                    
                entries.append({
                    "name": entry.name,
                    "path": str(entry),
                    "is_dir": is_dir
                })
            except PermissionError:
                continue
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Keine Berechtigung für: {path}")
    
    # Sortiere: Verzeichnisse zuerst
    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    
    return {
        "current_path": str(target_path),
        "parent_path": str(target_path.parent) if target_path != target_path.parent else None,
        "entries": entries
    }


@app.get("/api/logs")
async def get_logs(limit: int = 100, category: str = None):
    """Gibt die letzten Log-Einträge zurück"""
    logs = log_buffer[-limit:]
    
    if category:
        logs = [l for l in logs if l.get("category") == category]
    
    return {
        "logs": logs,
        "total": len(log_buffer)
    }


@app.get("/api/merge/queue")
async def get_merge_queue():
    """Gibt den Status der Merge-Queue zurück"""
    if not capture_service or not capture_service.capture_engine:
        return {
            "pending_count": 0,
            "current_job": None,
            "completed_count": 0,
            "jobs": []
        }
    
    return capture_service.capture_engine.get_merge_queue_status()


@app.post("/api/logs/clear")
async def clear_logs():
    """Löscht alle Logs"""
    global log_buffer
    log_buffer = []
    return {"status": "ok"}


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket-Endpoint für Live-Updates"""
    await websocket.accept()
    websocket_connections.append(websocket)
    
    # Beim Verbinden aktuellen Status pushen, damit Buttons/Titel/Jahr sofort stimmen
    try:
        await websocket.send_json({
            "type": "status",
            "status": "capture_started" if (capture_service and capture_service.is_capturing()) else "capture_stopped",
            "data": active_capture
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
        if websocket in websocket_connections:
            websocket_connections.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket-Fehler: {e}")
        if websocket in websocket_connections:
            websocket_connections.remove(websocket)
    finally:
        if websocket in websocket_connections:
            websocket_connections.remove(websocket)


@app.on_event("startup")
async def on_startup():
    """Merkt sich die Event-Loop für thread-sichere Broadcasts"""
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()
    await _start_update_scheduler()
    if update_manager:
        try:
            result = await asyncio.to_thread(update_manager._ensure_service_enabled)
            if not result.get("success", False):
                add_log_entry(f"Autostart konnte nicht gesetzt werden: {result.get('error')}", "update")
        except Exception as e:
            logger.error(f"Fehler beim Aktivieren des Autostarts: {e}")
            add_log_entry(f"Fehler beim Aktivieren des Autostarts: {e}", "update")


def get_html_interface() -> str:
    """Gibt das HTML-Interface zurück"""
    try:
        web_dir = Path(__file__).resolve().parent / "web"
        html_path = web_dir / "index.html"
        css_path = web_dir / "index.css"
        js_path = web_dir / "index.js"

        html = html_path.read_text(encoding="utf-8")
        css = css_path.read_text(encoding="utf-8")
        js = js_path.read_text(encoding="utf-8")

        # Inline CSS/JS, damit wir ohne Static-Hosting auskommen.
        style_tag = f"<style>\n{css}\n</style>\n"
        script_tag = f"<script>\n{js}\n</script>\n"

        if "</head>" in html:
            html = html.replace("</head>", f"{style_tag}</head>", 1)
        else:
            html = f"{style_tag}\n{html}"

        if "</body>" in html:
            html = html.replace("</body>", f"{script_tag}</body>", 1)
        else:
            html = f"{html}\n{script_tag}"

        return html
    except Exception as e:
        logger.exception("Konnte Web-Interface nicht laden")
        return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>DV2Plex</title>
  <style>
    body {{ font-family: system-ui, sans-serif; padding: 24px; background: #111; color: #eee; }}
    pre {{ background: #1b1b1b; padding: 12px; border-radius: 8px; overflow: auto; }}
  </style>
</head>
<body>
  <h2>Web-Interface konnte nicht geladen werden</h2>
  <p>Prüfe ob <code>dv2plex/web/index.html</code>, <code>index.css</code> und <code>index.js</code> vorhanden sind.</p>
  <pre>{str(e)}</pre>
</body>
</html>"""


def main():
    """Startet den Webserver"""
    setup_services()
    
    logger.info("DV2Plex Web-Server wird gestartet...")
    logger.info("Öffne http://0.0.0.0:5000 im Browser")
    logger.info("Für SSH-Zugriff: ssh -L 5000:localhost:5000 user@host")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5000,
        log_level="info"
    )


if __name__ == "__main__":
    main()

