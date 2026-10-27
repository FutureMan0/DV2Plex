"""
Service-Layer für DV2Plex - GUI-unabhängige Business-Logik
Wird vom Webserver (und damit vom Desktop-Fenster) verwendet.

The heavy cover and poster libraries (torch, diffusers, rembg, OpenCV, Playwright) are
imported only when a cover or poster is made, so the app starts without them.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Callable, Dict, List, Optional, Tuple

from .capture import CaptureEngine, MergeJob
from .config import Config
from .frame_extraction import FrameExtractionEngine
from .merge import MergeEngine, find_split_files
from .naming import InvalidName, movie_folder_name
from .naming import parse_movie_folder_name as _parse_folder
from .notifications import send_ntfy
from .plex_export import PlexExporter
from .upscale import UpscaleEngine

logger = logging.getLogger(__name__)

MERGED_PATTERNS = ("movie_merged*.mp4", "movie_merged*.avi", "movie_merged*.mov", "movie_merged*.mkv")
WORK_DIR_NAME = ".dv2plex-tmp"


def parse_movie_folder_name(folder_name: str) -> Tuple[str, str]:
    """Extrahiert Titel und Jahr aus Ordnernamen"""
    return _parse_folder(folder_name)


def find_merged_file(lowres_dir: Path) -> Optional[Path]:
    """Newest movie_merged.* in a LowRes folder, or None."""
    if not lowres_dir.is_dir():
        return None
    candidates = [p for pattern in MERGED_PATTERNS for p in lowres_dir.glob(pattern) if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def highres_file(project_dir: Path) -> Path:
    return project_dir / "HighRes" / f"{project_dir.name}_4k.mp4"


def find_pending_movies(config: Config) -> List[Path]:
    """
    Projects that still need upscaling: they have a merged film, or clips that were never
    merged (a merge that failed or was interrupted), and no upscaled film yet.
    """
    dv_root = config.get_dv_import_root()
    if not dv_root.is_dir():
        return []
    pending = []
    for project_dir in sorted(dv_root.iterdir()):
        if not project_dir.is_dir() or project_dir.name.startswith("."):
            continue
        lowres = project_dir / "LowRes"
        if not (find_merged_file(lowres) or find_split_files(lowres / "splits")):
            continue
        if not highres_file(project_dir).exists():
            pending.append(project_dir)
    return pending


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
        for video_file in sorted(highres_dir.glob("*_4k.mp4")):
            title, year = parse_movie_folder_name(movie_dir.name)
            videos.append((video_file, title, year))
    return videos


def find_available_videos(config: Config) -> List[Tuple[Path, str, str]]:
    """Videos für die Cover-Generierung (alle upgescalten Filme)."""
    return find_upscaled_videos(config)


def find_exported_plex_videos(config: Config) -> List[Tuple[Path, str, str]]:
    """
    Findet exportierte Videos in der Plex-Movie-Library (plex_movies_root).

    Erwartete Struktur: PlexMovies/<Titel (Jahr)>/<Titel (Jahr)>.mp4
    """
    videos: List[Tuple[Path, str, str]] = []
    plex_root = config.get_plex_movies_root()
    if not plex_root.exists():
        return videos

    exts = {".mp4", ".mkv", ".avi", ".mov"}
    for movie_dir in sorted(plex_root.iterdir()):
        if not movie_dir.is_dir():
            continue
        preferred = movie_dir / f"{movie_dir.name}.mp4"
        chosen: Optional[Path] = preferred if preferred.exists() else None
        if chosen is None:
            candidates = [p for p in movie_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
            if not candidates:
                continue
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            chosen = candidates[0]
        title, year = parse_movie_folder_name(movie_dir.name)
        videos.append((chosen, title, year))
    return videos


def merge_options_from(config: Config) -> Dict[str, object]:
    """Date overlay settings for a merge."""
    return {
        "timestamp_overlay": bool(config.get("capture.timestamp_overlay", True)),
        "timestamp_duration": config.get("capture.timestamp_duration", 4),
    }


class PostprocessingService:
    """Upscaling (and, if needed, merging first) and the optional export, one film at a time."""

    def __init__(
        self,
        config: Config,
        log_callback: Optional[Callable[[str], None]] = None,
        merge_busy: Optional[Callable[[Path], bool]] = None,
    ):
        self.config = config
        self.log_callback = log_callback or (lambda msg: logger.info(msg))
        # Tells whether the capture merge queue is still working on a project
        self.merge_busy = merge_busy or (lambda project_dir: False)
        self._running = False
        self._current: Optional[str] = None
        self._queue: Queue = Queue()
        self._queued: set = set()
        self._queued_lock = Lock()
        self._worker_thread: Optional[Thread] = None
        self._worker_stop = Event()

    def _log(self, message: str):
        self.log_callback(message)

    def process_movie(
        self,
        movie_dir: Path,
        profile_name: str,
        progress_callback: Optional[Callable[[int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        finished_callback: Optional[Callable[[bool, str], None]] = None,
    ) -> Tuple[bool, str]:
        """Legt einen Job in die Queue (Merge falls nötig → Upscale → optional Export)."""
        key = str(Path(movie_dir).resolve())
        with self._queued_lock:
            if key in self._queued:
                return False, f"{Path(movie_dir).name} is already queued for upscaling."
            self._queued.add(key)
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
        with self._queued_lock:
            self._queued.add(str(Path(movie_dir).resolve()))
        self._queue.put({
            "movie_dir": Path(movie_dir),
            "profile_name": profile_name,
            "progress_callback": progress_callback,
            "status_callback": status_callback,
            "finished_callback": finished_callback,
        })
        self._start_worker()

    def queued_count(self) -> int:
        return self._queue.qsize()

    def current(self) -> Optional[str]:
        return self._current

    def _start_worker(self):
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._worker_stop.clear()
        self._worker_thread = Thread(target=self._worker_loop, daemon=True, name="PostprocessWorker")
        self._worker_thread.start()

    def _worker_loop(self):
        while not self._worker_stop.is_set():
            try:
                job = self._queue.get(timeout=1)
            except Empty:
                continue

            self._running = True
            movie_dir = job["movie_dir"]
            self._current = movie_dir.name
            finished_callback = job.get("finished_callback")
            success, message = False, "Upscaling fehlgeschlagen"
            try:
                success, message = self._process_movie_now(
                    movie_dir,
                    job["profile_name"],
                    job.get("progress_callback"),
                    job.get("status_callback"),
                )
                self._notify_ntfy(f"Upscaling {'erfolgreich' if success else 'fehlgeschlagen'}: {message}")
            except Exception as e:
                logger.exception("Fehler im Postprocessing-Worker")
                message = f"Upscaling failed: {e}"
                self._notify_ntfy(f"Upscaling fehlgeschlagen: {e}")
            finally:
                self._running = False
                self._current = None
                with self._queued_lock:
                    self._queued.discard(str(movie_dir.resolve()))
                self._queue.task_done()
            if finished_callback:
                try:
                    finished_callback(success, message)
                except Exception:
                    logger.exception("Fehler im finished_callback")

    def _process_movie_now(
        self,
        movie_dir: Path,
        profile_name: str,
        progress_callback: Optional[Callable[[int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[bool, str]:
        title, year = parse_movie_folder_name(movie_dir.name)
        movie_name = movie_dir.name
        title = title or movie_name
        display_name = f"{title} ({year})" if year else movie_name

        def progress(value: int):
            if progress_callback:
                progress_callback(max(0, min(100, int(value))))

        if status_callback:
            status_callback(f"Postprocessing: {display_name}")
        progress(0)

        lowres_dir = movie_dir / "LowRes"
        merged_file = find_merged_file(lowres_dir)
        if merged_file is None:
            splits_dir = lowres_dir / "splits"
            if not find_split_files(splits_dir):
                return False, f"No merged film and no clips found for {display_name} in {lowres_dir}."
            if self.merge_busy(movie_dir):
                return False, f"{display_name} is still being merged; upscale it when the merge is done."
            self._log(f"=== Merging the clips of {display_name} first ===")
            options = merge_options_from(self.config)
            merged_file = MergeEngine(self.config.get_ffmpeg_path(), log_callback=self._log).merge_splits(
                splits_dir,
                lowres_dir / "movie_merged.mp4",
                timestamp_overlay=bool(options["timestamp_overlay"]),
                overlay_seconds=float(options["timestamp_duration"] or 4),
                progress=lambda f: progress(f * 20),
            )
            if not merged_file:
                return False, f"Merging the clips of {display_name} failed; see the log."
        progress(20)

        profile = self.config.get_upscaling_profile(profile_name)
        if not profile:
            return False, f"Upscaling profile '{profile_name}' not found."
        self._log(f"=== Upscaling {display_name} with '{profile_name}' ===")
        output_file = highres_file(movie_dir)

        upscale_engine = UpscaleEngine(
            self.config.get_realesrgan_path(),
            ffmpeg_path=self.config.get_ffmpeg_path(),
            log_callback=self._log,
        )
        if not upscale_engine.upscale(merged_file, output_file, profile, progress_hook=lambda p: progress(20 + p * 0.75)):
            return False, f"Upscaling failed for {display_name}; see the log."
        progress(95)

        if self.config.get("capture.auto_export", False):
            self._log("=== Starte Plex-Export ===")
            exporter = PlexExporter(self.config.get_plex_movies_root(), log_callback=self._log)
            result = exporter.export_movie(output_file, title, year or "", overwrite=False)
            progress(100)
            if result:
                return True, f"{display_name} exportiert: {result}"
            return True, f"{display_name} upscaled; the export did not happen (see the log)."
        progress(100)
        return True, f"{display_name} verarbeitet: {output_file}"

    def _notify_ntfy(self, message: str):
        send_ntfy(self.config, message, self._log)

    def is_running(self) -> bool:
        return self._running


class CaptureService:
    """Service für Capture-Operationen (eine CaptureEngine für die ganze Laufzeit)."""

    def __init__(
        self,
        config: Config,
        log_callback: Optional[Callable[[str], None]] = None,
        merge_progress_callback: Optional[Callable] = None,
        state_callback: Optional[Callable[[str], None]] = None,
        merge_finished_callback: Optional[Callable[[MergeJob], None]] = None,
    ):
        self.config = config
        self.log_callback = log_callback or (lambda msg: logger.info(msg))
        self.merge_progress_callback = merge_progress_callback
        self.state_callback = state_callback
        self.merge_finished_callback = merge_finished_callback
        self._capture_running = False
        # One engine, created once: it owns the merge queue and its worker thread.
        # (A new engine per status request used to start a worker thread each time.)
        self.capture_engine: CaptureEngine = CaptureEngine(
            self.config.get_ffmpeg_path(),
            device_path=self.config.get_firewire_device(),
            log_callback=self._log,
            state_callback=self._on_capture_state,
            notify_callback=self._notify,
            dvgrab_cmd=self.config.get_dvgrab_command(),
            use_sudo=self.config.get_use_sudo(),
            merge_options=lambda: merge_options_from(self.config),
            merge_finished_callback=self._on_merge_finished,
            rewind_seconds=int(self.config.get("capture.rewind_seconds", 300) or 300),
        )
        if self.merge_progress_callback:
            self.capture_engine.merge_progress_callback = self.merge_progress_callback

    def _log(self, message: str):
        self.log_callback(message)

    def _notify(self, message: str):
        """Push notification for capture and merge events, if a ntfy topic is set."""
        send_ntfy(self.config, message, self._log)

    def _on_merge_finished(self, job: MergeJob):
        if self.merge_finished_callback:
            self.merge_finished_callback(job)

    def _refresh_engine_settings(self):
        """Settings may have changed in the UI since the engine was created."""
        engine = self.capture_engine
        engine.ffmpeg_path = self.config.get_ffmpeg_path()
        engine.device_path = self.config.get_firewire_device()
        engine.dvgrab_cmd = self.config.get_dvgrab_command()
        engine.use_sudo = self.config.get_use_sudo()

    def get_device(self) -> Optional[str]:
        """Ermittelt das verfügbare FireWire-Gerät"""
        self._refresh_engine_settings()
        return self.capture_engine.get_device()

    def start_capture(
        self,
        title: str,
        year: str,
        preview_callback: Optional[Callable] = None,
        auto_rewind_play: bool = True,
    ) -> Tuple[bool, Optional[str]]:
        """
        Startet eine Capture-Session

        Returns:
            (success, error_message)
        """
        try:
            movie_name = movie_folder_name(title, year)
        except InvalidName as e:
            return False, str(e)

        self._refresh_engine_settings()
        device = self.capture_engine.get_device()
        if not device:
            return False, "No FireWire device found. Connect the camera, switch it to playback (VCR) and check the cable."

        ffmpeg_path = self.config.get_ffmpeg_path()
        if not ffmpeg_path.exists() and not shutil.which("ffmpeg"):
            return False, f"ffmpeg not found ({ffmpeg_path}). Install ffmpeg or set its path in the settings."

        dv_import_root = self.config.get_dv_import_root()
        home_dv_import = Path.home() / "DV2Plex" / "DV_Import"
        try:
            dv_import_root.mkdir(parents=True, exist_ok=True)
            if not os.access(dv_import_root, os.W_OK):
                return False, (
                    f"No write permission for {dv_import_root}. Choose a folder you own in the settings, "
                    f"for example {home_dv_import}, or fix the owner: sudo chown -R $USER:$USER {dv_import_root}"
                )
        except PermissionError:
            return False, (
                f"No permission to create {dv_import_root}. Choose a folder you own in the settings, "
                f"for example {home_dv_import}."
            )
        except OSError as e:
            return False, f"Could not create {dv_import_root}: {e}"

        movie_dir = dv_import_root / movie_name
        lowres_dir = movie_dir / "LowRes"
        try:
            if lowres_dir.exists():
                return False, f"A project named '{movie_name}' already exists. Choose another title or year."
            lowres_dir.mkdir(parents=True, exist_ok=False)
        except PermissionError:
            return False, f"No permission to create {lowres_dir}. Check the owner of the import folder."
        except OSError as e:
            return False, f"Could not create {lowres_dir}: {e}"

        if self.capture_engine.is_rewind_block_active():
            remaining = self.capture_engine.get_rewind_block_remaining()
            return False, f"The tape is still rewinding for {remaining} seconds. Please wait."

        preview_fps = self.config.get("ui.preview_fps", 10)
        clean_title, clean_year = parse_movie_folder_name(movie_name)
        capture_started = self.capture_engine.start_capture(
            lowres_dir,
            1,
            preview_callback=preview_callback,
            preview_fps=preview_fps,
            auto_rewind_play=auto_rewind_play,
            title=clean_title,
            year=clean_year,
        )
        if capture_started:
            self._capture_running = True
            return True, None

        # Nothing was recorded: remove the empty folders so the same title can be tried again
        try:
            if not any(p.is_file() for p in lowres_dir.rglob("*")):
                shutil.rmtree(lowres_dir)
                if not any(movie_dir.iterdir()):
                    movie_dir.rmdir()
        except OSError:
            pass
        detail = getattr(self.capture_engine, "last_dvgrab_error", None)
        return False, detail or "Capture could not be started; see the log."

    def stop_capture(self) -> bool:
        """Stoppt die laufende Capture-Session"""
        result = self.capture_engine.stop_capture()
        self._capture_running = False
        return result

    def is_capturing(self) -> bool:
        return self._capture_running

    def has_active_merge(self) -> bool:
        """Prüft ob ein Merge-Job aktiv oder ausstehend ist"""
        engine = self.capture_engine
        current_job = getattr(engine, "current_merge_job", None)
        if current_job and current_job.status in ("running", "pending"):
            return True
        if any(j.status in ("running", "pending") for j in getattr(engine, "merge_jobs", [])):
            return True
        queue = getattr(engine, "merge_queue", None)
        return bool(queue and not queue.empty())

    def is_merging(self, project_dir: Path) -> bool:
        """Whether a merge for this project is queued or running."""
        target = Path(project_dir).resolve()
        for job in getattr(self.capture_engine, "merge_jobs", []):
            if job.status in ("running", "pending"):
                try:
                    if Path(job.splits_dir).resolve().parent.parent == target:
                        return True
                except OSError:
                    continue
        return False

    def _on_capture_state(self, state: str):
        if state == "stopped":
            self._capture_running = False
            if self.state_callback:
                try:
                    self.state_callback(state)
                except Exception:
                    pass

    def rewind_camera(self) -> bool:
        self._refresh_engine_settings()
        return bool(self.capture_engine.rewind())

    def play_camera(self) -> bool:
        self._refresh_engine_settings()
        return bool(self.capture_engine.play())

    def pause_camera(self) -> bool:
        self._refresh_engine_settings()
        return bool(self.capture_engine.pause())


class MovieModeService:
    """Merging finished films and exporting to Plex."""

    def __init__(self, config: Config, log_callback: Optional[Callable[[str], None]] = None):
        self.config = config
        self.log_callback = log_callback or (lambda msg: logger.info(msg))

    def _log(self, message: str):
        self.log_callback(message)

    def merge_videos(
        self,
        video_paths: List[Path],
        title: str,
        year: str,
    ) -> Tuple[bool, Optional[Path], Optional[str]]:
        """
        Merged mehrere Videos zu einem Film

        Returns:
            (success, merged_file_path, error_message)
        """
        if len(video_paths) < 2:
            return False, None, "Select at least two videos."
        try:
            name = movie_folder_name(title, year)
        except InvalidName as e:
            return False, None, str(e)

        # Next to the films, not in /tmp: 4K films do not fit a small temp partition
        work_dir = self.config.get_dv_import_root() / WORK_DIR_NAME
        work_dir.mkdir(parents=True, exist_ok=True)
        temp_output = work_dir / f"{name}_merged.mp4"
        try:
            merged_file = MergeEngine(self.config.get_ffmpeg_path(), log_callback=self._log).merge_videos(
                list(video_paths), temp_output
            )
            if not merged_file or not merged_file.exists():
                return False, None, "Merge failed; see the log."
            return True, merged_file, None
        except Exception as e:
            logger.exception("Fehler beim Mergen")
            return False, None, f"Merge failed: {e}"

    def export_to_plex(
        self,
        video_path: Path,
        title: Optional[str] = None,
        year: Optional[str] = None,
        overwrite: bool = True,
    ) -> Tuple[bool, Optional[Path], Optional[str]]:
        """
        Exportiert ein Video nach PlexMovies

        Returns:
            (success, exported_path, error_message)
        """
        if not video_path.exists():
            return False, None, f"Video not found: {video_path}"
        try:
            exporter = PlexExporter(self.config.get_plex_movies_root(), log_callback=self._log)
            result = exporter.export_single_video(video_path, title, year, overwrite=overwrite)
            if result:
                return True, Path(result), None
            return False, None, "Export failed; see the log."
        except Exception as e:
            logger.exception("Fehler beim Export")
            return False, None, f"Export failed: {e}"


def _load_full_poster_engine():
    """The full poster generator, or None with the reason if its libraries are missing."""
    try:
        from .poster_generation import PosterGenerationEngine  # cv2, rembg, scikit-learn, Playwright
    except ImportError as e:
        return None, str(e)
    return PosterGenerationEngine, None


class CoverService:
    """Service für Cover- und Poster-Generierung"""

    def __init__(self, config: Config, log_callback: Optional[Callable[[str], None]] = None):
        self.config = config
        self.log_callback = log_callback or (lambda msg: logger.info(msg))
        self._running = False
        self._queue: Queue = Queue()
        self._worker_thread: Optional[Thread] = None
        self._worker_stop = Event()

    def _log(self, message: str):
        self.log_callback(message)

    def extract_frames(self, video_path: Path, count: int = 4) -> Tuple[bool, List[Path], Optional[str]]:
        """Extrahiert zufällige Frames aus einem Video"""
        if not video_path.exists():
            return False, [], f"Video not found: {video_path}"
        try:
            frames = FrameExtractionEngine(self.config.get_ffmpeg_path(), log_callback=self._log).extract_random_frames(
                video_path, count=count
            )
            if not frames:
                return False, [], "No frames could be extracted."
            return True, frames, None
        except Exception as e:
            logger.exception("Fehler bei Frame-Extraktion")
            return False, [], f"Frame extraction failed: {e}"

    def generate_cover(
        self,
        frame_path: Path,
        title: str,
        year: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[bool, Optional[Path], Optional[str]]:
        """Generiert ein Cover aus einem Frame mit Stable Diffusion (benötigt torch und diffusers)."""
        if not frame_path.exists():
            return False, None, f"Frame not found: {frame_path}"
        try:
            from .cover_generation import CoverGenerationEngine
        except ImportError as e:
            return False, None, f"Stable Diffusion covers need torch, diffusers and Pillow ({e})."
        try:
            import tempfile

            if progress_callback:
                progress_callback(10)
            if status_callback:
                status_callback("Lade Stable Diffusion Model...")

            size_str = str(self.config.get("cover.output_size", "1000x1500"))
            try:
                width, height = map(int, size_str.lower().split("x"))
                output_size = (width, height)
            except ValueError:
                output_size = (1000, 1500)

            cover_engine = CoverGenerationEngine(
                model_id=self.config.get("cover.default_model", "stable-diffusion-v1-5/stable-diffusion-v1-5"),
                log_callback=self._log,
            )
            if progress_callback:
                progress_callback(30)
            if status_callback:
                status_callback("Generiere Cover...")

            temp_dir = Path(tempfile.gettempdir()) / "dv2plex_covers"
            temp_dir.mkdir(parents=True, exist_ok=True)
            result_path = cover_engine.generate_cover(
                frame_path,
                temp_dir / f"cover_{frame_path.stem}.jpg",
                prompt=self.config.get("cover.default_prompt", CoverGenerationEngine.DEFAULT_PROMPT),
                strength=self.config.get("cover.strength", 0.6),
                guidance_scale=self.config.get("cover.guidance_scale", 8.0),
                num_inference_steps=self.config.get("cover.num_inference_steps", 50),
                output_size=output_size,
            )
            if not result_path or not result_path.exists():
                return False, None, "Cover generation failed; see the log."
            if progress_callback:
                progress_callback(80)

            saved_path = PlexExporter(self.config.get_plex_movies_root(), log_callback=self._log).save_cover(
                result_path, title, year or "", overwrite=True
            )
            if saved_path:
                if progress_callback:
                    progress_callback(100)
                return True, Path(saved_path), f"Cover saved: {saved_path}"
            return False, None, "Cover generated, but saving it failed."
        except Exception as e:
            logger.exception("Fehler bei Cover-Generierung")
            return False, None, f"Cover generation failed: {e}"

    def generate_poster(
        self,
        video_path: Path,
        title: str,
        year: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[bool, Optional[Path], Optional[str]]:
        """
        Makes poster.jpg next to the film.

        cover.poster_engine: "auto" uses the full generator when its libraries are installed
        and the simple one otherwise; "full" or "simple" force one of them.
        """
        if not video_path.exists():
            return False, None, f"Video not found: {video_path}"
        if progress_callback:
            progress_callback(10)
        if status_callback:
            status_callback("Extrahiere besten Frame...")
        output_path = video_path.parent / "poster.jpg"

        choice = str(self.config.get("cover.poster_engine", "auto") or "auto").lower()
        engine_class, missing = (None, "simple poster chosen") if choice == "simple" else _load_full_poster_engine()
        try:
            if engine_class is not None:
                template_path = Path(__file__).parent / "resources" / "poster_template.html"
                engine = engine_class(template_path=template_path if template_path.exists() else None, log_callback=self._log)
                if progress_callback:
                    progress_callback(30)
                if status_callback:
                    status_callback("Generiere Poster...")
                poster_path = engine.generate_poster(video_path, title, year, output_path=output_path, size=(3000, 4500))
            elif choice == "full":
                return False, None, f"The full poster generator needs rembg, OpenCV, scikit-learn and Playwright ({missing})."
            else:
                from .simple_poster import make_simple_poster

                if choice != "simple":
                    self._log(f"Full poster generator not available ({missing}); making a simple poster.")
                if progress_callback:
                    progress_callback(30)
                poster_path = make_simple_poster(
                    video_path, title, year, output_path, ffmpeg_path=self.config.get_ffmpeg_path(), log=self._log
                )
            if not poster_path or not Path(poster_path).exists():
                return False, None, "Poster generation failed; see the log."
            if progress_callback:
                progress_callback(100)
            if status_callback:
                status_callback("Poster erfolgreich generiert!")
            return True, Path(poster_path), f"Poster saved: {poster_path}"
        except Exception as e:
            logger.exception("Fehler bei Poster-Generierung")
            return False, None, f"Poster generation failed: {e}"

    def enqueue_poster(
        self,
        video_path: Path,
        title: str,
        year: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        finished_callback: Optional[Callable[[bool, str, Optional[Path]], None]] = None,
    ):
        """Fügt einen Poster-Generierungs-Job zur Queue hinzu"""
        self._queue.put({
            "video_path": video_path,
            "title": title,
            "year": year,
            "progress_callback": progress_callback,
            "status_callback": status_callback,
            "finished_callback": finished_callback,
        })
        self._start_worker()

    def _start_worker(self):
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._worker_stop.clear()
        self._worker_thread = Thread(target=self._worker_loop, daemon=True, name="PosterWorker")
        self._worker_thread.start()

    def _worker_loop(self):
        while not self._worker_stop.is_set():
            try:
                job = self._queue.get(timeout=1)
            except Empty:
                continue

            self._running = True
            finished_callback = job.get("finished_callback")
            try:
                self._log(f"Starte Poster-Generierung für: {job['title']} ({job.get('year')}) - {job['video_path']}")
                success, poster_path, message = self.generate_poster(
                    job["video_path"],
                    job["title"],
                    job.get("year"),
                    progress_callback=job.get("progress_callback"),
                    status_callback=job.get("status_callback"),
                )
                self._log(message or "")
                if finished_callback:
                    try:
                        finished_callback(success, message or "", poster_path)
                    except Exception:
                        logger.exception("Fehler im finished_callback")
            except Exception as e:
                logger.exception("Fehler im Poster-Worker")
                if finished_callback:
                    try:
                        finished_callback(False, f"Poster generation failed: {e}", None)
                    except Exception:
                        pass
            finally:
                self._running = False
                self._queue.task_done()

    def is_running(self) -> bool:
        return self._running
