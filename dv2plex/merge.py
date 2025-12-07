"""
Merge-Engine für das Zusammenfügen mehrerer Capture-Parts
"""

import subprocess
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Callable, Tuple
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
        self._is_dv_cache: dict[Path, bool] = {}

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

    def _is_dv_stream(self, video_path: Path) -> bool:
        """
        Prüft per ffprobe, ob der Videostream DV (dvvideo) ist.
        Ergebnis wird gecached, um Mehrfach-Aufrufe zu vermeiden.
        """
        cached = self._is_dv_cache.get(video_path)
        if cached is not None:
            return cached

        ffprobe_path = self._get_ffprobe_path()
        cmd = [
            str(ffprobe_path),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=nk=1:nw=1",
            str(video_path),
        ]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            codec = result.stdout.strip().lower()
            is_dv = codec == "dvvideo"
            self._is_dv_cache[video_path] = is_dv
            return is_dv
        except Exception:
            self._is_dv_cache[video_path] = False
            return False

    def _bcd(self, value: int, mask: int = 0xFF) -> int:
        """Dekodiert ein BCD-basiertes Byte (unter Berücksichtigung einer Maske)."""
        v = value & mask
        return ((v >> 4) & 0x0F) * 10 + (v & 0x0F)

    def _parse_dv_date_pack(self, pack: bytes) -> Optional[Tuple[int, int, int]]:
        """
        Parst den DV-Datecode (Aufnahmedatum) aus Pack-ID 0x13.
        Layout: BCD-JJ (Byte1), BCD-MM (Byte2), BCD-TT (Byte3).
        """
        if len(pack) != 5 or pack[0] != 0x13:
            return None
        year_2d = self._bcd(pack[1])
        month = self._bcd(pack[2] & 0x1F)  # obere Bits sind Flags
        day = self._bcd(pack[3] & 0x3F)

        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None

        year = 2000 + year_2d if year_2d < 70 else 1900 + year_2d
        return year, month, day

    def _parse_dv_time_pack(self, pack: bytes) -> Optional[Tuple[int, int, int]]:
        """
        Parst die DV-Aufnahmezeit aus Pack-ID 0x62.
        Layout (BCD): HH (Byte1), MM (Byte2), SS (Byte3).
        """
        if len(pack) != 5 or pack[0] != 0x62:
            return None
        hour = self._bcd(pack[1] & 0x3F)
        minute = self._bcd(pack[2] & 0x7F)
        second = self._bcd(pack[3] & 0x7F)

        if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
            return None
        return hour, minute, second

    def _extract_dv_datecode(self, video_path: Path) -> Optional[float]:
        """
        Versucht, DV-Datecode (Aufnahme-Datum/Uhrzeit) direkt aus DV-Stream zu lesen.
        Nur sinnvoll, wenn der Videostream dvvideo ist.
        """
        if not self._is_dv_stream(video_path):
            return None

        block_size = 80  # DIF-Block-Größe
        max_bytes = 8 * 1024 * 1024  # genug für etliche Frames
        date_parts: Optional[Tuple[int, int, int]] = None
        time_parts: Optional[Tuple[int, int, int]] = None

        try:
            with open(video_path, "rb") as f:
                data = f.read(max_bytes)
        except Exception as e:
            self.log(f"DV-Datecode: konnte Datei nicht lesen: {e}")
            return None

        data_len = len(data)
        if data_len < block_size:
            return None

        for i in range(0, data_len - block_size + 1, block_size):
            block = data[i : i + block_size]
            if block[0] != 0x1F:
                continue
            block_type = block[1] >> 5  # 0=subcode, 1=VAUX
            if block_type not in (0, 1):
                continue
            payload = block[3:]
            for p in range(0, len(payload) - 4, 5):
                pack = payload[p : p + 5]
                pid = pack[0]
                if pid == 0x13 and date_parts is None:
                    date_parts = self._parse_dv_date_pack(pack)
                elif pid == 0x62 and time_parts is None:
                    time_parts = self._parse_dv_time_pack(pack)
                if date_parts and time_parts:
                    break
            if date_parts and time_parts:
                break

        if not (date_parts and time_parts):
            self.log("DV-Datecode nicht gefunden (kein 0x13/0x62 Pack im Stream)")
            return None

        try:
            year, month, day = date_parts
            hour, minute, second = time_parts
            dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
            ts = dt.timestamp()
            self.log(f"DV-Datecode gefunden: {dt.isoformat()}")
            return ts
        except Exception as e:
            self.log(f"DV-Datecode konnte nicht geparst werden: {e}")
            return None

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
    
    def _parse_timecode_from_filename(self, filename: str) -> Optional[Tuple[int, int, int, int]]:
        """
        Parst Timecode aus dvgrab-Dateinamen
        
        Format: capture-001-00.00.00.000.avi oder ähnlich
        Gibt zurück: (hours, minutes, seconds, frames) oder None
        
        Args:
            filename: Dateiname (z.B. "capture-001-00.00.00.000.avi")
        
        Returns:
            Tuple (hours, minutes, seconds, frames) oder None
        """
        try:
            # Suche nach Timecode-Pattern: HH.MM.SS.FFF oder HH:MM:SS:FFF
            # dvgrab verwendet normalerweise Format: capture-XXX-HH.MM.SS.FFF.avi
            patterns = [
                r'(\d{2})\.(\d{2})\.(\d{2})\.(\d{3})',  # 00.00.00.000
                r'(\d{2}):(\d{2}):(\d{2}):(\d{3})',      # 00:00:00:000
                r'(\d{2})\.(\d{2})\.(\d{2})',            # 00.00.00 (ohne Frames)
            ]
            
            for pattern in patterns:
                match = re.search(pattern, filename)
                if match:
                    groups = match.groups()
                    hours = int(groups[0])
                    minutes = int(groups[1])
                    seconds = int(groups[2])
                    frames = int(groups[3]) if len(groups) > 3 else 0
                    
                    # Validiere Werte
                    if 0 <= hours < 24 and 0 <= minutes < 60 and 0 <= seconds < 60:
                        return (hours, minutes, seconds, frames)
            
            return None
        except Exception:
            return None
    
    def _timecode_to_seconds(self, timecode: Tuple[int, int, int, int]) -> float:
        """
        Konvertiert Timecode zu Sekunden (für Sortierung)
        
        Args:
            timecode: (hours, minutes, seconds, frames)
        
        Returns:
            Sekunden als float
        """
        hours, minutes, seconds, frames = timecode
        return hours * 3600 + minutes * 60 + seconds + frames / 30.0  # DV hat 30 FPS
    
    def merge_splits(self, splits_dir: Path, output_path: Path) -> Optional[Path]:
        """
        Fügt alle Split-Dateien nach Timecode zusammen
        
        Args:
            splits_dir: Pfad zu LowRes/splits/
            output_path: Ausgabepfad für zusammengefügtes Video
        
        Returns:
            Pfad zur zusammengefügten Datei oder None
        """
        if not splits_dir.exists():
            self.log(f"splits-Ordner nicht gefunden: {splits_dir}")
            return None
        
        # Finde alle Video-Dateien im splits-Ordner (avi, dv, etc.)
        split_files = []
        for pattern in ["*.avi", "*.dv", "*.AVI", "*.DV"]:
            split_files.extend(splits_dir.glob(pattern))
        
        if not split_files:
            self.log("Keine Split-Dateien gefunden!")
            return None
        
        # Filtere leere Dateien
        split_files = [f for f in split_files if f.stat().st_size > 0]
        if not split_files:
            self.log("Keine gültigen Split-Dateien gefunden (alle Dateien sind leer)!")
            return None
        
        self.log(f"Gefunden: {len(split_files)} Split-Dateien")
        
        # Wenn nur eine Datei, kopiere sie (aber prüfe Format)
        if len(split_files) == 1:
            self.log(f"Nur eine Split-Datei, kopiere zu {output_path.name}...")
            try:
                import shutil
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Wenn Ausgabeformat anders ist, konvertiere mit ffmpeg
                source_ext = split_files[0].suffix.lower()
                target_ext = output_path.suffix.lower()
                
                if source_ext == target_ext:
                    # Gleiches Format, einfach kopieren
                    shutil.copy2(split_files[0], output_path)
                else:
                    # Anderes Format, konvertiere mit ffmpeg
                    self.log(f"Konvertiere {source_ext} zu {target_ext}...")
                    cmd = [
                        str(self.ffmpeg_path),
                        "-i", str(split_files[0]),
                        "-c", "copy",  # Copy-Modus wenn möglich
                        "-y",
                        str(output_path)
                    ]
                    result = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    if result.returncode != 0:
                        self.log(f"Konvertierungs-Fehler: {result.stderr[-500:]}")
                        return None
                
                self.log(f"Datei erfolgreich kopiert/konvertiert: {output_path}")
                return output_path
            except Exception as e:
                self.log(f"Fehler beim Kopieren: {e}")
                return None
        
        # Sortiere nach Timecode (aus Dateinamen)
        files_with_timecode = []
        for file_path in split_files:
            timecode = self._parse_timecode_from_filename(file_path.name)
            if timecode:
                seconds = self._timecode_to_seconds(timecode)
                files_with_timecode.append((seconds, file_path))
                self.log(f"  {file_path.name} -> Timecode: {timecode[0]:02d}:{timecode[1]:02d}:{timecode[2]:02d}.{timecode[3]:03d}")
            else:
                # Fallback: Verwende mtime für Sortierung
                mtime = file_path.stat().st_mtime
                files_with_timecode.append((mtime, file_path))
                self.log(f"  {file_path.name} -> Kein Timecode, verwende mtime: {mtime}")
        
        # Sortiere nach Timecode/Sekunden
        files_with_timecode.sort(key=lambda x: x[0])
        sorted_files = [f[1] for f in files_with_timecode]
        
        self.log(f"Sortiere {len(sorted_files)} Dateien nach Timecode...")
        
        # Erstelle concat-Liste
        output_path.parent.mkdir(parents=True, exist_ok=True)
        list_file = output_path.parent / "merge_splits_list.txt"
        
        try:
            # Erstelle concat-Liste
            with open(list_file, 'w', encoding='utf-8') as f:
                for split_file in sorted_files:
                    # Verwende absolute Pfade für ffmpeg
                    abs_path = split_file.resolve()
                    # Escape single quotes für Windows-Pfade
                    escaped_path = str(abs_path).replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")
            
            # Bestimme Ausgabeformat basierend auf Input
            output_ext = output_path.suffix.lower()
            if output_ext == ".avi":
                output_format = "avi"
            elif output_ext == ".mp4":
                output_format = "mp4"
            else:
                # Fallback: Verwende Format der ersten Datei
                first_ext = sorted_files[0].suffix.lower()
                if first_ext == ".avi":
                    output_format = "avi"
                    output_path = output_path.with_suffix(".avi")
                else:
                    output_format = "mp4"
                    output_path = output_path.with_suffix(".mp4")
            
            # ffmpeg concat-Befehl
            # Versuche zuerst -c copy (schnell), falls das fehlschlägt, re-encode
            cmd = [
                str(self.ffmpeg_path),
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",  # Copy-Modus für schnelles Zusammenfügen
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
                # Copy-Modus fehlgeschlagen, versuche Re-Encoding
                self.log("Copy-Modus fehlgeschlagen, versuche Re-Encoding...")
                error_msg = result.stderr[-500:]
                if "cannot find a valid video stream" in error_msg.lower() or "invalid data" in error_msg.lower():
                    # Dateien sind möglicherweise beschädigt oder unvollständig
                    self.log(f"WARNUNG: Dateien scheinen beschädigt oder unvollständig zu sein")
                    self.log(f"Fehler: {error_msg}")
                    return None
                
                # Versuche Re-Encoding als Fallback
                cmd_reencode = [
                    str(self.ffmpeg_path),
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(list_file),
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    "-preset", "medium",
                    "-crf", "23",
                    "-y",
                    str(output_path)
                ]
                
                self.log(f"Re-Encoding-Befehl: {' '.join(cmd_reencode)}")
                result2 = subprocess.run(
                    cmd_reencode,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                if result2.returncode == 0:
                    self.log(f"Merge erfolgreich (Re-Encoded): {output_path}")
                    return output_path
                else:
                    self.log(f"ffmpeg-Fehler beim Re-Encoding: {result2.stderr[-500:]}")
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

            # Quelle für Startzeit priorisieren: DV-Datecode -> Metadaten -> mtime -> 00:00:00
            base_timestamp = self._extract_dv_datecode(input_path)
            if base_timestamp:
                human_readable = datetime.fromtimestamp(base_timestamp, tz=timezone.utc).isoformat(
                    timespec="seconds"
                )
                self.log(f"Nutze DV-Datecode für Overlay: {human_readable}")
            else:
                base_timestamp = self._extract_creation_timestamp(input_path)
                if base_timestamp:
                    human_readable = datetime.fromtimestamp(base_timestamp).isoformat(
                        timespec="seconds"
                    )
                    self.log(f"Nutze Metadaten-Startzeit für Overlay: {human_readable}")
                else:
                    self.log("Keine DV/Metadaten-Startzeit gefunden, nutze 00:00:00 ab Video-Start")

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

