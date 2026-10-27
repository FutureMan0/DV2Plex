"""Settings, updates, system information, logs, the folder browser and permission fixes."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dv2plex import __version__
from dv2plex import web_app as state

router = APIRouter()
logger = logging.getLogger("dv2plex.web_app")


class ChownRequest(BaseModel):
    path: str


@router.get("/api/info")
async def get_info():
    """What this installation can do: version, mode, ffmpeg, capture and upscaling backends."""
    import importlib.util
    import platform

    from dv2plex.media import has_filter
    from dv2plex.merge import ffmpeg_version
    from dv2plex.upscale import realesrgan_available

    ffmpeg = state.config.get_ffmpeg_path()
    ffmpeg_found = ffmpeg.exists() or bool(shutil.which(str(ffmpeg)))
    dvgrab_cmd = state.config.get_dvgrab_command()
    dvgrab_found = bool(shutil.which(dvgrab_cmd[0])) or Path(dvgrab_cmd[0]).is_file()
    esr_reason = realesrgan_available()
    full_poster = all(importlib.util.find_spec(m) is not None for m in ("cv2", "rembg", "playwright"))
    profiles = state.config.get("upscaling.profiles", {}) or {}
    return {
        "version": __version__,
        "platform": sys.platform,
        "os": platform.platform(terse=True),
        "frozen": bool(getattr(sys, "frozen", False)),
        "demo": bool(state.config.get("demo.enabled", False)),
        "mode": state.run_mode,
        "language": state.config.get("ui.language", "") or "",
        "ffmpeg": {
            "path": str(ffmpeg),
            "found": ffmpeg_found,
            "version": await asyncio.to_thread(ffmpeg_version, ffmpeg) if ffmpeg_found else None,
            "drawtext": bool(ffmpeg_found and await asyncio.to_thread(has_filter, ffmpeg, "drawtext")),
        },
        "capture": {
            "dvgrab_found": dvgrab_found,
            "supported": dvgrab_found and (sys.platform.startswith("linux") or bool(state.config.get("demo.enabled", False))),
        },
        "upscaling": {
            "realesrgan": esr_reason is None,
            "realesrgan_reason": esr_reason,
            "profiles": [
                {"name": name, "backend": p.get("backend", "realesrgan"), "scale_factor": p.get("scale_factor"),
                 "available": p.get("backend") == "ffmpeg" or esr_reason is None}
                for name, p in profiles.items()
            ],
        },
        "poster": {"full": full_poster, "engine": state.config.get("cover.poster_engine", "auto")},
        "paths": {
            "dv_import_root": str(state.config.get_dv_import_root()),
            "plex_movies_root": str(state.config.get_plex_movies_root()),
            "settings": str(state.config.config_path),
            "logs": str(state.config.get_log_directory()),
        },
    }


@router.get("/api/update/status")
async def get_update_status(refresh: bool = False):
    """Gibt den Update-Status zurück"""
    if not state.update_manager:
        raise HTTPException(status_code=500, detail="Update-Manager nicht initialisiert")
    status = await state.update_manager.get_status(refresh=refresh)
    busy_reason = state.update_manager.busy_reason()
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
        "last_result": state.update_manager.last_result,
    }


@router.post("/api/update/run")
async def trigger_update():
    """Löst ein manuelles Update aus (git pull + Restart)"""
    if not state.update_manager:
        raise HTTPException(status_code=500, detail="Update-Manager nicht initialisiert")
    result = await state.update_manager.check_and_update(auto=False)
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


@router.get("/api/settings")
def get_settings():
    """Gibt die aktuellen Einstellungen zurück"""
    return {
        "plex_movies_root": str(state.config.get_plex_movies_root()),
        "dv_import_root": str(state.config.get_dv_import_root()),
        "ffmpeg_path": str(state.config.get_ffmpeg_path()),
        "auto_postprocess": state.config.get("capture.auto_postprocess", False),
        "auto_upscale": state.config.get("capture.auto_upscale", True),
        "auto_export": state.config.get("capture.auto_export", False),
        "timestamp_overlay": state.config.get("capture.timestamp_overlay", True),
        "ui_theme": state.config.get("ui.theme", "plex"),
        "ui_language": state.config.get("ui.language", ""),
        "show_cover_tab": state.config.get("ui.show_cover_tab", True),
        "update_enabled": state.config.get("update.enabled", False),
        "update_interval_minutes": state.config.get("update.interval_minutes", 60),
        "default_profile": state.config.get("upscaling.default_profile", "realesrgan_2x"),
    }


class SettingsUpdate(BaseModel):
    plex_movies_root: Optional[str] = None
    dv_import_root: Optional[str] = None
    ffmpeg_path: Optional[str] = None
    auto_postprocess: Optional[bool] = None
    auto_upscale: Optional[bool] = None
    auto_export: Optional[bool] = None
    timestamp_overlay: Optional[bool] = None
    ui_theme: Optional[str] = None
    ui_language: Optional[str] = None
    show_cover_tab: Optional[bool] = None
    update_enabled: Optional[bool] = None
    update_interval_minutes: Optional[int] = None
    default_profile: Optional[str] = None


@router.post("/api/settings")
def update_settings(update: SettingsUpdate):
    """Aktualisiert die Einstellungen"""
    settings = update.model_dump(exclude_none=True) if hasattr(update, "model_dump") else update.dict(exclude_none=True)
    for key in ("plex_movies_root", "dv_import_root"):
        if key in settings and not str(settings[key]).strip():
            raise HTTPException(status_code=400, detail=f"{key} must not be empty.")
    if "update_interval_minutes" in settings and not (5 <= settings["update_interval_minutes"] <= 24 * 60):
        raise HTTPException(status_code=400, detail="update_interval_minutes must be between 5 and 1440.")
    if "default_profile" in settings and not state.config.get_upscaling_profile(settings["default_profile"]):
        raise HTTPException(status_code=400, detail=f"Unknown upscaling profile: {settings['default_profile']}")
    if "ui_language" in settings and settings["ui_language"] not in ("", "en", "de"):
        raise HTTPException(status_code=400, detail="ui_language must be en, de or empty.")
    if "timestamp_overlay" in settings:
        state.config.set("capture.timestamp_overlay", settings["timestamp_overlay"])
    if "ui_language" in settings:
        state.config.set("ui.language", settings["ui_language"])
    if "default_profile" in settings:
        state.config.set("upscaling.default_profile", settings["default_profile"])
    if "plex_movies_root" in settings:
        state.config.set("paths.plex_movies_root", settings["plex_movies_root"])
    if "dv_import_root" in settings:
        state.config.set("paths.dv_import_root", settings["dv_import_root"])
    if "ffmpeg_path" in settings:
        state.config.set("paths.ffmpeg_path", settings["ffmpeg_path"])
    if "auto_postprocess" in settings:
        state.config.set("capture.auto_postprocess", settings["auto_postprocess"])
    if "auto_upscale" in settings:
        state.config.set("capture.auto_upscale", settings["auto_upscale"])
    if "auto_export" in settings:
        state.config.set("capture.auto_export", settings["auto_export"])
    if "ui_theme" in settings:
        state.config.set("ui.theme", settings["ui_theme"])
    if "show_cover_tab" in settings:
        state.config.set("ui.show_cover_tab", bool(settings["show_cover_tab"]))
    if "update_enabled" in settings:
        state.config.set("update.enabled", settings["update_enabled"])
    if "update_interval_minutes" in settings:
        state.config.set("update.interval_minutes", settings["update_interval_minutes"])

    try:
        state.config.save_config()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not save the settings to {state.config.config_path}: {e}")
    return {"success": True, "message": "Einstellungen gespeichert"}


@router.post("/api/chown")
def apply_chown(request: ChownRequest):
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


@router.post("/api/fix-config-permissions")
def fix_config_permissions():
    """Korrigiert die Berechtigungen des Config-Ordners"""
    import subprocess
    import os
    import pwd
    
    try:
        config_dir = state.config.config_dir
        current_user = pwd.getpwuid(os.getuid()).pw_name
        
        # sudo chown -R auf state.config-Ordner ausführen
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


@router.get("/api/browse")
def browse_directory(path: str = "/"):
    """Listet Verzeichnisse auf für den Datei-Browser"""
    
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


@router.get("/api/logs")
def get_logs(limit: int = 100, category: str = None):
    """Gibt die letzten Log-Einträge zurück"""
    logs = state.log_buffer[-limit:]
    
    if category:
        logs = [l for l in logs if l.get("category") == category]
    
    return {
        "logs": logs,
        "total": len(state.log_buffer)
    }


@router.post("/api/logs/clear")
def clear_logs():
    """Löscht alle Logs"""
    state.log_buffer = []
    return {"status": "ok"}


