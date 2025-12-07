"""
Web-App für DV2Plex - FastAPI-basierte Web-UI
"""

import sys
import logging
import base64
import asyncio
import threading
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
    parse_movie_folder_name
)

# Try to import QImage for preview conversion
try:
    from PySide6.QtGui import QImage
    QIMAGE_AVAILABLE = True
except ImportError:
    QImage = None
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

# WebSocket connections for broadcasting
websocket_connections: List[WebSocket] = []

# Active operations
active_capture: Optional[Dict[str, Any]] = None
active_postprocessing: Optional[Dict[str, Any]] = None


def setup_services():
    """Initialisiert die Services"""
    global capture_service, postprocessing_service, movie_mode_service, cover_service
    
    def log_callback(msg: str):
        logger.info(msg)
        broadcast_message_sync({"type": "log", "message": msg})
    
    capture_service = CaptureService(config, log_callback=log_callback)
    postprocessing_service = PostprocessingService(config, log_callback=log_callback)
    movie_mode_service = MovieModeService(config, log_callback=log_callback)
    cover_service = CoverService(config, log_callback=log_callback)


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
    
    # Try to get the event loop
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        # No event loop in this thread, create a new one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # Check if loop is running
    if loop.is_running():
        # Schedule the coroutine in the running loop
        for ws in websocket_connections[:]:
            try:
                asyncio.run_coroutine_threadsafe(ws.send_json(message), loop)
            except Exception as e:
                logger.error(f"Fehler beim Senden an WebSocket: {e}")
                if ws in websocket_connections:
                    websocket_connections.remove(ws)
    else:
        # Run the coroutine directly
        try:
            loop.run_until_complete(broadcast_message(message))
        except Exception as e:
            logger.error(f"Fehler bei WebSocket-Broadcast: {e}")


def qimage_to_base64(image) -> Optional[str]:
    """Konvertiert QImage zu Base64-kodiertem JPEG"""
    if not QIMAGE_AVAILABLE or image is None:
        return None
    
    try:
        # Convert QImage to JPEG bytes
        from io import BytesIO
        import io
        ba = io.BytesIO()
        image.save(ba, format='JPEG')
        jpeg_bytes = ba.getvalue()
        return base64.b64encode(jpeg_bytes).decode('utf-8')
    except Exception as e:
        logger.error(f"Fehler bei QImage-Konvertierung: {e}")
        return None


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


class CoverExtractRequest(BaseModel):
    video_path: str
    count: int = 4


class CoverGenerateRequest(BaseModel):
    frame_path: str
    title: str
    year: Optional[str] = None


# Preview callback for capture
def preview_callback(image):
    """Callback für Preview-Frames während Capture"""
    if QIMAGE_AVAILABLE and image:
        base64_image = qimage_to_base64(image)
        if base64_image:
            broadcast_message_sync({
                "type": "preview_frame",
                "data": f"data:image/jpeg;base64,{base64_image}"
            })


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
        "device_available": capture_service.get_device() is not None if capture_service else False
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
    for video_path, title, year in videos:
        result.append({
            "path": str(video_path),
            "title": title,
            "year": year,
            "display": f"{title} ({year})" if year else f"{title} - {video_path.name}"
        })
    return {"videos": result}


