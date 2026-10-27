"""
Plex exporter: copies a finished film into the Plex movie library.

Plex expects <Library>/<Title (Year)>/<Title (Year)>.mp4, with poster.jpg next to it.
The film is copied under a temporary name and renamed at the end, so Plex never indexes a
half-copied file.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .naming import InvalidName, movie_folder_name, parse_movie_folder_name


class PlexExporter:
    """Copies films and posters into the Plex movie library."""

    def __init__(self, plex_movies_root: Path, log_callback: Optional[Callable[[str], None]] = None):
        self.plex_movies_root = Path(plex_movies_root)
        self.log_callback = log_callback
        self.logger = logging.getLogger(__name__)

    def target_for(self, movie_title: str, year: Optional[str]) -> Path:
        """Where the film for this title and year goes."""
        name = movie_folder_name(movie_title, year, year_required=False)
        return self.plex_movies_root / name / f"{name}.mp4"

    def export_movie(self, source_path: Path, movie_title: str, year: str, overwrite: bool = False) -> Optional[Path]:
        """Exports a film under 'Title (Year)'. Returns the target path or None."""
        return self._export(Path(source_path), movie_title, year, overwrite)

    def export_single_video(
        self,
        source_path: Path,
        movie_title: Optional[str] = None,
        year: Optional[str] = None,
        overwrite: bool = False,
    ) -> Optional[Path]:
        """
        Exports a film; title and year default to those in its path
        (.../DV_Import/Title (Year)/HighRes/...).
        """
        source_path = Path(source_path)
        if movie_title is None or year is None:
            for part in reversed(source_path.parts[:-1]):
                title_guess, year_guess = parse_movie_folder_name(part)
                if year_guess:
                    movie_title = movie_title if movie_title is not None else title_guess
                    year = year if year is not None else year_guess
                    break
        if movie_title is None:
            movie_title = source_path.stem
        return self._export(source_path, movie_title, year or "", overwrite)

    def get_movie_path(self, movie_title: str, year: str) -> Path:
        return self.target_for(movie_title, year)

    def save_cover(self, cover_path: Path, movie_title: str, year: str, overwrite: bool = True) -> Optional[Path]:
        """Saves a cover as poster.jpg in the film's library folder."""
        cover_path = Path(cover_path)
        if not cover_path.exists():
            self.log(f"Cover not found: {cover_path}")
            return None
        try:
            target = self.target_for(movie_title, year).parent / "poster.jpg"
        except InvalidName as e:
            self.log(f"Cover not saved: {e}")
            return None
        if target.exists() and not overwrite:
            self.log(f"Cover already exists: {target}")
            return None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._copy_file(cover_path, target)
            self.log(f"Cover saved: {target}")
            return target
        except OSError as e:
            self.log(f"Could not save the cover: {e}")
            return None

    # ------------------------------------------------------------------ helpers

    def _export(self, source_path: Path, movie_title: str, year: str, overwrite: bool) -> Optional[Path]:
        if not source_path.exists():
            self.log(f"Source file not found: {source_path}")
            return None
        try:
            target_file = self.target_for(movie_title, year)
        except InvalidName as e:
            self.log(f"Export not possible: {e}")
            return None
        target_dir = target_file.parent

        if target_file.exists() and not overwrite:
            self.log(f"Already in the library, not overwritten: {target_file}")
            return None

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            needed = source_path.stat().st_size
            free = shutil.disk_usage(target_dir).free
            if needed > free:
                self.log(
                    f"Not enough space in {target_dir}: the film needs {needed / 1e9:.1f} GB, "
                    f"{free / 1e9:.1f} GB are free."
                )
                return None

            self.log(f"Exporting {target_dir.name}")
            self.log(f"  from {source_path}")
            self.log(f"  to   {target_file}")
            self._copy_file(source_path, target_file)

            source_poster = source_path.parent / "poster.jpg"
            if source_poster.exists():
                try:
                    self._copy_file(source_poster, target_dir / "poster.jpg")
                    self.log(f"Poster copied: {target_dir / 'poster.jpg'}")
                except OSError as e:
                    self.log(f"Warning: could not copy the poster: {e}")

            self.log(f"Export done: {target_file}")
            return target_file
        except (OSError, RuntimeError) as e:
            self.log(f"Export failed: {e}")
            return None

    def _copy_file(self, source_path: Path, target_file: Path) -> None:
        """
        Copies to a temporary name next to the target, then renames.

        On Linux and macOS `cp -p` runs as its own process (large films, network shares);
        elsewhere shutil.copy2.
        """
        source_path = Path(source_path)
        target_file = Path(target_file)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        partial = target_file.with_name(f".{target_file.name}.partial")
        try:
            if os.name == "posix" and shutil.which("cp"):
                result = subprocess.run(["cp", "-p", str(source_path), str(partial)], capture_output=True, text=True)
                if result.returncode != 0:
                    stderr = (result.stderr or result.stdout or "").strip()
                    raise RuntimeError(f"cp failed (code {result.returncode}): {stderr}")
            else:
                shutil.copy2(source_path, partial)
            os.replace(partial, target_file)
        finally:
            if partial.exists():
                partial.unlink()

    def log(self, message: str):
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)
