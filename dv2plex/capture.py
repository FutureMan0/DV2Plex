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
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, IO
from queue import Queue, Empty

from .merge import MergeEngine

try:
    from PySide6.QtGui import QImage
except ImportError:
    # Fallback falls PySide6 nicht verfügbar
    QImage = None


# Datenklasse für Merge-Job
class MergeJob:
    """Repräsentiert einen Merge-Job in der Queue"""
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


class CaptureEngine:
    """Verwaltet DV-Capture über dvgrab (Linux)"""

    def __init__(
        self,
        ffmpeg_path: Path,
        device_path: Optional[str] = None,
        dvgrab_path: str = "dvgrab",
        log_callback: Optional[Callable[[str], None]] = None,
        state_callback: Optional[Callable[[str], None]] = None,
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
        self.state_callback = state_callback
        self.last_split_time: Optional[float] = None  # Letzte erkannte Split-Datei
        self.auto_stop_inactivity_triggered: bool = False
        self.inactivity_monitor_thread: Optional[threading.Thread] = None
        # Neue Architektur: Separater interaktiver Prozess für Steuerung
        self.interactive_dvgrab_process: Optional[subprocess.Popen] = None  # Interaktiver dvgrab nur für Steuerung
        # Recording-Prozess (non-interaktiv)
        self.recording_dvgrab_process: Optional[subprocess.Popen] = None  # Non-interaktiver dvgrab für Aufnahme
        self.splits_dir: Optional[Path] = None  # Pfad zu LowRes/splits/
        # Preview-Queue-System
        self.preview_queue: Queue = Queue()  # Queue für Preview-Dateien
        self.preview_worker_thread: Optional[threading.Thread] = None  # Thread der Queue abarbeitet
        self.preview_monitor_thread: Optional[threading.Thread] = None  # Thread der neue Dateien zur Queue hinzufügt
        self.preview_file_process: Optional[subprocess.Popen] = None  # ffmpeg für Preview aus Datei
        # Kompatibilität
        self.interactive_process: Optional[subprocess.Popen] = None  # Alias für interactive_dvgrab_process
        self.autosplit_dvgrab_process: Optional[subprocess.Popen] = None  # Alias für recording_dvgrab_process
        # sudo-Keepalive, damit Rechte während langer Läufe nicht ablaufen
        self.sudo_keepalive_thread: Optional[threading.Thread] = None
        self.sudo_keepalive_stop: Optional[threading.Event] = None
        # Background-Merge-System
        self.merge_queue: Queue = Queue()  # Queue für Merge-Jobs
        self.merge_jobs: list[MergeJob] = []  # Liste aller Jobs (für Status-Abfrage)
        self.merge_worker_thread: Optional[threading.Thread] = None
        self.merge_stop_event: Optional[threading.Event] = None
        self.current_merge_job: Optional[MergeJob] = None
        self.merge_progress_callback: Optional[Callable[[MergeJob], None]] = None
        # Aktueller Capture-Titel/Jahr für Merge-Jobs
        self.current_capture_title: str = ""
        self.current_capture_year: str = ""
        # Starte Background-Merge-Worker
        self._start_merge_worker()

    def _notify_state(self, state: str):
        """Optionaler Callback für Zustandsänderungen (z.B. stopped)"""
        if self.state_callback:
            try:
                self.state_callback(state)
            except Exception:
                pass

    def _start_merge_worker(self):
        """Startet den Background-Worker für Merge-Jobs"""
        if self.merge_worker_thread and self.merge_worker_thread.is_alive():
            return
        
        self.merge_stop_event = threading.Event()
        self.merge_worker_thread = threading.Thread(
            target=self._merge_worker_loop,
            daemon=True,
            name="MergeWorker"
        )
        self.merge_worker_thread.start()
        self.log("Background-Merge-Worker gestartet")

    def _merge_worker_loop(self):
        """Worker-Loop für Background-Merge"""
        while not self.merge_stop_event.is_set():
            try:
                # Warte auf Job (mit Timeout für graceful shutdown)
                try:
                    job = self.merge_queue.get(timeout=1.0)
                except Empty:
                    continue
                
                # Verarbeite Job
                self.current_merge_job = job
                job.status = "running"
                job.started_at = time.time()
                job.message = "Merge gestartet..."
                self._notify_merge_progress(job)
                
                try:
                    self.log(f"Background-Merge: Starte {job.title} ({job.year})")
                    
                    # Führe Merge durch
                    merge_engine = MergeEngine(self.ffmpeg_path, log_callback=self.log)
                    merged_file = merge_engine.merge_splits(job.splits_dir, job.output_path)
                    
                    if merged_file and merged_file.exists():
                        job.status = "completed"
                        job.progress = 100
                        job.result_path = merged_file
                        job.message = f"Merge abgeschlossen: {merged_file.name}"
                        job.completed_at = time.time()
                        self.log(f"Background-Merge erfolgreich: {merged_file}")
                        
                        # Sende Benachrichtigung
                        self._notify_completion(f"Merge abgeschlossen: {job.title} ({job.year})")
                    else:
                        job.status = "failed"
                        job.message = "Merge fehlgeschlagen"
                        job.completed_at = time.time()
                        self.log(f"Background-Merge fehlgeschlagen: {job.title}")
                        self._notify_completion(f"Merge fehlgeschlagen: {job.title} ({job.year})")
                    
                except Exception as e:
                    job.status = "failed"
                    job.message = f"Fehler: {e}"
                    job.completed_at = time.time()
                    self.log(f"Background-Merge Fehler: {e}")
                    self._notify_completion(f"Merge Fehler: {job.title} - {e}")
                
                finally:
                    self._notify_merge_progress(job)
                    self.current_merge_job = None
                    self.merge_queue.task_done()
                
            except Exception as e:
                self.log(f"Merge-Worker Fehler: {e}")
        
        self.log("Background-Merge-Worker beendet")

    def _notify_merge_progress(self, job: MergeJob):
        """Benachrichtigt über Merge-Progress"""
        if self.merge_progress_callback:
            try:
                self.merge_progress_callback(job)
            except Exception as e:
                self.log(f"Merge-Progress-Callback Fehler: {e}")

    def queue_merge_job(self, splits_dir: Path, output_path: Path, title: str = "", year: str = "") -> MergeJob:
        """Fügt einen Merge-Job zur Queue hinzu"""
        job = MergeJob(splits_dir, output_path, title, year)
        self.merge_jobs.append(job)
        self.merge_queue.put(job)
        self.log(f"Merge-Job zur Queue hinzugefügt: {title} ({year})")
        return job

    def get_merge_queue_status(self) -> dict:
        """Gibt den Status der Merge-Queue zurück"""
        pending = [j for j in self.merge_jobs if j.status == "pending"]
        running = self.current_merge_job
        completed = [j for j in self.merge_jobs if j.status in ("completed", "failed")]
        
        return {
            "pending_count": len(pending),
            "current_job": {
                "title": running.title,
                "year": running.year,
                "progress": running.progress,
                "message": running.message,
                "status": running.status
            } if running else None,
            "completed_count": len(completed),
            "jobs": [
                {
                    "title": j.title,
                    "year": j.year,
                    "status": j.status,
                    "progress": j.progress,
                    "message": j.message
                }
                for j in self.merge_jobs[-10:]  # Letzte 10 Jobs
            ]
        }

    def clear_completed_merge_jobs(self):
        """Entfernt abgeschlossene Jobs aus der Liste"""
        self.merge_jobs = [j for j in self.merge_jobs if j.status in ("pending", "running")]

    def _start_sudo_keepalive(self):
        """Hält sudo-Timestamp aktiv, damit dvgrab/Steuerung nicht die Rechte verliert."""
        if os.geteuid() == 0:
            return  # Bereits root, nichts zu tun
        if shutil.which("sudo") is None:
            return
        if self.sudo_keepalive_thread and self.sudo_keepalive_thread.is_alive():
            return
        
        # Prüfe, ob ein sudo-Timestamp existiert (ohne Passwortabfrage)
        try:
            result = subprocess.run(
                ["sudo", "-n", "-v"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                self.log("sudo Keepalive nicht möglich (kein sudo-Timestamp). Bitte Programm mit sudo starten.")
                return
        except Exception as e:
            self.log(f"sudo Keepalive konnte nicht geprüft werden: {e}")
            return
        
        self.sudo_keepalive_stop = threading.Event()
        
        def _keepalive():
            while self.sudo_keepalive_stop and not self.sudo_keepalive_stop.wait(60):
                try:
                    subprocess.run(
                        ["sudo", "-n", "-v"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception as e:
                    self.log(f"sudo Keepalive fehlgeschlagen: {e}")
                    break
        
        self.sudo_keepalive_thread = threading.Thread(target=_keepalive, daemon=True)
        self.sudo_keepalive_thread.start()
        self.log("sudo Keepalive gestartet, um Root-Rechte während der Aufnahme zu halten.")

    def _stop_sudo_keepalive(self):
        """Beendet den sudo-Keepalive-Thread."""
        if self.sudo_keepalive_stop:
            self.sudo_keepalive_stop.set()
        if self.sudo_keepalive_thread and self.sudo_keepalive_thread.is_alive():
            self.sudo_keepalive_thread.join(timeout=2)
        self.sudo_keepalive_thread = None
        self.sudo_keepalive_stop = None

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

    def _start_interactive_dvgrab(self, device: str) -> bool:
        """
        Startet interaktiven dvgrab nur für Steuerung (Rewind/Play/Pause)
        
        Args:
            device: FireWire-Gerät
        
        Returns:
            True wenn erfolgreich gestartet
        """
        if self.interactive_dvgrab_process:
            return True  # Bereits gestartet
        
        # Prüfe, ob wir root sind
        is_root = os.geteuid() == 0
        # Halte sudo aktiv, falls nicht root
        self._start_sudo_keepalive()
        
        try:
            # Baue dvgrab-Befehl: -i (interaktiv, nur Steuerung)
            dvgrab_cmd = [
                self.dvgrab_path,
            ] + self._format_device_for_dvgrab(device) + [
                "-i",  # Interaktiver Modus
            ]
            
            # Wenn nicht root, versuche mit sudo
            if not is_root:
                cmd = ["sudo"] + dvgrab_cmd
                self.log("HINWEIS: dvgrab benötigt root-Rechte. Versuche mit sudo...")
            else:
                cmd = dvgrab_cmd
            
            self.log("Starte interaktiven dvgrab für Steuerung...")
            self.log(f"dvgrab-Befehl: {' '.join(cmd)}")
            
            # Starte dvgrab (stdin für interaktive Befehle)
            self.interactive_dvgrab_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=False,  # Binärmodus für stdin (Befehle als Bytes)
                bufsize=0,
            )
            
            # Warte kurz, damit der Prozess startet
            time.sleep(1)
            
            if self.interactive_dvgrab_process.poll() is None:
                self.log("Interaktiver dvgrab gestartet (nur Steuerung)")
                self.log("Verfügbare Befehle: a=rewind, p=play, k=pause, Esc=stop")
                # Setze auch interactive_process für Kompatibilität
                self.interactive_process = self.interactive_dvgrab_process
                return True
            else:
                error_output = ""
                if self.interactive_dvgrab_process.stderr:
                    try:
                        error_output_bytes = self.interactive_dvgrab_process.stderr.read()
                        if isinstance(error_output_bytes, bytes):
                            error_output = error_output_bytes.decode('utf-8', errors='ignore')
                        else:
                            error_output = str(error_output_bytes)
                    except Exception as e:
                        self.log(f"Fehler beim Lesen von stderr: {e}")
                self.log(f"Fehler beim Starten von interaktivem dvgrab: Return-Code {self.interactive_dvgrab_process.returncode}")
                if error_output:
                    self.log(f"Fehler-Ausgabe: {error_output[:500]}")
                
                self.interactive_dvgrab_process = None
                return False
                
        except Exception as e:
            self.log(f"Fehler beim Starten von interaktivem dvgrab: {e}")
            self.interactive_dvgrab_process = None
            return False

    def _start_recording_dvgrab(self, device: str, splits_dir: Path, use_rewind: bool = True) -> bool:
        """
        Startet non-interaktiven dvgrab für Aufnahme mit autosplit
        
        Args:
            device: FireWire-Gerät
            splits_dir: Ausgabeordner für Split-Dateien
        
        Returns:
            True wenn erfolgreich gestartet
        """
        if self.recording_dvgrab_process:
            return True  # Bereits gestartet
        
        # Prüfe, ob wir root sind
        is_root = os.geteuid() == 0
        
        try:
            # Erstelle splits-Ordner
            splits_dir.mkdir(parents=True, exist_ok=True)
            
            # Baue dvgrab-Befehl: optional -rewind, immer -autosplit -t -f dv1
            # Ausgabe-Präfix: dvgrab fügt automatisch Timestamp hinzu (dvgrab-YYYY.MM.DD_HH-MM-SS.avi)
            output_prefix = str(splits_dir / "dvgrab")
            base_cmd = [self.dvgrab_path] + self._format_device_for_dvgrab(device)
            if use_rewind:
                base_cmd.append("-rewind")  # Automatisches Rewind (optional)
            base_cmd += [
                "-autosplit",  # Autosplit bei Szenenänderungen
                "-t",  # Timestamp im Dateinamen
                "-f", "dv1",  # DV Type 1 Format
                output_prefix,  # Ausgabe-Präfix (dvgrab fügt Timestamp hinzu)
            ]
            dvgrab_cmd = base_cmd
            
            # Wenn nicht root, versuche mit sudo
            if not is_root:
                cmd = ["sudo"] + dvgrab_cmd
                self.log("HINWEIS: dvgrab benötigt root-Rechte. Versuche mit sudo...")
            else:
                cmd = dvgrab_cmd
            
            self.log("Starte non-interaktiven dvgrab für Aufnahme...")
            self.log(f"dvgrab-Befehl: {' '.join(cmd)}")
            self.log(f"Ausgabe-Verzeichnis: {splits_dir}")
            
            # Starte dvgrab (non-interaktiv, schreibt direkt Dateien)
            self.recording_dvgrab_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
            )
            
            # Warte kurz, damit der Prozess startet
            time.sleep(1)
            
            if self.recording_dvgrab_process.poll() is None:
                self.log("Recording dvgrab gestartet (non-interaktiv mit autosplit)")
                # Setze auch autosplit_dvgrab_process für Kompatibilität
                self.autosplit_dvgrab_process = self.recording_dvgrab_process
                return True
            else:
                error_output = ""
                if self.recording_dvgrab_process.stderr:
                    try:
                        error_output_bytes = self.recording_dvgrab_process.stderr.read()
                        if isinstance(error_output_bytes, bytes):
                            error_output = error_output_bytes.decode('utf-8', errors='ignore')
                        else:
                            error_output = str(error_output_bytes)
                    except Exception as e:
                        self.log(f"Fehler beim Lesen von stderr: {e}")
                self.log(f"Fehler beim Starten von recording dvgrab: Return-Code {self.recording_dvgrab_process.returncode}")
                if error_output:
                    self.log(f"Fehler-Ausgabe: {error_output[:500]}")
                
                self.recording_dvgrab_process = None
                return False
                
        except Exception as e:
            self.log(f"Fehler beim Starten von recording dvgrab: {e}")
            self.recording_dvgrab_process = None
            return False

    # _get_latest_split_file() wurde entfernt - wird durch Preview-Queue ersetzt

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
            # Prüfe Dateigröße - zu kleine Dateien überspringen
            file_size = file_path.stat().st_size
            if file_size < 300 * 1024:
                self.log(f"Preview: Datei zu klein ({file_path.name}, {file_size} bytes) – überspringe.")
                return None
            
            def launch(cmd_desc, cmd_list):
                # Knapp loggen, um Spam zu vermeiden
                self.log(f"Preview: ffmpeg {cmd_desc} startet für {file_path.name}")
                proc = subprocess.Popen(
                    cmd_list,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,  # verhindert Blockieren
                    text=False,
                    bufsize=0,
                )
                time.sleep(0.3)
                poll = proc.poll()
                if poll is not None:
                    self.log(f"Preview-ffmpeg ({cmd_desc}) für {file_path.name} sofort beendet mit Code {poll}")
                    return None
                return proc

            # Variante 1: Standard lesen (AVI / DV im Container)
            avi_cmd = [
                str(self.ffmpeg_path),
                "-hide_banner",
                "-loglevel", "error",
                "-fflags", "+genpts+igndts",
                "-analyzeduration", "10000000",
                "-probesize", "10000000",
                "-i", str(file_path),
                "-vf", f"yadif,fps={fps},scale=640:-1",
                "-vcodec", "mjpeg",
                "-f", "image2pipe",
                "-q:v", "5",
                "-",
            ]
            process = launch("avi", avi_cmd)
            if process:
                return process

            # Variante 2: Roh-DV erzwingen (wenn Index fehlt / .dv)
            raw_dv_cmd = [
                str(self.ffmpeg_path),
                "-hide_banner",
                "-loglevel", "error",
                "-f", "dv",
                "-i", str(file_path),
                "-vf", f"yadif,fps={fps},scale=640:-1",
                "-vcodec", "mjpeg",
                "-f", "image2pipe",
                "-q:v", "5",
                "-",
            ]
            process = launch("raw-dv", raw_dv_cmd)
            if process:
                return process

            # Variante 3: Fehler ignorieren (Fallback)
            fallback_cmd = [
                str(self.ffmpeg_path),
                "-hide_banner",
                "-loglevel", "warning",
                "-err_detect", "ignore_err",
                "-fflags", "+genpts+discardcorrupt",
                "-i", str(file_path),
                "-vf", f"yadif,fps={fps},scale=640:-1",
                "-vcodec", "mjpeg",
                "-f", "image2pipe",
                "-q:v", "7",
                "-",
            ]
            process = launch("fallback", fallback_cmd)
            return process
            
        except Exception as e:
            self.log(f"Fehler beim Starten von Preview-ffmpeg aus Datei {file_path.name}: {e}")
            return None

    def _wait_for_file_complete(self, file_path: Path, max_wait: float = 5.0) -> bool:
        """
        Wartet bis eine Datei vollständig geschrieben ist (nicht mehr wächst)
        
        Args:
            file_path: Pfad zur Datei
            max_wait: Maximale Wartezeit in Sekunden
        
        Returns:
            True wenn Datei vollständig ist
        """
        if not file_path.exists():
            return False
        
        waited = 0.0
        check_interval = 0.5
        
        while waited < max_wait:
            size1 = file_path.stat().st_size
            time.sleep(check_interval)
            waited += check_interval
            
            if not file_path.exists():
                return False
            
            size2 = file_path.stat().st_size
            if size1 == size2 and size1 > 0:
                return True
        
        # Timeout erreicht, aber Datei existiert und hat Größe > 0
        return file_path.exists() and file_path.stat().st_size > 0

    def _monitor_splits_queue(self):
        """
        Thread-Funktion: Überwacht splits-Ordner und fügt neue Dateien zur Queue hinzu
        """
        if not self.splits_dir:
            self.log("Preview-Queue-Monitor: splits_dir nicht gesetzt")
            return
        
        self.log("Preview-Queue-Monitor: Starte Überwachung...")
        known_files = set()
        
        try:
            while (
                self.is_capturing
                and (not self.preview_stop_event or not self.preview_stop_event.is_set())
            ):
                # Finde neue Dateien (dvgrab*.avi oder .dv – dvgrab schreibt ohne Bindestrich)
                current_files = set(self.splits_dir.glob("dvgrab*.avi")) | set(self.splits_dir.glob("dvgrab*.dv"))
                new_files = current_files - known_files
                
                for file_path in new_files:
                    # Warte bis Datei vollständig geschrieben ist
                    if self._wait_for_file_complete(file_path):
                        self.preview_queue.put(file_path)
                        known_files.add(file_path)
                        self.last_split_time = time.time()
                        self.log(f"Preview-Queue: Neue Datei hinzugefügt: {file_path.name}")
                
                time.sleep(0.5)  # Prüfe alle 0.5 Sekunden
                
        except Exception as e:
            self.log(f"Preview-Queue-Monitor: Fehler: {e}")
        finally:
            self.log("Preview-Queue-Monitor: Beendet")

    def _monitor_split_inactivity(self, timeout_seconds: int = 600):
        """
        Überwacht, ob neue Splits eintreffen. Stoppt Aufnahme nach Timeout ohne neue Datei.
        """
        if not self.splits_dir:
            return
        
        known_files = set(self.splits_dir.glob("dvgrab*.avi")) | set(self.splits_dir.glob("dvgrab*.dv"))
        if known_files:
            self.last_split_time = time.time()
        
        self.log("Inaktivitätsmonitor: gestartet")
        
        try:
            while self.is_capturing and not self.auto_stop_inactivity_triggered:
                now = time.time()
                
                current_files = set(self.splits_dir.glob("dvgrab*.avi")) | set(self.splits_dir.glob("dvgrab*.dv"))
                new_files = current_files - known_files
                if new_files:
                    self.last_split_time = now
                    known_files |= new_files
                
                if self.last_split_time and (now - self.last_split_time) >= timeout_seconds:
                    self.auto_stop_inactivity_triggered = True
                    self.log("Inaktivitätsmonitor: 10 Minuten keine neuen Splits - stoppe Aufnahme.")
                    try:
                        self.stop_capture()
                    except Exception as e:
                        self.log(f"Inaktivitätsmonitor: Fehler beim Stoppen: {e}")
                    break
                
                time.sleep(5)
        except Exception as e:
            self.log(f"Inaktivitätsmonitor: Fehler: {e}")
        finally:
            self.log("Inaktivitätsmonitor: beendet")

    def _play_file_for_preview(self, file_path: Path):
        """
        Spielt eine Datei vollständig für Preview ab
        
        Args:
            file_path: Pfad zur Video-Datei
        """
        if not file_path.exists() or not self.preview_callback:
            return
        
        # Warte bis Datei genug Daten hat (mind. 100KB für DV-Video)
        min_size = 100 * 1024  # 100 KB
        max_wait = 10  # Max 10 Sekunden warten
        waited = 0
        while waited < max_wait:
            if not file_path.exists():
                return
            try:
                size = file_path.stat().st_size
                if size >= min_size:
                    self.log(f"Preview: Datei {file_path.name} hat {size // 1024} KB, starte Wiedergabe")
                    break
            except:
                pass
            time.sleep(0.5)
            waited += 0.5
            # Prüfe ob Aufnahme noch läuft
            if self.preview_stop_event and self.preview_stop_event.is_set():
                return
        else:
            self.log(f"Preview: Datei {file_path.name} zu klein nach {max_wait}s Warten")
            return
        
        preview_fps = getattr(self, 'preview_fps', 10)
        process = self._start_preview_from_file(file_path, preview_fps)
        
        if not process:
            self.log(f"Preview: Konnte Datei nicht abspielen: {file_path.name}")
            return
        
        self.log(f"Preview: Spiele Datei ab: {file_path.name}")
        
        # Lese Frames bis Datei fertig ist
        try:
            self._read_preview_from_process(process, file_path)
        except Exception as e:
            self.log(f"Preview: Fehler beim Abspielen von {file_path.name}: {e}")
        finally:
            # Cleanup
            if process:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except:
                    try:
                        process.kill()
                    except:
                        pass

    def _process_preview_queue(self):
        """
        Thread-Funktion: Arbeitet Preview-Queue ab - spielt jede Datei bis zum Ende
        """
        self.log("Preview-Queue-Worker: Starte...")
        
        while True:
            try:
                # Prüfe Stop-Signal
                if self.preview_stop_event and self.preview_stop_event.is_set():
                    # Prüfe ob noch Dateien in Queue
                    if self.preview_queue.empty():
                        break
                
                try:
                    file_path = self.preview_queue.get(timeout=1.0)
                except Empty:
                    # Keine Datei verfügbar, prüfe ob noch aufnahme läuft
                    if not self.is_capturing:
                        break
                    continue
                
                # Spiele Datei vollständig ab
                self._play_file_for_preview(file_path)
                self.preview_queue.task_done()
                
            except Exception as e:
                self.log(f"Preview-Queue-Worker: Fehler: {e}")
                time.sleep(0.5)
        
        self.log("Preview-Queue-Worker: Beendet")

    def _read_preview_from_process(self, process: subprocess.Popen, file_path: Path):
        """
        Liest Preview-Frames von einem ffmpeg-Prozess (der eine Datei liest)
        
        Args:
            process: ffmpeg-Prozess
            file_path: Pfad zur Datei (für Logging)
        """
        if not process or not process.stdout or not self.preview_callback:
            self.log(f"Preview: Kein Prozess/stdout/callback für {file_path.name}")
            return
        
        buffer = bytearray()
        jpeg_start = b"\xff\xd8"
        jpeg_end = b"\xff\xd9"
        frame_count = 0
        last_frame_time = 0
        preview_fps = getattr(self, 'preview_fps', 10)
        target_frame_interval = 1.0 / max(preview_fps, 5)
        bytes_read = 0
        
        self.log(f"Preview: Starte Frame-Lesen von {file_path.name}")
        
        # Prüfe initialen Prozess-Status
        poll_result = process.poll()
        if poll_result is not None:
            self.log(f"Preview: Prozess bereits beendet mit Code {poll_result}")
            # Lese stderr
            try:
                if process.stderr:
                    err = process.stderr.read()
                    if err:
                        self.log(f"Preview: ffmpeg stderr: {err.decode('utf-8', errors='ignore')[:500]}")
            except:
                pass
            return
        
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
                            self.log(f"Preview: Prozess beendet, {bytes_read} bytes gelesen, {frame_count} frames")
                            break
                        time.sleep(0.01)
                        continue
                    
                    bytes_read += len(chunk)
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
                        
                        if self.preview_callback:
                            try:
                                current_time = time.time()
                                if current_time - last_frame_time >= target_frame_interval:
                                    # Sende immer rohe JPEG-Bytes (Browser-Websocket erwartet Base64)
                                    self.preview_callback(jpeg_data)
                                    frame_count += 1
                                    last_frame_time = current_time
                                    if frame_count == 1:
                                        self.log(f"Preview: Erstes Frame (Bytes) von {file_path.name}")
                            except Exception as e:
                                self.log(f"Preview: Fehler bei Frame-Callback: {e}")
                
                except Exception as e:
                    self.log(f"Preview: Fehler beim Lesen: {e}")
                    time.sleep(0.1)
                    continue
        
        except Exception as e:
            self.log(f"Preview: Fehler: {e}")
        finally:
            self.log(f"Preview: Beendet - {bytes_read} bytes gelesen, {frame_count} frames gesendet")
            # Wenn keine Frames gefunden wurden, logge Stderr für Diagnose
            if frame_count == 0 and process:
                try:
                    if process.stderr:
                        err = process.stderr.read()
                        if err:
                            err_txt = err.decode("utf-8", errors="ignore")
                            self.log(f"Preview: Keine Frames, ffmpeg stderr: {err_txt[:500]}")
                except Exception:
                    pass
            try:
                if process and process.stdout:
                    process.stdout.close()
                if process and process.stderr:
                    process.stderr.close()
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
                "-hide_banner",
                "-loglevel", "error",
                "-nostdin",
                "-f", "dv",  # DV-Format vom stdin
                "-i", "-",  # Input von stdin
                "-map", "0:v",  # Nur Video-Stream (MJPEG unterstützt kein Audio)
                "-vf", f"yadif,fps={fps},scale=640:-1",  # Deinterlace + FPS + Skalierung
                "-f", "mjpeg",  # MJPEG-Format
                "-q:v", "5",  # Qualität
                "-",  # Ausgabe nach stdout
            ]
            
            # Nur knappe Info statt kompletten Befehl
            self.log("Starte Preview-ffmpeg...")
            
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
        Sendet einen Befehl an dvgrab im interaktiven Modus (nur für Steuerung)
        
        Args:
            command: Befehl (z.B. 'a' für rewind, 'p' für play, 'k' für pause, '\x1b' für Esc/Stop)
                    Im interaktiven Modus werden einzelne Zeichen ohne Newline gesendet
        """
        # Verwende interactive_dvgrab_process
        process = self.interactive_dvgrab_process or self.interactive_process
        if not process or process.poll() is not None:
            self.log("Interaktiver Modus nicht aktiv - starte ihn zuerst")
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
        """Stoppt alle Prozesse (recording dvgrab, interaktiver dvgrab, preview)"""
        # Stoppe Preview-Queue (Worker und Monitor)
        if self.preview_stop_event:
            self.preview_stop_event.set()
        
        if self.preview_worker_thread and self.preview_worker_thread.is_alive():
            self.preview_worker_thread.join(timeout=3)
        self.preview_worker_thread = None
        
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
        
        # Stoppe recording dvgrab (non-interaktiv) - sende SIGINT
        if self.recording_dvgrab_process:
            try:
                import signal
                # Sende SIGINT (Strg+C)
                self.recording_dvgrab_process.send_signal(signal.SIGINT)
                self.recording_dvgrab_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Falls SIGINT nicht funktioniert, terminate
                try:
                    self.recording_dvgrab_process.terminate()
                    self.recording_dvgrab_process.wait(timeout=2)
                except:
                    try:
                        self.recording_dvgrab_process.kill()
                        self.recording_dvgrab_process.wait(timeout=1)
                    except:
                        pass
            except Exception:
                pass
            self.recording_dvgrab_process = None
        
        # Stoppe interaktiven dvgrab (nur Steuerung)
        if self.interactive_dvgrab_process:
            try:
                # Sende Stop-Befehl (ESC)
                if self.interactive_dvgrab_process.stdin and not self.interactive_dvgrab_process.stdin.closed:
                    try:
                        self.interactive_dvgrab_process.stdin.write(b"\x1b")  # ESC als Bytes
                        self.interactive_dvgrab_process.stdin.flush()
                        time.sleep(0.5)
                    except (BrokenPipeError, OSError):
                        pass
                
                self.interactive_dvgrab_process.terminate()
                self.interactive_dvgrab_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    self.interactive_dvgrab_process.kill()
                    self.interactive_dvgrab_process.wait(timeout=1)
                except:
                    pass
            except Exception:
                pass
            self.interactive_dvgrab_process = None
        
        # Cleanup Aliase
        self.interactive_process = None
        self.autosplit_dvgrab_process = None
    
    def rewind(self) -> bool:
        """Spult die Kassette zurück (interaktiver Modus: 'a')"""
        # Starte interaktiven dvgrab falls nicht aktiv
        if not self.interactive_dvgrab_process or self.interactive_dvgrab_process.poll() is not None:
            device = self.get_device()
            if not device:
                self.log("Kein FireWire-Gerät verfügbar!")
                return False
            if not self._start_interactive_dvgrab(device):
                self.log("FEHLER: Interaktiver dvgrab konnte nicht gestartet werden")
                return False
        
        return self._send_interactive_command("a")

    def play(self) -> bool:
        """Startet die Wiedergabe (interaktiver Modus: 'p')"""
        # Starte interaktiven dvgrab falls nicht aktiv
        if not self.interactive_dvgrab_process or self.interactive_dvgrab_process.poll() is not None:
            device = self.get_device()
            if not device:
                self.log("Kein FireWire-Gerät verfügbar!")
                return False
            if not self._start_interactive_dvgrab(device):
                self.log("FEHLER: Interaktiver dvgrab konnte nicht gestartet werden")
                return False
        
        return self._send_interactive_command("p")

    def pause(self) -> bool:
        """Pausiert die Wiedergabe (interaktiver Modus: 'k')"""
        # Starte interaktiven dvgrab falls nicht aktiv
        if not self.interactive_dvgrab_process or self.interactive_dvgrab_process.poll() is not None:
            device = self.get_device()
            if not device:
                self.log("Kein FireWire-Gerät verfügbar!")
                return False
            if not self._start_interactive_dvgrab(device):
                self.log("FEHLER: Interaktiver dvgrab konnte nicht gestartet werden")
                return False
        
        return self._send_interactive_command("k")

    def start_capture(
        self,
        output_path: Path,
        part_number: int = 1,
        preview_callback: Optional[Callable[[QImage], None]] = None,
        preview_fps: int = 10,
        auto_rewind_play: bool = True,
        title: str = "",
        year: str = "",
    ) -> bool:
        """
        Startet DV-Aufnahme mit dvgrab autosplit
        
        Args:
            output_path: Ausgabeordner (LowRes-Verzeichnis)
            part_number: Part-Nummer (wird nicht mehr verwendet, aber für Kompatibilität behalten)
            preview_callback: Optionaler Callback für Preview-Frames
            preview_fps: FPS für Preview
            auto_rewind_play: Setzt -rewind (automatisches Rewind vor Aufnahme)
            title: Titel des Films (für Merge-Queue)
            year: Jahr des Films (für Merge-Queue)
        """
        # Speichere Titel und Jahr für Merge-Jobs
        self.current_capture_title = title
        self.current_capture_year = year
        try:
            if self.is_capturing:
                self.log("Aufnahme läuft bereits!")
                return False

            # Halte sudo-Rechte aktiv, falls wir nicht als root laufen
            self._start_sudo_keepalive()

            device = self.get_device()
            if not device:
                self.log("Kein FireWire-Gerät verfügbar!")
                return False

            output_dir = Path(output_path)
            # Ordner wird von CaptureService erstellt, hier nur sicherstellen dass er existiert
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Erstelle splits-Ordner
            self.splits_dir = output_dir / "splits"
            self.splits_dir.mkdir(parents=True, exist_ok=True)
            self.last_split_time = time.time()
            self.auto_stop_inactivity_triggered = False
            
            # Setze Ausgabepfad für Merge (wird nach dem Stoppen erstellt)
            # Standard jetzt MP4
            self.current_output_path = output_dir / "movie_merged.mp4"

            self.preview_callback = preview_callback
            # Begrenze Preview-FPS für stabileres Bild (zu hohe FPS flackern gern)
            preview_fps = max(5, min(preview_fps, 15))
            self.preview_fps = preview_fps
            enable_preview = preview_callback is not None

            # 1. Beende interaktiven Modus falls aktiv (wird durch non-interaktiven ersetzt)
            if self.interactive_dvgrab_process and self.interactive_dvgrab_process.poll() is None:
                self.log("Beende interaktiven dvgrab-Modus...")
                try:
                    if self.interactive_dvgrab_process.stdin:
                        self.interactive_dvgrab_process.stdin.write(b"\x1b")  # ESC
                        self.interactive_dvgrab_process.stdin.flush()
                        time.sleep(0.5)
                except:
                    pass
                try:
                    self.interactive_dvgrab_process.terminate()
                    self.interactive_dvgrab_process.wait(timeout=2)
                except:
                    try:
                        self.interactive_dvgrab_process.kill()
                    except:
                        pass
                self.interactive_dvgrab_process = None
                self.interactive_process = None
            
            # 2. Starte non-interaktiven dvgrab für Aufnahme
            self.log("=== Starte non-interaktiven dvgrab für Aufnahme ===")
            if not self._start_recording_dvgrab(device, self.splits_dir, use_rewind=auto_rewind_play):
                self.log("FEHLER: Recording dvgrab konnte nicht gestartet werden")
                return False
            
            # 3. Markiere als aktiv (vor Preview-Threads, sonst stoppen sie sofort)
            self.is_capturing = True
            self.process = self.recording_dvgrab_process  # Für Kompatibilität
            
            # 4. Starte Preview-Queue-System (falls aktiviert)
            if enable_preview:
                self.log("=== Starte Preview-Queue-System ===")
                self.preview_stop_event = threading.Event()
                
                # Monitor-Thread: Fügt neue Dateien zur Queue hinzu
                self.preview_monitor_thread = threading.Thread(
                    target=self._monitor_splits_queue,
                    daemon=True,
                )
                self.preview_monitor_thread.start()
                self.log("Preview-Queue-Monitor: Thread gestartet")
                
                # Worker-Thread: Arbeitet Queue ab
                self.preview_worker_thread = threading.Thread(
                    target=self._process_preview_queue,
                    daemon=True,
                )
                self.preview_worker_thread.start()
                self.log("Preview-Queue-Worker: Thread gestartet")
            
            # 5. Inaktivitätsüberwachung (immer aktiv)
            self.inactivity_monitor_thread = threading.Thread(
                target=self._monitor_split_inactivity,
                daemon=True,
            )
            self.inactivity_monitor_thread.start()
            
            # 6. Starte Monitoring-Thread
            self.capture_thread = threading.Thread(
                target=self._monitor_capture,
                daemon=True,
            )
            self.capture_thread.start()
            
            self.log("Aufnahme gestartet! dvgrab spult automatisch zurück und startet Aufnahme.")
            self.log("Dateien werden in splits/ gespeichert mit Timestamp im Dateinamen.")
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
        """Stoppt die Aufnahme (sendet SIGINT) und führt automatisch Merge durch"""
        if not self.is_capturing:
            return False

        try:
            self.log("Stoppe Aufnahme...")

            # Stoppe Preview-Queue
            self._stop_preview()

            # Sende SIGINT an recording dvgrab (Strg+C)
            if self.recording_dvgrab_process and self.recording_dvgrab_process.poll() is None:
                self.log("Sende SIGINT (Strg+C) an dvgrab...")
                try:
                    import signal
                    self.recording_dvgrab_process.send_signal(signal.SIGINT)
                    # Warte auf Beendigung
                    self.recording_dvgrab_process.wait(timeout=10)
                    self.log("dvgrab wurde beendet")
                except subprocess.TimeoutExpired:
                    self.log("WARNUNG: dvgrab reagiert nicht auf SIGINT, verwende terminate...")
                    try:
                        self.recording_dvgrab_process.terminate()
                        self.recording_dvgrab_process.wait(timeout=3)
                    except:
                        try:
                            self.recording_dvgrab_process.kill()
                        except:
                            pass
                except Exception as e:
                    self.log(f"Fehler beim Senden von SIGINT: {e}")

            # Stoppe alle Prozesse
            self._stop_all_processes()

            self.is_capturing = False
            self.log("Aufnahme gestoppt.")

            # Warte, damit alle Dateien vollständig geschrieben sind
            self.log("Warte auf vollständiges Schreiben der Split-Dateien...")
            if self.splits_dir and self.splits_dir.exists():
                max_wait = 10  # Maximal 10 Sekunden warten
                waited = 0
                while waited < max_wait:
                    files = list(self.splits_dir.glob("dvgrab-*.avi"))
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

            # SOFORT: Rewind durchführen (damit Benutzer weitermachen kann)
            self.log("Spule Kamera zurück...")
            self._rewind_after_merge()
            
            # SOFORT: Benachrichtigung senden
            self._notify_completion(f"Aufnahme beendet: {self.current_capture_title} ({self.current_capture_year}). Merge läuft im Hintergrund.")
            
            # HINTERGRUND: Merge-Job zur Queue hinzufügen (nicht blockierend)
            if self.splits_dir and self.splits_dir.exists():
                split_files = list(self.splits_dir.glob("dvgrab*.avi")) + list(self.splits_dir.glob("dvgrab*.dv"))
                self.log(f"Gefunden: {len(split_files)} Split-Dateien - Merge wird im Hintergrund durchgeführt")

                self.queue_merge_job(
                    splits_dir=self.splits_dir,
                    output_path=self.current_output_path,
                    title=self.current_capture_title,
                    year=self.current_capture_year
                )
            else:
                self.log(f"WARNUNG: splits-Ordner nicht gefunden: {self.splits_dir}")

            # sudo-Keepalive beenden (falls gestartet)
            self._stop_sudo_keepalive()
            self._notify_state("stopped")

            # State-Callback
            self._notify_state("stopped")

            return True

        except Exception as e:
            self.log(f"Fehler beim Stoppen der Aufnahme: {e}")
            self.is_capturing = False
            self._stop_preview()
            self._stop_all_processes()
            self._stop_sudo_keepalive()
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
                self._notify_state("stopped")
                
                # Wenn der Prozess sofort beendet wurde (z.B. kein Signal), logge Warnung
                # Return-Code -9 (SIGKILL) ist normal, wenn wir den Prozess hart beenden mussten
                if return_code != 0 and return_code not in [130, 143, -9]:
                    self.log(f"WARNUNG: Aufnahme wurde unerwartet beendet (Return-Code: {return_code}). Mögliche Ursachen:")
                    self.log("  - Kein Signal von der Kamera (Bitte Play auf der Kamera drücken)")
                    self.log("  - Kamera nicht richtig verbunden")
                    self.log("  - dvgrab-Fehler (siehe stderr-Logs)")
                
                # Führe automatisch Merge, Rewind und Benachrichtigung durch
                # (wie in stop_capture(), aber hier wenn dvgrab von selbst beendet)
                self._finalize_capture_after_dvgrab_end()

        except Exception as e:
            self.log(f"Fehler beim Überwachen der Aufnahme: {e}")
            self.is_capturing = False
            self._stop_preview()
            self._stop_all_processes()

    def _finalize_capture_after_dvgrab_end(self):
        """
        Führt Rewind, Benachrichtigung und Background-Merge durch, wenn dvgrab von selbst beendet wurde.
        (z.B. Band zu Ende, Kamera gestoppt, Signal verloren)
        """
        try:
            self.log("dvgrab wurde automatisch beendet - starte Finalisierung...")
            
            # Warte kurz, damit alle Dateien vollständig geschrieben sind
            self.log("Warte auf vollständiges Schreiben der Split-Dateien...")
            if self.splits_dir and self.splits_dir.exists():
                max_wait = 10  # Maximal 10 Sekunden warten
                waited = 0
                while waited < max_wait:
                    files = list(self.splits_dir.glob("dvgrab-*.avi")) + list(self.splits_dir.glob("dvgrab*.avi"))
                    if files:
                        # Prüfe ob alle Dateien stabil sind
                        all_stable = True
                        for f in files:
                            if f.exists():
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
            
            # SOFORT: Rewind durchführen (damit Benutzer weitermachen kann)
            self.log("Spule Kamera zurück...")
            self._rewind_after_merge()
            
            # SOFORT: Benachrichtigung senden
            self._notify_completion(f"Aufnahme automatisch beendet: {self.current_capture_title} ({self.current_capture_year}). Merge läuft im Hintergrund.")
            
            # HINTERGRUND: Merge-Job zur Queue hinzufügen (nicht blockierend)
            if self.splits_dir and self.splits_dir.exists():
                split_files = list(self.splits_dir.glob("dvgrab*.avi")) + list(self.splits_dir.glob("dvgrab*.dv"))
                self.log(f"Gefunden: {len(split_files)} Split-Dateien - Merge wird im Hintergrund durchgeführt")
                
                self.queue_merge_job(
                    splits_dir=self.splits_dir,
                    output_path=self.current_output_path,
                    title=self.current_capture_title,
                    year=self.current_capture_year
                )
            else:
                self.log(f"WARNUNG: splits-Ordner nicht gefunden: {self.splits_dir}")
            
            # sudo-Keepalive beenden (falls gestartet)
            self._stop_sudo_keepalive()
            
        except Exception as e:
            self.log(f"Fehler bei Finalisierung nach dvgrab-Ende: {e}")
            self._notify_completion(f"Aufnahme beendet mit Fehler: {e}")

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

    def _rewind_after_merge(self):
        """Startet interaktiven Modus, führt Rewind aus und beendet ihn mit Ctrl+C"""
        try:
            device = self.get_device()
            if not device:
                self.log("Rewind nach Merge übersprungen: Kein FireWire-Gerät gefunden.")
                return
            
            if not self._start_interactive_dvgrab(device):
                self.log("Rewind nach Merge: Interaktiver Modus konnte nicht gestartet werden.")
                return
            
            self.log("Rewind nach Merge: Sende 'a' (rewind)...")
            self._send_interactive_command("a")
            time.sleep(1.5)
            
            proc = self.interactive_dvgrab_process or self.interactive_process
            if proc and proc.poll() is None:
                import signal
                self.log("Rewind nach Merge: Sende SIGINT (Ctrl+C) an interaktiven dvgrab...")
                try:
                    proc.send_signal(signal.SIGINT)
                    proc.wait(timeout=5)
                except Exception as e:
                    self.log(f"Rewind nach Merge: Fehler bei SIGINT: {e}")
            self.interactive_dvgrab_process = None
            self.interactive_process = None
        except Exception as e:
            self.log(f"Rewind nach Merge: Fehler: {e}")

    def _notify_completion(self, message: str):
        """Sendet Abschlussmeldung ins Log und an ntfy (dv2plex-complete)"""
        self.log(message)
        try:
            req = urllib.request.Request(
                "https://ntfy.sh/dv2plex-complete",
                data=message.encode("utf-8"),
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            self.log("ntfy-Benachrichtigung an dv2plex-complete gesendet.")
        except Exception as e:
            self.log(f"ntfy-Benachrichtigung fehlgeschlagen: {e}")

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
