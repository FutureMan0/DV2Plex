"""
Service-Layer für DV2Plex - GUI-unabhängige Business-Logik
Wird sowohl von der GUI als auch vom Webserver verwendet
"""

import re
import logging
import tempfile
import os
from pathlib import Path
from typing import Optional, List, Tuple, Callable
from threading import Thread, Event
from queue import Queue, Empty
import urllib.request
import urllib.error

from .config import Config
from .capture import CaptureEngine
from .merge import MergeEngine
from .upscale import UpscaleEngine
from .plex_export import PlexExporter
from .frame_extraction import FrameExtractionEngine
from .cover_generation import CoverGenerationEngine


logger = logging.getLogger(__name__)


def parse_movie_folder_name(folder_name: str) -> Tuple[str, str]:
    """Extrahiert Titel und Jahr aus Ordnernamen"""
    match = re.match(r"^(.+?)\s*\((\d{4})\)$", folder_name)
    if match:
        return match.group(1).strip(), match.group(2)
    return folder_name, ""


def find_pending_movies(config: Config) -> List[Path]:
    """Findet alle Filme, die noch verarbeitet werden müssen."""
    pending_set: set[Path] = set()
    dv_root = config.get_dv_import_root()
    if not dv_root.exists():
        return []
    
    def add_if_pending(project_dir: Path):
        """Fügt Projekt hinzu, falls kein HighRes-Output existiert."""
        highres_dir = project_dir / "HighRes"
        expected_file = highres_dir / f"{project_dir.name}_4k.mp4"
        if not expected_file.exists():
            pending_set.add(project_dir)

    # 1) Klassische Struktur: DV_Import/<Projekt>/LowRes/movie_merged.*
    for movie_dir in sorted(dv_root.iterdir()):
        if not movie_dir.is_dir():
            continue
        lowres_dir = movie_dir / "LowRes"
        if not lowres_dir.exists():
            continue
        merged_files = []
        merged_files += list(lowres_dir.glob("movie_merged*.mp4"))
        merged_files += list(lowres_dir.glob("movie_merged*.avi"))
        merged_files += list(lowres_dir.glob("movie_merged*.mov"))
        merged_files += list(lowres_dir.glob("movie_merged*.mkv"))
        if merged_files:
            add_if_pending(movie_dir)

    # 2) Fallback: Suche nach movie_merged* irgendwo unter DV_Import (z.B. wenn Struktur abweicht)
    for merged_file in dv_root.glob("**/movie_merged*.*"):
        # Projektordner ist der Parent von LowRes, sonst der direkte Parent
        parent = merged_file.parent
        project_dir = parent.parent if parent.name.lower() == "lowres" else parent
        # Nur Projekte innerhalb des DV_Import akzeptieren
        try:
            project_dir.relative_to(dv_root)
        except ValueError:
            continue
        add_if_pending(project_dir)

    return sorted(pending_set)


def find_upscaled_videos(config: Config) -> List[Tuple[Path, str, str]]:
    """
    Findet alle upscaled Videos in HighRes-Ordnern
    
    Returns:
        Liste von Tupeln: (video_path, title, year)
    """
    videos = []
    dv_root = config.get_dv_import_root()
    if not dv_root.exists():
        return videos
    
    for movie_dir in sorted(dv_root.iterdir()):
        if not movie_dir.is_dir():
            continue
        highres_dir = movie_dir / "HighRes"
        if not highres_dir.exists():
            continue
        
        # Search for *_4k.mp4 files
        for video_file in highres_dir.glob("*_4k.mp4"):
            title, year = parse_movie_folder_name(movie_dir.name)
            videos.append((video_file, title, year))
    
    return videos


def find_available_videos(config: Config) -> List[Tuple[Path, str, str]]:
    """
    Findet alle verfügbaren Videos für Cover-Generierung
    Sucht in HighRes-Ordnern nach *_4k.mp4 Dateien
    
    Returns:
        Liste von Tupeln: (video_path, title, year)
    """
    return find_upscaled_videos(config)


