"""
Upscale engine: turns the merged tape (720x576 or 720x480) into an HD or 4K film.

Two backends, chosen by the profile:
- realesrgan: the Real-ESRGAN video script (PyTorch) upscales 2x; for 4x profiles ffmpeg
  scales that result on to 4K.
- ffmpeg: plain Lanczos scaling, fast, no AI.

Either way the result has square pixels and the tape's display aspect: a 4:3 tape becomes
2880x2160 in the 4x profiles, a 16:9 tape 3840x2160. DV is interlaced; unless the profile
says otherwise it is deinterlaced (bwdif) before scaling, so the combing is not enlarged.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .media import (
    H264_COMPAT,
    MP4_FASTSTART,
    VideoInfo,
    audio_args_for_mp4,
    display_geometry,
    popen_kwargs,
    probe,
    run_ffmpeg,
)

# Size each scale factor fits into
BOXES = {4: (3840, 2160), 2: (1920, 1080)}
_TQDM_PERCENT = re.compile(r"inference:\s+(\d{1,3})%")
_INTERLACED_ORDERS = {"tt", "bb", "tb", "bt"}


def deinterlace_filter(info: Optional[VideoInfo], setting: Any = True) -> Optional[str]:
    """
    bwdif filter for interlaced sources, or None.

    setting: True/"auto" deinterlaces DV-sized and interlaced-flagged video, False never.
    DV is bottom field first; the merged MP4 no longer carries that flag, so DV-sized video
    is treated as bottom field first.
    """
    if setting in (False, "off", "false", "no", None):
        return None
    if info is None:
        return None
    if info.field_order in ("tt", "tb"):
        parity = "tff"
    elif info.field_order in ("bb", "bt"):
        parity = "bff"
    elif info.is_dv_resolution:
        parity = "bff"
    else:
        return None
    return f"bwdif=mode=send_frame:parity={parity}:deint=all"


def realesrgan_available() -> Optional[str]:
    """None if the PyTorch Real-ESRGAN backend can run here, else the reason why not."""
    if getattr(sys, "frozen", False):
        return "Real-ESRGAN (PyTorch) is not part of the desktop app; use an ffmpeg profile."
    import importlib.util

    missing = [name for name in ("torch", "torchvision", "basicsr", "cv2", "ffmpeg")
               if importlib.util.find_spec(name) is None]
    if missing:
        return ("Real-ESRGAN needs PyTorch and its helpers (missing: " + ", ".join(missing)
                + "). Install them with: pip install -r requirements.txt")
    return None


class UpscaleEngine:
    """Runs one upscaling job."""

    def __init__(
        self,
        realesrgan_path: Path,
        ffmpeg_path: Optional[Path] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        python_executable: Optional[str] = None,
    ):
        self.realesrgan_path = Path(realesrgan_path)
        self.ffmpeg_path = ffmpeg_path
        self.log_callback = log_callback
        self.python = python_executable or sys.executable
        self.logger = logging.getLogger(__name__)
        self.process: Optional[subprocess.Popen] = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------ public API

    def upscale(
        self,
        input_path: Path,
        output_path: Path,
        profile: Dict[str, Any],
        progress_hook: Optional[Callable[[int], None]] = None,
    ) -> bool:
        """Upscales input_path into output_path (MP4). Returns True on success."""
        # Real-ESRGAN runs in its own folder; relative paths would point elsewhere there
        input_path = Path(input_path).resolve()
        output_path = Path(output_path).resolve()
        if not input_path.exists():
            self.log(f"Input not found: {input_path}")
            return False
        if not self.ffmpeg_path or not Path(self.ffmpeg_path).exists():
            self.log("ffmpeg not found. Install ffmpeg or set its path in the settings.")
            return False
        if not profile:
            self.log("Upscaling profile not found; check upscaling.profiles in the settings.")
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)
        info = probe(input_path, self.ffmpeg_path)
        if info is None or not info.width:
            self.log(f"ffprobe cannot read {input_path}; is it a complete video?")
            return False
        self.log(
            f"Source: {info.width}x{info.height}, display aspect {info.dar.numerator}:{info.dar.denominator}, "
            f"{(info.duration or 0):.0f} s, audio {info.audio_codec or 'none'}"
        )

        backend = profile.get("backend", "realesrgan")
        partial = output_path.with_name(f".{output_path.stem}.partial{output_path.suffix}")
        try:
            if backend == "ffmpeg":
                ok = self._ffmpeg_upscale(input_path, partial, profile, info, progress_hook)
            else:
                ok = self._realesrgan_upscale(input_path, partial, profile, info, progress_hook)
            if not ok:
                return False
            partial.replace(output_path)
            result = probe(output_path, self.ffmpeg_path)
            if result:
                self.log(f"Upscaled film: {output_path} ({result.width}x{result.height})")
            if progress_hook:
                progress_hook(100)
            return True
        finally:
            partial.unlink(missing_ok=True)

    def stop(self) -> None:
        """Stops a running job."""
        self._stop.set()
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    # ------------------------------------------------------------------ ffmpeg backend

    def _scale_filters(self, info: VideoInfo, scale_factor: Any, deinterlace: Any) -> List[str]:
        filters = []
        deint = deinterlace_filter(info, deinterlace)
        if deint:
            filters.append(deint)
        try:
            factor = int(scale_factor)
        except (TypeError, ValueError):
            factor = 4
        if factor in BOXES:
            width, height = display_geometry(info.dar, *BOXES[factor])
        else:
            # Any other factor: that many times the display width, square pixels
            square_width = info.height * info.dar
            width, height = display_geometry(info.dar, int(square_width * factor), int(info.height * factor))
        filters.append(f"scale={width}:{height}:flags=lanczos")
        filters.append("setsar=1")
        return filters

    def _encoder_args(self, profile: Dict[str, Any], default_preset: str = "veryfast") -> List[str]:
        options = dict(profile.get("encoder_options") or {})
        args = ["-c:v", str(profile.get("encoder", "libx264"))]
        args += ["-preset", str(options.pop("preset", default_preset))]
        args += ["-crf", str(options.pop("crf", 18))]
        for key, value in options.items():
            args += [f"-{key}", str(value)]
        return args + H264_COMPAT

    def _ffmpeg_upscale(self, input_path, output_path, profile, info, progress_hook) -> bool:
        filters = self._scale_filters(info, profile.get("scale_factor", 4), profile.get("deinterlace", True))
        cmd = [
            str(self.ffmpeg_path), "-hide_banner", "-y",
            "-i", str(input_path),
            "-map", "0:v:0", "-map", "0:a?",
            "-vf", ",".join(filters),
            *self._encoder_args(profile),
            *audio_args_for_mp4(info),
            *MP4_FASTSTART,
            str(output_path),
        ]
        self.log(f"ffmpeg upscaling: {', '.join(filters)}")
        code, _ = run_ffmpeg(
            cmd,
            duration=info.duration,
            progress=(lambda f: progress_hook(int(f * 99))) if progress_hook else None,
            log=self.log,
            stop_event=self._stop,
        )
        return code == 0 and output_path.exists()

    # ------------------------------------------------------------------ Real-ESRGAN backend

    def _realesrgan_upscale(self, input_path, output_path, profile, info, progress_hook) -> bool:
        reason = realesrgan_available()
        if reason:
            self.log(reason)
            return False
        if not self.realesrgan_path.exists():
            self.log(f"Real-ESRGAN not found: {self.realesrgan_path}")
            return False

        work_dir = output_path.parent / f".realesrgan-{os.getpid()}"
        shutil.rmtree(work_dir, ignore_errors=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            scale_factor = profile.get("scale_factor", 4)
            options = profile.get("encoder_options") or {}
            final_in_script = int(scale_factor) <= 2
            deint = deinterlace_filter(info, profile.get("deinterlace", True))
            cmd = [
                self.python, str(self.realesrgan_path),
                "-i", str(input_path),
                "-n", str(profile.get("model", "RealESRGAN_x4plus")),
                "-s", "2",
                "-o", str(work_dir),
                "--tile", str(profile.get("tile_size", 400)),
                "--tile_pad", str(profile.get("tile_pad", 10)),
                "--num_process_per_gpu", "1",
                "--ffmpeg_bin", str(self.ffmpeg_path),
                # The 2x result is the final film; for 4x it is an intermediate step
                "--crf", str(options.get("crf", 18) if final_in_script else 14),
                "--x264_preset", str(options.get("preset", "slow") if final_in_script else "veryfast"),
            ]
            if deint:
                cmd += ["--deinterlace", deint]
            if profile.get("face_enhance"):
                cmd.append("--face_enhance")
            self.log("Starting Real-ESRGAN (2x). The first run downloads the model weights.")
            self.log(f"Command: {' '.join(cmd)}")

            stage_share = 0.85 if not final_in_script else 0.97
            if not self._run_realesrgan(cmd, progress_hook, stage_share):
                return False

            produced = sorted(work_dir.glob("*.mp4"))
            if not produced:
                self.log(f"Real-ESRGAN finished without writing a video into {work_dir}.")
                return False
            intermediate = produced[0]
            self.log("Real-ESRGAN 2x done.")

            if final_in_script:
                return self._fix_aspect(intermediate, output_path, info.dar)

            # The intermediate lost the tape's pixel aspect; the size comes from the source
            width, height = display_geometry(info.dar, *BOXES.get(int(scale_factor), (3840, 2160)))
            filters = [f"scale={width}:{height}:flags=lanczos", "setsar=1"]
            inter_info = probe(intermediate, self.ffmpeg_path)
            cmd = [
                str(self.ffmpeg_path), "-hide_banner", "-y",
                "-i", str(intermediate),
                "-map", "0:v:0", "-map", "0:a?",
                "-vf", ",".join(filters),
                *self._encoder_args(profile),
                *audio_args_for_mp4(inter_info),
                *MP4_FASTSTART,
                str(output_path),
            ]
            self.log(f"Scaling to {width}x{height} with ffmpeg...")
            code, _ = run_ffmpeg(
                cmd,
                duration=info.duration,
                progress=(lambda f: progress_hook(int(85 + f * 14))) if progress_hook else None,
                log=self.log,
                stop_event=self._stop,
            )
            return code == 0 and output_path.exists()
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _run_realesrgan(self, cmd: List[str], progress_hook, stage_share: float) -> bool:
        """Runs the script; stdout and stderr share one pipe so neither can fill up and block."""
        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(self.realesrgan_path.parent),
            env=env,
            **popen_kwargs(),
        )
        tail: List[str] = []
        last_percent = -1
        assert self.process.stdout is not None
        for line in self.process.stdout:  # tqdm's \r updates arrive as separate lines
            line = line.strip()
            if not line:
                continue
            match = _TQDM_PERCENT.search(line)
            if match:
                percent = int(match.group(1))
                if percent != last_percent:
                    last_percent = percent
                    if progress_hook:
                        progress_hook(int(percent * stage_share))
                    if percent % 10 == 0:
                        self.log(f"Real-ESRGAN: {percent}%")
                continue
            tail.append(line)
            del tail[:-40]
        code = self.process.wait()
        if code != 0:
            self.log(f"Real-ESRGAN failed (exit code {code}):\n" + "\n".join(tail[-15:]))
            hint = _realesrgan_hint("\n".join(tail))
            if hint:
                self.log(hint)
            return False
        return True

    def _fix_aspect(self, source: Path, output_path: Path, dar: Fraction) -> bool:
        """Sets the pixel aspect in the H.264 stream so the 2x film shows as 4:3 or 16:9."""
        info = probe(source, self.ffmpeg_path)
        if info is None or not info.width:
            shutil.copy2(source, output_path)
            return True
        sar = (dar * info.height / info.width).limit_denominator(1000)
        cmd = [
            str(self.ffmpeg_path), "-hide_banner", "-y", "-i", str(source),
            "-map", "0", "-c", "copy",
            "-bsf:v", f"h264_metadata=sample_aspect_ratio={sar.numerator}/{sar.denominator}",
            *MP4_FASTSTART, str(output_path),
        ]
        code, _ = run_ffmpeg(cmd, log=self.log)
        if code != 0:
            self.log("Could not set the aspect ratio; keeping the Real-ESRGAN output as it is.")
            shutil.copy2(source, output_path)
        return True

    def log(self, message: str):
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)


def _realesrgan_hint(output: str) -> Optional[str]:
    """A plain-language next step for the usual Real-ESRGAN failures."""
    text = output.lower()
    if "no module named 'torch'" in text or 'no module named "torch"' in text:
        return "PyTorch is missing. Install the upscaling packages: pip install -r requirements.txt"
    if "no module named 'basicsr'" in text:
        return "basicsr is missing. Install the upscaling packages: pip install -r requirements.txt"
    if "out of memory" in text:
        return "The GPU ran out of memory. Use a profile with a smaller tile_size (for example 200)."
    if "urlopen error" in text or "connection" in text and "weights" in text:
        return "Downloading the model weights failed. Check the internet connection and try again."
    return None
