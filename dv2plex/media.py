"""
ffmpeg and ffprobe helpers shared by merge, upscale, export and the demo.

- probe(): the facts about a video that the steps need (size, aspect, codecs, duration)
- display_geometry(): output size with square pixels, fitted into a box, aspect kept
- run_ffmpeg(): runs ffmpeg, reports progress from its -progress output, keeps stderr short
- has_filter(): whether this ffmpeg build has a filter (drawtext needs libfreetype)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Callable, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Encoder settings every H.264 output needs to play on TVs, browsers and Plex clients.
# DV from NTSC tapes is 4:1:1; without this libx264 writes High 4:2:2, which most players refuse.
H264_COMPAT = ["-pix_fmt", "yuv420p"]
# Index at the start of the file: the Video Player and Plex can start playing before the end loads.
MP4_FASTSTART = ["-movflags", "+faststart"]
# Audio codecs that can be copied into MP4 as they are
MP4_AUDIO_COPY = {"aac", "mp3", "ac3", "eac3", "alac"}

if sys.platform == "win32":
    # Keeps ffmpeg from opening a console window next to the desktop app
    _NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
else:
    _NO_WINDOW = 0


def popen_kwargs() -> dict:
    """Extra Popen/run arguments for child processes (no console windows on Windows)."""
    return {"creationflags": _NO_WINDOW} if _NO_WINDOW else {}


def ffprobe_for(ffmpeg_path: Optional[Path | str]) -> str:
    """ffprobe next to the given ffmpeg, else the one on PATH."""
    if ffmpeg_path:
        ffmpeg = Path(ffmpeg_path)
        name = "ffprobe.exe" if ffmpeg.suffix.lower() == ".exe" else "ffprobe"
        candidate = ffmpeg.with_name(name)
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ffprobe") or "ffprobe"


@dataclass
class VideoInfo:
    """What ffprobe says about a video file."""

    duration: Optional[float] = None
    width: int = 0
    height: int = 0
    sar: Fraction = Fraction(1, 1)
    codec: str = ""
    pix_fmt: str = ""
    field_order: str = ""
    fps: Optional[float] = None
    audio_codec: Optional[str] = None
    nb_frames: Optional[int] = None

    @property
    def dar(self) -> Fraction:
        """Display aspect ratio (width x pixel aspect / height)."""
        if not self.width or not self.height:
            return Fraction(4, 3)
        return Fraction(self.width, self.height) * self.sar

    @property
    def is_dv_resolution(self) -> bool:
        """PAL (720x576) or NTSC (720x480) DV frame size."""
        return self.width == 720 and self.height in (576, 480)


def _fraction(value: Optional[str], default: Fraction) -> Fraction:
    if not value or value in ("0:1", "N/A", "0/0", "1:0"):
        return default
    try:
        num, den = value.replace(":", "/").split("/")
        result = Fraction(int(num), int(den))
        return result if result > 0 else default
    except (ValueError, ZeroDivisionError):
        return default


def probe(path: Path | str, ffmpeg_path: Optional[Path | str] = None) -> Optional[VideoInfo]:
    """Reads size, aspect, codecs and duration of a video. None if ffprobe fails."""
    cmd = [
        ffprobe_for(ffmpeg_path),
        "-v", "error",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,sample_aspect_ratio,"
        "pix_fmt,field_order,avg_frame_rate,nb_frames,duration",
        "-of", "json",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, **popen_kwargs())
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("ffprobe failed for %s: %s", path, e)
        return None
    if result.returncode != 0:
        logger.warning("ffprobe failed for %s: %s", path, result.stderr.strip()[-300:])
        return None
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None

    info = VideoInfo()
    duration = (data.get("format") or {}).get("duration")
    for stream in data.get("streams") or []:
        kind = stream.get("codec_type")
        if kind == "video" and not info.codec:
            info.codec = stream.get("codec_name", "") or ""
            info.width = int(stream.get("width") or 0)
            info.height = int(stream.get("height") or 0)
            info.sar = _fraction(stream.get("sample_aspect_ratio"), Fraction(1, 1))
            info.pix_fmt = stream.get("pix_fmt", "") or ""
            info.field_order = stream.get("field_order", "") or ""
            rate = _fraction(stream.get("avg_frame_rate"), Fraction(0, 1)) if stream.get("avg_frame_rate") else Fraction(0, 1)
            info.fps = float(rate) if rate else None
            try:
                info.nb_frames = int(stream["nb_frames"]) if stream.get("nb_frames") not in (None, "N/A") else None
            except (TypeError, ValueError):
                info.nb_frames = None
            duration = duration or stream.get("duration")
        elif kind == "audio" and info.audio_codec is None:
            info.audio_codec = stream.get("codec_name") or ""
    try:
        info.duration = float(duration) if duration not in (None, "N/A") else None
    except (TypeError, ValueError):
        info.duration = None
    return info


def even(value: float) -> int:
    """Nearest even integer, at least 2 (H.264 with 4:2:0 needs even sizes)."""
    return max(2, int(round(value / 2.0)) * 2)


def display_geometry(dar: Fraction, max_width: int, max_height: int) -> tuple[int, int]:
    """
    Largest size with square pixels and the given display aspect that fits the box.

    A 4:3 tape in a 3840x2160 box becomes 2880x2160, a 16:9 tape 3840x2160.
    """
    if dar <= 0:
        dar = Fraction(4, 3)
    if Fraction(max_width, max_height) > dar:
        height = max_height
        width = even(max_height * dar)
    else:
        width = max_width
        height = even(max_width / dar)
    return even(width), even(height)


def audio_args_for_mp4(info: Optional[VideoInfo], bitrate: str = "192k") -> List[str]:
    """Copies MP4-compatible audio, converts the rest (DV's PCM) to AAC."""
    if info is not None and info.audio_codec is None:
        return ["-an"]
    if info is not None and info.audio_codec in MP4_AUDIO_COPY:
        return ["-c:a", "copy"]
    return ["-c:a", "aac", "-b:a", bitrate]


@lru_cache(maxsize=16)
def _filters_of(ffmpeg: str) -> frozenset:
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30, **popen_kwargs()
        )
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    names = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        # " T.. drawtext          V->V       Draw text ..."
        if len(parts) >= 3 and "->" in parts[2]:
            names.add(parts[1])
    return frozenset(names)


