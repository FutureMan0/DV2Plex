"""
Web server of DV2Plex (FastAPI): the app, its shared state and the access rules.

The routes live in dv2plex/api/ (capture, library, covers, system, live). They read the
shared state from this module (config, the services, the WebSocket connections), so tests
and the desktop window can swap it here.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
import os
import shutil
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse

from dv2plex.access import (
    ALWAYS_PROTECTED_PATHS,
    STATE_CHANGING_METHODS,
    TOKEN_SETTING,
    RedactTokenFilter,
    host_allowed,
    is_loopback,
    load_or_create_token,
    origin_allowed,
    requires_token,
    token_from_environment,
    token_from_request,
    token_matches,
)
from dv2plex.config import Config
from dv2plex.service import CaptureService, CoverService, MovieModeService, PostprocessingService
from dv2plex.update_manager import UpdateManager

project_root = Path(__file__).parent.parent

logger = logging.getLogger(__name__)
# Keep the API token out of uvicorn's request and WebSocket log lines
for _uvicorn_logger in ("uvicorn.access", "uvicorn.error"):
    logging.getLogger(_uvicorn_logger).addFilter(RedactTokenFilter())


# FastAPI app
@asynccontextmanager
async def _lifespan(_app: FastAPI):
    await on_startup()
    yield


app = FastAPI(title="DV2Plex Web Interface", lifespan=_lifespan)

# Global state
config = Config()
# "server" (headless, may manage the systemd service) or "desktop" (window on this machine)
run_mode = "server"
capture_service: Optional[CaptureService] = None
postprocessing_service: Optional[PostprocessingService] = None
movie_mode_service: Optional[MovieModeService] = None
cover_service: Optional[CoverService] = None
update_manager: Optional[UpdateManager] = None
update_task: Optional[asyncio.Task] = None
main_event_loop: Optional[asyncio.AbstractEventLoop] = None

# WebSocket connections for broadcasting
websocket_connections: List[WebSocket] = []

# API token, set by setup_access(). Without it, protected requests are refused.
api_token: Optional[str] = None
# True when the server listens on more than the loopback interface
token_required_everywhere = False

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


def setup_services(mode: str = "server"):
    """Initialisiert die Services"""
    global capture_service, postprocessing_service, movie_mode_service, cover_service, update_manager, run_mode
    run_mode = mode
    
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
        global active_capture
        if state == "stopped":
            # Also when the tape ended by itself; /api/status showed the old capture before
            active_capture = None
            broadcast_message_sync({
                "type": "status",
                "status": "capture_stopped",
                "data": None,
                "operation": "capture"
            })
    
    def merge_finished_callback(job):
        """After a capture's merge: upscale (and export) automatically if that is switched on."""
        if job.status != "completed" or not config.get("capture.auto_postprocess", False):
            return
        if not config.get("capture.auto_upscale", True):
            add_log_entry(f"Auto-postprocessing is on, auto-upscaling off: {job.title} stays merged only.", "merge")
            return
        project_dir = Path(job.splits_dir).parent.parent
        profile = config.get("upscaling.default_profile", "realesrgan_2x")
        add_log_entry(f"Merge done, upscaling {project_dir.name} automatically ({profile}).", "merge")
        _start_postprocessing(project_dir, profile)

    capture_service = CaptureService(
        config, 
        log_callback=log_callback,
        merge_progress_callback=merge_progress_callback,
        state_callback=capture_state_callback,
        merge_finished_callback=merge_finished_callback,
    )
    
    postprocessing_service = PostprocessingService(
        config, log_callback=log_callback, merge_busy=capture_service.is_merging
    )
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


def setup_access(bind_host: str, port: Optional[int] = None) -> str:
    """
    Loads or creates the API token and decides which requests need it.

    On a loopback host only the routes in ALWAYS_PROTECTED_PATHS need it; on any other host,
    every /api request and the WebSocket do.
    """
    global api_token, token_required_everywhere
    api_token = load_or_create_token(config)
    token_required_everywhere = not is_loopback(bind_host)

    if token_from_environment():
        source = "it is set by DV2PLEX_TOKEN"
    else:
        source = f"it is stored as {TOKEN_SETTING} in {config.config_path}"
    if token_required_everywhere:
        logger.warning("Listening on %s: every /api request and /ws need the API token.", bind_host)
        logger.warning(
            "Print the token with `python -m dv2plex --show-token` (%s), then open "
            "http://<this machine>:%s/?token=<token> once; the browser keeps it.",
            source, port if port else "<port>",
        )
    else:
        logger.info(
            "Listening on %s only. %s need the API token; print it with "
            "`python -m dv2plex --show-token` (%s).",
            bind_host, ", ".join(sorted(ALWAYS_PROTECTED_PATHS)), source,
        )
    return api_token


