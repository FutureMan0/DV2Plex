"""
A light poster: one well-exposed frame of the film with its title and year.

Used when the full poster generator (rembg cut-out, Playwright rendering) is not installed,
in the desktop app and in the demo. Needs ffmpeg; with Pillow the poster gets the title,
without it the frame alone becomes the poster.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional, Tuple

from .media import popen_kwargs, probe

logger = logging.getLogger(__name__)

PAPER = (246, 243, 236)
INK = (31, 35, 40)
MUTED = (89, 99, 110)
ACCENT = (154, 91, 0)


def _extract(ffmpeg: str, video: Path, seconds: float, target: Path) -> bool:
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{seconds:.2f}", "-i", str(video),
        # Deinterlace and square the pixels, so the frame looks like the film does
        "-vf", "bwdif=mode=send_frame:deint=interlaced,scale=iw*sar:ih,setsar=1",
        "-frames:v", "1", "-q:v", "2", str(target),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, **popen_kwargs())
    return result.returncode == 0 and target.exists() and target.stat().st_size > 0


def _score(path: Path) -> float:
    """Prefers frames that are neither dark nor flat."""
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return 0.0
    with Image.open(path) as image:
        stat = ImageStat.Stat(image.convert("L"))
    mean, spread = stat.mean[0], stat.stddev[0]
    return spread * (1.0 if 50 < mean < 210 else 0.4)


def _font(size: int):
    from PIL import ImageFont

    for name in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _fit_lines(draw, text: str, font_size: int, max_width: int) -> Tuple[list, object]:
    """Wraps the title onto at most three lines, shrinking the font if needed."""
    while font_size >= 28:
        font = _font(font_size)
        words, lines, line = text.split(), [], ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width:
                line = candidate
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)
        if len(lines) <= 3 and all(draw.textlength(item, font=font) <= max_width for item in lines):
            return lines, font
        font_size -= 6
    font = _font(28)
    return [text[:40]], font


def make_simple_poster(
    video_path: Path,
    title: str,
    year: Optional[str],
    output_path: Path,
    ffmpeg_path: Path | str = "ffmpeg",
    size: Tuple[int, int] = (1000, 1500),
    log: Optional[Callable[[str], None]] = None,
) -> Optional[Path]:
    """Writes poster.jpg for the film. Returns the path, or None if no frame could be read."""
    say = log or logger.info
    ffmpeg = str(ffmpeg_path)
    info = probe(video_path, ffmpeg)
    duration = (info.duration if info and info.duration else 0.0) or 0.0
    points = [duration * f for f in (0.25, 0.4, 0.55, 0.7)] if duration > 1 else [0.0]

    with tempfile.TemporaryDirectory(prefix="dv2plex-poster-") as tmp:
        frames = []
        for index, seconds in enumerate(points):
            target = Path(tmp) / f"frame_{index}.png"
            if _extract(ffmpeg, video_path, seconds, target):
                frames.append(target)
        if not frames:
            say(f"Poster: no frame could be read from {video_path.name}.")
            return None
        best = max(frames, key=_score)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            from PIL import Image, ImageDraw
        except ImportError:
            # No Pillow: the frame itself, cropped to poster shape by ffmpeg
            width, height = size
            cmd = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(best),
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
                "-q:v", "2", str(output_path),
            ]
            subprocess.run(cmd, capture_output=True, timeout=120, **popen_kwargs())
            say(f"Poster (frame only; install Pillow for the title): {output_path}")
            return output_path if output_path.exists() else None

        width, height = size
        margin = width // 12
        poster = Image.new("RGB", size, PAPER)
        draw = ImageDraw.Draw(poster)

        with Image.open(best) as frame:
            frame = frame.convert("RGB")
            box_w = width - 2 * margin
            box_h = int(height * 0.58)
            scale = max(box_w / frame.width, box_h / frame.height)
            resized = frame.resize((max(1, int(frame.width * scale)), max(1, int(frame.height * scale))), Image.LANCZOS)
            left = (resized.width - box_w) // 2
            top = (resized.height - box_h) // 2
            photo = resized.crop((left, top, left + box_w, top + box_h))
        poster.paste(photo, (margin, margin))
        draw.rectangle([margin - 1, margin - 1, margin + box_w, margin + box_h], outline=MUTED, width=2)

        # Crop marks in the corners, like a drafting sheet
        mark = margin // 2
        for x, y, dx, dy in ((mark, mark, 1, 1), (width - mark, mark, -1, 1), (mark, height - mark, 1, -1),
                             (width - mark, height - mark, -1, -1)):
            draw.line([(x, y), (x + dx * 28, y)], fill=MUTED, width=2)
            draw.line([(x, y), (x, y + dy * 28)], fill=MUTED, width=2)

        text_top = margin + box_h + margin
        lines, font = _fit_lines(draw, title.strip() or "Untitled", 96, width - 2 * margin)
        y = text_top
        for line in lines:
            draw.text((margin, y), line, font=font, fill=INK)
            y += int(font.size * 1.15) if hasattr(font, "size") else 60
        small = _font(34)
        draw.text((margin, y + 18), (year or "").strip() or "—", font=small, fill=ACCENT)
        draw.text((margin, height - margin - 34), "DIGITIZED FROM MINIDV", font=_font(26), fill=MUTED)

        poster.save(output_path, "JPEG", quality=92)
    say(f"Poster written: {output_path}")
    return output_path