def has_filter(ffmpeg_path: Path | str, name: str) -> bool:
    """Whether this ffmpeg build has the filter (drawtext needs a build with libfreetype)."""
    return name in _filters_of(str(ffmpeg_path))


def default_font_file() -> Optional[str]:
    """
    A font file for drawtext on systems where ffmpeg has no fontconfig (Windows builds).
    None lets ffmpeg pick its default font.
    """
    candidates: List[str] = []
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        candidates += [os.path.join(windir, "Fonts", name) for name in ("segoeui.ttf", "arial.ttf")]
    elif sys.platform == "darwin":
        candidates += ["/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf"]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def escape_filter_path(path: str) -> str:
    """Escapes a file path for use inside an ffmpeg filter argument (C:/... needs C\\:/...)."""
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


ProgressCallback = Callable[[float], None]


def run_ffmpeg(
    cmd: Sequence[str],
    duration: Optional[float] = None,
    progress: Optional[ProgressCallback] = None,
    log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> tuple[int, str]:
    """
    Runs ffmpeg and returns (exit code, last lines of stderr).

    Progress (0.0 to 1.0) comes from ffmpeg's -progress output on stdout, measured against
    the duration of the input; stderr is drained in a thread so neither pipe can fill up.
    """
    cmd = list(cmd)
    if "-progress" not in cmd:
        # Insert right after the binary, before inputs and outputs
        cmd[1:1] = ["-nostdin", "-progress", "pipe:1", "-nostats"]
    stderr_tail: List[str] = []

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **popen_kwargs(),
    )

    def drain_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            line = line.rstrip()
            if line:
                stderr_tail.append(line)
                if len(stderr_tail) > 60:
                    del stderr_tail[:-60]

    reader = threading.Thread(target=drain_stderr, daemon=True)
    reader.start()

    last_reported = -1.0
    assert process.stdout is not None
    for line in process.stdout:
        if stop_event is not None and stop_event.is_set():
            process.terminate()
            break
        key, _, value = line.strip().partition("=")
        if key in ("out_time_us", "out_time_ms") and duration and progress:
            try:
                seconds = int(value) / 1_000_000
            except ValueError:
                continue
            fraction = max(0.0, min(1.0, seconds / duration))
            if fraction - last_reported >= 0.01:
                last_reported = fraction
                progress(fraction)
    returncode = process.wait()
    reader.join(timeout=5)
    if progress and returncode == 0:
        progress(1.0)
    tail = "\n".join(_relevant_errors(stderr_tail)[-12:])
    if returncode != 0 and log:
        log(f"ffmpeg exited with code {returncode}: {tail or '(no output)'}")
    return returncode, tail


def _relevant_errors(lines: List[str]) -> List[str]:
    """Drops the DV decoder noise that hides the real error."""
    noise = ("Concealing bitstream errors", "AC EOB marker is absent", "Last message repeated")
    return [line for line in lines if not any(n in line for n in noise)]
