"""Projects: the upscaling list, the Plex export, the video player, merge of films, deletion."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from dv2plex import web_app as state
from dv2plex.naming import InvalidName, movie_folder_name
from dv2plex.service import find_merged_file, find_pending_movies, find_upscaled_videos, parse_movie_folder_name

router = APIRouter()
logger = logging.getLogger("dv2plex.web_app")


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


class PlayerRenameRequest(BaseModel):
    project_path: str
    new_title: str
    new_year: Optional[str] = None


def _project_folder(path: Path) -> Path:
    """A project folder directly inside the import folder; never the import folder itself."""
    resolved = state._ensure_in_dv_import_root(path)
    if resolved.parent != state.config.get_dv_import_root().resolve():
        raise HTTPException(status_code=400, detail="Not a project folder of the import folder.")
    return resolved


def _refuse_busy(project_dir: Path) -> None:
    """Renaming or deleting a project that is being captured, merged or upscaled breaks that job."""
    capture = state.capture_service
    post = state.postprocessing_service
    if (capture and capture.is_busy_with(project_dir)) or (post and post.current() == project_dir.name):
        raise HTTPException(status_code=409, detail=f"{project_dir.name} is being worked on; try again when it is done.")


@router.get("/api/upscaling/profiles")
def get_upscaling_profiles():
    """Gibt alle verfügbaren Upscaling-Profile zurück"""
    profiles = state.config.get("upscaling.profiles", {})
    default_profile = state.config.get("upscaling.default_profile", "realesrgan_2x")
    return {
        "profiles": list(profiles.keys()),
        "default_profile": default_profile
    }


@router.get("/api/postprocess/list")
def get_postprocess_list():
    """Gibt Liste der zu verarbeitenden Filme zurück"""
    pending = find_pending_movies(state.config)
    result = []
    for movie_dir in pending:
        title, year = parse_movie_folder_name(movie_dir.name)
        result.append({
            "path": str(movie_dir),
            "title": title,
            "year": year,
            "display": f"{title} ({year})" if year else movie_dir.name,
            # Clips that were never merged; processing merges them first
            "needs_merge": find_merged_file(movie_dir / "LowRes") is None,
            "merging": bool(state.capture_service and state.capture_service.is_merging(movie_dir)),
        })
    return {"movies": result}


@router.get("/api/movie/list")
def get_movie_list():
    """Gibt Liste der upscaled Videos zurück"""
    videos = find_upscaled_videos(state.config)
    result = []
    plex_root = state.config.get_plex_movies_root()

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
        expected_poster = plex_root / movie_name / "poster.jpg"
        exported = expected_target.exists()
        has_poster = expected_poster.exists()
        
        # Größe der Quell-Datei (HighRes)
        size_bytes = None
        try:
            size_bytes = int(video_path.stat().st_size)
        except Exception:
            size_bytes = None
        
        # Poster-Größe schätzen (typisch ~2-5 MB für 3000x4500 JPEG)
        poster_size_bytes = 3 * 1024 * 1024  # 3 MB Schätzwert
        if has_poster:
            try:
                poster_size_bytes = int(expected_poster.stat().st_size)
            except Exception:
                pass

        if not exported and size_bytes is not None:
            # Füge Poster-Größe hinzu, wenn noch kein Poster existiert
            if not has_poster:
                required_bytes += size_bytes + poster_size_bytes
            else:
                required_bytes += size_bytes
            required_count += 1

        fits_now = True
        if not exported and free_bytes is not None and size_bytes is not None:
            total_size = size_bytes + (poster_size_bytes if not has_poster else 0)
            fits_now = total_size <= free_bytes
        result.append({
            "path": str(video_path),
            "title": title,
            "year": year,
            "display": f"{title} ({year})" if year else f"{title} - {video_path.name}",
            "exported": exported,
            "has_poster": has_poster,
            "expected_target": str(expected_target),
            "expected_poster": str(expected_poster),
            "size_bytes": size_bytes,
            "poster_size_bytes": poster_size_bytes if not has_poster else 0,
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


@router.get("/api/player/projects")
def list_player_projects():
    """Listet alle Projekte (LowRes/HighRes) im DV_Import-Ordner auf."""
    root = state.config.get_dv_import_root()
    projects = []
    if not root.exists():
        return {"projects": projects}

    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        lowres = state._list_videos_in_folder(project_dir / "LowRes")
        highres = state._list_videos_in_folder(project_dir / "HighRes")
        if not lowres and not highres:
            continue
        
        # Prüfe ob Poster im Projekt-Ordner existiert (HighRes hat Priorität)
        poster_path = None
        has_poster = False
        
        # Zuerst in HighRes suchen
        if highres:
            highres_video = Path(highres[0]["path"])
            highres_poster = highres_video.parent / "poster.jpg"
            if highres_poster.exists():
                poster_path = highres_poster
                has_poster = True
        # Falls nicht gefunden, in LowRes suchen
        if not has_poster and lowres:
            lowres_video = Path(lowres[0]["path"])
            lowres_poster = lowres_video.parent / "poster.jpg"
            if lowres_poster.exists():
                poster_path = lowres_poster
                has_poster = True
        
        projects.append({
            "title": project_dir.name,
            "path": str(project_dir),
            "lowres": lowres,
            "highres": highres,
            "poster_path": str(poster_path) if has_poster else None,
            "has_poster": has_poster,
        })

    return {"projects": projects}


@router.get("/api/player/stream")
def stream_video(path: str):
    """Spielt eine Videodatei aus dem DV_Import-Ordner ab."""
    if not path:
        raise HTTPException(status_code=400, detail="Pfad fehlt")
    file_path = state._ensure_in_dv_import_root(Path(path))
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    mime_type, _ = mimetypes.guess_type(file_path.name)
    return FileResponse(file_path, media_type=mime_type or "video/mp4", filename=file_path.name)


@router.get("/api/player/poster")
def get_poster(path: str):
    """Gibt ein Poster-Bild zurück"""
    if not path:
        raise HTTPException(status_code=400, detail="Pfad fehlt")
    
    poster_path = Path(path)
    plex_root = state.config.get_plex_movies_root()
    dv_import_root = state.config.get_dv_import_root()
    
    # Sicherheitsprüfung: Poster muss im Plex Movies Root ODER im DV_Import Root sein
    is_in_plex = False
    is_in_dv_import = False
    
    try:
        poster_path.resolve().relative_to(plex_root.resolve())
        is_in_plex = True
    except ValueError:
        pass
    
    try:
        poster_path.resolve().relative_to(dv_import_root.resolve())
        is_in_dv_import = True
    except ValueError:
        pass
    
    if not is_in_plex and not is_in_dv_import:
        raise HTTPException(status_code=403, detail="Ungültiger Poster-Pfad")
    
    if not poster_path.exists() or not poster_path.is_file():
        raise HTTPException(status_code=404, detail="Poster nicht gefunden")
    
    mime_type, _ = mimetypes.guess_type(poster_path.name)
    return FileResponse(poster_path, media_type=mime_type or "image/jpeg", filename=poster_path.name)


@router.post("/api/player/rename")
def rename_player_project(request: PlayerRenameRequest):
    """Benennt ein Projekt im Video Player um (Ordner und Dateien)"""
    if not request.project_path or not request.new_title:
        raise HTTPException(status_code=400, detail="Projekt-Pfad und neuer Titel müssen angegeben werden")
    
    project_dir = Path(request.project_path)
    
    # Sicherheitsprüfung: ein Projekt direkt im DV_Import-Ordner (nicht der Ordner selbst)
    project_dir = _project_folder(project_dir)
    _refuse_busy(project_dir)
    
    if not project_dir.exists() or not project_dir.is_dir():
        raise HTTPException(status_code=404, detail="Projekt-Ordner nicht gefunden")
    
    # Erstelle neuen Ordnernamen (gültig auf allen Systemen, nicht außerhalb des Import-Ordners)
    try:
        new_folder_name = movie_folder_name(request.new_title, request.new_year, year_required=False)
    except InvalidName as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Prüfe ob Zielordner bereits existiert
    new_project_dir = project_dir.parent / new_folder_name
    if new_project_dir.exists() and new_project_dir != project_dir:
        raise HTTPException(status_code=400, detail=f"Zielordner existiert bereits: {new_folder_name}")
    
    try:
        # 1. Benenne Projektordner um
        old_folder_name = project_dir.name
        project_dir.rename(new_project_dir)
        logger.info(f"Projektordner umbenannt: {old_folder_name} → {new_folder_name}")
        state.add_log_entry(f"Projektordner umbenannt: {old_folder_name} → {new_folder_name}", "player")
        
        # 2. Benenne HighRes-Dateien um (z.B. {alt}_4k.mp4 → {neu}_4k.mp4)
        highres_dir = new_project_dir / "HighRes"
        if highres_dir.exists() and highres_dir.is_dir():
            for video_file in highres_dir.glob("*_4k.mp4"):
                # Extrahiere Suffix (z.B. "_4k.mp4")
                suffix = "_4k.mp4"
                if video_file.name.endswith(suffix):
                    new_video_name = f"{new_folder_name}{suffix}"
                    new_video_path = highres_dir / new_video_name
                    if new_video_path != video_file:
                        video_file.rename(new_video_path)
                        logger.info(f"HighRes-Video umbenannt: {video_file.name} → {new_video_name}")
                        state.add_log_entry(f"HighRes-Video umbenannt: {video_file.name} → {new_video_name}", "player")
            
            # Benenne auch andere Video-Dateien um, die den alten Ordnernamen enthalten
            for video_file in highres_dir.glob("*"):
                if video_file.is_file() and old_folder_name in video_file.name:
                    new_name = video_file.name.replace(old_folder_name, new_folder_name)
                    if new_name != video_file.name:
                        new_path = highres_dir / new_name
                        if not new_path.exists():
                            video_file.rename(new_path)
                            logger.info(f"HighRes-Datei umbenannt: {video_file.name} → {new_name}")
                            state.add_log_entry(f"HighRes-Datei umbenannt: {video_file.name} → {new_name}", "player")
        
        # 3. Benenne LowRes-Dateien um, die den alten Ordnernamen enthalten
        lowres_dir = new_project_dir / "LowRes"
        if lowres_dir.exists() and lowres_dir.is_dir():
            for video_file in lowres_dir.glob("*"):
                if video_file.is_file() and old_folder_name in video_file.name:
                    new_name = video_file.name.replace(old_folder_name, new_folder_name)
                    if new_name != video_file.name:
                        new_path = lowres_dir / new_name
                        if not new_path.exists():
                            video_file.rename(new_path)
                            logger.info(f"LowRes-Datei umbenannt: {video_file.name} → {new_name}")
                            state.add_log_entry(f"LowRes-Datei umbenannt: {video_file.name} → {new_name}", "player")
        
        # 4. Benenne Poster-Dateien um, falls sie den alten Ordnernamen enthalten
        for poster_dir in [highres_dir, lowres_dir]:
            if poster_dir.exists() and poster_dir.is_dir():
                poster_file = poster_dir / "poster.jpg"
                if poster_file.exists() and old_folder_name in poster_file.name:
                    new_poster_name = poster_file.name.replace(old_folder_name, new_folder_name)
                    if new_poster_name != poster_file.name:
                        new_poster_path = poster_dir / new_poster_name
                        if not new_poster_path.exists():
                            poster_file.rename(new_poster_path)
                            logger.info(f"Poster umbenannt: {poster_file.name} → {new_poster_name}")
                            state.add_log_entry(f"Poster umbenannt: {poster_file.name} → {new_poster_name}", "player")
        
        return {
            "success": True,
            "message": f"Projekt erfolgreich umbenannt: {old_folder_name} → {new_folder_name}",
            "old_name": old_folder_name,
            "new_name": new_folder_name,
            "new_path": str(new_project_dir)
        }
    except Exception as e:
        logger.exception(f"Fehler beim Umbenennen des Projekts: {e}")
        raise HTTPException(status_code=500, detail=f"Fehler beim Umbenennen: {str(e)}")


@router.post("/api/postprocess/process")
def process_movie(request: PostprocessRequest):
    """Startet Postprocessing für einen Film"""
    if not state.postprocessing_service:
        raise HTTPException(status_code=500, detail="Postprocessing-Service nicht initialisiert")

    movie_dir = state._ensure_in_dv_import_root(Path(request.movie_dir))
    if not movie_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Project folder not found: {movie_dir.name}")
    if not state.config.get_upscaling_profile(request.profile_name):
        raise HTTPException(status_code=400, detail=f"Unknown upscaling profile: {request.profile_name}")

    queued, message = state._start_postprocessing(movie_dir, request.profile_name)
    if not queued:
        raise HTTPException(status_code=409, detail=message)
    return {"success": True, "message": "Postprocessing gestartet", "queued": state.postprocessing_service.queued_count()}


@router.post("/api/movie/merge")
def merge_videos(request: MergeRequest):
    """Merged mehrere Videos zu einem Film (läuft im Hintergrund)"""
    if not state.movie_mode_service:
        raise HTTPException(status_code=500, detail="Movie-Mode-Service nicht initialisiert")
    
    video_paths = [state._ensure_in_dv_import_root(Path(p)) for p in request.video_paths]

    if state.active_movie_merge.get("running"):
        raise HTTPException(status_code=409, detail="Merge läuft bereits")

    # Schnell validieren, damit wir sofort Fehler zurückgeben
    if len(video_paths) < 2:
        raise HTTPException(status_code=400, detail="Select at least two videos.")
    try:
        movie_folder_name(request.title, request.year)
    except InvalidName as e:
        raise HTTPException(status_code=400, detail=str(e))

    state.active_movie_merge = {"running": True, "current": f"{request.title} ({request.year})"}

    def run_merge():
        try:
            state.broadcast_message_sync({"type": "progress", "value": 0, "operation": "movie_merge"})
            state.broadcast_message_sync({
                "type": "status",
                "status": "movie_merge_started",
                "operation": "movie_merge",
                "data": {"title": request.title, "year": request.year, "count": len(video_paths)},
            })

            success, merged_file, error = state.movie_mode_service.merge_videos(
                video_paths,
                request.title,
                request.year
            )

            if not success or not merged_file:
                state.broadcast_message_sync({
                    "type": "status",
                    "status": "movie_merge_failed",
                    "operation": "movie_merge",
                    "data": {"error": error or "Merge fehlgeschlagen"},
                })
                return

            # Export to Plex
            export_success, exported_path, export_error = state.movie_mode_service.export_to_plex(
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
                state.broadcast_message_sync({"type": "progress", "value": 100, "operation": "movie_merge"})
                state.broadcast_message_sync({
                    "type": "status",
                    "status": "movie_merge_finished",
                    "operation": "movie_merge",
                    "data": {"exported_path": str(exported_path) if exported_path else None},
                })
            else:
                state.broadcast_message_sync({
                    "type": "status",
                    "status": "movie_merge_failed",
                    "operation": "movie_merge",
                    "data": {"error": export_error or "Export fehlgeschlagen"},
                })
        except Exception as e:
            logger.exception("Fehler beim Movie-Merge")
            state.broadcast_message_sync({
                "type": "status",
                "status": "movie_merge_failed",
                "operation": "movie_merge",
                "data": {"error": str(e)},
            })
        finally:
            state.active_movie_merge["running"] = False
            state.active_movie_merge["current"] = None

    threading.Thread(target=run_merge, daemon=True).start()
    return {"success": True, "message": "Merge gestartet (läuft im Hintergrund)."}


@router.post("/api/movie/export")
def export_video(request: ExportRequest):
    """Exportiert ein einzelnes Video nach PlexMovies (läuft im Hintergrund)"""
    if not state.movie_mode_service:
        raise HTTPException(status_code=500, detail="Movie-Mode-Service nicht initialisiert")
    
    video_path = state._ensure_in_dv_import_root(Path(request.video_path))

    if state.active_export_single.get("running"):
        raise HTTPException(status_code=409, detail="Export läuft bereits")

    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"Video nicht gefunden: {video_path}")

    state.active_export_single = {"running": True, "current": str(video_path)}

    def run_export_single():
        try:
            state.broadcast_message_sync({"type": "progress", "value": 0, "operation": "movie_export_single"})
            state.broadcast_message_sync({
                "type": "status",
                "status": "movie_export_single_started",
                "operation": "movie_export_single",
                "data": {"video_path": str(video_path)},
            })

            success, exported_path, error = state.movie_mode_service.export_to_plex(
                video_path,
                request.title,
                request.year
            )

            if success:
                state.broadcast_message_sync({"type": "progress", "value": 100, "operation": "movie_export_single"})
                state.broadcast_message_sync({
                    "type": "status",
                    "status": "movie_export_single_done",
                    "operation": "movie_export_single",
                    "data": {"video_path": str(video_path), "exported_path": str(exported_path) if exported_path else None},
                })
            else:
                state.broadcast_message_sync({
                    "type": "status",
                    "status": "movie_export_single_failed",
                    "operation": "movie_export_single",
                    "data": {"video_path": str(video_path), "error": error or "Export fehlgeschlagen"},
                })
        except Exception as e:
            logger.exception("Fehler beim Export (single)")
            state.broadcast_message_sync({
                "type": "status",
                "status": "movie_export_single_failed",
                "operation": "movie_export_single",
                "data": {"video_path": str(video_path), "error": str(e)},
            })
        finally:
            state.active_export_single["running"] = False
            state.active_export_single["current"] = None

    threading.Thread(target=run_export_single, daemon=True).start()
    return {"success": True, "message": "Export gestartet (läuft im Hintergrund)."}


@router.post("/api/movie/export-all")
def export_all_videos(request: ExportAllRequest):
    """Exportiert alle upscaled (HighRes) Videos nach PlexMovies (läuft im Hintergrund)."""

    if not state.movie_mode_service:
        raise HTTPException(status_code=500, detail="Movie-Mode-Service nicht initialisiert")

    if state.active_export_all.get("running"):
        raise HTTPException(status_code=409, detail="Export-All läuft bereits")

    videos = find_upscaled_videos(state.config)
    total = len(videos)
    if total == 0:
        return {"success": True, "message": "Keine Videos zum Exportieren gefunden.", "total": 0}

    plex_root = state.config.get_plex_movies_root()

    # Init state
    state.active_export_all = {
        "running": True,
        "total": total,
        "done": 0,
        "skipped": 0,
        "failed": 0,
        "current": None,
    }

    def run_export_all():
        try:
            state.broadcast_message_sync({
                "type": "status",
                "status": "movie_export_all_started",
                "operation": "movie_export_all",
                "data": {"total": total},
            })
            state.broadcast_message_sync({"type": "progress", "value": 0, "operation": "movie_export_all"})

            for idx, (video_path, title, year) in enumerate(videos, start=1):
                movie_name = f"{title} ({year})" if year else title
                expected_target = plex_root / movie_name / f"{movie_name}.mp4"
                state.active_export_all["current"] = str(video_path)

                # Skip existing if requested
                if request.skip_existing and expected_target.exists():
                    state.active_export_all["skipped"] += 1
                    state.active_export_all["done"] += 1
                    percent = int(round(state.active_export_all["done"] * 100 / max(state.active_export_all["total"], 1)))
                    state.broadcast_message_sync({
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
                    state.broadcast_message_sync({"type": "progress", "value": percent, "operation": "movie_export_all"})
                    continue

                state.broadcast_message_sync({
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

                success, exported_path, error = state.movie_mode_service.export_to_plex(
                    Path(video_path),
                    title,
                    year,
                    overwrite=True,
                )

                state.active_export_all["done"] += 1
                percent = int(round(state.active_export_all["done"] * 100 / max(state.active_export_all["total"], 1)))

                if success:
                    state.broadcast_message_sync({
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
                    state.active_export_all["failed"] += 1
                    state.broadcast_message_sync({
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

                state.broadcast_message_sync({"type": "progress", "value": percent, "operation": "movie_export_all"})

            state.broadcast_message_sync({
                "type": "status",
                "status": "movie_export_all_finished",
                "operation": "movie_export_all",
                "data": {
                    "total": total,
                    "skipped": state.active_export_all.get("skipped", 0),
                    "failed": state.active_export_all.get("failed", 0),
                },
            })
        except Exception as e:
            logger.exception("Fehler bei Export-All")
            state.broadcast_message_sync({
                "type": "status",
                "status": "movie_export_all_failed",
                "operation": "movie_export_all",
                "data": {"error": str(e)},
            })
        finally:
            state.active_export_all["running"] = False
            state.active_export_all["current"] = None

    thread = threading.Thread(target=run_export_all, daemon=True)
    thread.start()

    return {"success": True, "message": f"Export-All gestartet ({total} Videos).", "total": total}


@router.post("/api/project/delete")
async def delete_projects(request: DeleteProjectsRequest):
    """
    Löscht für ein oder mehrere DV_Import-Projekte die Ordner LowRes und HighRes.

    Akzeptiert als Input sowohl:
    - den Projektordner (DV_Import/<Projekt>)
    - einen Pfad zu einer Datei innerhalb LowRes/HighRes
    """
    if not request.paths:
        raise HTTPException(status_code=400, detail="paths darf nicht leer sein")


    def _delete_one(raw: str) -> Dict[str, Any]:
        p = Path(raw)

        # Erlaube sowohl Ordner als auch Datei; validiere immer gegen DV_Import
        resolved = state._ensure_in_dv_import_root(p)

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

        # Safety: ein Projekt direkt im DV_Import-Ordner, gerade nicht in Arbeit
        project_dir = _project_folder(project_dir)
        _refuse_busy(project_dir)

        deleted = []
        for sub in ("LowRes", "HighRes"):
            d = project_dir / sub
            if d.exists() and d.is_dir():
                state._rmtree_force(d)
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
        state.add_log_entry(f"Projekt(e) gelöscht: {len(results)}", "movie")
        return {"success": True, "results": results}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Fehler beim Löschen von Projekten")
        raise HTTPException(status_code=500, detail=str(e))


