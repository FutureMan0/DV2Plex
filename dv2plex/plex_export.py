"""
Plex-Exporter für den Export in die Plex-Movie-Library
"""

import shutil
import re
from pathlib import Path
from typing import Optional, Callable
import logging


class PlexExporter:
    """Verwaltet den Export von Videos in die Plex-Movie-Library"""
    
    def __init__(self, plex_movies_root: Path, log_callback: Optional[Callable] = None):
        """
        Initialisiert den Plex-Exporter
        
        Args:
            plex_movies_root: Root-Pfad der Plex-Movies-Library
            log_callback: Optionaler Callback für Log-Nachrichten
        """
        self.plex_movies_root = plex_movies_root
        self.log_callback = log_callback
        self.logger = logging.getLogger(__name__)
    
    def export_movie(
        self,
        source_path: Path,
        movie_title: str,
        year: str,
        overwrite: bool = False
    ) -> Optional[Path]:
        """
        Exportiert einen Film in die Plex-Library
        
        Args:
            source_path: Pfad zur Quell-Datei (HighRes-Video)
            movie_title: Filmtitel
            year: Jahr
            overwrite: Überschreibe vorhandene Datei
        
        Returns:
            Pfad zur exportierten Datei, oder None bei Fehler
        """
        if not source_path.exists():
            self.log(f"Quelldatei nicht gefunden: {source_path}")
            return None
        
        # Erstelle Filmname im Plex-Format: "Titel (Jahr)"
        movie_name = f"{movie_title} ({year})"
        
        # Erstelle Zielordner und -datei
        target_dir = self.plex_movies_root / movie_name
        target_file = target_dir / f"{movie_name}.mp4"
        
        # Prüfe ob Datei bereits existiert
        if target_file.exists() and not overwrite:
            self.log(f"Datei existiert bereits: {target_file}")
            self.log("Setze overwrite=True zum Überschreiben")
            return None
        
        try:
            # Erstelle Zielordner
            target_dir.mkdir(parents=True, exist_ok=True)
            
            self.log(f"Exportiere Film: {movie_name}")
            self.log(f"Quelle: {source_path}")
            self.log(f"Ziel: {target_file}")
            
            # Kopiere Datei
            shutil.copy2(source_path, target_file)
            
            self.log(f"Export erfolgreich: {target_file}")
            return target_file
            
        except Exception as e:
            self.log(f"Fehler beim Export: {e}")
            return None
    
    def export_single_video(
        self,
        source_path: Path,
        movie_title: Optional[str] = None,
        year: Optional[str] = None,
        overwrite: bool = False
    ) -> Optional[Path]:
        """
        Exportiert ein einzelnes Video direkt in die Plex-Library
        
        Args:
            source_path: Pfad zur Quell-Datei (HighRes-Video)
            movie_title: Filmtitel (optional, wird aus Ordnerstruktur extrahiert falls None)
            year: Jahr (optional, wird aus Ordnerstruktur extrahiert falls None)
            overwrite: Überschreibe vorhandene Datei
        
        Returns:
            Pfad zur exportierten Datei, oder None bei Fehler
        """
        if not source_path.exists():
            self.log(f"Quelldatei nicht gefunden: {source_path}")
            return None
        
        # Extrahiere Titel und Jahr aus Ordnerstruktur falls nicht angegeben
        if movie_title is None or year is None:
            # Versuche aus Pfad zu extrahieren: .../DV_Import/Titel (Jahr)/HighRes/video.mp4
            import re
            path_parts = source_path.parts
            for i, part in enumerate(path_parts):
                # Suche nach Muster "Titel (Jahr)"
                match = re.match(r"^(.+?)\s*\((\d{4})\)$", part)
                if match:
                    if movie_title is None:
                        movie_title = match.group(1).strip()
                    if year is None:
                        year = match.group(2)
                    break
        
        # Fallback: Verwende Dateiname ohne Extension
        if movie_title is None:
            movie_title = source_path.stem
        if year is None:
            year = ""
        
        # Erstelle Filmname im Plex-Format: "Titel (Jahr)" oder nur "Titel"
        if year:
            movie_name = f"{movie_title} ({year})"
        else:
            movie_name = movie_title
        
        # Erstelle Zielordner und -datei
        target_dir = self.plex_movies_root / movie_name
        target_file = target_dir / f"{movie_name}.mp4"
        
        # Prüfe ob Datei bereits existiert
        if target_file.exists() and not overwrite:
            self.log(f"Datei existiert bereits: {target_file}")
            self.log("Setze overwrite=True zum Überschreiben")
            return None
        
        try:
            # Erstelle Zielordner
            target_dir.mkdir(parents=True, exist_ok=True)
            
            self.log(f"Exportiere Video: {movie_name}")
            self.log(f"Quelle: {source_path}")
            self.log(f"Ziel: {target_file}")
            
            # Kopiere Datei
            shutil.copy2(source_path, target_file)
            
            self.log(f"Export erfolgreich: {target_file}")
            return target_file
            
        except Exception as e:
            self.log(f"Fehler beim Export: {e}")
            return None
    
    def get_movie_path(self, movie_title: str, year: str) -> Path:
        """
        Gibt den erwarteten Pfad für einen Film zurück (ohne Export)
        
        Args:
            movie_title: Filmtitel
            year: Jahr
        
        Returns:
            Pfad zur erwarteten Datei
        """
        movie_name = f"{movie_title} ({year})"
        target_dir = self.plex_movies_root / movie_name
        target_file = target_dir / f"{movie_name}.mp4"
        return target_file
    
    def save_cover(
        self,
        cover_path: Path,
        movie_title: str,
        year: str,
        overwrite: bool = True
    ) -> Optional[Path]:
        """
        Speichert ein Cover als poster.jpg im entsprechenden Plex Movies Ordner
        
        Args:
            cover_path: Pfad zum generierten Cover
            movie_title: Filmtitel
            year: Jahr
            overwrite: Überschreibe vorhandenes Cover
        
        Returns:
            Pfad zum gespeicherten Cover oder None bei Fehler
        """
        if not cover_path.exists():
            self.log(f"Cover nicht gefunden: {cover_path}")
            return None
        
        # Erstelle Filmname im Plex-Format: "Titel (Jahr)"
        movie_name = f"{movie_title} ({year})"
        
        # Erstelle Zielordner und -datei
        target_dir = self.plex_movies_root / movie_name
        target_file = target_dir / "poster.jpg"
        
        # Prüfe ob Datei bereits existiert
        if target_file.exists() and not overwrite:
            self.log(f"Cover existiert bereits: {target_file}")
            self.log("Setze overwrite=True zum Überschreiben")
            return None
        
        try:
            # Erstelle Zielordner
            target_dir.mkdir(parents=True, exist_ok=True)
            
            self.log(f"Speichere Cover für: {movie_name}")
            self.log(f"Quelle: {cover_path}")
            self.log(f"Ziel: {target_file}")
            
            # Kopiere Cover
            shutil.copy2(cover_path, target_file)
            
            self.log(f"Cover erfolgreich gespeichert: {target_file}")
            return target_file
            
        except Exception as e:
            self.log(f"Fehler beim Speichern des Covers: {e}")
            return None
    
    def log(self, message: str):
        """Loggt eine Nachricht"""
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)

