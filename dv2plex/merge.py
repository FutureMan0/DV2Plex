"""
Merge-Engine für das Zusammenfügen mehrerer Capture-Parts
"""

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Callable
import logging


class MergeEngine:
    """Verwaltet das Zusammenfügen mehrerer DV-Parts zu einem Film"""
    
    def __init__(self, ffmpeg_path: Path, log_callback: Optional[Callable] = None):
        """
        Initialisiert die Merge-Engine
        
        Args:
            ffmpeg_path: Pfad zu ffmpeg
            log_callback: Optionaler Callback für Log-Nachrichten
        """
        self.ffmpeg_path = ffmpeg_path
        self.log_callback = log_callback
        self.logger = logging.getLogger(__name__)
        self._ffprobe_path: Optional[Path] = None

    def _get_ffprobe_path(self) -> Path:
        """
        Liefert den vermuteten ffprobe-Pfad (gleicher Ordner wie ffmpeg oder aus PATH)
        """
        if self._ffprobe_path:
            return self._ffprobe_path

        ffmpeg_path = Path(self.ffmpeg_path)
        # Versuche ffprobe im gleichen Verzeichnis
        candidate = ffmpeg_path.with_name("ffprobe")
        if candidate.exists():
            self._ffprobe_path = candidate
            return candidate

        # Fallback: ffprobe aus PATH
        self._ffprobe_path = Path("ffprobe")
        return self._ffprobe_path

    def _parse_creation_datetime(self, value: str) -> Optional[datetime]:
        """Parst einen Datums-String aus den Metadaten zu datetime"""
        try:
            cleaned = value.strip()
            if not cleaned:
                return None
            # ISO-8601 mit Z unterstützen
            if cleaned.endswith("Z"):
                cleaned = cleaned[:-1] + "+00:00"
            try:
                return datetime.fromisoformat(cleaned)
            except ValueError:
                # Häufiges Fallback-Format
                return datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    def _extract_creation_timestamp(self, video_path: Path) -> Optional[float]:
        """
        Liest den Aufnahmezeitpunkt aus den Metadaten (creation_time o.ä.).
        Gibt einen UTC-Timestamp zurück oder None.
        """
        ffprobe_path = self._get_ffprobe_path()
        tag_keys = [
            "format_tags=com.apple.quicktime.creationdate",
            "format_tags=creation_time",
            "stream_tags=timecode",
        ]

        for tag_key in tag_keys:
            try:
                cmd = [
                    str(ffprobe_path),
                    "-v",
                    "quiet",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    tag_key,
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(video_path),
                ]
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                value = result.stdout.strip()
                if not value:
                    continue
                dt = self._parse_creation_datetime(value)
                if dt:
                    # Sicherstellen, dass wir UTC/Epoch-Sekunden erhalten
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    ts = dt.timestamp()
                    self.log(f"Metadaten-Zeit gefunden ({tag_key}): {dt.isoformat()}")
                    return ts
            except Exception as e:
                self.log(f"Fehler beim Lesen von Metadaten ({tag_key}): {e}")
                continue

        # Fallback: Dateisystem-Zeitstempel
        try:
            mtime_ts = video_path.stat().st_mtime
            self.log(
                "Keine Metadaten-Zeit gefunden, verwende Dateisystem-Zeitstempel "
                f"({datetime.fromtimestamp(mtime_ts).isoformat(timespec='seconds')})"
            )
            return mtime_ts
        except Exception:
            return None
    
    def find_parts(self, lowres_dir: Path) -> List[Path]:
        """
        Findet alle Part-Dateien im LowRes-Ordner
        
        Args:
            lowres_dir: Pfad zum LowRes-Ordner
        
        Returns:
            Liste der Part-Dateien, sortiert nach Nummer
        """
        if not lowres_dir.exists():
            return []
        
        # Unterstütze alte AVI-Parts und neue MP4-Parts
        parts = sorted(lowres_dir.glob("part_*.avi")) + sorted(lowres_dir.glob("part_*.mp4"))
        return parts
    
    def merge_parts(self, lowres_dir: Path, output_name: str = "movie_merged.avi") -> Optional[Path]:
        """
        Fügt alle Parts zu einem Film zusammen
        
        Args:
            lowres_dir: Pfad zum LowRes-Ordner
            output_name: Name der Ausgabedatei
        
        Returns:
            Pfad zur zusammengefügten Datei, oder None bei Fehler
        """
        parts = self.find_parts(lowres_dir)
        
        if not parts:
            self.log("Keine Part-Dateien gefunden!")
            return None
        
        # Wähle Ausgabeformat passend zum Input
        first_ext = parts[0].suffix.lower()
        if first_ext == ".mp4":
            output_name = "movie_merged.mp4"
        elif first_ext == ".avi":
            output_name = "movie_merged.avi"
        else:
            # Fallback: mp4 ist kompatibler
            output_name = "movie_merged.mp4"
        output_path = lowres_dir / output_name
        
        # Wenn nur eine Datei, einfach kopieren/umbenennen (Container beibehalten)
        if len(parts) == 1:
            self.log(f"Nur eine Part-Datei gefunden, kopiere zu {output_name}...")
            try:
                import shutil
                shutil.copy2(parts[0], output_path)
                self.log(f"Datei erfolgreich kopiert: {output_path}")
                return output_path
            except Exception as e:
                self.log(f"Fehler beim Kopieren: {e}")
                return None
        
        # Mehrere Dateien: Erstelle concat-Liste
        self.log(f"Füge {len(parts)} Parts zusammen...")
        
        list_file = lowres_dir / "list.txt"
        
        try:
            # Erstelle concat-Liste
            with open(list_file, 'w', encoding='utf-8') as f:
                for part in parts:
                    # Verwende absolute Pfade für ffmpeg
                    abs_path = part.resolve()
                    # Escape single quotes für Windows-Pfade
                    escaped_path = str(abs_path).replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")
            
            # ffmpeg concat-Befehl
            cmd = [
                str(self.ffmpeg_path),
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",
                "-movflags", "+faststart",
                "-y",  # Überschreibe vorhandene Datei
                str(output_path)
            ]
            
            self.log(f"Starte Merge mit ffmpeg...")
            self.log(f"Befehl: {' '.join(cmd)}")
            
            # Führe ffmpeg aus
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Lösche temporäre Liste
            try:
                list_file.unlink()
            except:
                pass
            
            if result.returncode == 0:
                self.log(f"Merge erfolgreich: {output_path}")
                return output_path
            else:
                self.log(f"ffmpeg-Fehler beim Merge: {result.stderr[-500:]}")
                return None
                
        except Exception as e:
            self.log(f"Fehler beim Merge: {e}")
            # Lösche temporäre Liste
            try:
                if list_file.exists():
                    list_file.unlink()
            except:
                pass
            return None
    
    def merge_videos(self, video_paths: List[Path], output_path: Path) -> Optional[Path]:
        """
        Fügt mehrere HighRes-Videos (mp4) zu einem Film zusammen
        
        Args:
            video_paths: Liste der Video-Pfade (sortiert)
            output_path: Pfad zur Ausgabedatei
        
        Returns:
            Pfad zur zusammengefügten Datei, oder None bei Fehler
        """
        if not video_paths:
            self.log("Keine Videos zum Mergen angegeben!")
            return None
        
        if len(video_paths) == 1:
            self.log(f"Nur ein Video, kopiere zu {output_path.name}...")
            try:
                import shutil
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(video_paths[0], output_path)
                self.log(f"Datei erfolgreich kopiert: {output_path}")
                return output_path
            except Exception as e:
                self.log(f"Fehler beim Kopieren: {e}")
                return None
        
        # Mehrere Videos: Erstelle concat-Liste
        self.log(f"Füge {len(video_paths)} Videos zusammen...")
        
        # Erstelle temporäre Liste im Ausgabeordner
        list_file = output_path.parent / "merge_list.txt"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # Erstelle concat-Liste
            with open(list_file, 'w', encoding='utf-8') as f:
                for video in video_paths:
                    if not video.exists():
                        self.log(f"Warnung: Video nicht gefunden: {video}")
                        continue
                    # Verwende absolute Pfade für ffmpeg
                    abs_path = video.resolve()
                    # Escape single quotes für Windows-Pfade
                    escaped_path = str(abs_path).replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")
            
            # ffmpeg concat-Befehl für mp4-Videos
            # Verwende re-encoding statt copy, da mp4-Videos unterschiedliche Codecs haben können
            cmd = [
                str(self.ffmpeg_path),
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-c:v", "libx264",
                "-c:a", "aac",
                "-preset", "medium",
                "-crf", "18",
                "-y",  # Überschreibe vorhandene Datei
                str(output_path)
            ]
            
            self.log(f"Starte Merge mit ffmpeg...")
            self.log(f"Befehl: {' '.join(cmd)}")
            
            # Führe ffmpeg aus
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Lösche temporäre Liste
            try:
                list_file.unlink()
            except:
                pass
            
            if result.returncode == 0:
                self.log(f"Merge erfolgreich: {output_path}")
                return output_path
            else:
                self.log(f"ffmpeg-Fehler beim Merge: {result.stderr[-500:]}")
                return None
                
        except Exception as e:
            self.log(f"Fehler beim Merge: {e}")
            # Lösche temporäre Liste
            try:
                if list_file.exists():
                    list_file.unlink()
            except:
                pass
            return None
    
    def add_timestamp_overlay(
        self,
        input_path: Path,
        output_path: Path,
        duration: int = 4,
        scene_threshold: float = 0.3
    ) -> Optional[Path]:
        """
        Fügt Timestamp-Overlays bei Szenenänderungen hinzu
        
        Args:
            input_path: Eingabe-Video
            output_path: Ausgabe-Video mit Timestamps
            duration: Dauer der Timestamp-Anzeige in Sekunden (Standard: 4)
            scene_threshold: Threshold für Szenenänderung-Erkennung (Standard: 0.3)
        
        Returns:
            Pfad zur Ausgabedatei, oder None bei Fehler
        """
        if not input_path.exists():
            self.log(f"Eingabedatei nicht gefunden: {input_path}")
            return None
        
        try:
            self.log(f"Füge Timestamp-Overlays hinzu...")
            
            # Schritt 1: Erkenne Szenenänderungen
            self.log("Erkenne Szenenänderungen...")
            scene_changes = self._detect_scene_changes(input_path, scene_threshold)
            
            if not scene_changes:
                self.log("Keine Szenenänderungen erkannt, kopiere Datei ohne Overlays")
                import shutil
                shutil.copy2(input_path, output_path)
                return output_path
            
            self.log(f"{len(scene_changes)} Szenenänderungen erkannt")

            # Metadaten für Startzeit auslesen (creation_time o.ä.)
            base_timestamp = self._extract_creation_timestamp(input_path)
            if base_timestamp:
                human_readable = datetime.fromtimestamp(base_timestamp).isoformat(
                    timespec="seconds"
                )
                self.log(f"Nutze Metadaten-Startzeit für Overlay: {human_readable}")
            else:
                self.log("Keine Metadaten-Startzeit gefunden, nutze 00:00:00 ab Video-Start")

            # Timestamp-Format: Bei Metadaten volle Datums-/Zeitangabe, sonst Laufzeit
            if base_timestamp:
                base_seconds = int(base_timestamp)
                timestamp_template = (
                    f"%{{pts\\:gmtime\\:{base_seconds}\\:%Y\\-%m\\-%d\\ %H\\:%M\\:%S}}"
                )
            else:
                timestamp_template = "%{pts\\:gmtime\\:0\\:%H\\:%M\\:%S}"
            
            # Schritt 2: Erstelle drawtext-Filter für jede Szenenänderung
            # Format: drawtext für 4 Sekunden nach jeder Szenenänderung
            filter_parts = []
            
            for scene_time in scene_changes:
                # Timestamp-Text: Metadaten-Zeit (falls vorhanden) sonst Laufzeit
                # Verwende enable-Filter um nur für bestimmte Zeit zu zeigen
                end_time = scene_time + duration
                filter_expr = (
                    f"drawtext=text='{timestamp_template}'"
                    f":fontsize=24"
                    f":x=10"
                    f":y=10"
                    f":fontcolor=white"
                    f":box=1"
                    f":boxcolor=black@0.5"
                    f":enable='between(t,{scene_time},{end_time})'"
                )
                filter_parts.append(filter_expr)
            
            # Kombiniere alle Filter
            if len(filter_parts) == 1:
                vf_filter = filter_parts[0]
            else:
                # Mehrere Filter mit Komma verbinden
                vf_filter = ",".join(filter_parts)
            
            # Schritt 3: Wende Filter an
            cmd = [
                str(self.ffmpeg_path),
                "-i", str(input_path),
                "-vf", vf_filter,
                "-c:a", "copy",  # Audio kopieren
                "-y",
                str(output_path)
            ]
            
            self.log(f"Wende Timestamp-Overlays an...")
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            if result.returncode == 0:
                self.log(f"Timestamp-Overlays erfolgreich hinzugefügt: {output_path}")
                return output_path
            else:
                self.log(f"Fehler beim Hinzufügen von Timestamps: {result.stderr[-500:]}")
                return None
                
        except Exception as e:
            self.log(f"Fehler beim Hinzufügen von Timestamp-Overlays: {e}")
            return None
    
    def _detect_scene_changes(self, video_path: Path, threshold: float = 0.3) -> List[float]:
        """
        Erkennt Szenenänderungen im Video
        
        Args:
            video_path: Pfad zum Video
            threshold: Threshold für Szenenänderung (0.0-1.0)
        
        Returns:
            Liste von Zeitpunkten (in Sekunden) wo Szenenänderungen auftreten
        """
        try:
            # Verwende ffmpeg's scene-Filter
            cmd = [
                str(self.ffmpeg_path),
                "-i", str(video_path),
                "-vf", f"select='gt(scene,{threshold})',showinfo",
                "-f", "null",
                "-"
            ]
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Parse stderr für Zeitpunkte
            scene_times = []
            for line in result.stderr.split('\n'):
                if 'pts_time:' in line:
                    # Extrahiere Zeitpunkt
                    try:
                        # Format: "pts_time:1.234"
                        parts = line.split('pts_time:')
                        if len(parts) > 1:
                            time_str = parts[1].split()[0]
                            scene_times.append(float(time_str))
                    except (ValueError, IndexError):
                        continue
            
            return sorted(scene_times)
            
        except Exception as e:
            self.log(f"Fehler bei Szenenänderung-Erkennung: {e}")
            return []
    
    def log(self, message: str):
        """Loggt eine Nachricht"""
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)

