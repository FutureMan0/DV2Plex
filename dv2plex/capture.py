"""
Capture-Engine für DV-Aufnahmen über dvgrab (Linux)
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, IO
from queue import Queue

from .merge import MergeEngine

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
        self.raw_output_path: Optional[Path] = None  # DV-Rohdatei
        self.logger = logging.getLogger(__name__)
        self.interactive_process: Optional[subprocess.Popen] = None  # Für interaktiven Modus (dvgrab autosplit)
        self.preview_dvgrab_process: Optional[subprocess.Popen] = None  # dvgrab-Prozess für Preview (veraltet)
        # Neue Variablen für dvgrab autosplit Architektur
        self.autosplit_dvgrab_process: Optional[subprocess.Popen] = None  # dvgrab mit autosplit
        self.splits_dir: Optional[Path] = None  # Pfad zu LowRes/splits/
        self.preview_monitor_thread: Optional[threading.Thread] = None  # Thread für Preview-Monitoring
        self.preview_file_process: Optional[subprocess.Popen] = None  # ffmpeg für Preview aus Datei

    def detect_firewire_device(self) -> Optional[str]:
        """
        Erkennt automatisch das erste verfügbare FireWire-Gerät
        
        Returns:
            Gerätepfad (z.B. /dev/raw1394) oder Karten-Nummer (z.B. "0") oder None
        """
        try:
            # Methode 1: Prüfe /sys/bus/firewire/devices/ für moderne Linux-Systeme
            sys_firewire_path = Path("/sys/bus/firewire/devices")
            if sys_firewire_path.exists():
                # Finde alle FireWire-Geräte (fw0, fw1, etc.)
                devices = []
                for device_dir in sys_firewire_path.iterdir():
                    device_name = device_dir.name
                    # Ignoriere Untergeräte (z.B. fw1.0), nur Hauptgeräte (fw0, fw1)
                    if device_name.startswith("fw") and "." not in device_name:
                        # Prüfe ob es ein Verzeichnis ist und ein gültiges Gerät
                        if device_dir.is_dir():
                            # Extrahiere Karten-Nummer (fw0 -> 0, fw1 -> 1)
                            try:
                                card_num = int(device_name[2:])
                                devices.append((card_num, device_name))
                            except ValueError:
                                continue
                
                if devices:
                    # Sortiere nach Karten-Nummer und nimm das erste
                    devices.sort(key=lambda x: x[0])
                    card_num, device_name = devices[0]
                    self.log(f"FireWire-Gerät erkannt in /sys: {device_name} (Karte {card_num})")
                    # dvgrab verwendet -card Option mit Nummer, aber wir geben den Gerätenamen zurück
                    # für Kompatibilität geben wir die Karten-Nummer als String zurück
                    return str(card_num)
            
            # Methode 2: Prüfe Standard-Gerätepfade
            for device in ["/dev/raw1394", "/dev/video1394"]:
                if Path(device).exists():
                    self.log(f"FireWire-Gerät gefunden: {device}")
                    return device
            
            # Methode 3: Versuche dvgrab mit -card 0 (Standard)
            # Wenn dvgrab verfügbar ist, versuche einfach Karte 0
            if shutil.which(self.dvgrab_path):
                self.log("FireWire-Gerät: Verwende Standard-Karte 0")
                return "0"
            
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
    
    def _format_device_for_dvgrab(self, device: str) -> list[str]:
        """
        Formatiert das Gerät für dvgrab-Kommandos
        
        Args:
            device: Gerätepfad (z.B. /dev/raw1394) oder Karten-Nummer (z.B. "0")
        
        Returns:
            Liste von Argumenten für dvgrab (z.B. ["-card", "0"] oder ["-i", "/dev/raw1394"])
        """
        # Wenn es eine reine Zahl ist, verwende -card Option
        if device.isdigit():
            return ["-card", device]
        # Sonst verwende -i mit dem Gerätepfad
        return ["-i", device]

    def _start_dvgrab_autosplit(self, device: str, splits_dir: Path) -> bool:
        """
        Startet dvgrab mit autosplit-Funktion (schreibt direkt Dateien)
        
        Args:
            device: FireWire-Gerät
            splits_dir: Ausgabeordner für Split-Dateien
        
        Returns:
            True wenn erfolgreich gestartet
        """
        if self.autosplit_dvgrab_process:
            return True  # Bereits gestartet
        
        # Prüfe, ob wir root sind
        is_root = os.geteuid() == 0
        
        try:
            # Erstelle splits-Ordner
            splits_dir.mkdir(parents=True, exist_ok=True)
            
            # Baue dvgrab-Befehl: -i (interaktiv), -a (autosplit), -format dv2, -s 0 (keine Größen-Splits)
            # Ausgabe-Präfix: dvgrab fügt automatisch Timecode hinzu (z.B. capture-001-00.00.00.000.avi)
            output_prefix = str(splits_dir / "capture")
            dvgrab_cmd = [
                self.dvgrab_path,
            ] + self._format_device_for_dvgrab(device) + [
                "-i",  # Interaktiver Modus
                "-a",  # Autosplit bei Szenenänderungen
                "-format", "dv2",  # DV Type 2 / AVI-kompatibel
                "-s", "0",  # Keine Größen-Splits
                output_prefix,  # Ausgabe-Präfix (dvgrab fügt Timecode hinzu)
            ]
            
            # Wenn nicht root, versuche mit sudo
            if not is_root:
                cmd = ["sudo"] + dvgrab_cmd
                self.log("HINWEIS: dvgrab benötigt root-Rechte. Versuche mit sudo...")
            else:
                cmd = dvgrab_cmd
            
            self.log("Starte dvgrab mit autosplit...")
            self.log(f"dvgrab-Befehl: {' '.join(cmd)}")
            self.log(f"Ausgabe-Verzeichnis: {splits_dir}")
            
            # Starte dvgrab (stdout/stderr für Logging, stdin für interaktive Befehle)
            self.autosplit_dvgrab_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=False,  # Binärmodus für stdin (Befehle als Bytes)
                bufsize=0,  # Unbuffered
            )
            
            # Warte kurz, damit der Prozess startet
            time.sleep(1)
            
            if self.autosplit_dvgrab_process.poll() is None:
                self.log("dvgrab autosplit gestartet")
                self.log("Verfügbare Befehle: a=rewind, p=play, c=capture, k=pause, Esc=stop")
                # Setze auch interactive_process für Kompatibilität mit bestehenden Methoden
                self.interactive_process = self.autosplit_dvgrab_process
                return True
            else:
                error_output = ""
                if self.autosplit_dvgrab_process.stderr:
                    try:
                        error_output_bytes = self.autosplit_dvgrab_process.stderr.read()
                        if isinstance(error_output_bytes, bytes):
                            error_output = error_output_bytes.decode('utf-8', errors='ignore')
                        else:
                            error_output = str(error_output_bytes)
                    except Exception as e:
                        self.log(f"Fehler beim Lesen von stderr: {e}")
                self.log(f"Fehler beim Starten von dvgrab autosplit: Return-Code {self.autosplit_dvgrab_process.returncode}")
                if error_output:
                    self.log(f"Fehler-Ausgabe: {error_output[:500]}")
                
                # Wenn raw1394-Fehler und nicht root, gebe Hinweis
                if "raw1394" in error_output.lower() and not is_root:
                    self.log("")
                    self.log("=" * 60)
                    self.log("FEHLER: dvgrab benötigt root-Rechte für FireWire-Zugriff!")
                    self.log("")
                    self.log("Lösungen:")
                    self.log("1. Starten Sie die Anwendung mit sudo:")
                    self.log("   sudo python start.py --no-gui")
                    self.log("")
                    self.log("2. Oder konfigurieren Sie udev-Regeln für FireWire:")
                    self.log("   sudo nano /etc/udev/rules.d/99-raw1394.rules")
                    self.log("   Fügen Sie hinzu:")
                    self.log('   KERNEL=="raw1394", MODE="0666"')
                    self.log("   Dann: sudo udevadm control --reload-rules")
                    self.log("=" * 60)
                    self.log("")
                
                self.autosplit_dvgrab_process = None
                return False
                
        except Exception as e:
            self.log(f"Fehler beim Starten von dvgrab autosplit: {e}")
            self.autosplit_dvgrab_process = None
            return False

    def _get_latest_split_file(self) -> Optional[Path]:
        """
        Findet die neueste vollständig geschriebene Datei im splits-Ordner
        
        Returns:
            Pfad zur neuesten vollständigen Datei oder None
        """
        if not self.splits_dir or not self.splits_dir.exists():
            return None
        
        try:
            # Finde alle Video-Dateien im splits-Ordner (avi, dv, etc.)
            video_files = []
            for pattern in ["*.avi", "*.dv", "*.AVI", "*.DV"]:
                video_files.extend(self.splits_dir.glob(pattern))
            
            if not video_files:
                return None
            
            # Sortiere nach mtime (neueste zuerst)
            video_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            
            # Prüfe, ob die neueste Datei vollständig ist (nicht mehr wächst)
            # Warte bis die Dateigröße stabil ist
            latest = video_files[0]
            if latest.exists():
                # Prüfe ob Datei vollständig ist (nicht mehr wächst)
                size1 = latest.stat().st_size
                time.sleep(0.5)  # Warte 0.5 Sekunden
                if latest.exists():
                    size2 = latest.stat().st_size
                    # Wenn Größe gleich ist, ist die Datei wahrscheinlich vollständig
                    if size1 == size2 and size1 > 0:
                        return latest
                    # Wenn Datei noch wächst, ist sie noch nicht fertig
                    # Nimm die vorherige Datei, falls vorhanden
                    if len(video_files) > 1:
                        return video_files[1]
            
            return latest
        except Exception as e:
            self.log(f"Fehler beim Finden der neuesten Split-Datei: {e}")
            return None

    def _start_preview_from_file(self, file_path: Path, fps: int) -> Optional[subprocess.Popen]:
        """
        Startet ffmpeg-Prozess für Preview aus einer Datei
        
        Args:
            file_path: Pfad zur Video-Datei
            fps: FPS für Preview
        
        Returns:
            subprocess.Popen oder None bei Fehler
        """
        if not file_path.exists():
            return None
        
        try:
            # Prüfe Dateigröße - muss > 0 sein
            file_size = file_path.stat().st_size
            if file_size == 0:
                self.log(f"Preview: Datei ist leer: {file_path.name}")
                return None
            
            # ffmpeg liest Datei und konvertiert zu MJPEG
            # Verwende -analyzeduration und -probesize für bessere Kompatibilität
            ffmpeg_cmd = [
                str(self.ffmpeg_path),
                "-analyzeduration", "10000000",
                "-probesize", "10000000",
                "-i", str(file_path),  # Input-Datei
                "-vf", f"yadif,fps={fps},scale=640:-1",  # Deinterlace + FPS + Skalierung
                "-f", "mjpeg",  # MJPEG-Format
                "-q:v", "5",  # Qualität
                "-",  # Ausgabe nach stdout
            ]
            
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
            )
            
            # Warte kurz und prüfe ob Prozess gestartet wurde
            time.sleep(0.5)
            if process.poll() is not None:
                # Prozess wurde sofort beendet
                try:
                    if process.stderr:
                        stderr_data = b""
                        while True:
                            chunk = process.stderr.read(4096)
                            if not chunk:
                                break
                            stderr_data += chunk if isinstance(chunk, bytes) else chunk.encode()
                        if stderr_data:
                            stderr_text = stderr_data.decode('utf-8', errors='ignore')
                            self.log(f"Preview-ffmpeg-Fehler für {file_path.name}: {stderr_text[:500]}")
                except:
                    pass
                return None
            
            return process
            
        except Exception as e:
            self.log(f"Fehler beim Starten von Preview-ffmpeg aus Datei {file_path.name}: {e}")
            return None

    def _monitor_splits_for_preview(self):
        """
        Thread-Funktion: Überwacht splits-Ordner für Preview
        Liest kontinuierlich die neueste Datei und zeigt Frames an
        """
        if not self.splits_dir:
            self.log("Preview-Monitor: splits_dir nicht gesetzt")
            return
        
        if not self.preview_callback:
            self.log("Preview-Monitor: preview_callback nicht gesetzt")
            return
        
        self.log("Preview-Monitor: Starte Überwachung...")
        last_file = None
        preview_process = None
        preview_reader_thread = None
        
        try:
            while (
                self.is_capturing
                and (not self.preview_stop_event or not self.preview_stop_event.is_set())
            ):
                # Finde neueste Datei
                latest = self._get_latest_split_file()
                
                if latest and latest != last_file:
                    # Neue Datei gefunden, starte Preview
                    self.log(f"Preview-Monitor: Neue Datei gefunden: {latest.name}")
                    
                    # Stoppe alten Preview-Prozess
                    if preview_process:
                        try:
                            preview_process.terminate()
                            preview_process.wait(timeout=1)
                        except:
                            try:
                                preview_process.kill()
                            except:
                                pass
                        preview_process = None
                    
                    # Warte auf alten Reader-Thread
                    if preview_reader_thread and preview_reader_thread.is_alive():
                        preview_reader_thread.join(timeout=1)
                    
                    # Starte neuen Preview-Prozess
                    preview_fps = getattr(self, 'preview_fps', 10)
                    preview_process = self._start_preview_from_file(latest, preview_fps)
                    
                    if preview_process:
                        # Starte Reader-Thread für diese Datei
                        preview_reader_thread = threading.Thread(
                            target=self._read_preview_from_process,
                            args=(preview_process, latest),
                            daemon=True,
                        )
                        preview_reader_thread.start()
                        last_file = latest
                    else:
                        self.log("Preview-Monitor: Konnte Preview-Prozess nicht starten")
                
                # Prüfe alle 0.5 Sekunden
                time.sleep(0.5)
                
        except Exception as e:
            self.log(f"Preview-Monitor: Fehler: {e}")
        finally:
            # Cleanup
            if preview_process:
                try:
                    preview_process.terminate()
                    preview_process.wait(timeout=1)
                except:
                    try:
                        preview_process.kill()
                    except:
                        pass
            
            if preview_reader_thread and preview_reader_thread.is_alive():
                preview_reader_thread.join(timeout=1)
            
            self.log("Preview-Monitor: Beendet")

    def _read_preview_from_process(self, process: subprocess.Popen, file_path: Path):
        """
        Liest Preview-Frames von einem ffmpeg-Prozess (der eine Datei liest)
        
        Args:
            process: ffmpeg-Prozess
            file_path: Pfad zur Datei (für Logging)
        """
        if not process or not process.stdout or not self.preview_callback:
            return
        
        buffer = bytearray()
        jpeg_start = b"\xff\xd8"
        jpeg_end = b"\xff\xd9"
        frame_count = 0
        last_frame_time = 0
        preview_fps = getattr(self, 'preview_fps', 10)
        target_frame_interval = 1.0 / max(preview_fps, 5)
        
        try:
            while (
                (not self.preview_stop_event or not self.preview_stop_event.is_set())
                and process
                and process.poll() is None
            ):
                try:
                    chunk = process.stdout.read(8192)
                    
                    if not chunk:
                        if process.poll() is not None:
                            break
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
                                            self.log(f"Preview: Erstes Frame von {file_path.name}")
                            except Exception:
                                pass
                
                except Exception as e:
                    self.log(f"Preview: Fehler beim Lesen: {e}")
                    time.sleep(0.1)
                    continue
        
        except Exception as e:
            self.log(f"Preview: Fehler: {e}")
        finally:
            try:
                if process and process.stdout:
                    process.stdout.close()
            except Exception:
                pass

    def _start_preview_ffmpeg(self, fps: int) -> bool:
        """
        Startet ffmpeg-Prozess für Preview
        
        Args:
            fps: FPS für Preview
        
        Returns:
            True wenn erfolgreich gestartet
        """
        if self.preview_process:
            return True  # Bereits gestartet
        
        try:
            # ffmpeg liest DV von stdin und konvertiert zu MJPEG
            # HINWEIS: MJPEG unterstützt kein Audio, daher nur Video mappen
            # Audio bleibt im Recording erhalten (Recording-ffmpeg verwendet -map 0:v -map 0:a)
            ffmpeg_cmd = [
                str(self.ffmpeg_path),
                "-f", "dv",  # DV-Format vom stdin
                "-i", "-",  # Input von stdin
                "-map", "0:v",  # Nur Video-Stream (MJPEG unterstützt kein Audio)
                "-vf", f"yadif,fps={fps},scale=640:-1",  # Deinterlace + FPS + Skalierung
                "-f", "mjpeg",  # MJPEG-Format
                "-q:v", "5",  # Qualität
                "-",  # Ausgabe nach stdout
            ]
            
            self.log("Starte Preview-ffmpeg...")
            self.log(f"Preview-ffmpeg-Befehl: {' '.join(ffmpeg_cmd)}")
            
            self.preview_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
            )
            
            # Warte kurz und prüfe ob Prozess gestartet wurde
            time.sleep(0.5)
            if self.preview_process.poll() is not None:
                # Prozess wurde sofort beendet
                try:
                    if self.preview_process.stderr:
                        stderr_data = b""
                        while True:
                            chunk = self.preview_process.stderr.read(4096)
                            if not chunk:
                                break
                            stderr_data += chunk if isinstance(chunk, bytes) else chunk.encode()
                        
                        if stderr_data:
                            stderr_text = stderr_data.decode('utf-8', errors='ignore')
                            self.log(f"Preview-ffmpeg-Fehler: {stderr_text[:500]}")
                except:
                    pass
                self.preview_process = None
                return False
            
            self.log("Preview-ffmpeg gestartet")
            return True
            
        except Exception as e:
            self.log(f"Fehler beim Starten von Preview-ffmpeg: {e}")
            self.preview_process = None
            return False

    # Recording-ffmpeg wurde entfernt - dvgrab schreibt jetzt direkt Dateien mit autosplit
    
    def _send_interactive_command(self, command: str) -> bool:
        """
        Sendet einen Befehl an dvgrab im interaktiven Modus
        
        Args:
            command: Befehl (z.B. 'a' für rewind, 'p' für play, 'c' für capture, 'k' für pause, '\x1b' für Esc/Stop)
                    Im interaktiven Modus werden einzelne Zeichen ohne Newline gesendet
        """
        # Verwende autosplit_dvgrab_process oder interactive_process (für Kompatibilität)
        process = self.autosplit_dvgrab_process or self.interactive_process
        if not process or process.poll() is not None:
            self.log("Interaktiver Modus nicht aktiv")
            return False
        
        try:
            if process.stdin:
                # Sende Befehl (ohne Newline für einzelne Zeichen)
                # Im interaktiven Modus von dvgrab werden einzelne Zeichen direkt verarbeitet
                # stdin ist im Binärmodus, daher müssen wir Bytes schreiben
                if isinstance(command, str):
                    command_bytes = command.encode('utf-8')
                else:
                    command_bytes = command
                process.stdin.write(command_bytes)
                process.stdin.flush()
                return True
            else:
                self.log("stdin nicht verfügbar im interaktiven Modus")
                return False
        except Exception as e:
            self.log(f"Fehler beim Senden des Befehls '{command}': {e}")
            return False

    def _stop_all_processes(self):
        """Stoppt alle Prozesse (dvgrab autosplit, preview-ffmpeg)"""
        # Stoppe Preview-Monitor-Thread
        if self.preview_monitor_thread and self.preview_monitor_thread.is_alive():
            # Thread wird durch preview_stop_event gestoppt
            self.preview_monitor_thread.join(timeout=2)
        self.preview_monitor_thread = None
        
        # Stoppe Preview-Datei-Prozess
        if self.preview_file_process:
            try:
                self.preview_file_process.terminate()
                self.preview_file_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    self.preview_file_process.kill()
                    self.preview_file_process.wait(timeout=1)
                except:
                    pass
            except Exception:
                pass
            self.preview_file_process = None
        
        # Stoppe Preview-ffmpeg (für Kompatibilität)
        if self.preview_process:
            try:
                if self.preview_process.stdin and not self.preview_process.stdin.closed:
                    self.preview_process.stdin.close()
                self.preview_process.terminate()
                self.preview_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    self.preview_process.kill()
                    self.preview_process.wait(timeout=1)
                except:
                    pass
            except Exception:
                pass
            self.preview_process = None
        
        # Stoppe dvgrab autosplit
        if self.autosplit_dvgrab_process:
            try:
                # Sende Stop-Befehl (ESC)
                if self.autosplit_dvgrab_process.stdin and not self.autosplit_dvgrab_process.stdin.closed:
                    try:
                        self.autosplit_dvgrab_process.stdin.write(b"\x1b")  # ESC als Bytes
                        self.autosplit_dvgrab_process.stdin.flush()
                        time.sleep(0.5)
                    except (BrokenPipeError, OSError):
                        # stdin bereits geschlossen, ignoriere
                        pass
                
                self.autosplit_dvgrab_process.terminate()
                self.autosplit_dvgrab_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.autosplit_dvgrab_process.kill()
                self.autosplit_dvgrab_process.wait(timeout=2)
            except Exception:
                pass
            self.autosplit_dvgrab_process = None
        
        # Cleanup interactive_process (ist dasselbe wie autosplit_dvgrab_process)
        self.interactive_process = None
    
    def rewind(self) -> bool:
        """Spult die Kassette zurück (interaktiver Modus: 'a')"""
        if self.interactive_process:
            return self._send_interactive_command("a")
        else:
            self.log("HINWEIS: Interaktiver Modus nicht aktiv. Starte Aufnahme, um Kamerasteuerung zu aktivieren.")
            return False

    def play(self) -> bool:
        """Startet die Wiedergabe (interaktiver Modus: 'p')"""
        if self.interactive_process:
            return self._send_interactive_command("p")
        else:
            self.log("HINWEIS: Interaktiver Modus nicht aktiv. Starte Aufnahme, um Kamerasteuerung zu aktivieren.")
            return False

    def pause(self) -> bool:
        """Pausiert die Wiedergabe (interaktiver Modus: 'k')"""
        if self.interactive_process:
            return self._send_interactive_command("k")
        else:
            self.log("HINWEIS: Interaktiver Modus nicht aktiv. Starte Aufnahme, um Kamerasteuerung zu aktivieren.")
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
        Startet DV-Aufnahme mit dvgrab autosplit
        
        Args:
            output_path: Ausgabeordner (LowRes-Verzeichnis)
            part_number: Part-Nummer (wird nicht mehr verwendet, aber für Kompatibilität behalten)
            preview_callback: Optionaler Callback für Preview-Frames
            preview_fps: FPS für Preview
            auto_rewind_play: Automatisch Rewind und Play vor Aufnahme
        """
        try:
            if self.is_capturing:
                self.log("Aufnahme läuft bereits!")
                return False

            device = self.get_device()
            if not device:
                self.log("Kein FireWire-Gerät verfügbar!")
                return False

            output_dir = Path(output_path)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Erstelle splits-Ordner
            self.splits_dir = output_dir / "splits"
            self.splits_dir.mkdir(parents=True, exist_ok=True)
            
            # Setze Ausgabepfad für Merge (wird nach dem Stoppen erstellt)
            self.current_output_path = output_dir / "movie_merged.avi"

            self.preview_callback = preview_callback
            # Begrenze Preview-FPS für stabileres Bild (zu hohe FPS flackern gern)
            preview_fps = max(5, min(preview_fps, 15))
            self.preview_fps = preview_fps
            enable_preview = preview_callback is not None

            # 1. Starte dvgrab mit autosplit
            self.log("=== Starte dvgrab mit autosplit ===")
            if not self._start_dvgrab_autosplit(device, self.splits_dir):
                self.log("FEHLER: dvgrab autosplit konnte nicht gestartet werden")
                return False
            
            # 2. Starte Preview-Monitoring (falls aktiviert)
            if enable_preview:
                self.log("=== Starte Preview-Monitoring ===")
                self.preview_stop_event = threading.Event()
                self.preview_monitor_thread = threading.Thread(
                    target=self._monitor_splits_for_preview,
                    daemon=True,
                )
                self.preview_monitor_thread.start()
                self.log("Preview-Monitor: Thread gestartet")
            
            # 3. Automatischer Workflow: Rewind → Play → Start Capture
            if auto_rewind_play:
                self.log("=== Automatischer Workflow: Rewind → Play → Start Capture ===")
                
                # Rewind
                self.log("Spule Band zurück...")
                if self._send_interactive_command("a"):
                    self.log("Warte auf vollständiges Rewind (15 Sekunden)...")
                    time.sleep(15)
                else:
                    self.log("Warnung: Rewind-Befehl fehlgeschlagen")
                
                # Play
                self.log("Starte Wiedergabe...")
                if self._send_interactive_command("p"):
                    time.sleep(2)  # Warte auf Play-Start
                else:
                    self.log("Warnung: Play-Befehl fehlgeschlagen")
                
                # Capture-Befehl
                self.log("Starte Aufnahme...")
                if not self._send_interactive_command("c"):
                    self.log("Warnung: Capture-Befehl fehlgeschlagen (kann ignoriert werden)")
            else:
                self.log("=== Manueller Modus ===")
                self.log("Bitte steuern Sie die Kamera manuell oder verwenden Sie die Steuerungs-Buttons.")
                self.log("Verwenden Sie 'c' um die Aufnahme zu starten.")

            # 4. Markiere als aktiv und starte Monitoring
            self.is_capturing = True
            self.process = self.autosplit_dvgrab_process  # Für Kompatibilität
            
            self.capture_thread = threading.Thread(
                target=self._monitor_capture,
                daemon=True,
            )
            self.capture_thread.start()
            
            self.log("Aufnahme gestartet! Dateien werden in splits/ gespeichert.")
            return True

        except Exception as e:
            self.log(f"Fehler beim Starten der Aufnahme: {e}")
            self.is_capturing = False
            self._stop_preview()
            self._stop_all_processes()
            return False

    # Alte _start_preview() Methode entfernt - wird durch _start_preview_ffmpeg() ersetzt
    # Die neue Architektur verwendet unified dvgrab -> Stream-Verteilung -> Preview-ffmpeg

    def stop_capture(self) -> bool:
        """Stoppt die Aufnahme und führt automatisch Merge durch"""
        if not self.is_capturing:
            return False

        try:
            self.log("Stoppe Aufnahme...")

            # Stoppe Preview
            self._stop_preview()

            # Stoppe alle Prozesse (dvgrab autosplit)
            self._stop_all_processes()

            self.is_capturing = False
            self.log("Aufnahme gestoppt.")

            # Warte, damit alle Dateien vollständig geschrieben sind
            self.log("Warte auf vollständiges Schreiben der Split-Dateien...")
            # Warte bis Dateien nicht mehr wachsen
            if self.splits_dir and self.splits_dir.exists():
                max_wait = 10  # Maximal 10 Sekunden warten
                waited = 0
                while waited < max_wait:
                    files = list(self.splits_dir.glob("*.avi")) + list(self.splits_dir.glob("*.dv"))
                    if files:
                        # Prüfe ob alle Dateien stabil sind
                        all_stable = True
                        for f in files:
                            size1 = f.stat().st_size
                            time.sleep(0.5)
                            if f.exists():
                                size2 = f.stat().st_size
                                if size1 != size2:
                                    all_stable = False
                                    break
                        if all_stable:
                            break
                    waited += 0.5
                    time.sleep(0.5)
            else:
                time.sleep(2)

            # Führe automatisch Merge durch
            if self.splits_dir and self.splits_dir.exists():
                merge_engine = MergeEngine(self.ffmpeg_path, log_callback=self.log)
                merged_file = merge_engine.merge_splits(self.splits_dir, self.current_output_path)
                
                if merged_file and merged_file.exists():
                    self.log(f"Merge erfolgreich: {merged_file}")
                    # Zähle Split-Dateien für Info
                    split_files = list(self.splits_dir.glob("*.avi"))
                    self.log(f"Zusammengefügt: {len(split_files)} Split-Dateien")
                else:
                    self.log("WARNUNG: Merge fehlgeschlagen!")
            else:
                self.log(f"WARNUNG: splits-Ordner nicht gefunden: {self.splits_dir}")

            return True

        except Exception as e:
            self.log(f"Fehler beim Stoppen der Aufnahme: {e}")
            self.is_capturing = False
            self._stop_preview()
            self._stop_all_processes()
            return False

    def _read_preview_stderr(self):
        """Liest stderr vom Preview-ffmpeg-Prozess für Fehlerdiagnose"""
        if not self.preview_process or not self.preview_process.stderr:
            return
        
        try:
            while (
                self.preview_process
                and self.preview_process.poll() is None
                and (not self.preview_stop_event or not self.preview_stop_event.is_set())
            ):
                chunk = self.preview_process.stderr.read(1024)
                if chunk:
                    if isinstance(chunk, bytes):
                        stderr_text = chunk.decode('utf-8', errors='ignore')
                    else:
                        stderr_text = str(chunk)
                    # Logge nur wichtige Fehler (ignoriere "Concealing bitstream errors" - das ist normal bei DV)
                    # Ignoriere auch "Broken pipe", da dies beim Stoppen der Aufnahme normal ist
                    if any(keyword in stderr_text.lower() for keyword in ['error', 'failed', 'cannot', 'invalid']) and 'concealing bitstream errors' not in stderr_text.lower() and 'broken pipe' not in stderr_text.lower():
                        self.log(f"Preview-ffmpeg: {stderr_text[:200]}")
                else:
                    time.sleep(0.1)
        except Exception as e:
            # Ignoriere Fehler beim Lesen von stderr
            pass

    def _stop_preview(self):
        """Stoppt den Preview-Stream"""
        if self.preview_stop_event:
            self.preview_stop_event.set()
        
        # Stoppe Preview-Monitor-Thread
        if self.preview_monitor_thread and self.preview_monitor_thread.is_alive():
            self.preview_monitor_thread.join(timeout=2)
        self.preview_monitor_thread = None
        
        # Stoppe Preview-Datei-Prozess
        if self.preview_file_process:
            try:
                self.preview_file_process.terminate()
                self.preview_file_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    self.preview_file_process.kill()
                    self.preview_file_process.wait(timeout=1)
                except:
                    pass
            except Exception:
                pass
            self.preview_file_process = None
        
        # Stoppe Preview-ffmpeg-Prozess (für Kompatibilität mit alter Architektur)
        if self.preview_process:
            try:
                # Schließe stdin, damit ffmpeg sauber beendet wird
                if self.preview_process.stdin and not self.preview_process.stdin.closed:
                    self.preview_process.stdin.close()
                self.preview_process.terminate()
                self.preview_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    self.preview_process.kill()
                    self.preview_process.wait(timeout=1)
                except:
                    pass
            except Exception:
                pass
            self.preview_process = None

        # Alte Threads (nur wenn sie noch existieren)
        if hasattr(self, 'preview_reader_thread') and self.preview_reader_thread:
            if self.preview_reader_thread.is_alive():
                self.preview_reader_thread.join(timeout=1)
            self.preview_reader_thread = None
        
        if hasattr(self, 'preview_stderr_thread') and self.preview_stderr_thread:
            if self.preview_stderr_thread.is_alive():
                self.preview_stderr_thread.join(timeout=1)
            self.preview_stderr_thread = None
        
        self.preview_stop_event = None

    # _transcode_raw_to_mp4() wurde entfernt - nicht mehr benötigt mit autosplit

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
            return_code = self.process.wait()
            
            # Log return code für Debugging
            self.log(f"dvgrab-Prozess beendet mit Return-Code: {return_code}")

            # Warte kurz, damit stderr-Thread fertig wird
            stderr_thread.join(timeout=1)

            # Nur als beendet markieren, wenn nicht manuell gestoppt
            # (wenn stop_capture() aufgerufen wurde, wird is_capturing bereits False sein)
            if self.is_capturing:
                self.is_capturing = False
                self._stop_preview()
                self._stop_all_processes()
                
                # Wenn der Prozess sofort beendet wurde (z.B. kein Signal), logge Warnung
                # Return-Code -9 (SIGKILL) ist normal, wenn wir den Prozess hart beenden mussten
                if return_code != 0 and return_code not in [130, 143, -9]:
                    self.log(f"WARNUNG: Aufnahme wurde unerwartet beendet (Return-Code: {return_code}). Mögliche Ursachen:")
                    self.log("  - Kein Signal von der Kamera (Bitte Play auf der Kamera drücken)")
                    self.log("  - Kamera nicht richtig verbunden")
                    self.log("  - dvgrab-Fehler (siehe stderr-Logs)")

        except Exception as e:
            self.log(f"Fehler beim Überwachen der Aufnahme: {e}")
            self.is_capturing = False
            self._stop_preview()
            self._stop_all_processes()

    def _read_stderr(self):
        """Liest stderr in einem separaten Thread"""
        try:
            if not self.process or not self.process.stderr:
                return
                
            # Prüfe, ob stderr im Text- oder Binärmodus ist
            # Wenn text=True in subprocess.Popen, ist stderr ein Text-Stream
            # Wenn text=False, ist stderr ein Bytes-Stream
            stderr_data = ""
            stderr_bytes = b""
            is_text_mode = hasattr(self.process.stderr, 'encoding')
            
            if is_text_mode:
                # Text-Modus: Lese als String
                while self.process.poll() is None:
                    chunk = self.process.stderr.read(4096)
                    if chunk:
                        stderr_data += chunk
                    else:
                        time.sleep(0.1)
                
                remaining = self.process.stderr.read()
                if remaining:
                    stderr_data += remaining
                
                # Konvertiere zu Bytes für _process_stderr
                stderr_bytes = stderr_data.encode('utf-8', errors='ignore')
            else:
                # Binärmodus: Lese als Bytes
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
        """Verarbeitet stderr-Ausgabe von dvgrab"""
        return_code = self.process.returncode if self.process else None
        stderr_text = stderr_bytes.decode("utf-8", errors="ignore") if stderr_bytes else ""
        
        # Log stderr für Debugging (nur relevante Teile)
        if stderr_text:
            # Zeige wichtige Meldungen
            if "Waiting for DV" in stderr_text:
                self.log("dvgrab wartet auf DV-Signal...")
            elif "Capture Started" in stderr_text or "capture started" in stderr_text.lower():
                self.log("dvgrab: Aufnahme gestartet!")
            elif "Capture Stopped" in stderr_text or "capture stopped" in stderr_text.lower():
                self.log("dvgrab: Aufnahme gestoppt.")
            elif "autosplit" in stderr_text.lower() or "new file" in stderr_text.lower():
                # Zeige Autosplit-Meldungen
                self.log(f"dvgrab: {stderr_text.strip()[:200]}")
            elif len(stderr_text) > 0:
                # Zeige nur die letzten 300 Zeichen, um nicht zu viel zu loggen
                self.log(f"dvgrab: {stderr_text[-300:]}")

        if return_code == 0 or return_code is None:
            self.log(f"Aufnahme erfolgreich beendet: {self.current_output_path}")
        elif return_code in [1, 130, 143, -9]:  # Normal beendet (SIGTERM/SIGINT/SIGKILL durch Stop)
            self.log(f"Aufnahme erfolgreich gestoppt: {self.current_output_path}")
        else:
            if "End of file" in stderr_text or "Interrupted" in stderr_text:
                self.log(f"Aufnahme beendet (Bandende oder manuell): {self.current_output_path}")
            elif "No input" in stderr_text or "Cannot open" in stderr_text or "Device" in stderr_text or "Waiting for DV" in stderr_text:
                self.log(f"WARNUNG: dvgrab konnte kein DV-Signal empfangen.")
                self.log(f"Mögliche Ursachen:")
                self.log(f"  - Kamera ist nicht im Play-Modus")
                self.log(f"  - Kamera sendet kein Signal")
                self.log(f"  - FireWire-Verbindung problematisch")
                self.log(f"Bitte stellen Sie die Kamera in den 'Edit/Play'-Modus und drücken Sie Play.")
                if stderr_text:
                    self.log(f"dvgrab-Ausgabe: {stderr_text[-500:]}")
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
                        # Prüfe, ob der Prozess beendet wurde
                        if self.preview_process.poll() is not None:
                            # Prozess beendet - lese stderr für Fehler
                            try:
                                if self.preview_process.stderr:
                                    # Warte kurz, damit stderr vollständig geschrieben wird
                                    time.sleep(0.2)
                                    # Lese alle verfügbaren Daten in mehreren Chunks
                                    stderr_data = b""
                                    while True:
                                        chunk = self.preview_process.stderr.read(4096)
                                        if not chunk:
                                            break
                                        if isinstance(chunk, bytes):
                                            stderr_data += chunk
                                        else:
                                            stderr_data += chunk.encode('utf-8', errors='ignore')
                                    
                                    if stderr_data:
                                        if isinstance(stderr_data, bytes):
                                            stderr_text = stderr_data.decode('utf-8', errors='ignore')
                                        else:
                                            stderr_text = str(stderr_data)
                                        if "Permission denied" in stderr_text or "Cannot open" in stderr_text:
                                            self.log("Preview-Fehler: Keine Berechtigung für FireWire-Gerät")
                                            self.log("HINWEIS: dvgrab benötigt root-Rechte. Starten Sie die Anwendung mit sudo.")
                                        elif "No such file" in stderr_text or "Device" in stderr_text:
                                            self.log(f"Preview-Fehler: Gerät nicht gefunden: {stderr_text[:200]}")
                                        else:
                                            self.log(f"Preview-Fehler: {stderr_text[:300]}")
                            except:
                                pass
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
