"""
Live preview during a capture.

dvgrab writes one clip per scene. A monitor thread puts each new clip into a queue once it
stops growing; a worker plays the queued clips through ffmpeg as a stream of JPEG frames
and hands each frame (raw JPEG bytes) to the preview callback, which the web server sends
to the browser.
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from queue import Empty, Queue
from typing import Callable, List, Optional

from ..media import popen_kwargs
from .processes import terminate_process

JPEG_START = b"\xff\xd8"
JPEG_END = b"\xff\xd9"
MIN_CLIP_BYTES = 300 * 1024  # a few DV frames


def clip_files(splits_dir: Path) -> set:
    """The dvgrab clips in the folder (dvgrab*.avi or .dv)."""
    return set(splits_dir.glob("dvgrab*.avi")) | set(splits_dir.glob("dvgrab*.dv"))


def split_jpeg_frames(buffer: bytearray) -> List[bytes]:
    """Takes every complete JPEG off the front of the buffer and returns them."""
    frames = []
    while True:
        start = buffer.find(JPEG_START)
        if start == -1:
            if len(buffer) > 500_000:
                del buffer[:]
            break
        if start > 0:
            del buffer[:start]
        end = buffer.find(JPEG_END, 2)
        if end == -1:
            break
        frames.append(bytes(buffer[: end + 2]))
        del buffer[: end + 2]
    return frames


class PreviewPipeline:
    """Preview threads of one capture."""

    def __init__(self, ffmpeg_path: Callable[[], Path], log: Callable[[str], None], is_capturing: Callable[[], bool]):
        self._ffmpeg_path = ffmpeg_path
        self.log = log
        self._is_capturing = is_capturing
        self.callback: Optional[Callable[[bytes], None]] = None
        self.fps = 10
        self.splits_dir: Optional[Path] = None
        self.queue: Queue = Queue()
        self.stop_event: Optional[threading.Event] = None
        self.monitor_thread: Optional[threading.Thread] = None
        self.worker_thread: Optional[threading.Thread] = None
        self.on_new_clip: Optional[Callable[[Path], None]] = None

    def start(self, splits_dir: Path, callback: Callable[[bytes], None], fps: int) -> None:
        self.splits_dir = splits_dir
        self.callback = callback
        # Too many frames per second make the browser flicker
        self.fps = max(5, min(int(fps or 10), 15))
        self.queue = Queue()
        self.stop_event = threading.Event()
        self.log("=== Starte Preview-Queue-System ===")
        self.monitor_thread = threading.Thread(target=self._monitor, daemon=True, name="PreviewMonitor")
        self.monitor_thread.start()
        self.worker_thread = threading.Thread(target=self._work, daemon=True, name="PreviewWorker")
        self.worker_thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        if self.stop_event:
            self.stop_event.set()
        for thread in (self.monitor_thread, self.worker_thread):
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=timeout)
        self.monitor_thread = None
        self.worker_thread = None
        self.stop_event = None

    def _stopped(self) -> bool:
        return bool(self.stop_event and self.stop_event.is_set())

    # ------------------------------------------------------------------ threads

    def _monitor(self) -> None:
        """Queues each new clip once it is completely written."""
        assert self.splits_dir is not None
        self.log("Preview-Queue-Monitor: Starte Überwachung...")
        known: set = set()
        try:
            while self._is_capturing() and not self._stopped():
                for path in clip_files(self.splits_dir) - known:
                    if self._wait_until_complete(path):
                        self.queue.put(path)
                        known.add(path)
                        if self.on_new_clip:
                            self.on_new_clip(path)
                        self.log(f"Preview-Queue: Neue Datei hinzugefügt: {path.name}")
                time.sleep(0.5)
        except Exception as e:
            self.log(f"Preview-Queue-Monitor: Fehler: {e}")
        finally:
            self.log("Preview-Queue-Monitor: Beendet")

    def _work(self) -> None:
        """Plays each queued clip to the end."""
        self.log("Preview-Queue-Worker: Starte...")
        while True:
            if self._stopped() and self.queue.empty():
                break
            try:
                path = self.queue.get(timeout=1.0)
            except Empty:
                if not self._is_capturing():
                    break
                continue
            try:
                self._play(path)
            except Exception as e:
                self.log(f"Preview-Queue-Worker: Fehler: {e}")
            finally:
                self.queue.task_done()
        self.log("Preview-Queue-Worker: Beendet")

    # ------------------------------------------------------------------ playing a clip

    @staticmethod
    def _wait_until_complete(path: Path, max_wait: float = 5.0) -> bool:
        """True once the file stops growing (or has data after max_wait)."""
        waited = 0.0
        while waited < max_wait:
            try:
                before = path.stat().st_size
            except OSError:
                return False
            time.sleep(0.5)
            waited += 0.5
            try:
                after = path.stat().st_size
            except OSError:
                return False
            if before == after and before > 0:
                return True
        try:
            return path.stat().st_size > 0
        except OSError:
            return False

    def _commands(self, path: Path) -> List[tuple]:
        ffmpeg = str(self._ffmpeg_path())
        # Square pixels, so a 4:3 tape looks 4:3 in the browser (DV stores 720 x 576)
        scale = "scale=trunc(iw*sar/2)*2:ih,scale=640:-2,setsar=1"
        video = ["-vf", f"yadif,fps={self.fps},{scale}", "-vcodec", "mjpeg", "-f", "image2pipe"]
        return [
            # AVI or DV in a container
            ("avi", [ffmpeg, "-hide_banner", "-loglevel", "error", "-fflags", "+genpts+igndts",
                     "-analyzeduration", "10000000", "-probesize", "10000000", "-i", str(path),
                     *video, "-q:v", "5", "-"]),
            # raw DV (no index, .dv)
            ("raw-dv", [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "dv", "-i", str(path),
                        *video, "-q:v", "5", "-"]),
            # damaged: ignore errors
            ("fallback", [ffmpeg, "-hide_banner", "-loglevel", "warning", "-err_detect", "ignore_err",
                          "-fflags", "+genpts+discardcorrupt", "-i", str(path), *video, "-q:v", "7", "-"]),
        ]

    def _launch(self, path: Path) -> Optional[subprocess.Popen]:
        for name, cmd in self._commands(path):
            self.log(f"Preview: ffmpeg {name} startet für {path.name}")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0, **popen_kwargs())
            time.sleep(0.3)
            if process.poll() is None:
                return process
            self.log(f"Preview-ffmpeg ({name}) für {path.name} sofort beendet mit Code {process.returncode}")
        return None

    def _play(self, path: Path) -> None:
        if not path.exists() or not self.callback:
            return
        # Wait until the clip has a few frames
        waited = 0.0
        while waited < 10:
            try:
                if path.stat().st_size >= MIN_CLIP_BYTES:
                    break
            except OSError:
                return
            if self._stopped():
                return
            time.sleep(0.5)
            waited += 0.5
        else:
            self.log(f"Preview: Datei {path.name} zu klein nach 10s Warten")
            return

        process = self._launch(path)
        if not process:
            self.log(f"Preview: Konnte Datei nicht abspielen: {path.name}")
            return
        self.log(f"Preview: Spiele Datei ab: {path.name}")
        try:
            self._read_frames(process, path)
        finally:
            terminate_process(process)

    def _read_frames(self, process: subprocess.Popen, path: Path) -> None:
        assert process.stdout is not None
        buffer = bytearray()
        interval = 1.0 / max(self.fps, 5)
        last_sent = 0.0
        sent = 0
        try:
            while not self._stopped():
                chunk = process.stdout.read(8192)
                if not chunk:  # ffmpeg reached the end of the clip
                    break
                buffer.extend(chunk)
                for frame in split_jpeg_frames(buffer):
                    now = time.time()
                    if now - last_sent >= interval and self.callback:
                        try:
                            self.callback(frame)
                        except Exception as e:
                            self.log(f"Preview: Fehler bei Frame-Callback: {e}")
                        sent += 1
                        last_sent = now
        finally:
            self.log(f"Preview: Beendet - {sent} frames gesendet ({path.name})")
            try:
                process.stdout.close()
            except OSError:
                pass
