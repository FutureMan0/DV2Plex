"""Covers and posters: frames, Stable Diffusion covers, posters (one or many)."""

from __future__ import annotations

import base64
import logging
import threading
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dv2plex import web_app as state
from dv2plex.service import find_upscaled_videos

router = APIRouter()
logger = logging.getLogger("dv2plex.web_app")


class CoverExtractRequest(BaseModel):
    video_path: str
    count: int = 4


class CoverGenerateRequest(BaseModel):
    frame_path: str
    title: str
    year: Optional[str] = None


@router.get("/api/cover/videos")
def get_cover_videos():
    """Gibt Liste der verfügbaren Videos für Cover-Generierung zurück"""
    # Cover-Generator soll alle upgescalten Projekte anzeigen
    videos = find_upscaled_videos(state.config)
    result = []
    
    for video_path, title, year in videos:
        # Prüfe ob bereits ein Poster im Video-Ordner existiert
        video_dir = Path(video_path).parent
        expected_poster = video_dir / "poster.jpg"
        has_poster = expected_poster.exists()
        
        result.append({
            "path": str(video_path),
            "title": title,
            "year": year,
            "display": f"{title} ({year})" if year else f"{title} - {video_path.name}",
            "has_poster": has_poster,
            "poster_path": str(expected_poster) if has_poster else None
        })
    return {"videos": result}


@router.post("/api/cover/extract")
def extract_frames(request: CoverExtractRequest):
    """Extrahiert Frames aus einem Video"""
    if not state.cover_service:
        raise HTTPException(status_code=500, detail="Cover-Service nicht initialisiert")
    
    video_path = state._ensure_in_dv_import_root(Path(request.video_path))
    count = max(1, min(int(request.count or 4), 16))

    success, frames, error = state.cover_service.extract_frames(video_path, count)
    
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


@router.post("/api/cover/generate")
def generate_cover(request: CoverGenerateRequest):
    """Generiert ein Cover aus einem Frame (alte Methode)"""
    if not state.cover_service:
        raise HTTPException(status_code=500, detail="Cover-Service nicht initialisiert")
    
    frame_path = state._ensure_within(Path(request.frame_path), [state._frames_dir()], "Frame")

    # Run in background thread
    def run_generation():
        def progress_cb(value: int):
            state.broadcast_message_sync({"type": "progress", "value": value, "operation": "cover_generation"})
        
        def status_cb(status: str):
            state.broadcast_message_sync({"type": "status", "status": status, "operation": "cover_generation"})
        
        success, cover_path, error = state.cover_service.generate_cover(
            frame_path,
            request.title,
            request.year,
            progress_callback=progress_cb,
            status_callback=status_cb
        )
        
        state.broadcast_message_sync({
            "type": "cover_generation_finished",
            "success": success,
            "message": error if not success else f"Cover erfolgreich generiert: {cover_path}",
            "cover_path": str(cover_path) if cover_path else None
        })
    
    thread = threading.Thread(target=run_generation, daemon=True)
    thread.start()
    
    return {"success": True, "message": "Cover-Generierung gestartet"}


class PosterGenerateRequest(BaseModel):
    video_path: str
    title: str
    year: Optional[str] = None


@router.post("/api/poster/generate")
def generate_poster(request: PosterGenerateRequest):
    """Generiert ein Poster direkt aus einem Video (neue Poster-Generierung)"""
    if not state.cover_service:
        raise HTTPException(status_code=500, detail="Cover-Service nicht initialisiert")
    
    video_path = state._ensure_in_dv_import_root(Path(request.video_path))
    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"Video not found: {video_path.name}")

    # Füge Job zur Queue hinzu
    def progress_cb(value: int):
        state.broadcast_message_sync({"type": "progress", "value": value, "operation": "poster_generation"})
    
    def status_cb(status: str):
        state.broadcast_message_sync({"type": "status", "status": status, "operation": "poster_generation"})
    
    def finished_cb(success: bool, message: str, poster_path: Optional[Path]):
        state.broadcast_message_sync({
            "type": "poster_generation_finished",
            "success": success,
            "message": message,
            "poster_path": str(poster_path) if poster_path else None
        })
    
    state.cover_service.enqueue_poster(
        video_path,
        request.title,
        request.year,
        progress_callback=progress_cb,
        status_callback=status_cb,
        finished_callback=finished_cb
    )
    
    return {"success": True, "message": "Poster-Generierung zur Queue hinzugefügt"}


class PosterGenerateBatchRequest(BaseModel):
    video_paths: List[str]


@router.post("/api/poster/generate-batch")
def generate_poster_batch(request: PosterGenerateBatchRequest):
    """Generiert Poster für mehrere Videos (Batch-Verarbeitung)"""
    if not state.cover_service:
        raise HTTPException(status_code=500, detail="Cover-Service nicht initialisiert")
    
    logger.info(f"Poster-Batch-Generierung gestartet: {len(request.video_paths)} Videos")
    state.add_log_entry(f"Poster-Batch-Generierung gestartet: {len(request.video_paths)} Videos", "poster_generation")
    
    # Extrahiere Titel und Jahr aus jedem Video-Pfad
    videos = find_upscaled_videos(state.config)
    video_map = {str(video_path): (title, year) for video_path, title, year in videos}
    
    added_count = 0
    for video_path_str in request.video_paths:
        try:
            video_path = state._ensure_in_dv_import_root(Path(video_path_str))
        except HTTPException:
            continue
        if not video_path.exists():
            continue
        
        # Hole Titel und Jahr aus der Map
        title, year = video_map.get(video_path_str, (video_path.stem, None))
        
        def progress_cb(value: int):
            state.broadcast_message_sync({
                "type": "progress",
                "value": value,
                "operation": "poster_generation_batch",
                "video_path": str(video_path)
            })
        
        def status_cb(status: str):
            state.broadcast_message_sync({
                "type": "status",
                "status": status,
                "operation": "poster_generation_batch",
                "video_path": str(video_path)
            })
        
        def finished_cb(success: bool, message: str, poster_path: Optional[Path]):
            state.broadcast_message_sync({
                "type": "poster_generation_finished",
                "success": success,
                "message": message,
                "poster_path": str(poster_path) if poster_path else None,
                "video_path": str(video_path)
            })
        
        try:
            state.cover_service.enqueue_poster(
                video_path,
                title,
                year,
                progress_callback=progress_cb,
                status_callback=status_cb,
                finished_callback=finished_cb
            )
            added_count += 1
            logger.info(f"Poster-Job zur Queue hinzugefügt: {title} ({year})")
            state.add_log_entry(f"Poster-Job zur Queue hinzugefügt: {title} ({year})", "poster_generation")
        except Exception as e:
            logger.error(f"Fehler beim Hinzufügen des Poster-Jobs für {video_path_str}: {e}")
            state.add_log_entry(f"Fehler beim Hinzufügen des Poster-Jobs: {e}", "poster_generation")
    
    logger.info(f"Poster-Batch-Generierung: {added_count} Jobs zur Queue hinzugefügt")
    state.add_log_entry(f"Poster-Batch-Generierung: {added_count} Jobs zur Queue hinzugefügt", "poster_generation")
    
    return {"success": True, "message": f"{added_count} Poster-Generierungs-Jobs zur Queue hinzugefügt", "count": added_count}