class PostprocessingService:
    """Service für Postprocessing-Operationen"""
    
    def __init__(self, config: Config, log_callback: Optional[Callable[[str], None]] = None):
        self.config = config
        self.log_callback = log_callback or (lambda msg: logger.info(msg))
        self._running = False
        self._stop_event = Event()
        self._queue: Queue = Queue()
        self._worker_thread: Optional[Thread] = None
        self._worker_stop = Event()
    
    def _log(self, message: str):
        """Log-Nachricht ausgeben"""
        self.log_callback(message)
    
    def process_movie(
        self,
        movie_dir: Path,
        profile_name: str,
        progress_callback: Optional[Callable[[int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        finished_callback: Optional[Callable[[bool, str], None]] = None,
    ) -> Tuple[bool, str]:
        """
        Legt einen Postprocessing-Job in die Queue (Upscale vorhandenes Merge → optional Export).
        """
        self.enqueue_movie(movie_dir, profile_name, progress_callback, status_callback, finished_callback)
        return True, "Job zur Postprocessing-Queue hinzugefügt."

    def enqueue_movie(
        self,
        movie_dir: Path,
        profile_name: str,
        progress_callback: Optional[Callable[[int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        finished_callback: Optional[Callable[[bool, str], None]] = None,
    ):
        self._queue.put({
            "movie_dir": movie_dir,
            "profile_name": profile_name,
            "progress_callback": progress_callback,
            "status_callback": status_callback,
            "finished_callback": finished_callback,
        })
        self._start_worker()

    def _start_worker(self):
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._worker_stop.clear()
        self._worker_thread = Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def _worker_loop(self):
        while not self._worker_stop.is_set():
            try:
                job = self._queue.get(timeout=1)
            except Empty:
                continue

            self._running = True
            movie_dir = job["movie_dir"]
            profile_name = job["profile_name"]
            progress_callback = job.get("progress_callback")
            status_callback = job.get("status_callback")
            finished_callback = job.get("finished_callback")

            try:
                success, message = self._process_movie_now(
                    movie_dir,
                    profile_name,
                    progress_callback,
                    status_callback,
                )
                # ntfy Notify
                self._notify_ntfy(f"Upscaling {'erfolgreich' if success else 'fehlgeschlagen'}: {message}")
                if finished_callback:
                    try:
                        finished_callback(success, message)
                    except Exception:
                        logger.exception("Fehler im finished_callback")
            except Exception as e:
                logger.exception("Fehler im Postprocessing-Worker")
                self._notify_ntfy(f"Upscaling fehlgeschlagen: {e}")
            finally:
                self._running = False
                self._queue.task_done()

    def _process_movie_now(
        self,
        movie_dir: Path,
        profile_name: str,
        progress_callback: Optional[Callable[[int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None
    ) -> Tuple[bool, str]:
        title, year = parse_movie_folder_name(movie_dir.name)
        movie_name = movie_dir.name
        title = title or movie_name
        display_name = f"{title} ({year})" if year else movie_name

        if status_callback:
            status_callback(f"Postprocessing: {display_name}")
        if progress_callback:
            progress_callback(0)

        # Suche vorhandenes Merge
        self._log(f"=== Suche vorhandenes Merge: {display_name} ===")
        lowres_dir = movie_dir / "LowRes"
        merged_file = self._find_existing_merge(lowres_dir)

        if not merged_file or not merged_file.exists():
            return False, f"Kein fertiges Merge gefunden für {display_name}! Erwartet z.B. movie_merged.mp4 in {lowres_dir}"

        if progress_callback:
            progress_callback(15)

        # Timestamp-Overlay wird übersprungen (bereits im LowRes enthalten)
        self._log("Überspringe Timestamp-Overlay (bereits im LowRes enthalten).")
        if progress_callback:
            progress_callback(25)

        # Upscale
        self._log("=== Starte Upscaling ===")
        highres_dir = movie_dir / "HighRes"
        highres_dir.mkdir(parents=True, exist_ok=True)

        profile = self.config.get_upscaling_profile(profile_name)
        output_file = highres_dir / f"{movie_name}_4k.mp4"

        upscale_engine = UpscaleEngine(
            self.config.get_realesrgan_path(),
            ffmpeg_path=self.config.get_ffmpeg_path(),
            log_callback=self._log
        )

        def ffmpeg_progress_hook(pct: int):
            if progress_callback:
                mapped = 25 + int(0.65 * pct)
                progress_callback(min(90, max(25, mapped)))

        if upscale_engine.upscale(merged_file, output_file, profile, progress_hook=ffmpeg_progress_hook):
            if progress_callback:
                progress_callback(95)

            # Export
            auto_export = self.config.get("capture.auto_export", False)
            if auto_export:
                self._log("=== Starte Plex-Export ===")
                plex_exporter = PlexExporter(
                    self.config.get_plex_movies_root(),
                    log_callback=self._log
                )

                result = plex_exporter.export_movie(
                    output_file,
                    title,
                    year or ""
                )

                if result:
                    if progress_callback:
                        progress_callback(100)
                    return True, f"{display_name} exportiert: {result}"
                else:
                    return True, f"{display_name} verarbeitet (Export fehlgeschlagen)"
            else:
                if progress_callback:
                    progress_callback(100)
                return True, f"{display_name} verarbeitet: {output_file}"
        else:
            return False, f"Upscaling fehlgeschlagen für {display_name}"

    def _notify_ntfy(self, message: str):
        """Sendet eine ntfy-Benachrichtigung für Upscaling-Events."""
        try:
            req = urllib.request.Request(
                "https://ntfy.sh/dv2plex-upscale",
                data=message.encode("utf-8"),
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            self._log("ntfy-Benachrichtigung (upscale) gesendet.")
        except Exception as e:
            self._log(f"ntfy-Benachrichtigung fehlgeschlagen: {e}")

    def _find_existing_merge(self, lowres_dir: Path) -> Optional[Path]:
        """Sucht nach vorhandenen movie_merged-Dateien im LowRes-Ordner."""
        if not lowres_dir.exists():
            return None

        candidates = []
        patterns = ["movie_merged*.mp4", "movie_merged*.avi", "movie_merged*.mov", "movie_merged*.mkv"]
        for pattern in patterns:
            candidates.extend(lowres_dir.glob(pattern))

        if not candidates:
            return None

        # Wähle die neueste Datei
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]
    
    def is_running(self) -> bool:
        """Prüft ob Postprocessing läuft"""
        return self._running


class CaptureService:
    """Service für Capture-Operationen"""
    
    def __init__(
        self,
        config: Config,
        log_callback: Optional[Callable[[str], None]] = None,
        merge_progress_callback: Optional[Callable] = None,
        state_callback: Optional[Callable[[str], None]] = None,
    ):
        self.config = config
        self.log_callback = log_callback or (lambda msg: logger.info(msg))
        self.merge_progress_callback = merge_progress_callback
        self.state_callback = state_callback
        self.capture_engine: Optional[CaptureEngine] = None
        self._capture_running = False
    
    def _log(self, message: str):
        """Log-Nachricht ausgeben"""
        self.log_callback(message)
    
    def get_device(self) -> Optional[str]:
        """Ermittelt das verfügbare FireWire-Gerät"""
        ffmpeg_path = self.config.get_ffmpeg_path()
        device_path = self.config.get_firewire_device()
        
        capture_engine = CaptureEngine(
            ffmpeg_path,
            device_path=device_path,
            log_callback=self._log,
        )
        
        return capture_engine.get_device()
    
    def start_capture(
        self,
        title: str,
        year: str,
        preview_callback: Optional[Callable] = None,
        auto_rewind_play: bool = True
    ) -> Tuple[bool, Optional[str]]:
        """
        Startet eine Capture-Session
        
        Returns:
            (success, error_message)
        """
        if not title or not year:
            return False, "Titel und Jahr müssen angegeben werden"
        
        # Check device
        device = self.get_device()
        if not device:
            return False, "Kein FireWire-Gerät gefunden"
        
        # Check ffmpeg
        import shutil
        ffmpeg_path = self.config.get_ffmpeg_path()
        if not ffmpeg_path.exists() and not shutil.which("ffmpeg"):
            return False, f"ffmpeg nicht gefunden: {ffmpeg_path}"
        
        # Create work directory
        movie_name = f"{title} ({year})"
        dv_import_root = self.config.get_dv_import_root()
        # Ensure absolute path
        if not dv_import_root.is_absolute():
            dv_import_root = dv_import_root.resolve()
        
        # Ensure parent directory exists with proper permissions
        try:
            dv_import_root.mkdir(parents=True, exist_ok=True)
            # Check if we can write to the directory
            if not os.access(dv_import_root, os.W_OK):
                # Suggest alternative path in home directory
                import pathlib
                home_dv_import = Path.home() / "DV2Plex" / "DV_Import"
                return False, (
                    f"Keine Schreibberechtigung für: {dv_import_root}\n\n"
                    f"Lösung: Ändere den DV_Import-Pfad in den Einstellungen zu:\n"
                    f"{home_dv_import}\n\n"
                    f"Oder ändere die Berechtigungen mit:\n"
                    f"sudo chown -R $USER:$USER {dv_import_root}"
                )
        except PermissionError as e:
            import pathlib
            home_dv_import = Path.home() / "DV2Plex" / "DV_Import"
            return False, (
                f"Keine Berechtigung zum Erstellen des Verzeichnisses: {dv_import_root}\n\n"
                f"Lösung: Ändere den DV_Import-Pfad in den Einstellungen zu:\n"
                f"{home_dv_import}\n\n"
                f"Oder ändere die Berechtigungen mit:\n"
                f"sudo chown -R $USER:$USER {dv_import_root}"
            )
        except Exception as e:
            return False, f"Fehler beim Erstellen des Root-Verzeichnisses: {dv_import_root}. Fehler: {e}"
        
        movie_dir = dv_import_root / movie_name
        lowres_dir = movie_dir / "LowRes"
        
        try:
            # Wenn der Zielordner bereits existiert, abbrechen und klare Fehlermeldung liefern
            if lowres_dir.exists():
                return False, f"Ausgabeverzeichnis existiert bereits: {lowres_dir}. Bitte anderen Titel/Jahr wählen."
            lowres_dir.mkdir(parents=True, exist_ok=False)
        except PermissionError as e:
            return False, f"Keine Berechtigung zum Erstellen des Verzeichnisses: {lowres_dir}. Bitte prüfe die Berechtigungen oder ändere den DV_Import-Pfad in den Einstellungen."
        except Exception as e:
            return False, f"Fehler beim Erstellen des Verzeichnisses: {lowres_dir}. Fehler: {e}"
        
        # Find next part number
        existing_parts = list(lowres_dir.glob("part_*.avi"))
        if existing_parts:
            numbers = [int(p.stem.split('_')[1]) for p in existing_parts]
            part_number = max(numbers) + 1
        else:
            part_number = 1
        
        # Create or reuse capture engine (wichtig, um Rewind-Sperre zu behalten)
        if not self.capture_engine:
            self.capture_engine = CaptureEngine(
                ffmpeg_path,
                device_path=self.config.get_firewire_device(),
                log_callback=self._log,
                state_callback=self._on_capture_state,
            )
            # Setze Merge-Progress-Callback
            if self.merge_progress_callback:
                self.capture_engine.merge_progress_callback = self.merge_progress_callback
        else:
            # Update evtl. Gerätpfad falls geändert
            self.capture_engine.device_path = self.config.get_firewire_device()

        # Blockiere Start, falls Auto-Rewind noch läuft
        if self.capture_engine.is_rewind_block_active():
            remaining = self.capture_engine.get_rewind_block_remaining()
            return False, f"Auto-Rewind läuft noch {remaining} Sekunden. Bitte warten."
        
        preview_fps = self.config.get("ui.preview_fps", 10)
        
        capture_started = self.capture_engine.start_capture(
            lowres_dir,
            part_number,
            preview_callback=preview_callback,
            preview_fps=preview_fps,
            auto_rewind_play=auto_rewind_play,
            title=title,
            year=year,
        )
        
        if capture_started:
            self._capture_running = True
            return True, None
        else:
            return False, "Aufnahme konnte nicht gestartet werden"
    
    def stop_capture(self) -> bool:
        """Stoppt die laufende Capture-Session"""
        if self.capture_engine:
            result = self.capture_engine.stop_capture()
            self._capture_running = False
            return result
        return False
    
    def is_capturing(self) -> bool:
        """Prüft ob Capture läuft"""
        return self._capture_running

    def has_active_merge(self) -> bool:
        """Prüft ob ein Merge-Job aktiv oder ausstehend ist"""
        engine = getattr(self, "capture_engine", None)
        if not engine:
            return False

        # Aktiver Job
        current_job = getattr(engine, "current_merge_job", None)
        if current_job and current_job.status in ("running", "pending"):
            return True

        # Jobs in Liste oder Queue
        jobs = getattr(engine, "merge_jobs", [])
        if any(j.status in ("running", "pending") for j in jobs):
            return True

        queue = getattr(engine, "merge_queue", None)
        if queue and hasattr(queue, "empty") and not queue.empty():
            return True

        return False

    def _on_capture_state(self, state: str):
        """Callback aus CaptureEngine (z.B. stopped)"""
        if state == "stopped":
            self._capture_running = False
            if self.state_callback:
                try:
                    self.state_callback(state)
                except Exception:
                    pass
    
    def rewind_camera(self):
        """Spult die Kamera zurück"""
        if self.capture_engine:
            self.capture_engine.rewind()
    
    def play_camera(self):
        """Startet Wiedergabe auf der Kamera"""
        if self.capture_engine:
            self.capture_engine.play()
    
    def pause_camera(self):
        """Pausiert die Kamera"""
        if self.capture_engine:
            self.capture_engine.pause()


class MovieModeService:
    """Service für Movie Mode Operationen"""
    
    def __init__(self, config: Config, log_callback: Optional[Callable[[str], None]] = None):
        self.config = config
        self.log_callback = log_callback or (lambda msg: logger.info(msg))
    
    def _log(self, message: str):
        """Log-Nachricht ausgeben"""
        self.log_callback(message)
    
    def merge_videos(
        self,
        video_paths: List[Path],
        title: str,
        year: str
    ) -> Tuple[bool, Optional[Path], Optional[str]]:
        """
        Merged mehrere Videos zu einem Film
        
        Returns:
            (success, merged_file_path, error_message)
        """
        if len(video_paths) < 2:
            return False, None, "Mindestens 2 Videos erforderlich"
        
        if not title or not year:
            return False, None, "Titel und Jahr müssen angegeben werden"
        
        # Create temporary output file
        temp_dir = Path(tempfile.gettempdir()) / "dv2plex_merge"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_output = temp_dir / f"{title}_{year}_merged.mp4"
        
        try:
            # Merge
            merge_engine = MergeEngine(
                self.config.get_ffmpeg_path(),
                log_callback=self._log
            )
            
            self._log(f"=== Starte Merge: {len(video_paths)} Videos ===")
            merged_file = merge_engine.merge_videos(video_paths, temp_output)
            
            if not merged_file or not merged_file.exists():
                return False, None, "Merge fehlgeschlagen!"
            
            return True, merged_file, None
        
        except Exception as e:
            logger.exception("Fehler beim Mergen")
            return False, None, f"Fehler beim Mergen: {e}"
    
    def export_to_plex(
        self,
        video_path: Path,
        title: Optional[str] = None,
        year: Optional[str] = None,
        overwrite: bool = True
    ) -> Tuple[bool, Optional[Path], Optional[str]]:
        """
        Exportiert ein Video nach PlexMovies
        
        Returns:
            (success, exported_path, error_message)
        """
        if not video_path.exists():
            return False, None, f"Video nicht gefunden: {video_path}"
        
        try:
            plex_exporter = PlexExporter(
                self.config.get_plex_movies_root(),
                log_callback=self._log
            )
            
            result = plex_exporter.export_single_video(
                video_path,
                title,
                year,
                overwrite=overwrite
            )
            
            if result:
                return True, Path(result), None
            else:
                return False, None, "Export fehlgeschlagen"
        
        except Exception as e:
            logger.exception("Fehler beim Export")
            return False, None, f"Fehler beim Export: {e}"


class CoverService:
    """Service für Cover-Generierung"""
    
    def __init__(self, config: Config, log_callback: Optional[Callable[[str], None]] = None):
        self.config = config
        self.log_callback = log_callback or (lambda msg: logger.info(msg))
    
    def _log(self, message: str):
        """Log-Nachricht ausgeben"""
        self.log_callback(message)
    
    def extract_frames(
        self,
        video_path: Path,
        count: int = 4
    ) -> Tuple[bool, List[Path], Optional[str]]:
        """
        Extrahiert zufällige Frames aus einem Video
        
        Returns:
            (success, frame_paths, error_message)
        """
        if not video_path.exists():
            return False, [], f"Video nicht gefunden: {video_path}"
        
        try:
            frame_engine = FrameExtractionEngine(
                self.config.get_ffmpeg_path(),
                log_callback=self._log
            )
            
            frames = frame_engine.extract_random_frames(video_path, count=count)
            
            if not frames:
                return False, [], "Konnte keine Frames extrahieren"
            
            return True, frames, None
        
        except Exception as e:
            logger.exception("Fehler bei Frame-Extraktion")
            return False, [], f"Fehler bei Frame-Extraktion: {e}"
    
    def generate_cover(
        self,
        frame_path: Path,
        title: str,
        year: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None
    ) -> Tuple[bool, Optional[Path], Optional[str]]:
        """
        Generiert ein Cover aus einem Frame
        
        Returns:
            (success, cover_path, error_message)
        """
        if not frame_path.exists():
            return False, None, f"Frame nicht gefunden: {frame_path}"
        
        try:
            import tempfile
            from .plex_export import PlexExporter
            
            if progress_callback:
                progress_callback(10)
            
            if status_callback:
                status_callback("Lade Stable Diffusion Model...")
            
            # Get config values
            model_id = self.config.get("cover.default_model", "runwayml/stable-diffusion-v1-5")
            prompt = self.config.get("cover.default_prompt", "cinematic movie poster, dramatic lighting, vintage film look, high detail, professional photography")
            strength = self.config.get("cover.strength", 0.6)
            guidance_scale = self.config.get("cover.guidance_scale", 8.0)
            num_steps = self.config.get("cover.num_inference_steps", 50)
            
            # Parse output_size
            size_str = self.config.get("cover.output_size", "1000x1500")
            try:
                width, height = map(int, size_str.split("x"))
                output_size = (width, height)
            except:
                output_size = (1000, 1500)
            
            # Create CoverGenerationEngine
            cover_engine = CoverGenerationEngine(
                model_id=model_id,
                log_callback=self._log
            )
            
            if progress_callback:
                progress_callback(30)
            
            if status_callback:
                status_callback("Generiere Cover...")
            
            # Create temporary output directory
            temp_dir = Path(tempfile.gettempdir()) / "dv2plex_covers"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_cover = temp_dir / f"cover_{frame_path.stem}.jpg"
            
            # Generate cover
            result_path = cover_engine.generate_cover(
                frame_path,
                temp_cover,
                prompt=prompt,
                strength=strength,
                guidance_scale=guidance_scale,
                num_inference_steps=num_steps,
                output_size=output_size
            )
            
            if not result_path or not result_path.exists():
                return False, None, "Cover-Generierung fehlgeschlagen!"
            
            if progress_callback:
                progress_callback(80)
            
            if status_callback:
                status_callback("Speichere Cover...")
            
            # Save cover in Plex Movies folder
            plex_exporter = PlexExporter(
                self.config.get_plex_movies_root(),
                log_callback=self._log
            )
            
            saved_path = plex_exporter.save_cover(
                result_path,
                title,
                year or "",
                overwrite=True
            )
            
            if saved_path:
                if progress_callback:
                    progress_callback(100)
                return True, Path(saved_path), f"Cover erfolgreich generiert und gespeichert:\n{saved_path}"
            else:
                return False, None, "Cover generiert, aber Speicherung fehlgeschlagen!"
        
        except Exception as e:
            logger.exception("Fehler bei Cover-Generierung")
            return False, None, f"Fehler bei Cover-Generierung: {e}"

