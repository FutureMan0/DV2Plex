"""
Frame-Extraktion Engine für die Extraktion von Frames aus Videos
"""

import subprocess
import random
import tempfile
from pathlib import Path
from typing import List, Optional, Callable
import logging


class FrameExtractionEngine:
    """Verwaltet die Extraktion von Frames aus Videos"""
    
    def __init__(self, ffmpeg_path: Path, log_callback: Optional[Callable] = None):
        """
        Initialisiert die Frame-Extraktion Engine
        
        Args:
            ffmpeg_path: Pfad zu ffmpeg
            log_callback: Optionaler Callback für Log-Nachrichten
        """
        self.ffmpeg_path = ffmpeg_path
        self.log_callback = log_callback
        self.logger = logging.getLogger(__name__)
        self.temp_dir = Path(tempfile.gettempdir()) / "dv2plex_cover_frames"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._ffprobe_path: Optional[Path] = None

    def _get_ffprobe_path(self) -> Path:
        """
        Liefert einen ffprobe-Pfad (neben ffmpeg oder aus PATH).
        Unter Windows ist ffprobe typischerweise ffprobe.exe.
        """
        if self._ffprobe_path is not None:
            return self._ffprobe_path

        ffmpeg_path = Path(self.ffmpeg_path)
        # Kandidat im gleichen Ordner wie ffmpeg
        if ffmpeg_path.suffix.lower() == ".exe":
            candidate = ffmpeg_path.with_name("ffprobe.exe")
        else:
            candidate = ffmpeg_path.with_name("ffprobe")

        if candidate.exists():
            self._ffprobe_path = candidate
            return candidate

        # Fallback: ffprobe aus PATH
        self._ffprobe_path = Path("ffprobe")
        return self._ffprobe_path
    
    def get_video_duration(self, video_path: Path) -> Optional[float]:
        """
        Ermittelt die Dauer eines Videos in Sekunden
        
        Args:
            video_path: Pfad zum Video
            
        Returns:
            Dauer in Sekunden oder None bei Fehler
        """
        try:
            # Preferiere ffprobe (robuster als ffmpeg-Output zu parsen)
            ffprobe = self._get_ffprobe_path()
            cmd = [
                str(ffprobe),
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nk=1:nw=1",
                str(video_path),
            ]

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            out = (result.stdout or "").strip()
            if result.returncode == 0 and out:
                try:
                    return float(out)
                except Exception:
                    pass

            # Fallback: ffmpeg-Parsing (falls ffprobe nicht verfügbar ist)
            cmd2 = [
                str(self.ffmpeg_path),
                "-i",
                str(video_path),
                "-hide_banner",
                "-f",
                "null",
                "-",
            ]

            result2 = subprocess.run(
                cmd2,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

            for line in (result2.stdout or "").split("\n"):
                if "Duration:" in line:
                    duration_str = line.split("Duration:")[1].split(",")[0].strip()
                    parts = duration_str.split(":")
                    if len(parts) == 3:
                        hours = float(parts[0])
                        minutes = float(parts[1])
                        seconds = float(parts[2])
                        return hours * 3600 + minutes * 60 + seconds

            return None
        except Exception as e:
            self.log(f"Fehler beim Ermitteln der Video-Dauer: {e}")
            return None
    
    def extract_random_frames(
        self,
        video_path: Path,
        count: int = 4,
        output_dir: Optional[Path] = None
    ) -> List[Path]:
        """
        Extrahiert zufällige Frames aus einem Video
        
        Args:
            video_path: Pfad zum Video
            count: Anzahl der zu extrahierenden Frames
            output_dir: Optional: Ausgabe-Verzeichnis (Standard: temp)
            
        Returns:
            Liste der Pfade zu den extrahierten Frames
        """
        if not video_path.exists():
            self.log(f"Video nicht gefunden: {video_path}")
            return []
        
        if output_dir is None:
            output_dir = self.temp_dir
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Ermittle Video-Dauer
        duration = self.get_video_duration(video_path)
        if duration is None or duration <= 0:
            self.log(f"Konnte Video-Dauer nicht ermitteln für: {video_path}")
            return []
        
        # Generiere zufällige Zeitpunkte (vermeide erste und letzte 5 Sekunden)
        min_time = 5.0
        max_time = max(duration - 5.0, min_time + 1.0)
        
        if max_time <= min_time:
            # Video zu kurz, nimm einfach gleichmäßig verteilte Frames
            time_points = [duration / (count + 1) * (i + 1) for i in range(count)]
        else:
            time_points = [random.uniform(min_time, max_time) for _ in range(count)]
            time_points.sort()
        
        extracted_frames = []
        
        try:
            for i, time_point in enumerate(time_points):
                output_file = output_dir / f"frame_{video_path.stem}_{i:02d}.jpg"
                
                # Extrahiere Frame bei spezifischem Zeitpunkt
                cmd = [
                    str(self.ffmpeg_path),
                    "-hide_banner",
                    "-y",  # Überschreibe vorhandene Datei
                    # Wichtig (Windows): -ss VOR -i nutzt Keyframe-Seek und ist deutlich stabiler.
                    # Mit -ss nach -i haben wir reproduzierbar ffmpeg-Crashes (0xC0000005) gesehen.
                    "-ss", str(time_point),
                    "-i", str(video_path),
                    "-map", "0:v:0",
                    "-an",
                    "-sn",
                    "-frames:v", "1",
                    "-q:v", "2",  # Hohe Qualität
                    # ffmpeg warnt sonst bei einem einzelnen Bild ohne Sequenzpattern.
                    "-update", "1",
                    str(output_file)
                ]
                
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True
                )
                
                if result.returncode == 0 and output_file.exists():
                    extracted_frames.append(output_file)
                    self.log(f"Frame extrahiert: {output_file.name} (bei {time_point:.2f}s)")
                else:
                    self.log(f"Fehler beim Extrahieren von Frame bei {time_point:.2f}s: {result.stdout}")
            
            return extracted_frames
            
        except Exception as e:
            self.log(f"Fehler bei Frame-Extraktion: {e}")
            return extracted_frames
    
    def cleanup_temp_frames(self, keep_recent: int = 10):
        """
        Bereinigt temporäre Frame-Dateien (behält die neuesten)
        
        Args:
            keep_recent: Anzahl der neuesten Dateien, die behalten werden sollen
        """
        try:
            if not self.temp_dir.exists():
                return
            
            # Sortiere nach Änderungsdatum (neueste zuerst)
            frames = sorted(
                self.temp_dir.glob("frame_*.jpg"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            
            # Lösche alte Frames
            for frame in frames[keep_recent:]:
                try:
                    frame.unlink()
                    self.log(f"Alten Frame gelöscht: {frame.name}")
                except Exception as e:
                    self.log(f"Fehler beim Löschen von {frame.name}: {e}")
        
        except Exception as e:
            self.log(f"Fehler bei Cleanup: {e}")
    
    def log(self, message: str):
        """Loggt eine Nachricht"""
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)
