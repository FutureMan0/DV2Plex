"""
The background merge queue: after each capture the tape's clips are joined into one film,
one job at a time, while the next tape can already be captured.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Dict, List, Optional

from ..merge import MergeEngine


class MergeJob:
    """One tape waiting for or going through the merge."""

    def __init__(self, splits_dir: Path, output_path: Path, title: str = "", year: str = ""):
        self.splits_dir = splits_dir
        self.output_path = output_path
        self.title = title
        self.year = year
        self.status = "pending"  # pending, running, completed, failed
        self.progress = 0  # 0-100
        self.message = ""
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None
        self.result_path: Optional[Path] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "year": self.year,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
        }


class MergeQueue:
    """Runs merge jobs one after another in a background thread."""

    def __init__(
        self,
        ffmpeg_path: Callable[[], Path],
        log: Callable[[str], None],
        options: Callable[[], Dict[str, Any]],
        notify: Callable[[str], None],
        finished_callback: Optional[Callable[[MergeJob], None]] = None,
    ):
        self._ffmpeg_path = ffmpeg_path
        self.log = log
        self.options = options
        self.notify = notify
        self.finished_callback = finished_callback
        self.progress_callback: Optional[Callable[[MergeJob], None]] = None
        self.queue: Queue = Queue()
        self.jobs: List[MergeJob] = []
        self.current: Optional[MergeJob] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ control

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="MergeWorker")
        self._thread.start()
        self.log("Background-Merge-Worker gestartet")

    def stop(self) -> None:
        self._stop.set()

    def add(self, splits_dir: Path, output_path: Path, title: str = "", year: str = "") -> MergeJob:
        job = MergeJob(splits_dir, output_path, title, year)
        self.jobs.append(job)
        self.queue.put(job)
        self.log(f"Merge-Job zur Queue hinzugefügt: {title} ({year})")
        return job

    def status(self) -> Dict[str, Any]:
        running = self.current
        return {
            "pending_count": sum(1 for j in self.jobs if j.status == "pending"),
            "current_job": running.as_dict() if running else None,
            "completed_count": sum(1 for j in self.jobs if j.status in ("completed", "failed")),
            "jobs": [j.as_dict() for j in self.jobs[-10:]],  # Letzte 10 Jobs
        }

    def clear_completed(self) -> None:
        self.jobs = [j for j in self.jobs if j.status in ("pending", "running")]

    # ------------------------------------------------------------------ worker

    def _report(self, job: MergeJob) -> None:
        if self.progress_callback:
            try:
                self.progress_callback(job)
            except Exception as e:
                self.log(f"Merge-Progress-Callback Fehler: {e}")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self.queue.get(timeout=1.0)
            except Empty:
                continue
            try:
                self._process(job)
            except Exception as e:  # keep the worker alive whatever happens
                self.log(f"Merge-Worker Fehler: {e}")
        self.log("Background-Merge-Worker beendet")

    def _process(self, job: MergeJob) -> None:
        self.current = job
        job.status = "running"
        job.started_at = time.time()
        job.message = "Merge gestartet..."
        self._report(job)
        try:
            self.log(f"Background-Merge: Starte {job.title} ({job.year})")
            try:
                options = dict(self.options() or {})
            except Exception as e:
                self.log(f"Merge settings could not be read, using defaults: {e}")
                options = {}
            last_sent = [0.0]

            def on_progress(fraction: float) -> None:
                job.progress = int(fraction * 100)
                # At most every 2 seconds, so the WebSocket is not flooded
                if time.time() - last_sent[0] >= 2 or job.progress >= 100:
                    last_sent[0] = time.time()
                    self._report(job)

            merged_file = MergeEngine(self._ffmpeg_path(), log_callback=self.log).merge_splits(
                job.splits_dir,
                job.output_path,
                timestamp_overlay=bool(options.get("timestamp_overlay", True)),
                overlay_seconds=float(options.get("timestamp_duration", 4) or 4),
                progress=on_progress,
            )
            job.completed_at = time.time()
            if merged_file and merged_file.exists():
                job.status = "completed"
                job.progress = 100
                job.result_path = merged_file
                job.message = f"Merge abgeschlossen: {merged_file.name}"
                self.log(f"Background-Merge erfolgreich: {merged_file}")
                self.notify(f"Merge abgeschlossen: {job.title} ({job.year})")
            else:
                job.status = "failed"
                job.message = "Merge fehlgeschlagen"
                self.log(f"Background-Merge fehlgeschlagen: {job.title}")
                self.notify(f"Merge fehlgeschlagen: {job.title} ({job.year})")
        except Exception as e:
            job.status = "failed"
            job.message = f"Fehler: {e}"
            job.completed_at = time.time()
            self.log(f"Background-Merge Fehler: {e}")
            self.notify(f"Merge Fehler: {job.title} - {e}")
        finally:
            self._report(job)
            self.current = None
            self.queue.task_done()
            if self.finished_callback:
                try:
                    self.finished_callback(job)
                except Exception as e:
                    self.log(f"Merge-finished callback failed: {e}")
