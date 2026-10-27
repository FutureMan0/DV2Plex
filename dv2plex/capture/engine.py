"""
Capture engine: records a MiniDV tape over FireWire with dvgrab (Linux).

The flow of one capture:

1. start_capture(): the recording dvgrab writes one clip per scene into LowRes/splits/,
   the preview pipeline shows the clips live, a monitor thread waits for dvgrab to end
2. the tape ends (dvgrab exits) or the user stops (stop_capture(), like Ctrl+C)
3. finalize once: the camera rewinds (and blocks new captures meanwhile), the clips go
   into the merge queue, a notification is sent after the rewind

Camera control (rewind, play, pause) uses a second, interactive dvgrab.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..merge import find_split_files
from .dvgrab import Dvgrab
from .merge_queue import MergeJob, MergeQueue
from .preview import PreviewPipeline, clip_files
from .processes import interrupt_process, terminate_process


class CaptureEngine:
    """Verwaltet DV-Capture über dvgrab (Linux)"""

    def __init__(
        self,
        ffmpeg_path: Path,
        device_path: Optional[str] = None,
        dvgrab_path: str = "dvgrab",
        log_callback: Optional[Callable[[str], None]] = None,
        state_callback: Optional[Callable[[str], None]] = None,
        notify_callback: Optional[Callable[[str], None]] = None,
        dvgrab_cmd: Optional[List[str]] = None,
        use_sudo: Optional[bool] = None,
        merge_options: Optional[Callable[[], Dict[str, Any]]] = None,
        merge_finished_callback: Optional[Callable[[MergeJob], None]] = None,
        rewind_seconds: int = 300,
    ):
        self.ffmpeg_path = ffmpeg_path
        self.device_path = device_path
        self.log_callback = log_callback
        self.state_callback = state_callback
        # Push notification (ntfy); sends only when a topic is set
        self.notify_callback = notify_callback
        self.logger = logging.getLogger(__name__)

        self.dvgrab = Dvgrab(list(dvgrab_cmd) if dvgrab_cmd else [dvgrab_path], use_sudo, self.log)
        self.preview = PreviewPipeline(lambda: self.ffmpeg_path, self.log, lambda: self.is_capturing)
        self.preview.on_new_clip = lambda path: setattr(self, "last_split_time", time.time())
        self.merger = MergeQueue(
            ffmpeg_path=lambda: self.ffmpeg_path,
            log=self.log,
            options=merge_options or (lambda: {}),
            notify=self._notify_completion,
            finished_callback=merge_finished_callback,
        )

        self.is_capturing = False
        # Set by stop_capture(): the monitor thread must not finalize a second time
        self._stop_requested = False
        self.recording_dvgrab_process: Optional[subprocess.Popen] = None
        self.interactive_dvgrab_process: Optional[subprocess.Popen] = None
        self.capture_thread: Optional[threading.Thread] = None
        self.inactivity_thread: Optional[threading.Thread] = None
        self.splits_dir: Optional[Path] = None
        self.current_output_path: Optional[Path] = None
        self.current_capture_title = ""
        self.current_capture_year = ""
        self.last_split_time: Optional[float] = None

        # The camera rewinds after each capture; meanwhile no new capture and no control
        self.rewind_notification_delay_seconds = int(rewind_seconds)
        self.rewind_block_until: Optional[float] = None
        self.rewind_block_timer: Optional[threading.Timer] = None
        self.rewind_block_active = False

        self.capture_start_time: Optional[float] = None
        self._duration_stop: Optional[threading.Event] = None
        self._duration_thread: Optional[threading.Thread] = None

        self.merger.start()

    # ------------------------------------------------------------------ settings and status

    @property
    def dvgrab_cmd(self) -> List[str]:
        return self.dvgrab.command

    @dvgrab_cmd.setter
    def dvgrab_cmd(self, value: List[str]) -> None:
        self.dvgrab.command = list(value)

    @property
    def use_sudo(self) -> bool:
        return self.dvgrab.use_sudo

    @use_sudo.setter
    def use_sudo(self, value: Optional[bool]) -> None:
        from .processes import default_use_sudo

        self.dvgrab.use_sudo = default_use_sudo() if value is None else bool(value)

    @property
    def last_dvgrab_error(self) -> Optional[str]:
        return self.dvgrab.last_error

    @property
    def last_dvgrab_command(self) -> Optional[List[str]]:
        return self.dvgrab.last_command

    @property
    def process(self) -> Optional[subprocess.Popen]:
        """The recording dvgrab (older name)."""
        return self.recording_dvgrab_process

    # The merge queue, as the service and the update manager see it
    @property
    def merge_jobs(self) -> List[MergeJob]:
        return self.merger.jobs

    @property
    def merge_queue(self):
        return self.merger.queue

    @property
    def current_merge_job(self) -> Optional[MergeJob]:
        return self.merger.current

    @property
    def merge_progress_callback(self):
        return self.merger.progress_callback

    @merge_progress_callback.setter
    def merge_progress_callback(self, callback) -> None:
        self.merger.progress_callback = callback

    def queue_merge_job(self, splits_dir: Path, output_path: Path, title: str = "", year: str = "") -> MergeJob:
        return self.merger.add(splits_dir, output_path, title, year)

    def get_merge_queue_status(self) -> dict:
        return self.merger.status()

    def clear_completed_merge_jobs(self) -> None:
        self.merger.clear_completed()

    def _sudo_prefix(self) -> List[str]:
        return self.dvgrab.sudo_prefix()

    def _format_device_for_dvgrab(self, device: str) -> List[str]:
        return Dvgrab.device_args(device)

    def detect_firewire_device(self) -> Optional[str]:
        return self.dvgrab.detect_device()

    def get_device(self) -> Optional[str]:
        """Gibt das zu verwendende Gerät zurück (automatisch erkannt oder konfiguriert)"""
        return self.device_path or self.dvgrab.detect_device()

    def get_current_output_path(self) -> Optional[Path]:
        return self.current_output_path

    def is_active(self) -> bool:
        return self.is_capturing

    # ------------------------------------------------------------------ camera control

    def _ensure_interactive(self) -> bool:
        process = self.interactive_dvgrab_process
        if process and process.poll() is None:
            return True
        device = self.get_device()
        if not device:
            self.log("Kein FireWire-Gerät verfügbar!")
            return False
        self.interactive_dvgrab_process = self.dvgrab.start_interactive(device)
        if not self.interactive_dvgrab_process:
            self.log("FEHLER: Interaktiver dvgrab konnte nicht gestartet werden")
            return False
        return True

    def _send_interactive_command(self, command: str) -> bool:
        """Sends one key to the interactive dvgrab (a, p, k or Esc)."""
        process = self.interactive_dvgrab_process
        if not process or process.poll() is not None or not process.stdin:
            self.log("Interaktiver Modus nicht aktiv - starte ihn zuerst")
            return False
        try:
            process.stdin.write(command.encode("utf-8"))
            process.stdin.flush()
            return True
        except (BrokenPipeError, OSError) as e:
            self.log(f"Fehler beim Senden des Befehls '{command}': {e}")
            return False

    def _control(self, key: str, name: str) -> bool:
        if self._is_rewind_block_active():
            self.log(f"{name} gesperrt für {self._remaining_rewind_block_seconds()} Sekunden (Auto-Rewind läuft).")
            return False
        if not self._ensure_interactive():
            return False
        return self._send_interactive_command(key)

    def rewind(self) -> bool:
        """Spult die Kassette zurück (interaktiver Modus: 'a')"""
        return self._control("a", "Rewind")

    def play(self) -> bool:
        """Startet die Wiedergabe (interaktiver Modus: 'p')"""
        return self._control("p", "Play")

    def pause(self) -> bool:
        """Pausiert die Wiedergabe (interaktiver Modus: 'k')"""
        return self._control("k", "Pause")

    def _close_interactive(self) -> None:
        process = self.interactive_dvgrab_process
        self.interactive_dvgrab_process = None
        if not process or process.poll() is not None:
            return
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.write(b"\x1b")  # Esc ends interactive mode
                process.stdin.flush()
                time.sleep(0.5)
        except (BrokenPipeError, OSError):
            pass
        terminate_process(process, timeout=3)

    # ------------------------------------------------------------------ capture

    def start_capture(
        self,
        output_path: Path,
        part_number: int = 1,
        preview_callback: Optional[Callable[[bytes], None]] = None,
        preview_fps: int = 10,
        auto_rewind_play: bool = True,
        title: str = "",
        year: str = "",
    ) -> bool:
        """
        Startet DV-Aufnahme mit dvgrab autosplit

        Args:
            output_path: Ausgabeordner (LowRes-Verzeichnis)
            part_number: nicht mehr verwendet (Kompatibilität)
            preview_callback: Callback für Preview-Frames (rohe JPEG-Bytes)
            preview_fps: FPS für Preview
            auto_rewind_play: dvgrab -rewind (Band vor der Aufnahme zurückspulen)
            title, year: für die Merge-Queue und Benachrichtigungen
        """
        self.current_capture_title = title
        self.current_capture_year = year
        try:
            if self.is_capturing:
                self.log("Aufnahme läuft bereits!")
                return False
            if self._is_rewind_block_active():
                self.log(f"Aufnahme gesperrt, Auto-Rewind läuft noch {self._remaining_rewind_block_seconds()} Sekunden.")
                return False

            self.dvgrab.start_sudo_keepalive()
            device = self.get_device()
            if not device:
                self.log("Kein FireWire-Gerät verfügbar!")
                return False

            output_dir = Path(output_path)
            output_dir.mkdir(parents=True, exist_ok=True)
            self.splits_dir = output_dir / "splits"
            self.splits_dir.mkdir(parents=True, exist_ok=True)
            self.last_split_time = time.time()
            self.current_output_path = output_dir / "movie_merged.mp4"

            # The recording dvgrab replaces the interactive one
            if self.interactive_dvgrab_process and self.interactive_dvgrab_process.poll() is None:
                self.log("Beende interaktiven dvgrab-Modus...")
            self._close_interactive()

            self.log("=== Starte non-interaktiven dvgrab für Aufnahme ===")
            self.recording_dvgrab_process = self.dvgrab.start_recording(device, self.splits_dir, rewind=auto_rewind_play)
            if not self.recording_dvgrab_process:
                self.log("FEHLER: Recording dvgrab konnte nicht gestartet werden")
                self.dvgrab.stop_sudo_keepalive()
                return False
            self.log("Recording dvgrab gestartet (non-interaktiv mit autosplit)")

            # Active before the threads start, or they stop right away
            self._stop_requested = False
            self.is_capturing = True
            self._start_duration_logger()
            if preview_callback is not None:
                self.preview.start(self.splits_dir, preview_callback, preview_fps)
            self.inactivity_thread = threading.Thread(target=self._watch_inactivity, daemon=True, name="InactivityMonitor")
            self.inactivity_thread.start()
            self.capture_thread = threading.Thread(target=self._monitor_capture, daemon=True, name="CaptureMonitor")
            self.capture_thread.start()

            self.log("Aufnahme gestartet! dvgrab spult automatisch zurück und startet Aufnahme.")
            self.log("Dateien werden in splits/ gespeichert mit Timestamp im Dateinamen.")
            return True
        except Exception as e:
            self.log(f"Fehler beim Starten der Aufnahme: {e}")
            self.is_capturing = False
            self.preview.stop()
            self._stop_duration_logger()
            self._stop_all_processes()
            return False

    def stop_capture(self) -> bool:
        """Stops like Ctrl+C, then rewinds and queues the merge."""
        if not self.is_capturing or self._stop_requested:
            return False
        # From here on, stop_capture() finalizes; the monitor thread only watches
        self._stop_requested = True
        try:
            self.log("Stoppe Aufnahme...")
            self.preview.stop()
            process = self.recording_dvgrab_process
            if process and process.poll() is None:
                self.log("Sende SIGINT (Strg+C) an dvgrab...")
                try:
                    interrupt_process(process, timeout=10)
                    self.log("dvgrab wurde beendet")
                except Exception as e:
                    self.log(f"Fehler beim Stoppen von dvgrab: {e}")
            self._stop_all_processes()
            self.is_capturing = False
            self._stop_duration_logger()
            self.log("Aufnahme gestoppt.")
            self._finalize("Aufnahme beendet")
            return True
        except Exception as e:
            self.log(f"Fehler beim Stoppen der Aufnahme: {e}")
            self.is_capturing = False
            self.preview.stop()
            self._stop_all_processes()
            self.dvgrab.stop_sudo_keepalive()
            return False

    def _monitor_capture(self) -> None:
        """Waits for the recording dvgrab; finalizes when the tape ended by itself."""
        process = self.recording_dvgrab_process
        if process is None:
            return
        try:
            stderr_chunks: List[bytes] = []
            reader = threading.Thread(target=self._collect_stderr, args=(process, stderr_chunks), daemon=True)
            reader.start()
            return_code = process.wait()
            self.log(f"dvgrab-Prozess beendet mit Return-Code: {return_code}")
            reader.join(timeout=1)
            self._report_dvgrab_output(return_code, b"".join(stderr_chunks).decode("utf-8", errors="ignore"))

            if self.is_capturing and not self._stop_requested:
                self.is_capturing = False
                self.preview.stop()
                self._stop_all_processes()
                self._stop_duration_logger()
                if return_code != 0 and return_code not in (130, 143, -9):
                    self.log(f"WARNUNG: Aufnahme wurde unerwartet beendet (Return-Code: {return_code}). Mögliche Ursachen:")
                    self.log("  - Kein Signal von der Kamera (Bitte Play auf der Kamera drücken)")
                    self.log("  - Kamera nicht richtig verbunden")
                    self.log("  - dvgrab-Fehler (siehe stderr-Logs)")
                self.log("dvgrab wurde automatisch beendet - starte Finalisierung...")
                self._finalize("Aufnahme automatisch beendet")
        except Exception as e:
            self.log(f"Fehler beim Überwachen der Aufnahme: {e}")
            self.is_capturing = False
            self.preview.stop()
            self._stop_all_processes()

    def _finalize(self, reason: str) -> None:
        """After a capture, once: rewind, queue the merge, notify later, report 'stopped'."""
        try:
            self.log("Warte auf vollständiges Schreiben der Split-Dateien...")
            self._wait_for_stable_clips()
            self.log("Spule Kamera zurück...")
            self._rewind_after_capture()
            self._notify_completion(
                f"{reason}: {self.current_capture_title} ({self.current_capture_year}). Merge läuft im Hintergrund.",
                delay_seconds=self.rewind_notification_delay_seconds,
            )
            if self.splits_dir and self.splits_dir.exists():
                count = len(find_split_files(self.splits_dir))
                self.log(f"Gefunden: {count} Split-Dateien - Merge wird im Hintergrund durchgeführt")
                self.merger.add(self.splits_dir, self.current_output_path, self.current_capture_title,
                                self.current_capture_year)
            else:
                self.log(f"WARNUNG: splits-Ordner nicht gefunden: {self.splits_dir}")
        except Exception as e:
            self.log(f"Fehler bei Finalisierung nach dvgrab-Ende: {e}")
            self._notify_completion(f"Aufnahme beendet mit Fehler: {e}")
        finally:
            self.dvgrab.stop_sudo_keepalive()
            self._notify_state("stopped")

    def _wait_for_stable_clips(self, max_wait: float = 10.0) -> None:
        """Waits until no clip grows any more (dvgrab may still flush the last one)."""
        if not self.splits_dir or not self.splits_dir.exists():
            time.sleep(2)
            return
        waited = 0.0
        while waited < max_wait:
            files = find_split_files(self.splits_dir)
            sizes = {f: f.stat().st_size for f in files if f.exists()}
            time.sleep(0.5)
            waited += 0.5
            if files and all(f.exists() and f.stat().st_size == size for f, size in sizes.items()):
                return

    def _stop_all_processes(self) -> None:
        """Stops the preview and both dvgrab processes."""
        self.preview.stop()
        process = self.recording_dvgrab_process
        self.recording_dvgrab_process = None
        if process:
            try:
                interrupt_process(process, timeout=5)
            except Exception as e:
                self.log(f"dvgrab could not be stopped: {e}")
        self._close_interactive()

    # ------------------------------------------------------------------ dvgrab output

    @staticmethod
    def _collect_stderr(process: subprocess.Popen, chunks: List[bytes]) -> None:
        try:
            while process.stderr:
                chunk = process.stderr.read(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        except (OSError, ValueError):
            pass

    def _report_dvgrab_output(self, return_code: Optional[int], text: str) -> None:
        """Puts what dvgrab said into the log, with a hint for the usual problems."""
        if text:
            if "Waiting for DV" in text:
                self.log("dvgrab wartet auf DV-Signal...")
            elif "capture started" in text.lower():
                self.log("dvgrab: Aufnahme gestartet!")
            elif "capture stopped" in text.lower():
                self.log("dvgrab: Aufnahme gestoppt.")
            else:
                self.log(f"dvgrab: {text[-300:]}")

        if return_code in (0, None):
            self.log(f"Aufnahme erfolgreich beendet: {self.current_output_path}")
        elif return_code in (1, 130, 143, -9, -2, -15):  # stopped by a signal
            self.log(f"Aufnahme erfolgreich gestoppt: {self.current_output_path}")
        elif "End of file" in text or "Interrupted" in text:
            self.log(f"Aufnahme beendet (Bandende oder manuell): {self.current_output_path}")
        elif any(key in text for key in ("No input", "Cannot open", "Device", "Waiting for DV")):
            self.log("WARNUNG: dvgrab konnte kein DV-Signal empfangen.")
            self.log("Mögliche Ursachen:")
            self.log("  - Kamera ist nicht im Play-Modus")
            self.log("  - Kamera sendet kein Signal")
            self.log("  - FireWire-Verbindung problematisch")
            self.log("Bitte stellen Sie die Kamera in den 'Edit/Play'-Modus und drücken Sie Play.")
            self.log(f"dvgrab-Ausgabe: {text[-500:]}")
        else:
            self.log(f"dvgrab-Fehler (Code {return_code}): {text[-500:]}")

    def _watch_inactivity(self, timeout_seconds: int = 600) -> None:
        """Logs when no new clip arrived for a while; the capture keeps running."""
        if not self.splits_dir:
            return
        known = clip_files(self.splits_dir)
        if known:
            self.last_split_time = time.time()
        self.log("Inaktivitätsmonitor: gestartet")
        try:
            while self.is_capturing:
                now = time.time()
                current = clip_files(self.splits_dir)
                if current - known:
                    self.last_split_time = now
                    known |= current
                if self.last_split_time and now - self.last_split_time >= timeout_seconds:
                    self.log(f"Inaktivitätsmonitor: {timeout_seconds / 60:.1f} Minuten keine neuen Splits "
                             "(keine Aktion, Aufnahme läuft weiter).")
                    self.last_split_time = now
                time.sleep(5)
        except Exception as e:
            self.log(f"Inaktivitätsmonitor: Fehler: {e}")
        finally:
            self.log("Inaktivitätsmonitor: beendet")

    # ------------------------------------------------------------------ rewind after a capture

    def _rewind_after_capture(self) -> None:
        """Rewinds the tape in the background and blocks captures and controls meanwhile."""

        def run() -> None:
            duration = self.rewind_notification_delay_seconds
            self._begin_rewind_block(duration)
            try:
                device = self.get_device()
                if not device:
                    self.log("Rewind nach Merge übersprungen: Kein FireWire-Gerät gefunden.")
                    return
                if not self._ensure_interactive():
                    self.log("Rewind nach Merge: Interaktiver Modus konnte nicht gestartet werden.")
                    return
                self.log(f"Rewind nach Merge: Sende 'a' (rewind) und halte für {duration} Sekunden...")
                self._send_interactive_command("a")
                end = time.time() + duration
                while time.time() < end:
                    process = self.interactive_dvgrab_process
                    if not process or process.poll() is not None:
                        self.log("Rewind nach Merge: Interaktiver dvgrab beendet sich unerwartet.")
                        break
                    time.sleep(1)
                process = self.interactive_dvgrab_process
                self.interactive_dvgrab_process = None
                if process and process.poll() is None:
                    self.log("Rewind nach Merge: Sende SIGINT (Ctrl+C) an interaktiven dvgrab...")
                    interrupt_process(process, timeout=5)
            except Exception as e:
                self.log(f"Rewind nach Merge: Fehler: {e}")
            finally:
                self._end_rewind_block()

        threading.Thread(target=run, daemon=True, name="RewindAfterCapture").start()

    def _begin_rewind_block(self, duration_seconds: int) -> None:
        self._end_rewind_block()
        self.rewind_block_active = True
        self.rewind_block_until = time.time() + duration_seconds
        self.rewind_block_timer = threading.Timer(duration_seconds, self._end_rewind_block)
        self.rewind_block_timer.daemon = True
        self.rewind_block_timer.start()
        self.log(f"Rewind-Sperre aktiv für {duration_seconds} Sekunden.")

    def _end_rewind_block(self) -> None:
        if self.rewind_block_timer:
            self.rewind_block_timer.cancel()
        self.rewind_block_timer = None
        was_active = self.rewind_block_active
        self.rewind_block_active = False
        self.rewind_block_until = None
        if was_active:
            self.log("Rewind-Sperre aufgehoben. Aufnahme und Steuerung wieder möglich.")

    def _is_rewind_block_active(self) -> bool:
        if not self.rewind_block_active:
            return False
        if self.rewind_block_until and time.time() > self.rewind_block_until:
            self._end_rewind_block()
            return False
        return True

    def _remaining_rewind_block_seconds(self) -> int:
        if not self._is_rewind_block_active() or not self.rewind_block_until:
            return 0
        return max(0, int(self.rewind_block_until - time.time()))

    def is_rewind_block_active(self) -> bool:
        return self._is_rewind_block_active()

    def get_rewind_block_remaining(self) -> int:
        return self._remaining_rewind_block_seconds()

    # ------------------------------------------------------------------ notifications and log

    def _notify_state(self, state: str) -> None:
        if self.state_callback:
            try:
                self.state_callback(state)
            except Exception:
                pass

    def _notify_completion(self, message: str, delay_seconds: float = 0, *, _from_timer: bool = False) -> None:
        """Logs a message and passes it to notify_callback (ntfy, if a topic is set), optionally later."""
        if delay_seconds > 0 and not _from_timer:
            self.log(f"Benachrichtigung wird in {delay_seconds / 60:.1f} Minuten gesendet: {message}")
            timer = threading.Timer(delay_seconds, self._notify_completion, args=[message], kwargs={"_from_timer": True})
            timer.daemon = True
            timer.start()
            return
        self.log(message)
        if self.notify_callback:
            self.notify_callback(message)

    def _start_duration_logger(self) -> None:
        """Logs how long the capture runs, once a minute."""
        self._stop_duration_logger()
        self.capture_start_time = time.time()
        stop = threading.Event()
        self._duration_stop = stop
        self.log("Aufnahme läuft seit 00:00:00")

        def loop() -> None:
            while not stop.wait(60):
                if not self.capture_start_time:
                    break
                elapsed = int(time.time() - self.capture_start_time)
                hours, rest = divmod(elapsed, 3600)
                minutes, seconds = divmod(rest, 60)
                self.log(f"Aufnahme läuft seit {hours:02d}:{minutes:02d}:{seconds:02d}")

        self._duration_thread = threading.Thread(target=loop, daemon=True, name="CaptureDurationLogger")
        self._duration_thread.start()

    def _stop_duration_logger(self) -> None:
        if self._duration_stop:
            self._duration_stop.set()
        if self._duration_thread and self._duration_thread.is_alive():
            self._duration_thread.join(timeout=1)
        self._duration_thread = None
        self._duration_stop = None
        self.capture_start_time = None

    def log(self, message: str) -> None:
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)
