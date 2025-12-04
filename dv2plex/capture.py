"""
Capture-Engine für DV-Aufnahmen über DirectShow
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Callable

try:
    from PySide6.QtGui import QImage
except ImportError:
    # Fallback falls PySide6 nicht verfügbar
    QImage = None


# Audio-Extraktion aktivieren (DV Type 1 → Type 2 Konvertierung)
AUDIO_EXTRACTION_ENABLED = True


class CaptureEngine:
    """Verwaltet DV-Capture über ffmpeg"""

    def __init__(
        self,
        ffmpeg_path: Path,
        device_name: str,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.ffmpeg_path = ffmpeg_path
        self.device_name = device_name
        self.log_callback = log_callback
        self.process: Optional[subprocess.Popen] = None
        self.is_capturing = False
        self.capture_thread: Optional[threading.Thread] = None
        self.preview_reader_thread: Optional[threading.Thread] = None
        self.preview_stop_event: Optional[threading.Event] = None
        self.preview_callback: Optional[Callable[[QImage], None]] = None
        self.current_output_path: Optional[Path] = None
        self.logger = logging.getLogger(__name__)

    def start_capture(
        self,
        output_path: Path,
        part_number: int = 1,
        preview_callback: Optional[Callable[[QImage], None]] = None,
        preview_fps: int = 10,
    ) -> bool:
        if self.is_capturing:
            self.log("Aufnahme läuft bereits!")
            return False

        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        # Verwende .avi Dateiendung (für Kompatibilität), aber DV-Format für bessere Qualität
        self.current_output_path = output_dir / f"part_{part_number:03d}.avi"

        self.preview_callback = preview_callback
        self.preview_fps = preview_fps
        enable_preview_stream = preview_callback is not None

        # Erfasse DV-Stream vom DirectShow-Device
        # Bei DV-Kameras über FireWire kommt Video+Audio als interleaved Stream (MEDIATYPE_Interleaved)
        # WinDV erfasst den kompletten interleaved Stream - wir müssen das auch tun
        # Der Stream wird als DV Type 1 (interleaved) erfasst und kann später zu Type 2 konvertiert werden
        base_cmd = [
            str(self.ffmpeg_path),
            "-f",
            "dshow",
            "-i",
            f"video={self.device_name}",
        ]

        if enable_preview_stream:
            # Wichtig: -map 0 für alle Streams (Video + Audio), -map [v_preview] für den Preview-Stream
            # Audio wird direkt mit aufgenommen (DV-Stream über FireWire)
            # Verwende AVI-Container mit DV-Codec (Standard für DV-Aufnahmen)
            # Wichtig: Keine explizite Format-Angabe, damit ffmpeg automatisch das beste Format wählt
            cmd = [
                *base_cmd,
                "-filter_complex",
                f"[0:v]fps={preview_fps},scale=640:-1[v_preview]",
                "-map", "0",  # Alle Streams (Video + Audio)
                "-c", "copy",  # Alle Codecs kopieren (DV-Codec bleibt erhalten)
                "-avoid_negative_ts", "make_zero",  # Vermeide Timestamp-Probleme
                "-y", str(self.current_output_path),
                "-map", "[v_preview]", "-f", "mjpeg", "-q:v", "5", "-",
            ]
            stdout_target = subprocess.PIPE
        else:
            cmd = [
                *base_cmd,
                "-map", "0",  # Alle Streams (Video + Audio)
                "-c", "copy",  # Alle Codecs kopieren (DV-Codec bleibt erhalten)
                "-avoid_negative_ts", "make_zero",  # Vermeide Timestamp-Probleme
                "-y",
                str(self.current_output_path),
            ]
            stdout_target = subprocess.PIPE

        try:
            self.log(f"Starte Aufnahme: {self.current_output_path.name}")
            self.log(f"ffmpeg-Befehl: {' '.join(cmd)}")
            
            # Prüfe zuerst, welche Streams verfügbar sind (für Debugging)
            probe_cmd = [
                str(self.ffmpeg_path),
                "-f", "dshow",
                "-i", f"video={self.device_name}",
                "-t", "0.1",  # Nur sehr kurze Zeit
                "-f", "null",
                "-"
            ]
            try:
                probe_result = subprocess.run(
                    probe_cmd,
                    stderr=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    timeout=5
                )
                stderr_text = probe_result.stderr.decode("utf-8", errors="ignore")
                # Suche nach Stream-Informationen
                if "Stream #0" in stderr_text:
                    self.log(f"Verfügbare Streams: {stderr_text[stderr_text.find('Stream #0'):stderr_text.find('Stream #0')+200]}")
            except Exception:
                pass  # Ignoriere Fehler beim Proben

            self.process = subprocess.Popen(
                cmd,
                stdout=stdout_target,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=False,
                bufsize=0,
            )

            self.is_capturing = True

            if enable_preview_stream and self.process.stdout:
                self.log("Preview-Stream: Initialisiere...")
                self.preview_stop_event = threading.Event()
                self.preview_reader_thread = threading.Thread(
                    target=self._read_preview_stream,
                    daemon=True,
                )
                self.preview_reader_thread.start()
                self.log("Preview-Stream: Thread gestartet")
            elif enable_preview_stream:
                self.log("Preview-Stream: WARNUNG - stdout nicht verfügbar!")

            self.capture_thread = threading.Thread(
                target=self._monitor_capture,
                daemon=True,
            )
            self.capture_thread.start()

            return True

        except Exception as e:
            self.log(f"Fehler beim Starten der Aufnahme: {e}")
            self.is_capturing = False
            self._stop_preview_reader()
            return False

    def stop_capture(self) -> bool:
        if not self.is_capturing or self.process is None:
            return False

        try:
            self.log("Stoppe Aufnahme...")
            
            # Deaktiviere Preview-Callback, damit keine neuen Frames mehr verarbeitet werden
            # Aber lasse den Reader laufen, damit stdout nicht geschlossen wird
            old_callback = self.preview_callback
            self.preview_callback = None

            if self.process.stdin:
                try:
                    # Sende 'q' um ffmpeg sauber zu beenden
                    self.process.stdin.write(b"q")
                    self.process.stdin.flush()
                    self.process.stdin.close()
                except Exception:
                    pass

            # Warte länger, damit alle Daten geschrieben werden
            # Der Preview-Reader läuft weiter, damit stdout nicht geschlossen wird
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.log("ffmpeg beendet sich nicht automatisch, erzwinge Beendigung...")
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=1)

            # Jetzt können wir den Preview-Reader sicher stoppen
            self._stop_preview_reader()
            self.preview_callback = old_callback  # Wiederherstellen für zukünftige Verwendung

            self.is_capturing = False
            self.log("Aufnahme gestoppt.")

            # Warte kurz, damit die Datei vollständig geschrieben ist
            time.sleep(0.5)

            # Prüfe ob Audio vorhanden ist, falls nicht versuche nachträgliche Extraktion (Fallback)
            if (
                AUDIO_EXTRACTION_ENABLED
                and self.current_output_path
                and self.current_output_path.exists()
            ):
                # Bei DV-Videos ist Audio immer im Video-Stream eingebettet
                # Prüfe ob es bereits als separater Stream vorhanden ist
                if not self._has_audio_stream(self.current_output_path):
                    # Wenn es ein DV-Video ist, versuche Audio-Extraktion
                    if self._is_dv_video(self.current_output_path):
                        self.log("DV-Video erkannt, extrahiere Audio aus DV-Stream...")
                        self._extract_audio_from_dv()
                    else:
                        self.log("Kein Audio-Stream gefunden und keine DV-Datei - überspringe Extraktion.")
                else:
                    self.log("Audio erfolgreich mit aufgenommen.")

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
            self._stop_preview_reader()
            return False
    
    def _extract_audio_from_dv(self):
        """Extrahiert Audio aus dem DV-Stream, falls es eingebettet ist"""
        if not self.current_output_path or not self.current_output_path.exists():
            return
        
        try:
            if not AUDIO_EXTRACTION_ENABLED:
                self.log("Audio-Extraktion deaktiviert (Testmodus).")
                return

            raw_path = self.current_output_path
            if not raw_path or not raw_path.exists():
                self.log("Audio-Extraktion übersprungen: Datei nicht gefunden.")
                return

            backup_path = raw_path.with_name(f"{raw_path.stem}_raw{raw_path.suffix}")
            if not backup_path.exists():
                shutil.copy2(raw_path, backup_path)
                self.log(f"Rohdatei gesichert: {backup_path.name}")

            temp_output = raw_path.with_name(f"{raw_path.stem}_with_audio{raw_path.suffix}")

            # Bei DV über FireWire ist Audio im Video-Stream eingebettet (interleaved)
            # WinDV verwendet einen DV Splitter, um Video und Audio zu trennen
            # Wir verwenden -f dv, um den interleaved Stream zu dekodieren
            # Dann mappen wir Video und Audio separat
            extract_cmd = [
                str(self.ffmpeg_path),
                "-f", "dv",  # Explizit DV-Format für interleaved Stream
                "-i", str(backup_path),
                "-map", "0:v",  # Video-Stream
                "-map", "0:a:0",  # Ersten Audio-Stream aus DV extrahieren
                "-c:v", "copy",  # Video kopieren
                "-c:a", "pcm_s16le",  # Audio zu PCM konvertieren
                "-ar", "32000",  # DV verwendet typischerweise 32 kHz
                "-ac", "2",
                "-err_detect", "ignore_err",  # Ignoriere Demuxing-Fehler
                "-fflags", "+genpts",  # Generiere fehlende Timestamps
                "-y",
                str(temp_output),
            ]

            self.log("Extrahiere Audio (PCM) aus DV-Stream...")
            extract_result = subprocess.run(
                extract_cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if extract_result.returncode != 0:
                error_msg = extract_result.stderr[-500:] if extract_result.stderr else "Unbekannter Fehler"
                self.log(f"Audio-Konvertierung fehlgeschlagen: {error_msg}")
                if extract_result.stdout:
                    self.log(f"ffmpeg stdout: {extract_result.stdout[-200:]}")
                return

            if not temp_output.exists():
                self.log("Audio-Konvertierung erzeugte keine Datei.")
                return

            # Prüfe ob die neue Datei eine sinnvolle Länge hat
            try:
                check_cmd = [
                    str(self.ffmpeg_path.parent / "ffprobe.exe"),
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "csv=p=0",
                    str(temp_output),
                ]
                check_result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=5)
                new_duration = float(check_result.stdout.strip()) if check_result.stdout.strip() else 0
                
                # Prüfe Original-Dauer
                orig_cmd = [
                    str(self.ffmpeg_path.parent / "ffprobe.exe"),
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "csv=p=0",
                    str(backup_path),
                ]
                orig_result = subprocess.run(orig_cmd, capture_output=True, text=True, timeout=5)
                orig_duration = float(orig_result.stdout.strip()) if orig_result.stdout.strip() else 0
                
                # Neue Datei sollte mindestens 80% der Original-Länge haben
                if new_duration < orig_duration * 0.8:
                    self.log(f"Warnung: Neue Datei ist zu kurz ({new_duration:.2f}s vs {orig_duration:.2f}s). Überspringe Ersetzung.")
                    return
            except Exception as e:
                self.log(f"Fehler bei Dauer-Prüfung: {e}. Überspringe Ersetzung.")
                return

            raw_path.unlink(missing_ok=True)
            temp_output.rename(raw_path)
            self.log(f"DV-Datei erfolgreich mit Audio versehen ({new_duration:.2f}s).")

        except Exception as e:
            self.log(f"Fehler beim Extrahieren von Audio: {e}")

    def _has_audio_stream(self, file_path: Path) -> bool:
        """Prüft via ffprobe, ob ein Audio-Stream vorhanden ist"""
        try:
            cmd = [
                str(self.ffmpeg_path.parent / "ffprobe.exe"),
                "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                str(file_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return bool(result.stdout.strip())
        except Exception as e:
            self.log(f"Audio-Prüfung fehlgeschlagen: {e}")
            return False
    
    def _is_dv_video(self, file_path: Path) -> bool:
        """Prüft via ffprobe, ob es sich um ein DV-Video handelt"""
        try:
            cmd = [
                str(self.ffmpeg_path.parent / "ffprobe.exe"),
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "csv=p=0",
                str(file_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            codec = result.stdout.strip().lower()
            return codec == "dvvideo"
        except Exception as e:
            self.log(f"DV-Codec-Prüfung fehlgeschlagen: {e}")
            return False

    def _monitor_capture(self):
        if self.process is None:
            return

        try:
            # Wenn Preview aktiv ist, lese stderr in einem separaten Thread,
            # damit der Preview-Stream nicht blockiert wird
            if self.preview_callback and self.process.stderr:
                # Starte Thread zum Lesen von stderr
                stderr_thread = threading.Thread(
                    target=self._read_stderr,
                    daemon=True
                )
                stderr_thread.start()
                
                # Warte auf Prozess-Ende
                self.process.wait()
                
                # Warte kurz, damit stderr-Thread fertig wird
                stderr_thread.join(timeout=1)
            else:
                # Kein Preview: Normale Kommunikation
                _, stderr_bytes = self.process.communicate()
                self._process_stderr(stderr_bytes)

            self.is_capturing = False
            self._stop_preview_reader()

        except Exception as e:
            self.log(f"Fehler beim Überwachen der Aufnahme: {e}")
            self.is_capturing = False
            self._stop_preview_reader()
    
    def _read_stderr(self):
        """Liest stderr in einem separaten Thread (für Preview-Modus)"""
        try:
            stderr_bytes = b""
            if self.process and self.process.stderr:
                # Lese stderr in Chunks, bis Prozess beendet ist
                while self.process.poll() is None:
                    chunk = self.process.stderr.read(4096)
                    if chunk:
                        stderr_bytes += chunk
                    else:
                        time.sleep(0.1)
                
                # Lese restliche Daten
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
        elif return_code == 1:
            # Code 1 ist normal beim manuellen Stoppen (q-Befehl)
            self.log(f"Aufnahme erfolgreich gestoppt: {self.current_output_path}")
        else:
            stderr_text = stderr_bytes.decode("utf-8", errors="ignore") if stderr_bytes else ""
            if "End of file" in stderr_text or "Interrupted" in stderr_text:
                self.log(f"Aufnahme beendet (Bandende oder manuell): {self.current_output_path}")
            else:
                self.log(f"ffmpeg-Fehler (Code {return_code}): {stderr_text[-500:]}")

    def get_current_output_path(self) -> Optional[Path]:
        return self.current_output_path

    def is_active(self) -> bool:
        return self.is_capturing

    def log(self, message: str):
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)

    def _read_preview_stream(self):
        if not self.process or not self.process.stdout or not self.preview_callback:
            self.log("Preview-Stream: Fehlende Voraussetzungen (process, stdout oder callback)")
            return

        self.log("Preview-Stream: Starte Lesen...")
        buffer = bytearray()
        jpeg_start = b"\xff\xd8"
        jpeg_end = b"\xff\xd9"
        frame_count = 0
        last_frame_time = 0
        preview_fps = getattr(self, 'preview_fps', 10)
        target_frame_interval = 1.0 / max(preview_fps, 5)  # Mindestens 5 FPS

        try:
            while (
                self.preview_stop_event
                and not self.preview_stop_event.is_set()
                and self.process
                and self.process.poll() is None
            ):
                try:
                    # Direktes Lesen - Windows-kompatibel
                    chunk = self.process.stdout.read(8192)
                    
                    if not chunk:
                        # Rate limiting: nicht zu schnell wiederholen
                        current_time = time.time()
                        if current_time - last_frame_time < target_frame_interval:
                            time.sleep(0.01)
                        continue
                    
                    buffer.extend(chunk)

                    # Suche nach vollständigen JPEGs
                    frames_found = 0
                    while True:
                        start_idx = buffer.find(jpeg_start)
                        if start_idx == -1:
                            # Kein JPEG-Start gefunden, aber behalte letzten Teil des Buffers
                            if len(buffer) > 500000:  # Buffer zu groß, reset
                                buffer = bytearray()
                            break
                        if start_idx > 0:
                            buffer = buffer[start_idx:]
                        end_idx = buffer.find(jpeg_end, 2)
                        if end_idx == -1:
                            # JPEG-Start gefunden, aber noch kein Ende - warte auf mehr Daten
                            break
                        
                        jpeg_data = bytes(buffer[: end_idx + 2])
                        buffer = buffer[end_idx + 2 :]
                        
                        if QImage and self.preview_callback:
                            try:
                                image = QImage.fromData(jpeg_data)
                                if not image.isNull():
                                    # Rate limiting: nur neuestes Frame anzeigen
                                    current_time = time.time()
                                    if current_time - last_frame_time >= target_frame_interval:
                                        self.preview_callback(image)
                                        frame_count += 1
                                        last_frame_time = current_time
                                        if frame_count == 1:
                                            self.log("Preview-Stream: Erstes Frame empfangen")
                                        frames_found += 1
                            except Exception as e:
                                # Fehler beim Dekodieren - überspringe Frame
                                pass
                    
                    # Wenn viele Frames gefunden wurden, etwas pausieren
                    if frames_found > 0:
                        time.sleep(0.01)
                        
                except Exception as e:
                    self.log(f"Preview-Stream: Fehler beim Lesen: {e}")
                    time.sleep(0.1)
                    continue
                    
        except Exception as e:
            self.log(f"Preview-Stream: Fehler: {e}")
        finally:
            self.log(f"Preview-Stream: Beendet (Frames empfangen: {frame_count})")
            try:
                if self.process and self.process.stdout:
                    self.process.stdout.close()
            except Exception:
                pass

    def _stop_preview_reader(self):
        if self.preview_stop_event:
            self.preview_stop_event.set()
        if self.preview_reader_thread and self.preview_reader_thread.is_alive():
            self.preview_reader_thread.join(timeout=1)
        self.preview_reader_thread = None
        self.preview_stop_event = None

