"""
Merge engine: joins the scene clips of a tape into one film.

dvgrab writes one clip per scene, named after the recording time
(dvgrab-2003.06.14_15-30-00.avi). The clips are sorted by that time, joined with
ffmpeg's concat demuxer and encoded to H.264/AAC in an MP4. Optionally the recording date
is burned in at the start of each scene.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from .media import (
    H264_COMPAT,
    MP4_FASTSTART,
    default_font_file,
    escape_filter_path,
    has_filter,
    popen_kwargs,
    probe,
    run_ffmpeg,
)

# Clip formats dvgrab and other capture tools write
SPLIT_EXTENSIONS = (".avi", ".dv", ".mov", ".mkv", ".mp4", ".m2t")
_TIMESTAMP_IN_NAME = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})_(\d{2})-(\d{2})-(\d{2})")
_TIMECODE_IN_NAME = re.compile(r"(\d{2})[.:](\d{2})[.:](\d{2})(?:[.:](\d{2,3}))?")

DEFAULT_OVERLAY_SECONDS = 4


def find_split_files(splits_dir: Path) -> List[Path]:
    """
    Non-empty clips in the folder, each once.

    One pass over the folder with a case-insensitive extension check: globbing *.avi and
    *.AVI separately listed every clip twice where file names ignore case (Windows), and
    the film then contained each scene twice.
    """
    if not splits_dir.is_dir():
        return []
    found = []
    for entry in splits_dir.iterdir():
        if entry.name.startswith(".") or entry.suffix.lower() not in SPLIT_EXTENSIONS:
            continue
        try:
            if entry.is_file() and entry.stat().st_size > 0:
                found.append(entry)
        except OSError:
            continue
    return found


def timestamp_from_filename(filename: str) -> Optional[datetime]:
    """Recording time from a dvgrab name such as dvgrab-2001.06.30_01-42-02.avi."""
    match = _TIMESTAMP_IN_NAME.search(filename)
    if not match:
        return None
    year, month, day, hour, minute, second = (int(g) for g in match.groups())
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    except ValueError:
        return None


def _timecode_seconds(filename: str) -> Optional[float]:
    """Seconds from a timecode-style name such as capture-001-00.12.30.10.avi."""
    match = _TIMECODE_IN_NAME.search(filename)
    if not match:
        return None
    hours, minutes, seconds = (int(match.group(i)) for i in (1, 2, 3))
    if hours >= 24 or minutes >= 60 or seconds >= 60:
        return None
    frames = int(match.group(4) or 0)
    return hours * 3600 + minutes * 60 + seconds + frames / 30.0


def sort_splits(split_files: Sequence[Path]) -> List[Tuple[Path, Optional[datetime]]]:
    """Clips in recording order: by the time in the name, else timecode, else file time."""
    keyed = []
    for path in split_files:
        stamp = timestamp_from_filename(path.name)
        if stamp is not None:
            key = (0, stamp.timestamp(), path.name)
        else:
            timecode = _timecode_seconds(path.name)
            if timecode is not None:
                key = (1, timecode, path.name)
            else:
                key = (2, path.stat().st_mtime, path.name)
        keyed.append((key, path, stamp))
    keyed.sort(key=lambda item: item[0])
    return [(path, stamp) for _, path, stamp in keyed]


def _concat_line(path: Path) -> str:
    # The concat demuxer takes single-quoted paths; a quote inside is written as '\''
    escaped = str(path.resolve()).replace("'", "'\\''")
    return f"file '{escaped}'\n"


class MergeEngine:
    """Joins clips into one film."""

    def __init__(self, ffmpeg_path: Path, log_callback: Optional[Callable[[str], None]] = None):
        self.ffmpeg_path = ffmpeg_path
        self.log_callback = log_callback
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------ public API

    def merge_splits(
        self,
        splits_dir: Path,
        output_path: Path,
        timestamp_overlay: bool = True,
        overlay_seconds: float = DEFAULT_OVERLAY_SECONDS,
        progress: Optional[Callable[[float], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Optional[Path]:
        """
        Joins all clips in splits_dir into output_path (MP4) in recording order.

        With timestamp_overlay, the recording date and time from each clip's name is shown
        for overlay_seconds at the start of that clip. Returns the output path or None.
        """
        split_files = find_split_files(splits_dir)
        if not split_files:
            self.log(f"No clips found in {splits_dir}.")
            return None

        ordered = sort_splits(split_files)
        self.log(f"Merging {len(ordered)} clip(s) from {splits_dir}:")
        for path, stamp in ordered:
            self.log(f"  {path.name}" + (f"  recorded {stamp:%Y-%m-%d %H:%M:%S}" if stamp else ""))

        durations = self._durations([p for p, _ in ordered])
        total = sum(d for d in durations if d) or None

        overlay_filter = None
        if timestamp_overlay:
            overlay_filter = self._overlay_filter(ordered, durations, overlay_seconds)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        list_file = output_path.parent / f".{output_path.stem}_concat.txt"
        partial = output_path.with_name(f".{output_path.stem}.partial{output_path.suffix}")
        try:
            list_file.write_text("".join(_concat_line(p) for p, _ in ordered), encoding="utf-8")
            cmd = [
                str(self.ffmpeg_path), "-hide_banner", "-y",
                "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-map", "0:v:0", "-map", "0:a?",
            ]
            if overlay_filter:
                cmd += ["-vf", overlay_filter]
            # The tape's pixel aspect (4:3 or 16:9) carries over from the DV stream
            cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", *H264_COMPAT]
            cmd += ["-c:a", "aac", "-b:a", "192k", *MP4_FASTSTART, str(partial)]

            self.log("Encoding the film with ffmpeg (H.264/AAC)...")
            code, tail = run_ffmpeg(cmd, duration=total, progress=progress, log=self.log, stop_event=stop_event)
            if code != 0 and overlay_filter:
                self.log("Merging with the date overlay failed; merging again without it.")
                cmd_plain = [c for c in cmd]
                index = cmd_plain.index("-vf")
                del cmd_plain[index:index + 2]
                code, tail = run_ffmpeg(cmd_plain, duration=total, progress=progress, log=self.log, stop_event=stop_event)
            if code != 0:
                self.log(f"Merge failed. ffmpeg said: {tail or 'nothing'}")
                partial.unlink(missing_ok=True)
                return None
            partial.replace(output_path)
            self.log(f"Merge done: {output_path}")
            return output_path
        except OSError as e:
            self.log(f"Merge failed: {e}")
            partial.unlink(missing_ok=True)
            return None
        finally:
            list_file.unlink(missing_ok=True)

    def merge_videos(self, video_paths: List[Path], output_path: Path, progress=None) -> Optional[Path]:
        """Joins finished (upscaled) MP4 films into one; re-encodes, since sizes may differ."""
        videos = [v for v in video_paths if v.exists()]
        missing = [v for v in video_paths if not v.exists()]
        for v in missing:
            self.log(f"Video not found, left out: {v}")
        if not videos:
            self.log("No videos to merge.")
            return None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if len(videos) == 1:
            shutil.copy2(videos[0], output_path)
            return output_path

        infos = [probe(v, self.ffmpeg_path) for v in videos]
        total = sum(i.duration for i in infos if i and i.duration) or None
        # Scale everything to the first film's size so concat gets one format
        first = next((i for i in infos if i and i.width), None)
        list_file = output_path.parent / f".{output_path.stem}_concat.txt"
        try:
            list_file.write_text("".join(_concat_line(v) for v in videos), encoding="utf-8")
            cmd = [str(self.ffmpeg_path), "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file)]
            if first:
                cmd += ["-vf", f"scale={first.width}:{first.height}:force_original_aspect_ratio=decrease,"
                               f"pad={first.width}:{first.height}:(ow-iw)/2:(oh-ih)/2,setsar=1"]
            cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", *H264_COMPAT,
                    "-c:a", "aac", "-b:a", "192k", *MP4_FASTSTART, str(output_path)]
            self.log(f"Merging {len(videos)} videos...")
            code, tail = run_ffmpeg(cmd, duration=total, progress=progress, log=self.log)
            if code != 0:
                self.log(f"Merge failed. ffmpeg said: {tail or 'nothing'}")
                return None
            self.log(f"Merge done: {output_path}")
            return output_path
        finally:
            list_file.unlink(missing_ok=True)

    # ------------------------------------------------------------------ helpers

    def _durations(self, paths: Sequence[Path]) -> List[Optional[float]]:
        result = []
        for path in paths:
            info = probe(path, self.ffmpeg_path)
            result.append(info.duration if info else None)
        return result

    def _overlay_filter(
        self,
        ordered: Sequence[Tuple[Path, Optional[datetime]]],
        durations: Sequence[Optional[float]],
        seconds: float,
    ) -> Optional[str]:
        """drawtext filters that show each clip's recording time at its start."""
        if not any(stamp for _, stamp in ordered):
            self.log("The clip names carry no recording time; no date overlay.")
            return None
        if not has_filter(self.ffmpeg_path, "drawtext"):
            self.log(
                "The date overlay is skipped: this ffmpeg has no drawtext filter (it was built "
                "without libfreetype). Install a full ffmpeg build to get the overlay."
            )
            return None
        font = default_font_file()
        font_arg = f":fontfile='{escape_filter_path(font)}'" if font else ""
        parts = []
        start = 0.0
        for (path, stamp), duration in zip(ordered, durations):
            if stamp is not None:
                text = stamp.strftime("%Y-%m-%d %H\\:%M\\:%S")
                end = start + max(0.5, float(seconds))
                parts.append(
                    f"drawtext=text='{text}'{font_arg}:fontsize=h/24:x=w/40:y=h-th-h/30"
                    f":fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=6"
                    f":enable='between(t,{start:.3f},{end:.3f})'"
                )
            if duration is None:
                # Without a duration the later starts are unknown; stop here
                self.log(f"Could not read the length of {path.name}; later dates are left out.")
                break
            start += duration
        return ",".join(parts) if parts else None

    def log(self, message: str):
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)


def ffmpeg_version(ffmpeg_path: Path) -> Optional[str]:
    """First line of `ffmpeg -version`, for logs and bug reports."""
    try:
        result = subprocess.run([str(ffmpeg_path), "-version"], capture_output=True, text=True, timeout=15, **popen_kwargs())
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (result.stdout.splitlines() or [""])[0] or None
