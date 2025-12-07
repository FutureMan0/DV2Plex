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
from pathlib import Path
from typing import Optional, Callable
from queue import Queue

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
        self.interactive_process: Optional[subprocess.Popen] = None  # Für interaktiven Modus (unified dvgrab)
        self.preview_dvgrab_process: Optional[subprocess.Popen] = None  # dvgrab-Prozess für Preview (veraltet)
        # Neue Variablen für unified dvgrab Architektur
        self.unified_dvgrab_process: Optional[subprocess.Popen] = None  # Einziger dvgrab-Prozess
        self.recording_ffmpeg_process: Optional[subprocess.Popen] = None  # ffmpeg für Recording
        self.stream_distribution_thread: Optional[threading.Thread] = None  # Thread für Stream-Verteilung
        self.stream_distribution_stop_event: Optional[threading.Event] = None
        self.preview_pipe_writer: Optional[subprocess.Popen] = None  # Pipe-Writer für Preview
        self.recording_pipe_writer: Optional[subprocess.Popen] = None  # Pipe-Writer für Recording
        self.recording_stderr_thread: Optional[threading.Thread] = None  # Thread für Recording-ffmpeg stderr

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

    def _start_unified_dvgrab(self, device: str) -> bool:
        """
        Startet dvgrab im interaktiven Modus mit stdout-Ausgabe
        
        Args:
            device: FireWire-Gerät
        
        Returns:
            True wenn erfolgreich gestartet
        """
        if self.unified_dvgrab_process:
            return True  # Bereits gestartet
        
        # Prüfe, ob wir root sind
        is_root = os.geteuid() == 0
        
        try:
            # Baue dvgrab-Befehl: -i (interaktiv), -format dv2, -s 0 (keine Splits), - (stdout)
            dvgrab_cmd = [
                self.dvgrab_path,
            ] + self._format_device_for_dvgrab(device) + [
                "-i",  # Interaktiver Modus
                "-format", "dv2",  # DV Type 2 / AVI-kompatibel
                "-s", "0",  # Keine Größen-Splits
                "-",  # Ausgabe nach stdout
            ]
            
            # Wenn nicht root, versuche mit sudo
            if not is_root:
                cmd = ["sudo"] + dvgrab_cmd
                self.log("HINWEIS: dvgrab benötigt root-Rechte. Versuche mit sudo...")
            else:
                cmd = dvgrab_cmd
            
            self.log("Starte unified dvgrab (interaktiv mit stdout)...")
            self.log(f"dvgrab-Befehl: {' '.join(cmd)}")
            
            # WICHTIG: stdin muss text=True sein (für interaktive Befehle), 
            # aber stdout muss binär sein (für DV-Daten)
            # subprocess.Popen unterstützt text=True nur global, daher müssen wir
            # stdin separat handhaben oder text=False verwenden und stdin manuell encodieren
            # Lösung: text=False, stdin wird als Bytes geschrieben
            self.unified_dvgrab_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=False,  # Binärmodus für stdout (DV-Daten), stdin wird als Bytes geschrieben
                bufsize=0,  # Unbuffered
            )
            
            # Warte kurz, damit der Prozess startet
            time.sleep(1)
            
            if self.unified_dvgrab_process.poll() is None:
                self.log("Unified dvgrab gestartet")
                self.log("Verfügbare Befehle: a=rewind, p=play, c=capture, k=pause, Esc=stop")
                # Setze auch interactive_process für Kompatibilität mit bestehenden Methoden
                self.interactive_process = self.unified_dvgrab_process
                return True
            else:
                error_output = ""
                if self.unified_dvgrab_process.stderr:
                    try:
                        error_output_bytes = self.unified_dvgrab_process.stderr.read()
                        if isinstance(error_output_bytes, bytes):
                            error_output = error_output_bytes.decode('utf-8', errors='ignore')
                        else:
                            error_output = str(error_output_bytes)
                    except Exception as e:
                        self.log(f"Fehler beim Lesen von stderr: {e}")
                self.log(f"Fehler beim Starten von unified dvgrab: Return-Code {self.unified_dvgrab_process.returncode}")
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
                
                self.unified_dvgrab_process = None
                return False
                
        except Exception as e:
            self.log(f"Fehler beim Starten von unified dvgrab: {e}")
            self.unified_dvgrab_process = None
            return False

    def _distribute_stream(self):
        """
        Thread-Funktion: Liest dvgrab stdout und verteilt den Stream an beide Pipes (Preview + Recording)
        """
        if not self.unified_dvgrab_process or not self.unified_dvgrab_process.stdout:
            self.log("Stream-Verteilung: dvgrab stdout nicht verfügbar")
            return
        
        preview_pipe = None
        recording_pipe = None
        
        self.log("Stream-Verteilung: Starte...")
        chunk_size = 65536  # 64KB Chunks
        
        try:
            while (
                self.unified_dvgrab_process
                and self.unified_dvgrab_process.poll() is None
                and (not self.stream_distribution_stop_event or not self.stream_distribution_stop_event.is_set())
            ):
                # Dynamisch Pipes holen (falls sie später gestartet werden)
                if not preview_pipe and self.preview_process and self.preview_process.stdin:
                    preview_pipe = self.preview_process.stdin
                    self.log("Stream-Verteilung: Preview-Pipe hinzugefügt")
                
                if not recording_pipe and self.recording_ffmpeg_process and self.recording_ffmpeg_process.stdin:
                    recording_pipe = self.recording_ffmpeg_process.stdin
                    self.log("Stream-Verteilung: Recording-Pipe hinzugefügt")
                
                # Wenn keine Pipes verfügbar sind, warte kurz
                if not preview_pipe and not recording_pipe:
                    time.sleep(0.1)
                    continue
                
                try:
                    # Lese Chunk von dvgrab stdout
                    chunk = self.unified_dvgrab_process.stdout.read(chunk_size)
                    
                    if not chunk:
                        # Prüfe ob Prozess beendet wurde
                        if self.unified_dvgrab_process.poll() is not None:
                            break
                        time.sleep(0.01)
                        continue
                    
                    # Schreibe Chunk in beide Pipes (wenn verfügbar)
                    preview_failed = False
                    if preview_pipe and not preview_pipe.closed:
                        try:
                            preview_pipe.write(chunk)
                            preview_pipe.flush()
                        except (BrokenPipeError, OSError):
                            # Preview-Prozess beendet, schließe Pipe
                            preview_pipe = None
                            preview_failed = True
                            self.log("Stream-Verteilung: Preview-Pipe geschlossen (Preview-ffmpeg beendet)")
                    
                    recording_failed = False
                    if recording_pipe and not recording_pipe.closed:
                        try:
                            recording_pipe.write(chunk)
                            recording_pipe.flush()
                        except (BrokenPipeError, OSError):
                            # Recording-Prozess beendet, schließe Pipe
                            recording_pipe = None
                            recording_failed = True
                            self.log("Stream-Verteilung: Recording-Pipe geschlossen (Recording-ffmpeg beendet)")
                    
                    # Wenn Recording-Pipe geschlossen ist, ist das kritisch - stoppe
                    if recording_failed:
                        self.log("Stream-Verteilung: Recording beendet, beende Stream-Verteilung...")
                        break
                    
                    # Wenn nur Preview beendet wurde, fahre mit Recording fort
                    if preview_failed and recording_pipe:
                        self.log("Stream-Verteilung: Preview beendet, fahre mit Recording fort...")
                        preview_pipe = None
                        
                except Exception as e:
                    self.log(f"Stream-Verteilung: Fehler beim Lesen/Schreiben: {e}")
                    time.sleep(0.1)
                    continue
                    
        except Exception as e:
            self.log(f"Stream-Verteilung: Fehler: {e}")
        finally:
            self.log("Stream-Verteilung: Beendet")
            # Schließe Pipes
            try:
                if preview_pipe and not preview_pipe.closed:
                    preview_pipe.close()
            except:
                pass
            try:
                if recording_pipe and not recording_pipe.closed:
                    recording_pipe.close()
            except:
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

    def _start_recording_ffmpeg(self, output_path: Path) -> bool:
        """
        Startet ffmpeg-Prozess für Recording (H.264/AAC MP4)
        
        Args:
            output_path: Ausgabepfad für MP4-Datei
        
        Returns:
            True wenn erfolgreich gestartet
        """
        if self.recording_ffmpeg_process:
            return True  # Bereits gestartet
        
        try:
            # ffmpeg liest DV von stdin und konvertiert zu H.264/AAC MP4
            # WICHTIG: -analyzeduration und -probesize geben ffmpeg mehr Zeit, um auf Daten zu warten
            ffmpeg_cmd = [
                str(self.ffmpeg_path),
                "-analyzeduration", "10000000",  # 10 Sekunden für Analyse
                "-probesize", "10000000",  # 10MB Probe-Größe
                "-f", "dv",  # DV-Format vom stdin
                "-i", "-",  # Input von stdin
                "-map", "0:v",  # Video-Stream
                "-map", "0:a:0?",  # Nur erster Audiotrack (optional, falls vorhanden)
                "-c:v", "libx264",  # H.264 Video-Codec
                "-preset", "veryfast",  # Encoding-Preset
                "-crf", "18",  # Qualität (niedrigere Werte = bessere Qualität)
                "-c:a", "aac",  # AAC Audio-Codec
                "-b:a", "192k",  # Audio-Bitrate
                "-ac", "2",  # Erzwinge Stereo
                "-ar", "48000",  # Erzwinge 48kHz Sampling-Rate
                "-y",  # Überschreibe vorhandene Datei
                str(output_path),  # Ausgabedatei
            ]
            
            self.log("Starte Recording-ffmpeg...")
            self.log(f"Recording-ffmpeg-Befehl: {' '.join(ffmpeg_cmd)}")
            
            self.recording_ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
            )
            
            # Warte kurz und prüfe ob Prozess gestartet wurde
            time.sleep(0.5)
            if self.recording_ffmpeg_process.poll() is not None:
                # Prozess wurde sofort beendet
                try:
                    if self.recording_ffmpeg_process.stderr:
                        stderr_data = b""
                        while True:
                            chunk = self.recording_ffmpeg_process.stderr.read(4096)
                            if not chunk:
                                break
                            stderr_data += chunk if isinstance(chunk, bytes) else chunk.encode()
                        
                        if stderr_data:
                            stderr_text = stderr_data.decode('utf-8', errors='ignore')
                            self.log(f"Recording-ffmpeg-Fehler: {stderr_text[:500]}")
                except:
                    pass
                self.recording_ffmpeg_process = None
                return False
            
            self.log("Recording-ffmpeg gestartet")
            
            # Starte Thread zum Lesen von stderr für Fehlerdiagnose
            self.recording_stderr_thread = threading.Thread(
                target=self._read_recording_stderr,
                daemon=True,
            )
            self.recording_stderr_thread.start()
            
            return True
            
        except Exception as e:
            self.log(f"Fehler beim Starten von Recording-ffmpeg: {e}")
            self.recording_ffmpeg_process = None
            return False

    def _read_recording_stderr(self):
        """Liest stderr vom Recording-ffmpeg-Prozess für Fehlerdiagnose"""
        if not self.recording_ffmpeg_process or not self.recording_ffmpeg_process.stderr:
            return
        
        try:
            while (
                self.recording_ffmpeg_process
                and self.recording_ffmpeg_process.poll() is None
            ):
                chunk = self.recording_ffmpeg_process.stderr.read(1024)
                if chunk:
                    if isinstance(chunk, bytes):
                        stderr_text = chunk.decode('utf-8', errors='ignore')
                    else:
                        stderr_text = str(chunk)
                    # Filtere "Concealing bitstream errors" - das ist normal bei DV
                    if 'concealing bitstream errors' in stderr_text.lower():
                        # Ignoriere diese Warnungen
                        continue
                    
                    # Logge wichtige Fehler
                    if any(keyword in stderr_text.lower() for keyword in ['error', 'failed', 'cannot', 'invalid']) and 'concealing' not in stderr_text.lower():
                        self.log(f"Recording-ffmpeg: {stderr_text[:300]}")
                    # Logge auch Fortschrittsmeldungen (frame=, time=, bitrate=)
                    elif any(keyword in stderr_text.lower() for keyword in ['frame=', 'time=', 'bitrate=']):
                        # Zeige nur alle 5 Sekunden, um Log-Spam zu vermeiden
                        if hasattr(self, '_last_recording_log_time'):
                            if time.time() - self._last_recording_log_time > 5:
                                self.log(f"Recording-ffmpeg: {stderr_text.strip()[:200]}")
                                self._last_recording_log_time = time.time()
                        else:
                            self._last_recording_log_time = time.time()
                            self.log(f"Recording-ffmpeg: {stderr_text.strip()[:200]}")
                else:
                    time.sleep(0.1)
        except Exception as e:
            # Ignoriere Fehler beim Lesen von stderr
            pass
        finally:
            # Wenn Prozess beendet wurde, lese restliche stderr
            if self.recording_ffmpeg_process:
                try:
                    remaining = self.recording_ffmpeg_process.stderr.read()
                    if remaining:
                        if isinstance(remaining, bytes):
                            stderr_text = remaining.decode('utf-8', errors='ignore')
                        else:
                            stderr_text = str(remaining)
                        # Zeige wichtige Fehler
                        if any(keyword in stderr_text.lower() for keyword in ['error', 'failed', 'cannot', 'invalid']):
                            self.log(f"Recording-ffmpeg (beendet): {stderr_text[:500]}")
                except:
                    pass

    # Alte _start_interactive_mode() Methode entfernt - wird durch _start_unified_dvgrab() ersetzt
    # Die neue Architektur verwendet unified dvgrab mit stdout statt direkter Dateiausgabe
    
    def _send_interactive_command(self, command: str) -> bool:
        """
        Sendet einen Befehl an dvgrab im interaktiven Modus
        
        Args:
            command: Befehl (z.B. 'a' für rewind, 'p' für play, 'c' für capture, 'k' für pause, '\x1b' für Esc/Stop)
                    Im interaktiven Modus werden einzelne Zeichen ohne Newline gesendet
        """
        # Verwende unified_dvgrab_process oder interactive_process (für Kompatibilität)
        process = self.unified_dvgrab_process or self.interactive_process
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
        """Stoppt alle Prozesse (dvgrab, preview-ffmpeg, recording-ffmpeg)"""
        # Stoppe Stream-Verteilung
        if self.stream_distribution_stop_event:
            self.stream_distribution_stop_event.set()
        
        # Warte auf Stream-Verteilungs-Thread
        if self.stream_distribution_thread and self.stream_distribution_thread.is_alive():
            self.stream_distribution_thread.join(timeout=2)
        
        # Warte auf Recording-stderr-Thread
        if self.recording_stderr_thread and self.recording_stderr_thread.is_alive():
            self.recording_stderr_thread.join(timeout=1)
        self.recording_stderr_thread = None
        
        # Stoppe Recording-ffmpeg
        if self.recording_ffmpeg_process:
            try:
                if self.recording_ffmpeg_process.stdin and not self.recording_ffmpeg_process.stdin.closed:
                    self.recording_ffmpeg_process.stdin.close()
                self.recording_ffmpeg_process.terminate()
                self.recording_ffmpeg_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.recording_ffmpeg_process.kill()
                self.recording_ffmpeg_process.wait(timeout=1)
            except Exception:
                pass
            self.recording_ffmpeg_process = None
        
        # Stoppe Preview-ffmpeg (wird auch von _stop_preview() gemacht, aber sicherheitshalber hier auch)
        if self.preview_process:
            try:
                if self.preview_process.stdin and not self.preview_process.stdin.closed:
                    self.preview_process.stdin.close()
                self.preview_process.terminate()
                self.preview_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.preview_process.kill()
                self.preview_process.wait(timeout=1)
            except Exception:
                pass
            self.preview_process = None
        
        # Stoppe unified dvgrab
        if self.unified_dvgrab_process:
            try:
                # Sende Stop-Befehl (ESC)
                if self.unified_dvgrab_process.stdin and not self.unified_dvgrab_process.stdin.closed:
                    try:
                        self.unified_dvgrab_process.stdin.write(b"\x1b")  # ESC als Bytes
                        self.unified_dvgrab_process.stdin.flush()
                        time.sleep(0.5)
                    except (BrokenPipeError, OSError):
                        # stdin bereits geschlossen, ignoriere
                        pass
                
                self.unified_dvgrab_process.terminate()
                self.unified_dvgrab_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.unified_dvgrab_process.kill()
                self.unified_dvgrab_process.wait(timeout=2)
            except Exception:
                pass
            self.unified_dvgrab_process = None
        
        # Cleanup interactive_process (ist dasselbe wie unified_dvgrab_process)
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
        Startet DV-Aufnahme mit unified dvgrab -> ffmpeg Pipeline
        
        Args:
            output_path: Ausgabeordner
            part_number: Part-Nummer
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
            # Ausgabe als MP4 (H.264/AAC)
            self.current_output_path = output_dir / f"part_{part_number:03d}.mp4"

            self.preview_callback = preview_callback
            # Begrenze Preview-FPS für stabileres Bild (zu hohe FPS flackern gern)
            preview_fps = max(5, min(preview_fps, 15))
            self.preview_fps = preview_fps
            enable_preview = preview_callback is not None

            # 1. Starte unified dvgrab
            self.log("=== Starte unified dvgrab ===")
            if not self._start_unified_dvgrab(device):
                self.log("FEHLER: unified dvgrab konnte nicht gestartet werden")
                return False
            
            # 2. Starte Preview-ffmpeg sofort (falls aktiviert)
            if enable_preview:
                self.log("=== Starte Preview-ffmpeg ===")
                if not self._start_preview_ffmpeg(preview_fps):
                    self.log("WARNUNG: Preview-ffmpeg konnte nicht gestartet werden")
                    # Preview-Fehler sind nicht kritisch, fahre fort
                else:
                    # Starte Preview-Reader-Thread
                    self.preview_stop_event = threading.Event()
                    self.preview_stderr_thread = threading.Thread(
                        target=self._read_preview_stderr,
                        daemon=True,
                    )
                    self.preview_stderr_thread.start()
                    
                    self.preview_reader_thread = threading.Thread(
                        target=self._read_preview_stream,
                        daemon=True,
                    )
                    self.preview_reader_thread.start()
                    self.log("Preview-Stream: Thread gestartet")
            
            # 3. Starte Stream-Verteilungs-Thread
            self.stream_distribution_stop_event = threading.Event()
            self.stream_distribution_thread = threading.Thread(
                target=self._distribute_stream,
                daemon=True,
            )
            self.stream_distribution_thread.start()
            self.log("Stream-Verteilung: Thread gestartet")
            
            # 4. Automatischer Workflow: Rewind → Play → Start Recording
            if auto_rewind_play:
                self.log("=== Automatischer Workflow: Rewind → Play → Start Recording ===")
                
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
                
                # Starte Recording-ffmpeg
                self.log("Starte Recording-ffmpeg...")
                if not self._start_recording_ffmpeg(self.current_output_path):
                    self.log("FEHLER: Recording-ffmpeg konnte nicht gestartet werden")
                    return False
                
                # Capture-Befehl (optional, dvgrab streamt bereits)
                self.log("Starte Aufnahme...")
                if not self._send_interactive_command("c"):
                    self.log("Warnung: Capture-Befehl fehlgeschlagen (kann ignoriert werden)")
            else:
                self.log("=== Manueller Modus ===")
                self.log("Bitte steuern Sie die Kamera manuell oder verwenden Sie die Steuerungs-Buttons.")
                self.log("Verwenden Sie 'c' um die Aufnahme zu starten.")
                
                # Im manuellen Modus: Recording-ffmpeg wird später gestartet (nach manuellem 'c')
                # Für jetzt: Recording-ffmpeg starten, aber noch nicht aktiv aufnehmen
                # (dvgrab streamt bereits, ffmpeg wartet auf Daten)
                if not self._start_recording_ffmpeg(self.current_output_path):
                    self.log("FEHLER: Recording-ffmpeg konnte nicht gestartet werden")
                    return False

            # 5. Markiere als aktiv und starte Monitoring
            self.is_capturing = True
            self.process = self.unified_dvgrab_process  # Für Kompatibilität
            
            self.capture_thread = threading.Thread(
                target=self._monitor_capture,
                daemon=True,
            )
            self.capture_thread.start()
            
            self.log("Aufnahme gestartet!")
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
        """Stoppt die Aufnahme"""
        if not self.is_capturing:
            return False

        try:
            self.log("Stoppe Aufnahme...")

            # Stoppe Preview
            self._stop_preview()

            # Stoppe alle Prozesse (dvgrab, preview-ffmpeg, recording-ffmpeg)
            self._stop_all_processes()

            self.is_capturing = False
            self.log("Aufnahme gestoppt.")

            # Warte kurz, damit die Datei vollständig geschrieben ist
            time.sleep(1)

            # Prüfe ob Recording-Datei existiert und hat Audio
            if self.current_output_path and self.current_output_path.exists():
                # Validiere, dass Audio vorhanden ist
                try:
                    # Verwende ffprobe um Streams zu prüfen (falls verfügbar)
                    ffprobe_cmd = [
                        str(self.ffmpeg_path).replace("ffmpeg", "ffprobe"),
                        "-v", "error",
                        "-select_streams", "a",
                        "-show_entries", "stream=codec_type",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        str(self.current_output_path),
                    ]
                    result = subprocess.run(
                        ffprobe_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=5,
                    )
                    if result.returncode == 0 and b"audio" in result.stdout:
                        self.log("Aufnahme erfolgreich: Audio-Stream vorhanden")
                    else:
                        self.log("WARNUNG: Audio-Stream nicht gefunden in Aufnahme!")
                except Exception:
                    # ffprobe nicht verfügbar oder Fehler - ignoriere
                    pass
            else:
                self.log(f"WARNUNG: Aufnahmedatei nicht gefunden: {self.current_output_path}")

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
        
        # Stoppe Preview-ffmpeg-Prozess
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

        if self.preview_reader_thread and self.preview_reader_thread.is_alive():
            self.preview_reader_thread.join(timeout=1)
        self.preview_reader_thread = None
        
        if self.preview_stderr_thread and self.preview_stderr_thread.is_alive():
            self.preview_stderr_thread.join(timeout=1)
        self.preview_stderr_thread = None
        
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
        """Verarbeitet stderr-Ausgabe"""
        return_code = self.process.returncode if self.process else None
        stderr_text = stderr_bytes.decode("utf-8", errors="ignore") if stderr_bytes else ""
        
        # Log stderr für Debugging (nur relevante Teile)
        if stderr_text:
            # Zeige wichtige Meldungen
            if "Waiting for DV" in stderr_text:
                self.log("dvgrab wartet auf DV-Signal...")
            elif "Capture Started" in stderr_text:
                self.log("dvgrab: Aufnahme gestartet!")
            elif "Capture Stopped" in stderr_text:
                self.log("dvgrab: Aufnahme gestoppt.")
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