def _allowed_hosts() -> List[str]:
    """Extra host names (reverse proxy, mDNS name) set in server.allowed_hosts."""
    value = config.get("server.allowed_hosts", []) or []
    if isinstance(value, str):
        value = [value]
    return [str(v) for v in value]


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    """
    Refuses requests from other web pages and protected requests without the API token
    (see dv2plex/access.py).
    """
    host_header = request.headers.get("host")
    if not host_allowed(host_header, not token_required_everywhere, _allowed_hosts()):
        return JSONResponse(
            status_code=421,
            content={"detail": "Unknown host name. Open DV2Plex as http://127.0.0.1:<port>/, or add the name to server.allowed_hosts."},
        )
    if request.method in STATE_CHANGING_METHODS and not origin_allowed(request.headers.get("origin"), host_header):
        return JSONResponse(
            status_code=403,
            content={"detail": "Request from another web page refused."},
        )
    if requires_token(request.scope["path"], token_required_everywhere):
        given = token_from_request(request.headers, request.query_params)
        if not token_matches(api_token, given):
            return JSONResponse(
                status_code=401,
                content={"detail": "API token missing or wrong. Print it on the server with: python -m dv2plex --show-token"},
            )
    return await call_next(request)


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
            if config.get("update.enabled", False):
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


# API Routes
@app.get("/", response_class=HTMLResponse)
async def root():
    """Hauptseite mit Web-Interface"""
    return get_html_interface()


def _ensure_within(file_path: Path, roots: List[Path], what: str = "Path") -> Path:
    """The resolved path, if it lies inside one of the roots; else 400."""
    try:
        resolved = file_path.resolve()
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{what}: invalid path")
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail=f"{what} is outside the folders DV2Plex works in.")


def _frames_dir() -> Path:
    import tempfile
    return Path(tempfile.gettempdir()) / "dv2plex_cover_frames"


def _ensure_in_dv_import_root(file_path: Path) -> Path:
    """Validiert, dass sich der Pfad innerhalb des DV_Import-Verzeichnisses befindet."""
    return _ensure_within(file_path, [config.get_dv_import_root()], "Path")


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


def _start_postprocessing(movie_dir: Path, profile_name: str) -> tuple:
    """Queues upscaling for a project; progress and the result go out over the WebSocket."""
    global active_postprocessing

    def progress_cb(value: int):
        broadcast_message_sync({"type": "progress", "value": value, "operation": "postprocessing",
                                "project": movie_dir.name})

    def status_cb(status: str):
        global active_postprocessing
        active_postprocessing = {"movie_dir": str(movie_dir), "started_at": datetime.now().isoformat()}
        broadcast_message_sync({"type": "status", "status": status, "operation": "postprocessing"})

    def finished_cb(success: bool, message: str):
        global active_postprocessing
        active_postprocessing = None
        add_log_entry(message, "postprocessing")
        broadcast_message_sync({
            "type": "postprocessing_finished",
            "success": success,
            "message": message,
            "project": movie_dir.name,
        })

    return postprocessing_service.process_movie(
        movie_dir,
        profile_name,
        progress_callback=progress_cb,
        status_callback=status_cb,
        finished_callback=finished_cb,
    )


async def on_startup():
    """Merkt sich die Event-Loop für thread-sichere Broadcasts"""
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()
    await _start_update_scheduler()
    # Only a headless installation with automatic updates manages its systemd service;
    # the desktop window must not ask for sudo or enable a service.
    if update_manager and run_mode == "server" and config.get("update.enabled", False):
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
        # Texts of the interface in English and German
        i18n = (web_dir / "i18n.json").read_text(encoding="utf-8").replace("</", "<\\/")

        # Inline CSS/JS, damit wir ohne Static-Hosting auskommen.
        style_tag = f"<style>\n{css}\n</style>\n"
        script_tag = (
            f'<script id="i18n" type="application/json">{i18n}</script>\n'
            f"<script>\n{js}\n</script>\n"
        )

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
<html lang="en">
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
  <h2>The interface could not be loaded</h2>
  <p>Check that <code>dv2plex/web/</code> contains index.html, index.css, index.js and i18n.json.</p>
  <pre>{str(e)}</pre>
</body>
</html>"""


# The routes; imported last because they read the state above
from dv2plex.api import capture as _capture_api  # noqa: E402
from dv2plex.api import covers as _covers_api  # noqa: E402
from dv2plex.api import library as _library_api  # noqa: E402
from dv2plex.api import live as _live_api  # noqa: E402
from dv2plex.api import system as _system_api  # noqa: E402

for _module in (_capture_api, _library_api, _covers_api, _system_api, _live_api):
    app.include_router(_module.router)
