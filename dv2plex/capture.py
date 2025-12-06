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
        self.interactive_process: Optional[subprocess.Popen] = None  # Für interaktiven Modus
        self.preview_dvgrab_process: Optional[subprocess.Popen] = None  # dvgrab-Prozess für Preview

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

    def _start_interactive_mode(self, device: str, output_base: str, auto_rewind: bool = False) -> bool:
        """
        Startet dvgrab im interaktiven Modus für Kamerasteuerung
        
        Args:
            device: FireWire-Gerät
            output_base: Basisname für Ausgabedateien
            auto_rewind: Wenn True, wird automatisch Rewind-Befehl gesendet (nach Start)
        
        Returns:
            True wenn erfolgreich gestartet
        """
        if self.interactive_process:
            return True  # Bereits gestartet
        
        # Prüfe, ob wir root sind
        is_root = os.geteuid() == 0
        
        try:
            # Baue dvgrab-Befehl
            dvgrab_cmd = [
                self.dvgrab_path,
            ] + self._format_device_for_dvgrab(device) + [
                "-i",  # Interaktiver Modus
                "-a",  # Audio aktivieren
                "-f", "dv2",  # DV2-Format (AVI-kompatibel)
                output_base,  # Ausgabebasisname
            ]
            
            # Wenn nicht root, versuche mit sudo
            if not is_root:
                cmd = ["sudo"] + dvgrab_cmd
                self.log("HINWEIS: dvgrab benötigt root-Rechte. Versuche mit sudo...")
            else:
                cmd = dvgrab_cmd
            
            self.log("Starte dvgrab im interaktiven Modus...")
            self.log(f"dvgrab-Befehl: {' '.join(cmd)}")
            
            self.interactive_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,  # Text-Modus für stdin
                bufsize=1,
            )
            
            # Warte kurz, damit der Prozess startet
            time.sleep(1)
            
            if self.interactive_process.poll() is None:
                self.log("Interaktiver Modus aktiviert")
                self.log("Verfügbare Befehle: a=rewind, p=play, c=capture, k=pause, Esc=stop")
                return True
            else:
                error_output = ""
                if self.interactive_process.stderr:
                    try:
                        # Da text=True, ist stderr bereits ein String
                        error_output = self.interactive_process.stderr.read()
                        if isinstance(error_output, bytes):
                            error_output = error_output.decode('utf-8', errors='ignore')
                    except Exception as e:
                        self.log(f"Fehler beim Lesen von stderr: {e}")
                self.log(f"Fehler beim Starten des interaktiven Modus: Return-Code {self.interactive_process.returncode}")
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
                
                self.interactive_process = None
                return False
                
        except Exception as e:
            self.log(f"Fehler beim Starten des interaktiven Modus: {e}")
            self.interactive_process = None
            return False
    
    def _send_interactive_command(self, command: str) -> bool:
        """
        Sendet einen Befehl an dvgrab im interaktiven Modus
        
        Args:
            command: Befehl (z.B. 'a' für rewind, 'p' für play, 'c' für capture, 'k' für pause, '\x1b' für Esc/Stop)
                    Im interaktiven Modus werden einzelne Zeichen ohne Newline gesendet
        """
        if not self.interactive_process or self.interactive_process.poll() is not None:
            self.log("Interaktiver Modus nicht aktiv")
            return False
        
        try:
            if self.interactive_process.stdin:
                # Sende Befehl (ohne Newline für einzelne Zeichen)
                # Im interaktiven Modus von dvgrab werden einzelne Zeichen direkt verarbeitet
                self.interactive_process.stdin.write(command)
                self.interactive_process.stdin.flush()
                return True
            else:
                self.log("stdin nicht verfügbar im interaktiven Modus")
                return False
        except Exception as e:
            self.log(f"Fehler beim Senden des Befehls '{command}': {e}")
            return False
    
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
        Startet DV-Aufnahme mit dvgrab
        
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
            # dvgrab erstellt Dateien mit Timestamp-Format
            # Wir verwenden ein einfaches Format für Part-Namen
            self.current_output_path = output_dir / f"part_{part_number:03d}.avi"

            self.preview_callback = preview_callback
            self.preview_fps = preview_fps
            enable_preview = preview_callback is not None

            # Starte interaktiven Modus für Kamerasteuerung
            output_base = str(self.current_output_path.parent / f"part_{part_number:03d}")
            # Verwende -rewind Option wenn auto_rewind_play aktiviert ist
            interactive_started = self._start_interactive_mode(device, output_base, auto_rewind=auto_rewind_play)
            
            if not interactive_started:
                self.log("WARNUNG: Interaktiver Modus konnte nicht gestartet werden")
                return False
            
            # Automatischer Workflow: Rewind → Play → Capture
            if auto_rewind_play:
                self.log("=== Automatischer Workflow: Rewind → Play → Capture ===")
                
                # Rewind
                self.log("Spule Band zurück...")
                if self._send_interactive_command("a"):
                    # Warte länger für vollständiges Rewind (10-15 Sekunden)
                    # MiniDV-Bänder können 60-90 Minuten lang sein
                    self.log("Warte auf vollständiges Rewind (15 Sekunden)...")
                    time.sleep(15)  # Längere Wartezeit für vollständiges Rewind
                else:
                    self.log("Warnung: Rewind-Befehl fehlgeschlagen")
                
                # Play
                self.log("Starte Wiedergabe...")
                if self._send_interactive_command("p"):
                    time.sleep(2)  # Warte auf Play-Start
                    
                    # Starte Preview NACH Play-Befehl, damit die Kamera Signal sendet
                    if enable_preview:
                        self.log("Starte Preview nach Play-Befehl...")
                        self._start_preview(device, preview_fps)
                        time.sleep(1)  # Kurze Pause, damit Preview initialisiert wird
                else:
                    self.log("Warnung: Play-Befehl fehlgeschlagen")
                
                # Capture starten
                self.log("Starte Aufnahme...")
                if not self._send_interactive_command("c"):
                    self.log("Warnung: Capture-Befehl fehlgeschlagen")
                    return False
            else:
                self.log("=== Manueller Modus ===")
                self.log("Bitte steuern Sie die Kamera manuell oder verwenden Sie die Steuerungs-Buttons.")
                self.log("Verwenden Sie 'c' um die Aufnahme zu starten.")
                
                # Im manuellen Modus: Starte Preview sofort (falls aktiviert)
                if enable_preview:
                    self._start_preview(device, preview_fps)

            # Verwende den interaktiven Prozess für Capture
            if self.interactive_process and self.interactive_process.poll() is None:
                # Capture wurde bereits gestartet (wenn auto_rewind_play), sonst starte jetzt
                if not auto_rewind_play:
                    self.log("Starte Aufnahme im interaktiven Modus...")
                    if not self._send_interactive_command("c"):
                        self.log("Fehler: Capture-Befehl konnte nicht gesendet werden")
                        return False
                
                # Verwende den interaktiven Prozess als Capture-Prozess
                self.process = self.interactive_process
                self.is_capturing = True
                
                self.capture_thread = threading.Thread(
                    target=self._monitor_capture,
                    daemon=True,
                )
                self.capture_thread.start()
                
                return True
            else:
                # Sollte nicht passieren, da interaktiver Modus bereits gestartet wurde
                self.log("FEHLER: Interaktiver Modus nicht verfügbar")
                return False

        except Exception as e:
            self.log(f"Fehler beim Starten der Aufnahme: {e}")
            self.is_capturing = False
            self._stop_preview()
            return False

    def _start_preview(self, device: str, fps: int):
        """Startet Preview-Stream mit dvgrab -> ffmpeg Pipeline"""
        try:
            # Verwende dvgrab -> ffmpeg Pipeline für Preview
            # dvgrab liest vom FireWire-Gerät und sendet an ffmpeg
            dvgrab_cmd = [
                self.dvgrab_path,
            ] + self._format_device_for_dvgrab(device) + [
                "-a",  # Audio aktivieren
                "-f", "dv2",  # DV2-Format
                "-",  # Ausgabe nach stdout
            ]
            
            ffmpeg_cmd = [
                str(self.ffmpeg_path),
                "-f", "dv",  # DV-Format vom stdin
                "-i", "-",  # Input von stdin
                "-vf", f"fps={fps},scale=640:-1",
                "-f", "mjpeg",
                "-q:v", "5",
                "-",  # Ausgabe nach stdout
            ]
            
            # Prüfe, ob wir root sind - dvgrab benötigt root für FireWire
            is_root = os.geteuid() == 0
            if not is_root:
                dvgrab_cmd = ["sudo"] + dvgrab_cmd
                self.log("HINWEIS: dvgrab benötigt root-Rechte für FireWire-Zugriff. Verwende sudo...")
            
            self.log("Starte Preview-Stream (dvgrab -> ffmpeg Pipeline)...")
            self.log(f"Preview-Gerät: {device}")
            self.log("HINWEIS: Preview funktioniert nur, wenn die Kamera im Play-Modus ist und Signal sendet.")
            
            # Starte dvgrab-Prozess
            dvgrab_process = subprocess.Popen(
                dvgrab_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=False,
                bufsize=0,
            )
            
            # Starte ffmpeg-Prozess mit stdin von dvgrab
            self.preview_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=dvgrab_process.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
            )
            
            # Schließe dvgrab stdout in ffmpeg
            dvgrab_process.stdout.close()
            
            # Speichere dvgrab-Prozess für späteres Stoppen
            self.preview_dvgrab_process = dvgrab_process
            
            # Warte länger und prüfe, ob der Prozess sofort beendet wurde
            # ffmpeg braucht etwas Zeit, um das Gerät zu öffnen und Fehler zu melden
            time.sleep(1.5)
            if self.preview_process.poll() is not None:
                # Prozess wurde sofort beendet - lese stderr für Fehler
                try:
                    if self.preview_process.stderr:
                        # Warte kurz, damit stderr vollständig geschrieben wird
                        time.sleep(0.2)
                        # Lese alle verfügbaren Daten
                        stderr_data = b""
                        while True:
                            chunk = self.preview_process.stderr.read(4096)
                            if not chunk:
                                break
                            stderr_data += chunk if isinstance(chunk, bytes) else chunk.encode()
                        
                        if stderr_data:
                            if isinstance(stderr_data, bytes):
                                stderr_text = stderr_data.decode('utf-8', errors='ignore')
                            else:
                                stderr_text = str(stderr_data)
                            # Zeige vollständige Fehlermeldung - suche nach dem eigentlichen Fehler
                            # (nach der Versionsinfo)
                            error_lines = stderr_text.split('\n')
                            error_found = False
                            for i, line in enumerate(error_lines):
                                if any(keyword in line.lower() for keyword in ['error', 'failed', 'cannot', 'invalid', 'permission', 'no such', 'device']):
                                    # Zeige diese Zeile und Kontext
                                    start_idx = max(0, i-2)
                                    end_idx = min(len(error_lines), i+5)
                                    error_section = '\n'.join(error_lines[start_idx:end_idx])
                                    self.log(f"Preview-Fehler (Prozess beendet):\n{error_section}")
                                    error_found = True
                                    break
                            if not error_found:
                                # Falls kein Fehler gefunden, zeige die letzten Zeilen (nach Versionsinfo)
                                # Versionsinfo ist normalerweise am Anfang
                                lines_after_version = [line for line in error_lines if 'ffmpeg version' not in line.lower() and 'libav' not in line.lower() and line.strip()]
                                if lines_after_version:
                                    self.log(f"Preview-Fehler (Prozess beendet, letzte Zeilen):\n{chr(10).join(lines_after_version[-10:])}")
                                else:
                                    # Zeige die vollständige Ausgabe, aber filtere Versionsinfo
                                    important_lines = [line for line in error_lines if any(keyword in line.lower() for keyword in ['input', 'output', 'stream', 'error', 'failed', 'cannot', 'device', 'permission'])]
                                    if important_lines:
                                        self.log(f"Preview-Fehler (Prozess beendet, wichtige Zeilen):\n{chr(10).join(important_lines)}")
                                    else:
                                        self.log(f"Preview-Fehler: Prozess wurde sofort beendet. Mögliche Ursachen:")
                                        self.log(f"  - Gerät bereits von dvgrab verwendet (dvgrab blockiert FireWire-Gerät)")
                                        self.log(f"  - Keine Berechtigung für {ffmpeg_device}")
                                        self.log(f"  - Gerät nicht gefunden: {ffmpeg_device}")
                                        self.log(f"Vollständige stderr-Ausgabe (letzte 500 Zeichen):\n{stderr_text[-500:]}")
                            if "Permission denied" in stderr_text or "Cannot open" in stderr_text:
                                self.log("HINWEIS: ffmpeg benötigt root-Rechte. Starten Sie die Anwendung mit sudo.")
                            elif "No such file" in stderr_text or "Device" in stderr_text:
                                self.log(f"HINWEIS: FireWire-Gerät nicht gefunden. Versuchen Sie /dev/raw1394 oder /dev/video1394")
                except Exception as e:
                    self.log(f"Fehler beim Lesen von Preview-stderr: {e}")
                return

            if self.preview_process.stdout:
                self.preview_stop_event = threading.Event()
                # Starte auch einen Thread zum Lesen von stderr für besseres Error-Handling
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
            else:
                self.log("Preview-Stream: WARNUNG - stdout nicht verfügbar!")

        except Exception as e:
            self.log(f"Fehler beim Starten des Preview-Streams: {e}")
            self.log("HINWEIS: Preview erfordert, dass die Kamera im Play-Modus ist.")

    def stop_capture(self) -> bool:
        """Stoppt die Aufnahme"""
        if not self.is_capturing:
            return False

        try:
            self.log("Stoppe Aufnahme...")

            # Stoppe Preview
            self._stop_preview()

            # Wenn im interaktiven Modus: Sende Stop-Befehl (Esc oder 'q' für quit)
            if self.interactive_process and self.interactive_process.poll() is None:
                self.log("Sende Stop-Befehl an dvgrab...")
                # Versuche zuerst ESC, dann 'q' für quit
                self._send_interactive_command("\x1b")  # ESC für Stop
                time.sleep(0.5)
                # Falls ESC nicht funktioniert, versuche 'q'
                if self.interactive_process.poll() is None:
                    self._send_interactive_command("q")  # 'q' für quit
                time.sleep(1)  # Warte auf Stop
            
            # Stoppe dvgrab-Prozess
            process_to_stop = self.process if self.process else self.interactive_process
            if process_to_stop:
                try:
                    process_to_stop.terminate()
                    process_to_stop.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.log("dvgrab beendet sich nicht automatisch, erzwinge Beendigung...")
                    process_to_stop.kill()
                    process_to_stop.wait(timeout=2)
            
            # Cleanup interaktiven Prozess
            if self.interactive_process:
                try:
                    if self.interactive_process.poll() is None:
                        self.interactive_process.terminate()
                        self.interactive_process.wait(timeout=2)
                except:
                    pass
                self.interactive_process = None

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
                    # Logge nur wichtige Fehler
                    if "error" in stderr_text.lower() or "failed" in stderr_text.lower() or "cannot" in stderr_text.lower():
                        self.log(f"Preview-ffmpeg: {stderr_text[:200]}")
                else:
                    time.sleep(0.1)
        except Exception as e:
            # Ignoriere Fehler beim Lesen von stderr
            pass

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
                    # Logge nur wichtige Fehler
                    if "error" in stderr_text.lower() or "failed" in stderr_text.lower() or "cannot" in stderr_text.lower():
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
        
        # Stoppe dvgrab-Prozess für Preview
        if self.preview_dvgrab_process:
            try:
                self.preview_dvgrab_process.terminate()
                self.preview_dvgrab_process.wait(timeout=2)
            except:
                try:
                    self.preview_dvgrab_process.kill()
                except:
                    pass
            self.preview_dvgrab_process = None
        
        # Stoppe ffmpeg-Prozess
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
                
                # Wenn der Prozess sofort beendet wurde (z.B. kein Signal), logge Warnung
                if return_code != 0 and return_code not in [130, 143]:
                    self.log(f"WARNUNG: Aufnahme wurde unerwartet beendet (Return-Code: {return_code}). Mögliche Ursachen:")
                    self.log("  - Kein Signal von der Kamera (Bitte Play auf der Kamera drücken)")
                    self.log("  - Kamera nicht richtig verbunden")
                    self.log("  - dvgrab-Fehler (siehe stderr-Logs)")

        except Exception as e:
            self.log(f"Fehler beim Überwachen der Aufnahme: {e}")
            self.is_capturing = False
            self._stop_preview()

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
        elif return_code in [1, 130, 143]:  # Normal beendet (SIGTERM/SIGINT)
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