@app.get("/api/cover/videos")
async def get_cover_videos():
    """Gibt Liste der verfügbaren Videos für Cover-Generierung zurück"""
    videos = find_available_videos(config)
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
            await broadcast_message({"type": "status", "status": "capture_started"})
            return {"success": True, "message": "Capture gestartet"}
        else:
            error_msg = error or "Capture konnte nicht gestartet werden"
            logger.error(f"Capture-Fehler: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        error_msg = f"Unerwarteter Fehler beim Starten der Aufnahme: {str(e)}"
        logger.exception("Fehler in start_capture")
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/api/capture/stop")
async def stop_capture():
    """Stoppt die laufende Capture-Session"""
    global active_capture
    
    if not capture_service:
        raise HTTPException(status_code=500, detail="Capture-Service nicht initialisiert")
    
    if not capture_service.is_capturing():
        raise HTTPException(status_code=400, detail="Kein Capture aktiv")
    
    success = capture_service.stop_capture()
    if success:
        active_capture = None
        await broadcast_message({"type": "status", "status": "capture_stopped"})
        return {"success": True, "message": "Capture gestoppt"}
    else:
        raise HTTPException(status_code=400, detail="Capture konnte nicht gestoppt werden")


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


@app.post("/api/postprocess/process")
async def process_movie(request: PostprocessRequest):
    """Startet Postprocessing für einen Film"""
    global active_postprocessing
    
    if not postprocessing_service:
        raise HTTPException(status_code=500, detail="Postprocessing-Service nicht initialisiert")
    
    if postprocessing_service.is_running():
        raise HTTPException(status_code=400, detail="Postprocessing läuft bereits")
    
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
        
        success, message = postprocessing_service.process_movie(
            movie_dir,
            request.profile_name,
            progress_callback=progress_cb,
            status_callback=status_cb
        )
        
        active_postprocessing = None
        broadcast_message_sync({
            "type": "postprocessing_finished",
            "success": success,
            "message": message
        })
    
    thread = threading.Thread(target=run_postprocessing, daemon=True)
    thread.start()
    
    return {"success": True, "message": "Postprocessing gestartet"}


@app.post("/api/movie/merge")
async def merge_videos(request: MergeRequest):
    """Merged mehrere Videos zu einem Film"""
    if not movie_mode_service:
        raise HTTPException(status_code=500, detail="Movie-Mode-Service nicht initialisiert")
    
    video_paths = [Path(p) for p in request.video_paths]
    
    success, merged_file, error = movie_mode_service.merge_videos(
        video_paths,
        request.title,
        request.year
    )
    
    if success and merged_file:
        # Export to Plex
        export_success, exported_path, export_error = movie_mode_service.export_to_plex(
            merged_file,
            request.title,
            request.year
        )
        
        # Clean up temp file
        try:
            merged_file.unlink()
        except:
            pass
        
        if export_success:
            return {"success": True, "message": f"Videos erfolgreich gemerged und exportiert: {exported_path}"}
        else:
            return {"success": False, "message": export_error or "Export fehlgeschlagen"}
    else:
        raise HTTPException(status_code=400, detail=error or "Merge fehlgeschlagen")


@app.post("/api/movie/export")
async def export_video(request: ExportRequest):
    """Exportiert ein einzelnes Video nach PlexMovies"""
    if not movie_mode_service:
        raise HTTPException(status_code=500, detail="Movie-Mode-Service nicht initialisiert")
    
    video_path = Path(request.video_path)
    
    success, exported_path, error = movie_mode_service.export_to_plex(
        video_path,
        request.title,
        request.year
    )
    
    if success:
        return {"success": True, "message": f"Video erfolgreich exportiert: {exported_path}"}
    else:
        raise HTTPException(status_code=400, detail=error or "Export fehlgeschlagen")


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
    
    config.save_config()
    return {"success": True, "message": "Einstellungen gespeichert"}


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket-Endpoint für Live-Updates"""
    await websocket.accept()
    websocket_connections.append(websocket)
    
    try:
        while True:
            # Keep connection alive and wait for messages
            data = await websocket.receive_text()
            # Echo back or handle commands
            await websocket.send_json({"type": "pong", "data": data})
    except WebSocketDisconnect:
        websocket_connections.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket-Fehler: {e}")
        if websocket in websocket_connections:
            websocket_connections.remove(websocket)


def get_html_interface() -> str:
    """Gibt das HTML-Interface zurück"""
    return """<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DV2Plex - MiniDV Digitalisierung</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --plex-gold: #E5A00D;
            --plex-gold-light: #F5B82E;
            --plex-gold-dark: #CC8A00;
            --plex-orange: #CC7B19;
            --plex-bg-dark: #1F1F1F;
            --plex-bg-darker: #121212;
            --plex-surface: #282828;
            --plex-text: #EAEAEA;
            --plex-text-secondary: #999999;
            --glass-bg: rgba(40, 40, 40, 0.4);
            --glass-border: rgba(255, 255, 255, 0.08);
            --glass-highlight: rgba(255, 255, 255, 0.15);
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: 
                radial-gradient(ellipse at top left, rgba(229, 160, 13, 0.15) 0%, transparent 50%),
                radial-gradient(ellipse at bottom right, rgba(204, 123, 25, 0.1) 0%, transparent 50%),
                linear-gradient(180deg, #0d0d0d 0%, #1a1a1a 50%, #121212 100%);
            background-attachment: fixed;
            color: var(--plex-text);
            min-height: 100vh;
            padding: 30px;
        }
        
        /* Animated background orbs */
        body::before {
            content: '';
            position: fixed;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: 
                radial-gradient(circle at 20% 80%, rgba(229, 160, 13, 0.08) 0%, transparent 25%),
                radial-gradient(circle at 80% 20%, rgba(204, 123, 25, 0.06) 0%, transparent 25%),
                radial-gradient(circle at 40% 40%, rgba(229, 160, 13, 0.04) 0%, transparent 30%);
            animation: float 20s ease-in-out infinite;
            pointer-events: none;
            z-index: -1;
        }
        
        @keyframes float {
            0%, 100% { transform: translate(0, 0) rotate(0deg); }
            25% { transform: translate(2%, 2%) rotate(1deg); }
            50% { transform: translate(-1%, 3%) rotate(-1deg); }
            75% { transform: translate(1%, -2%) rotate(0.5deg); }
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: linear-gradient(135deg, 
                rgba(50, 50, 50, 0.6) 0%, 
                rgba(30, 30, 30, 0.8) 50%,
                rgba(40, 40, 40, 0.6) 100%);
            border-radius: 24px;
            padding: 30px;
            box-shadow: 
                0 25px 80px rgba(0, 0, 0, 0.6),
                0 10px 30px rgba(0, 0, 0, 0.4),
                inset 0 1px 0 rgba(255, 255, 255, 0.1),
                inset 0 -1px 0 rgba(0, 0, 0, 0.3);
            backdrop-filter: blur(40px) saturate(180%);
            -webkit-backdrop-filter: blur(40px) saturate(180%);
            border: 1px solid rgba(255, 255, 255, 0.08);
            position: relative;
            overflow: hidden;
        }
        
        /* Glass shine effect */
        .container::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 1px;
            background: linear-gradient(90deg, 
                transparent 0%, 
                rgba(255, 255, 255, 0.3) 20%,
                rgba(255, 255, 255, 0.5) 50%,
                rgba(255, 255, 255, 0.3) 80%,
                transparent 100%);
        }
        
        .logo-container {
            text-align: center;
            margin-bottom: 30px;
        }
        
        h1 {
            display: inline-flex;
            align-items: center;
            gap: 15px;
            font-size: 2.2em;
            font-weight: 700;
            background: linear-gradient(135deg, var(--plex-gold-light) 0%, var(--plex-gold) 50%, var(--plex-orange) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            text-shadow: none;
            filter: drop-shadow(0 2px 10px rgba(229, 160, 13, 0.3));
        }
        
        h1::before {
            content: '▶';
            font-size: 0.8em;
            -webkit-text-fill-color: var(--plex-gold);
        }
        
        .tabs {
            display: flex;
            gap: 12px;
            margin-bottom: 25px;
            flex-wrap: wrap;
            padding: 8px;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 16px;
            backdrop-filter: blur(10px);
        }
        
        .tab {
            padding: 14px 28px;
            background: transparent;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            color: var(--plex-text-secondary);
            font-weight: 600;
            font-size: 14px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
        }
        
        .tab::before {
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(135deg, var(--plex-gold), var(--plex-orange));
            opacity: 0;
            transition: opacity 0.3s;
            border-radius: 12px;
        }
        
        .tab:hover {
            color: var(--plex-text);
            background: rgba(255, 255, 255, 0.05);
        }
        
        .tab.active {
            color: #000000;
            font-weight: 700;
        }
        
        .tab.active::before {
            opacity: 1;
        }
        
        .tab span {
            position: relative;
            z-index: 1;
        }
        
        .tab-content {
            display: none;
            padding: 25px;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 16px;
            backdrop-filter: blur(10px);
            border: 1px solid var(--glass-border);
            animation: fadeIn 0.3s ease;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .tab-content.active {
            display: block;
        }
        
        .form-group {
            margin-bottom: 18px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            color: var(--plex-text);
            font-weight: 600;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        input[type="text"], input[type="number"], select {
            width: 100%;
            padding: 14px 16px;
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            color: var(--plex-text);
            font-size: 15px;
            font-family: inherit;
            transition: all 0.3s;
            backdrop-filter: blur(10px);
        }
        
        input:focus, select:focus {
            border-color: var(--plex-gold);
            background: rgba(0, 0, 0, 0.5);
            outline: none;
            box-shadow: 0 0 0 3px rgba(229, 160, 13, 0.15), 0 0 20px rgba(229, 160, 13, 0.1);
        }
        
        input::placeholder {
            color: var(--plex-text-secondary);
        }
        
        select {
            cursor: pointer;
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23E5A00D' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 16px center;
            padding-right: 40px;
        }
        
        button {
            padding: 14px 28px;
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.1), rgba(255, 255, 255, 0.05));
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            color: var(--plex-text);
            font-weight: 600;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            backdrop-filter: blur(10px);
            position: relative;
            overflow: hidden;
        }
        
        button::before {
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(135deg, var(--plex-gold), var(--plex-orange));
            opacity: 0;
            transition: opacity 0.3s;
        }
        
        button:hover:not(:disabled) {
            border-color: var(--plex-gold);
            box-shadow: 0 0 20px rgba(229, 160, 13, 0.2), 0 5px 15px rgba(0, 0, 0, 0.3);
            transform: translateY(-2px);
        }
        
        button:hover:not(:disabled)::before {
            opacity: 0.15;
        }
        
        button:active:not(:disabled) {
            transform: translateY(0);
        }
        
        button:disabled {
            background: rgba(30, 30, 30, 0.5);
            color: #555;
            cursor: not-allowed;
            border-color: transparent;
        }
        
        button span {
            position: relative;
            z-index: 1;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, var(--plex-gold), var(--plex-orange));
            color: #000;
            border: none;
            font-weight: 700;
        }
        
        .btn-primary:hover:not(:disabled) {
            box-shadow: 0 0 30px rgba(229, 160, 13, 0.4), 0 8px 25px rgba(0, 0, 0, 0.4);
        }
        
        .preview-container {
            background: linear-gradient(135deg, rgba(0, 0, 0, 0.6), rgba(20, 20, 20, 0.4));
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            padding: 20px;
            text-align: center;
            min-height: 400px;
            display: flex;
            align-items: center;
            justify-content: center;
            backdrop-filter: blur(20px);
            position: relative;
            overflow: hidden;
        }
        
        .preview-container::before {
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(135deg, rgba(229, 160, 13, 0.03), transparent);
            pointer-events: none;
        }
        
        .preview-container img {
            max-width: 100%;
            max-height: 500px;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
        }
        
        .list-container {
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            padding: 12px;
            max-height: 400px;
            overflow-y: auto;
            backdrop-filter: blur(10px);
        }
        
        .list-container::-webkit-scrollbar {
            width: 8px;
        }
        
        .list-container::-webkit-scrollbar-track {
            background: rgba(0, 0, 0, 0.2);
            border-radius: 4px;
        }
        
        .list-container::-webkit-scrollbar-thumb {
            background: var(--plex-gold);
            border-radius: 4px;
        }
        
        .list-item {
            padding: 14px 16px;
            margin: 6px 0;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid transparent;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            font-weight: 500;
        }
        
        .list-item:hover {
            background: rgba(229, 160, 13, 0.1);
            border-color: rgba(229, 160, 13, 0.3);
            transform: translateX(4px);
        }
        
        .list-item.selected {
            background: linear-gradient(135deg, rgba(229, 160, 13, 0.2), rgba(204, 123, 25, 0.15));
            border-color: var(--plex-gold);
            box-shadow: 0 0 20px rgba(229, 160, 13, 0.15);
        }
        
        .progress-bar {
            width: 100%;
            height: 32px;
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            overflow: hidden;
            margin: 15px 0;
            backdrop-filter: blur(10px);
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--plex-gold), var(--plex-orange), var(--plex-gold-light));
            background-size: 200% 100%;
            animation: shimmer 2s linear infinite;
            transition: width 0.3s;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #000;
            font-weight: 700;
            font-size: 13px;
            border-radius: 14px;
        }
        
        @keyframes shimmer {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }
        
        .log-container {
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 16px;
            max-height: 200px;
            overflow-y: auto;
            font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
            font-size: 12px;
            line-height: 1.6;
            color: var(--plex-text-secondary);
            backdrop-filter: blur(10px);
        }
        
        .frame-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 18px;
            margin: 25px 0;
        }
        
        .frame-item {
            background: rgba(0, 0, 0, 0.4);
            border: 2px solid var(--glass-border);
            border-radius: 14px;
            padding: 12px;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            backdrop-filter: blur(10px);
        }
        
        .frame-item:hover {
            border-color: rgba(229, 160, 13, 0.5);
            transform: scale(1.02);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
        }
        
        .frame-item.selected {
            border-color: var(--plex-gold);
            border-width: 3px;
            box-shadow: 0 0 30px rgba(229, 160, 13, 0.3);
        }
        
        .frame-item img {
            width: 100%;
            border-radius: 8px;
        }
        
        .status {
            padding: 14px 18px;
            margin: 15px 0;
            border-radius: 12px;
            background: rgba(229, 160, 13, 0.08);
            border: 1px solid rgba(229, 160, 13, 0.2);
            backdrop-filter: blur(10px);
            font-weight: 500;
        }
        
        .error {
            background: rgba(220, 53, 69, 0.1);
            border: 1px solid rgba(220, 53, 69, 0.3);
            color: #ff6b7a;
        }
        
        .success {
            background: rgba(40, 167, 69, 0.1);
            border: 1px solid rgba(40, 167, 69, 0.3);
            color: #5dd879;
        }
        
        /* Checkbox styling */
        input[type="checkbox"] {
            appearance: none;
            width: 20px;
            height: 20px;
            background: rgba(0, 0, 0, 0.4);
            border: 2px solid var(--glass-border);
            border-radius: 6px;
            cursor: pointer;
            position: relative;
            vertical-align: middle;
            margin-right: 8px;
            transition: all 0.3s;
        }
        
        input[type="checkbox"]:checked {
            background: linear-gradient(135deg, var(--plex-gold), var(--plex-orange));
            border-color: var(--plex-gold);
        }
        
        input[type="checkbox"]:checked::after {
            content: '✓';
            position: absolute;
            color: #000;
            font-weight: 700;
            font-size: 14px;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
        }
        
        /* Grid layout for capture */
        .capture-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 25px;
        }
        
        @media (max-width: 900px) {
            .capture-grid {
                grid-template-columns: 1fr;
            }
        }
        
        /* Button groups */
        .button-group {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        
        .button-group button {
            flex: 1;
            min-width: 120px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo-container">
            <h1>DV2Plex</h1>
        </div>
        
        <div class="tabs">
            <div class="tab active" onclick="switchTab('capture')"><span>Digitalisieren</span></div>
            <div class="tab" onclick="switchTab('postprocess')"><span>Upscaling</span></div>
            <div class="tab" onclick="switchTab('movie')"><span>Movie Mode</span></div>
            <div class="tab" onclick="switchTab('cover')"><span>Video Cover</span></div>
        </div>
        
        <!-- Capture Tab -->
        <div id="capture" class="tab-content active">
            <div class="capture-grid">
                <div>
                    <div class="preview-container" id="preview">
                        <div style="color: var(--plex-text-secondary);">▶ Kein Preview</div>
                    </div>
                </div>
                <div>
                    <div class="form-group">
                        <label>Titel</label>
                        <input type="text" id="capture-title" placeholder="Film-Titel eingeben...">
                    </div>
                    <div class="form-group">
                        <label>Jahr</label>
                        <input type="text" id="capture-year" placeholder="2024">
                    </div>
                    <div class="form-group">
                        <label style="display: flex; align-items: center; cursor: pointer;">
                            <input type="checkbox" id="auto-rewind" checked>
                            <span>Automatisches Rewind/Play</span>
                        </label>
                    </div>
                    <div class="form-group button-group">
                        <button class="btn-primary" onclick="startCapture()" id="capture-start-btn">
                            <span>▶ Aufnahme starten</span>
                        </button>
                        <button onclick="stopCapture()" id="capture-stop-btn" disabled>
                            <span>■ Stoppen</span>
                        </button>
                    </div>
                    <div class="form-group button-group">
                        <button onclick="rewindCamera()"><span>⏪ Zurück</span></button>
                        <button onclick="playCamera()"><span>▶ Play</span></button>
                        <button onclick="pauseCamera()"><span>⏸ Pause</span></button>
                    </div>
                    <div class="status" id="capture-status">Bereit zum Digitalisieren.</div>
                </div>
            </div>
        </div>
        
        <!-- Postprocess Tab -->
        <div id="postprocess" class="tab-content">
            <div class="form-group">
                <label>Upscaling-Profil</label>
                <select id="profile-select">
                    <!-- Wird dynamisch geladen -->
                </select>
            </div>
            <div class="list-container" id="postprocess-list"></div>
            <div class="form-group button-group" style="margin-top: 18px;">
                <button class="btn-primary" onclick="processSelected()">
                    <span>Ausgewählten verarbeiten</span>
                </button>
                <button onclick="processAll()"><span>Alle verarbeiten</span></button>
            </div>
            <div class="progress-bar" id="postprocess-progress" style="display: none;">
                <div class="progress-fill" id="postprocess-progress-fill" style="width: 0%">0%</div>
            </div>
            <div class="status" id="postprocess-status">Bereit für Upscaling.</div>
            <div class="log-container" id="postprocess-log"></div>
        </div>
        
        <!-- Movie Mode Tab -->
        <div id="movie" class="tab-content">
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                <div class="form-group">
                    <label>Titel</label>
                    <input type="text" id="movie-title" placeholder="Film-Titel eingeben...">
                </div>
                <div class="form-group">
                    <label>Jahr</label>
                    <input type="text" id="movie-year" placeholder="2024">
                </div>
            </div>
            <div class="list-container" id="movie-list"></div>
            <div class="form-group button-group" style="margin-top: 18px;">
                <button class="btn-primary" onclick="mergeVideos()" id="merge-btn" disabled>
                    <span>Videos mergen</span>
                </button>
                <button onclick="exportVideo()" id="export-btn" disabled>
                    <span>Nach Plex exportieren</span>
                </button>
            </div>
            <div class="status" id="movie-status">Wähle Videos zum Mergen oder Exportieren.</div>
            <div class="log-container" id="movie-log"></div>
        </div>
        
        <!-- Cover Tab -->
        <div id="cover" class="tab-content">
            <div class="list-container" id="cover-video-list"></div>
            <div class="form-group button-group" style="margin-top: 18px;">
                <button class="btn-primary" onclick="extractFrames()" id="extract-frames-btn" disabled>
                    <span>Frames extrahieren</span>
                </button>
            </div>
            <div class="frame-grid" id="frame-grid"></div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                <div class="form-group">
                    <label>Titel</label>
                    <input type="text" id="cover-title" placeholder="Film-Titel eingeben...">
                </div>
                <div class="form-group">
                    <label>Jahr</label>
                    <input type="text" id="cover-year" placeholder="2024">
                </div>
            </div>
            <div class="form-group button-group">
                <button class="btn-primary" onclick="generateCover()" id="generate-cover-btn" disabled>
                    <span>🎬 Cover generieren</span>
                </button>
            </div>
            <div class="progress-bar" id="cover-progress" style="display: none;">
                <div class="progress-fill" id="cover-progress-fill" style="width: 0%">0%</div>
            </div>
            <div class="status" id="cover-status">Wähle ein Video und extrahiere Frames.</div>
            <div class="log-container" id="cover-log"></div>
        </div>
    </div>
    
    <script>
        let ws = null;
        let selectedPostprocessMovie = null;
        let selectedMovieVideos = [];
        let selectedCoverVideo = null;
        let extractedFrames = [];
        let selectedFrameIndex = null;
        
        // WebSocket connection
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleWebSocketMessage(data);
            };
            
            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
            
            ws.onclose = () => {
                console.log('WebSocket closed, reconnecting...');
                setTimeout(connectWebSocket, 3000);
            };
        }
        
        function handleWebSocketMessage(data) {
            switch(data.type) {
                case 'preview_frame':
                    updatePreview(data.data);
                    break;
                case 'progress':
                    updateProgress(data.value, data.operation);
                    break;
                case 'status':
                    updateStatus(data.status, data.operation);
                    break;
                case 'log':
                    addLog(data.message, data.operation);
                    break;
                case 'postprocessing_finished':
                    handlePostprocessingFinished(data);
                    break;
                case 'cover_generation_finished':
                    handleCoverGenerationFinished(data);
                    break;
            }
        }
        
        function updatePreview(imageData) {
            const preview = document.getElementById('preview');
            preview.innerHTML = `<img src="${imageData}" alt="Preview">`;
        }
        
        function updateProgress(value, operation) {
            if (operation === 'postprocessing') {
                const progress = document.getElementById('postprocess-progress');
                const fill = document.getElementById('postprocess-progress-fill');
                progress.style.display = 'block';
                fill.style.width = value + '%';
                fill.textContent = value + '%';
            } else if (operation === 'cover_generation') {
                const progress = document.getElementById('cover-progress');
                const fill = document.getElementById('cover-progress-fill');
                progress.style.display = 'block';
                fill.style.width = value + '%';
                fill.textContent = value + '%';
            }
        }
        
        function updateStatus(status, operation) {
            // Update status displays
        }
        
        function addLog(message, operation) {
            const logId = operation === 'postprocessing' ? 'postprocess-log' :
                          operation === 'cover_generation' ? 'cover-log' : 'movie-log';
            const log = document.getElementById(logId);
            if (log) {
                log.innerHTML += message + '\\n';
                log.scrollTop = log.scrollHeight;
            }
        }
        
        function handlePostprocessingFinished(data) {
            document.getElementById('postprocess-progress').style.display = 'none';
            const status = document.getElementById('postprocess-status');
            status.textContent = data.success ? 'Erfolgreich!' : 'Fehler!';
            status.className = 'status ' + (data.success ? 'success' : 'error');
            loadPostprocessList();
        }
        
        function handleCoverGenerationFinished(data) {
            document.getElementById('cover-progress').style.display = 'none';
            const status = document.getElementById('cover-status');
            status.textContent = data.success ? 'Erfolgreich!' : 'Fehler!';
            status.className = 'status ' + (data.success ? 'success' : 'error');
            if (data.message) {
                addLog(data.message, 'cover_generation');
            }
        }
        
        // Tab switching
        function switchTab(tabName) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById(tabName).classList.add('active');
            
            if (tabName === 'postprocess') {
                loadPostprocessList();
            } else if (tabName === 'movie') {
                loadMovieList();
            } else if (tabName === 'cover') {
                loadCoverVideoList();
            }
        }
        
        // Capture functions
        async function startCapture() {
            const title = document.getElementById('capture-title').value;
            const year = document.getElementById('capture-year').value;
            const autoRewind = document.getElementById('auto-rewind').checked;
            
            if (!title || !year) {
                alert('Bitte Titel und Jahr eingeben');
                return;
            }
            
            try {
                const response = await fetch('/api/capture/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({title, year, auto_rewind_play: autoRewind})
                });
                
                const data = await response.json();
                if (response.ok) {
                    document.getElementById('capture-start-btn').disabled = true;
                    document.getElementById('capture-stop-btn').disabled = false;
                    document.getElementById('capture-status').textContent = 'Aufnahme läuft...';
                } else {
                    alert(data.detail || 'Fehler beim Starten der Aufnahme');
                }
            } catch (error) {
                alert('Fehler: ' + error.message);
            }
        }
        
        async function stopCapture() {
            try {
                const response = await fetch('/api/capture/stop', {method: 'POST'});
                const data = await response.json();
                if (response.ok) {
                    document.getElementById('capture-start-btn').disabled = false;
                    document.getElementById('capture-stop-btn').disabled = true;
                    document.getElementById('capture-status').textContent = 'Aufnahme beendet.';
                } else {
                    alert(data.detail || 'Fehler beim Stoppen der Aufnahme');
                }
            } catch (error) {
                alert('Fehler: ' + error.message);
            }
        }
        
        async function rewindCamera() {
            await fetch('/api/capture/rewind', {method: 'POST'});
        }
        
        async function playCamera() {
            await fetch('/api/capture/play', {method: 'POST'});
        }
        
        async function pauseCamera() {
            await fetch('/api/capture/pause', {method: 'POST'});
        }
        
        // Load upscaling profiles
        async function loadUpscalingProfiles() {
            try {
                const response = await fetch('/api/upscaling/profiles');
                const data = await response.json();
                const select = document.getElementById('profile-select');
                select.innerHTML = '';
                
                data.profiles.forEach(profile => {
                    const option = document.createElement('option');
                    option.value = profile;
                    option.textContent = profile;
                    if (profile === data.default_profile) {
                        option.selected = true;
                    }
                    select.appendChild(option);
                });
            } catch (error) {
                console.error('Fehler beim Laden der Profile:', error);
                // Fallback
                const select = document.getElementById('profile-select');
                select.innerHTML = '<option value="realesrgan_2x">realesrgan_2x</option>';
            }
        }
        
        // Postprocess functions
        async function loadPostprocessList() {
            try {
                const response = await fetch('/api/postprocess/list');
                const data = await response.json();
                const list = document.getElementById('postprocess-list');
                list.innerHTML = '';
                
                if (data.movies.length === 0) {
                    list.innerHTML = '<div class="list-item">Keine offenen Projekte 🎉</div>';
                    return;
                }
                
                data.movies.forEach(movie => {
                    const item = document.createElement('div');
                    item.className = 'list-item';
                    item.textContent = movie.display;
                    item.onclick = () => {
                        document.querySelectorAll('#postprocess-list .list-item').forEach(i => i.classList.remove('selected'));
                        item.classList.add('selected');
                        selectedPostprocessMovie = movie.path;
                    };
                    list.appendChild(item);
                });
            } catch (error) {
                console.error('Fehler beim Laden der Liste:', error);
            }
        }
        
        async function processSelected() {
            if (!selectedPostprocessMovie) {
                alert('Bitte einen Film auswählen');
                return;
            }
            
            const profile = document.getElementById('profile-select').value;
            
            try {
                const response = await fetch('/api/postprocess/process', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({movie_dir: selectedPostprocessMovie, profile_name: profile})
                });
                
                const data = await response.json();
                if (response.ok) {
                    document.getElementById('postprocess-status').textContent = 'Postprocessing gestartet...';
                    document.getElementById('postprocess-log').innerHTML = '';
                } else {
                    alert(data.detail || 'Fehler beim Starten des Postprocessings');
                }
            } catch (error) {
                alert('Fehler: ' + error.message);
            }
        }
        
        async function processAll() {
            // Similar to processSelected but for all movies
            const response = await fetch('/api/postprocess/list');
            const data = await response.json();
            if (data.movies.length === 0) {
                alert('Keine Filme zu verarbeiten');
                return;
            }
            
            if (!confirm(`Es werden ${data.movies.length} Filme verarbeitet. Fortfahren?`)) {
                return;
            }
            
            const profile = document.getElementById('profile-select').value;
            for (const movie of data.movies) {
                await fetch('/api/postprocess/process', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({movie_dir: movie.path, profile_name: profile})
                });
                await new Promise(resolve => setTimeout(resolve, 1000));
            }
        }
        
        // Movie Mode functions
        async function loadMovieList() {
            try {
                const response = await fetch('/api/movie/list');
                const data = await response.json();
                const list = document.getElementById('movie-list');
                list.innerHTML = '';
                
                data.videos.forEach(video => {
                    const item = document.createElement('div');
                    item.className = 'list-item';
                    item.textContent = video.display;
                    item.onclick = () => {
                        if (item.classList.contains('selected')) {
                            item.classList.remove('selected');
                            selectedMovieVideos = selectedMovieVideos.filter(v => v !== video.path);
                        } else {
                            item.classList.add('selected');
                            selectedMovieVideos.push(video.path);
                        }
                        updateMovieButtons();
                    };
                    list.appendChild(item);
                });
            } catch (error) {
                console.error('Fehler beim Laden der Liste:', error);
            }
        }
        
        function updateMovieButtons() {
            const mergeBtn = document.getElementById('merge-btn');
            const exportBtn = document.getElementById('export-btn');
            mergeBtn.disabled = selectedMovieVideos.length < 2;
            exportBtn.disabled = selectedMovieVideos.length !== 1;
        }
        
        async function mergeVideos() {
            if (selectedMovieVideos.length < 2) {
                alert('Bitte mindestens 2 Videos auswählen');
                return;
            }
            
            const title = document.getElementById('movie-title').value;
            const year = document.getElementById('movie-year').value;
            
            if (!title || !year) {
                alert('Bitte Titel und Jahr eingeben');
                return;
            }
            
            if (!confirm(`Es werden ${selectedMovieVideos.length} Videos zu '${title} (${year})' gemerged. Fortfahren?`)) {
                return;
            }
            
            try {
                const response = await fetch('/api/movie/merge', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({video_paths: selectedMovieVideos, title, year})
                });
                
                const data = await response.json();
                if (response.ok) {
                    document.getElementById('movie-status').textContent = 'Erfolgreich!';
                    document.getElementById('movie-status').className = 'status success';
                    addLog(data.message, 'movie');
                    loadMovieList();
                } else {
                    alert(data.detail || 'Fehler beim Mergen');
                }
            } catch (error) {
                alert('Fehler: ' + error.message);
            }
        }
        
        async function exportVideo() {
            if (selectedMovieVideos.length !== 1) {
                alert('Bitte genau ein Video auswählen');
                return;
            }
            
            if (!confirm('Video wird nach PlexMovies exportiert. Fortfahren?')) {
                return;
            }
            
            try {
                const response = await fetch('/api/movie/export', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({video_path: selectedMovieVideos[0]})
                });
                
                const data = await response.json();
                if (response.ok) {
                    document.getElementById('movie-status').textContent = 'Erfolgreich!';
                    document.getElementById('movie-status').className = 'status success';
                    addLog(data.message, 'movie');
                } else {
                    alert(data.detail || 'Fehler beim Exportieren');
                }
            } catch (error) {
                alert('Fehler: ' + error.message);
            }
        }
        
        // Cover functions
        async function loadCoverVideoList() {
            try {
                const response = await fetch('/api/cover/videos');
                const data = await response.json();
                const list = document.getElementById('cover-video-list');
                list.innerHTML = '';
                
                data.videos.forEach(video => {
                    const item = document.createElement('div');
                    item.className = 'list-item';
                    item.textContent = video.display;
                    item.onclick = () => {
                        document.querySelectorAll('#cover-video-list .list-item').forEach(i => i.classList.remove('selected'));
                        item.classList.add('selected');
                        selectedCoverVideo = video.path;
                        document.getElementById('extract-frames-btn').disabled = false;
                    };
                    list.appendChild(item);
                });
            } catch (error) {
                console.error('Fehler beim Laden der Liste:', error);
            }
        }
        
        async function extractFrames() {
            if (!selectedCoverVideo) {
                alert('Bitte ein Video auswählen');
                return;
            }
            
            try {
                const response = await fetch('/api/cover/extract', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({video_path: selectedCoverVideo, count: 4})
                });
                
                const data = await response.json();
                if (response.ok) {
                    extractedFrames = data.frames;
                    displayFrames(data.frames);
                    document.getElementById('cover-status').textContent = `${data.frames.length} Frames extrahiert`;
                } else {
                    alert(data.detail || 'Fehler bei Frame-Extraktion');
                }
            } catch (error) {
                alert('Fehler: ' + error.message);
            }
        }
        
        function displayFrames(frames) {
            const grid = document.getElementById('frame-grid');
            grid.innerHTML = '';
            
            frames.forEach((frame, index) => {
                const item = document.createElement('div');
                item.className = 'frame-item';
                item.innerHTML = `<img src="${frame.data}" alt="Frame ${index + 1}">`;
                item.onclick = () => {
                    document.querySelectorAll('.frame-item').forEach(f => f.classList.remove('selected'));
                    item.classList.add('selected');
                    selectedFrameIndex = index;
                    document.getElementById('generate-cover-btn').disabled = false;
                };
                grid.appendChild(item);
            });
        }
        
        async function generateCover() {
            if (selectedFrameIndex === null || !extractedFrames[selectedFrameIndex]) {
                alert('Bitte einen Frame auswählen');
                return;
            }
            
            const title = document.getElementById('cover-title').value;
            const year = document.getElementById('cover-year').value;
            
            if (!title) {
                alert('Bitte Titel eingeben');
                return;
            }
            
            try {
                const response = await fetch('/api/cover/generate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        frame_path: extractedFrames[selectedFrameIndex].path,
                        title,
                        year: year || null
                    })
                });
                
                const data = await response.json();
                if (response.ok) {
                    document.getElementById('cover-status').textContent = 'Generiere Cover...';
                    document.getElementById('cover-progress').style.display = 'block';
                } else {
                    alert(data.detail || 'Fehler bei Cover-Generierung');
                }
            } catch (error) {
                alert('Fehler: ' + error.message);
            }
        }
        
        // Initialize
        connectWebSocket();
        loadUpscalingProfiles();
        loadPostprocessList();
    </script>
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

