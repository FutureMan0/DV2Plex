"""
Capture-Engine für DV-Aufnahmen über dvgrab (Linux)
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
import shutil
from pathlib import Path
from typing import Optional, Callable

try:
    from PySide6.QtGui import QImage
except ImportError:
    # Fallback falls PySide6 nicht verfügbar
    QImage = None


class CaptureEngine:
    """Verwaltet DV-Capture über dvgrab (Linux)"""

    def __init__(
        self,
        ffmpeg_path: Path,
        device_path: Optional[str] = None,
        dvgrab_path: str = "dvgrab",
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.ffmpeg_path = ffmpeg_path
        self.device_path = device_path
        self.dvgrab_path = dvgrab_path
        self.log_callback = log_callback
        self.process: Optional[subprocess.Popen] = None
        self.preview_process: Optional[subprocess.Popen] = None
        self.is_capturing = False
        self.capture_thread: Optional[threading.Thread] = None
        self.preview_reader_thread: Optional[threading.Thread] = None
        self.preview_stop_event: Optional[threading.Event] = None
        self.preview_callback: Optional[Callable[[QImage], None]] = None
        self.current_output_path: Optional[Path] = None
        self.logger = logging.getLogger(__name__)

    def detect_firewire_device(self) -> Optional[str]:
        """
        Erkennt automatisch das erste verfügbare FireWire-Gerät
        
        Returns:
            Gerätepfad (z.B. /dev/raw1394) oder None
        """
        try:
            # Versuche dvgrab --list
            result = subprocess.run(
                [self.dvgrab_path, "--list"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0 and result.stdout:
                # Parse dvgrab --list Ausgabe
                # Format: "Device 0: /dev/raw1394"
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if "Device" in line and "/dev/" in line:
                        # Extrahiere Gerätepfad
                        parts = line.split()
                        for part in parts:
                            if part.startswith("/dev/"):
                                self.log(f"FireWire-Gerät erkannt: {part}")
                                return part
            
            # Fallback: Prüfe Standard-Geräte
            for device in ["/dev/raw1394", "/dev/video1394"]:
                if Path(device).exists():
                    self.log(f"FireWire-Gerät gefunden (Fallback): {device}")
                    return device
            
            self.log("Kein FireWire-Gerät gefunden")
            return None
            
        except FileNotFoundError:
            self.log(f"dvgrab nicht gefunden. Bitte installieren Sie dvgrab.")
            return None
        except Exception as e:
            self.log(f"Fehler bei Geräteerkennung: {e}")
            return None

    def get_device(self) -> Optional[str]:
        """Gibt das zu verwendende Gerät zurück (automatisch erkannt oder konfiguriert)"""
        if self.device_path:
            return self.device_path
        return self.detect_firewire_device()

    def rewind(self) -> bool:
        """Spult die Kassette zurück"""
        device = self.get_device()
        if not device:
            self.log("Kein Gerät verfügbar für Rewind")
            return False
        
        try:
            # dvgrab unterstützt -R für Rewind (falls von Kamera unterstützt)
            cmd = [self.dvgrab_path, "-i", device, "-R"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                self.log("Kassette zurückgespult")
                return True
            else:
                self.log(f"Rewind-Fehler: {result.stderr}")
                # Hinweis: Nicht alle Kameras unterstützen Remote-Rewind
                self.log("Hinweis: Bitte spulen Sie die Kassette manuell zurück")
                return False
        except Exception as e:
            self.log(f"Fehler beim Rewind: {e}")
            return False

    def play(self) -> bool:
        """Startet die Wiedergabe"""
        device = self.get_device()
        if not device:
            self.log("Kein Gerät verfügbar für Play")
            return False
        
        try:
            # dvgrab unterstützt -P für Play (falls von Kamera unterstützt)
            cmd = [self.dvgrab_path, "-i", device, "-P"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                self.log("Wiedergabe gestartet")
                return True
            else:
                self.log(f"Play-Fehler: {result.stderr}")
                # Hinweis: Nicht alle Kameras unterstützen Remote-Play
                self.log("Hinweis: Bitte drücken Sie Play auf der Kamera")
                return False
        except Exception as e:
            self.log(f"Fehler beim Play: {e}")
            return False

    def pause(self) -> bool:
        """Pausiert die Wiedergabe"""
        device = self.get_device()
        if not device:
            self.log("Kein Gerät verfügbar für Pause")
            return False
        
        try:
            # dvgrab unterstützt -S für Stop (falls von Kamera unterstützt)
            cmd = [self.dvgrab_path, "-i", device, "-S"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                self.log("Wiedergabe pausiert")
                return True
            else:
                self.log(f"Pause-Fehler: {result.stderr}")
                return False
        except Exception as e:
            self.log(f"Fehler beim Pause: {e}")
            return False

    def start_capture(
        self,
        output_path: Path,
        part_number: int = 1,
        preview_callback: Optional[Callable[[QImage], None]] = None,
        preview_fps: int = 10,
        auto_rewind_play: bool = True,
    ) -> bool:
        """
        Startet DV-Aufnahme mit dvgrab
        
        Args:
            output_path: Ausgabeordner
            part_number: Part-Nummer
            preview_callback: Optionaler Callback für Preview-Frames
            preview_fps: FPS für Preview
            auto_rewind_play: Automatisch Rewind und Play vor Aufnahme
        """
        if self.is_capturing:
            self.log("Aufnahme läuft bereits!")
            return False

        device = self.get_device()
        if not device:
            self.log("Kein FireWire-Gerät verfügbar!")
            return False

        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        # dvgrab erstellt Dateien mit Timestamp-Format
        # Wir verwenden ein einfaches Format für Part-Namen
        self.current_output_path = output_dir / f"part_{part_number:03d}.avi"

        self.preview_callback = preview_callback
        self.preview_fps = preview_fps
        enable_preview = preview_callback is not None

        # Automatischer Workflow: Rewind → Play → Aufnahme
        if auto_rewind_play:
            self.log("Automatischer Workflow: Rewind → Play → Aufnahme")
            if not self.rewind():
                self.log("Warnung: Rewind fehlgeschlagen, fahre fort...")
            time.sleep(2)  # Warte 2 Sekunden nach Rewind
            
            if not self.play():
                self.log("Warnung: Play fehlgeschlagen, fahre fort...")
            time.sleep(1)  # Warte 1 Sekunde nach Play

        # Starte Preview (separater ffmpeg-Prozess)
        if enable_preview:
            self._start_preview(device, preview_fps)

        # Starte dvgrab Capture
        # -a: Audio aktivieren (Type-2 AVI)
        # -t: Timestamp-Format (wir verwenden einfaches Format)
        # -i: Gerät
        cmd = [
            self.dvgrab_path,
            "-i", device,
            "-a",  # Audio aktivieren
            "-t", "%Y%m%d_%H%M%S",  # Timestamp-Format
            str(self.current_output_path.parent / f"part_{part_number:03d}"),  # Basisname (ohne Extension)
        ]

        try:
            self.log(f"Starte Aufnahme: {self.current_output_path.name}")
            self.log(f"dvgrab-Befehl: {' '.join(cmd)}")

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=False,
                bufsize=0,
            )

            self.is_capturing = True

            self.capture_thread = threading.Thread(
                target=self._monitor_capture,
                daemon=True,
            )
            self.capture_thread.start()

            return True

        except Exception as e:
            self.log(f"Fehler beim Starten der Aufnahme: {e}")
            self.is_capturing = False
            self._stop_preview()
            return False

    def _start_preview(self, device: str, fps: int):
        """Startet Preview-Stream mit ffmpeg"""
        try:
            # ffmpeg liest direkt vom FireWire-Gerät
            cmd = [
                str(self.ffmpeg_path),
                "-f", "dv1394",
                "-i", device,
                "-vf", f"fps={fps},scale=640:-1",
                "-f", "mjpeg",
                "-q:v", "5",
                "-",
            ]

            self.log("Starte Preview-Stream...")
            self.preview_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=False,
                bufsize=0,
            )

            if self.preview_process.stdout:
                self.preview_stop_event = threading.Event()
                self.preview_reader_thread = threading.Thread(
                    target=self._read_preview_stream,
                    daemon=True,
                )
                self.preview_reader_thread.start()
                self.log("Preview-Stream: Thread gestartet")
            else:
                self.log("Preview-Stream: WARNUNG - stdout nicht verfügbar!")

        except Exception as e:
            self.log(f"Fehler beim Starten des Preview-Streams: {e}")

    def stop_capture(self) -> bool:
        """Stoppt die Aufnahme"""
        if not self.is_capturing or self.process is None:
            return False

        try:
            self.log("Stoppe Aufnahme...")

            # Stoppe Preview
            self._stop_preview()

            # Stoppe dvgrab (sende SIGTERM)
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.log("dvgrab beendet sich nicht automatisch, erzwinge Beendigung...")
                self.process.kill()
                self.process.wait(timeout=2)

            self.is_capturing = False
            self.log("Aufnahme gestoppt.")

            # Warte kurz, damit die Datei vollständig geschrieben ist
            time.sleep(0.5)

            # dvgrab erstellt möglicherweise Dateien mit Timestamp
            # Finde die tatsächlich erstellte Datei
            if self.current_output_path and not self.current_output_path.exists():
                # Suche nach Dateien die mit dem Basisnamen beginnen
                base_name = self.current_output_path.stem
                parent = self.current_output_path.parent
                matching_files = list(parent.glob(f"{base_name}*.avi"))
                if matching_files:
                    # Benenne die erste gefundene Datei um
                    actual_file = matching_files[0]
                    if actual_file != self.current_output_path:
                        shutil.move(actual_file, self.current_output_path)
                        self.log(f"Datei umbenannt: {actual_file.name} -> {self.current_output_path.name}")

            return True

        except Exception as e:
            self.log(f"Fehler beim Stoppen der Aufnahme: {e}")
            if self.process:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=2)
                except:
                    try:
                        self.process.kill()
                    except:
                        pass
            self.is_capturing = False
            self._stop_preview()
            return False

    def _stop_preview(self):
        """Stoppt den Preview-Stream"""
        if self.preview_stop_event:
            self.preview_stop_event.set()
        
        if self.preview_process:
            try:
                self.preview_process.terminate()
                self.preview_process.wait(timeout=2)
            except:
                try:
                    self.preview_process.kill()
                except:
                    pass
            self.preview_process = None

        if self.preview_reader_thread and self.preview_reader_thread.is_alive():
            self.preview_reader_thread.join(timeout=1)
        self.preview_reader_thread = None
        self.preview_stop_event = None

    def _monitor_capture(self):
        """Überwacht den Capture-Prozess"""
        if self.process is None:
            return

        try:
            # Lese stderr für Logging
            stderr_thread = threading.Thread(
                target=self._read_stderr,
                daemon=True
            )
            stderr_thread.start()

            # Warte auf Prozess-Ende
            self.process.wait()

            # Warte kurz, damit stderr-Thread fertig wird
            stderr_thread.join(timeout=1)

            self.is_capturing = False
            self._stop_preview()

        except Exception as e:
            self.log(f"Fehler beim Überwachen der Aufnahme: {e}")
            self.is_capturing = False
            self._stop_preview()

    def _read_stderr(self):
        """Liest stderr in einem separaten Thread"""
        try:
            stderr_bytes = b""
            if self.process and self.process.stderr:
                while self.process.poll() is None:
                    chunk = self.process.stderr.read(4096)
                    if chunk:
                        stderr_bytes += chunk
                    else:
                        time.sleep(0.1)

                remaining = self.process.stderr.read()
                if remaining:
                    stderr_bytes += remaining

            self._process_stderr(stderr_bytes)
        except Exception as e:
            self.log(f"Fehler beim Lesen von stderr: {e}")

    def _process_stderr(self, stderr_bytes: bytes):
        """Verarbeitet stderr-Ausgabe"""
        return_code = self.process.returncode if self.process else None

        if return_code == 0 or return_code is None:
            self.log(f"Aufnahme erfolgreich beendet: {self.current_output_path}")
        elif return_code in [1, 130, 143]:  # Normal beendet (SIGTERM/SIGINT)
            self.log(f"Aufnahme erfolgreich gestoppt: {self.current_output_path}")
        else:
            stderr_text = stderr_bytes.decode("utf-8", errors="ignore") if stderr_bytes else ""
            if "End of file" in stderr_text or "Interrupted" in stderr_text:
                self.log(f"Aufnahme beendet (Bandende oder manuell): {self.current_output_path}")
            else:
                self.log(f"dvgrab-Fehler (Code {return_code}): {stderr_text[-500:]}")

    def _read_preview_stream(self):
        """Liest Preview-Frames vom ffmpeg-Stream"""
        if not self.preview_process or not self.preview_process.stdout or not self.preview_callback:
            self.log("Preview-Stream: Fehlende Voraussetzungen")
            return

        self.log("Preview-Stream: Starte Lesen...")
        buffer = bytearray()
        jpeg_start = b"\xff\xd8"
        jpeg_end = b"\xff\xd9"
        frame_count = 0
        last_frame_time = 0
        preview_fps = getattr(self, 'preview_fps', 10)
        target_frame_interval = 1.0 / max(preview_fps, 5)

        try:
            while (
                self.preview_stop_event
                and not self.preview_stop_event.is_set()
                and self.preview_process
                and self.preview_process.poll() is None
            ):
                try:
                    chunk = self.preview_process.stdout.read(8192)

                    if not chunk:
                        current_time = time.time()
                        if current_time - last_frame_time < target_frame_interval:
                            time.sleep(0.01)
                        continue

                    buffer.extend(chunk)

                    # Suche nach vollständigen JPEGs
                    while True:
                        start_idx = buffer.find(jpeg_start)
                        if start_idx == -1:
                            if len(buffer) > 500000:
                                buffer = bytearray()
                            break
                        if start_idx > 0:
                            buffer = buffer[start_idx:]
                        end_idx = buffer.find(jpeg_end, 2)
                        if end_idx == -1:
                            break

                        jpeg_data = bytes(buffer[: end_idx + 2])
                        buffer = buffer[end_idx + 2 :]

                        if QImage and self.preview_callback:
                            try:
                                image = QImage.fromData(jpeg_data)
                                if not image.isNull():
                                    current_time = time.time()
                                    if current_time - last_frame_time >= target_frame_interval:
                                        self.preview_callback(image)
                                        frame_count += 1
                                        last_frame_time = current_time
                                        if frame_count == 1:
                                            self.log("Preview-Stream: Erstes Frame empfangen")
                            except Exception:
                                pass

                except Exception as e:
                    self.log(f"Preview-Stream: Fehler beim Lesen: {e}")
                    time.sleep(0.1)
                    continue

        except Exception as e:
            self.log(f"Preview-Stream: Fehler: {e}")
        finally:
            self.log(f"Preview-Stream: Beendet (Frames empfangen: {frame_count})")
            try:
                if self.preview_process and self.preview_process.stdout:
                    self.preview_process.stdout.close()
            except Exception:
                pass

    def get_current_output_path(self) -> Optional[Path]:
        return self.current_output_path

    def is_active(self) -> bool:
        return self.is_capturing

    def log(self, message: str):
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)
