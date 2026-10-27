"""
Demo mode: DV2Plex without a camera.

`python -m dv2plex --demo` opens the normal interface on a separate demo workspace whose
"camera" is the simulated dvgrab (dv2plex/fake_dvgrab.py). Everything after the capture is
the real code: merge, date overlay, upscaling, poster, Plex export.

`python -m dv2plex --demo-run` runs the whole chain once without a window and prints a
report; the end-to-end test (dv2plex/test_e2e_demo.py) does the same.

The demo keeps its settings in its own folder (DV2PLEX_HOME), so it never touches the
settings, import folder or Plex library of a real installation.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

DEMO_PROFILE = "ffmpeg_hd"
DEFAULT_DEMO_DIR = Path.home() / "DV2Plex-Demo"


def fake_dvgrab_command() -> List[str]:
    """How to start the simulated dvgrab from this Python or this packaged app."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--fake-dvgrab"]
    return [sys.executable, "-m", "dv2plex.fake_dvgrab"]


def demo_settings(home: Path) -> Dict[str, Dict[str, object]]:
    """Settings that make the demo workspace use the simulated camera."""
    return {
        "paths": {
            "dv_import_root": str(home / "DV_Import"),
            "plex_movies_root": str(home / "PlexMovies"),
            "dvgrab_path": fake_dvgrab_command(),
        },
        "device": {"firewire_device": "0"},
        "capture": {
            "use_sudo": False,
            "rewind_seconds": 3,
            "auto_postprocess": True,
            "auto_upscale": True,
            "auto_export": True,
        },
        "upscaling": {"default_profile": DEMO_PROFILE},
        "cover": {"poster_engine": "simple"},
        "update": {"enabled": False},
        "ui": {"setup_done": True},
        "demo": {"enabled": True},
    }


def prepare_demo_home(home: Optional[Path] = None) -> Path:
    """
    Points DV2Plex at the demo workspace (DV2PLEX_HOME) and writes its settings.

    Must run before dv2plex.config is used. Returns the workspace folder.
    """
    home = Path(home or DEFAULT_DEMO_DIR).expanduser().resolve()
    (home / "config").mkdir(parents=True, exist_ok=True)
    os.environ["DV2PLEX_HOME"] = str(home)

    import dv2plex.config as config_module

    config_module.CONFIG_DIR = home / "config"
    settings_file = home / "config" / config_module.SETTINGS_FILE_NAME
    current: Dict[str, Dict[str, object]] = {}
    if settings_file.is_file():
        try:
            current = json.loads(settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
    for section, values in demo_settings(home).items():
        current.setdefault(section, {}).update(values)
    settings_file.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    return home


def is_demo(config) -> bool:
    return bool(config.get("demo.enabled", False))


@dataclass
class DemoReport:
    """What the end-to-end run produced, and how long each step took."""

    ok: bool = False
    steps: List[Dict[str, object]] = field(default_factory=list)
    checks: List[Dict[str, object]] = field(default_factory=list)
    files: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None

    def step(self, name: str, started: float, ok: bool, detail: str = "") -> None:
        self.steps.append({"step": name, "ok": ok, "seconds": round(time.time() - started, 1), "detail": detail})

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})

    def text(self) -> str:
        lines = ["DV2Plex end-to-end demo run", ""]
        for s in self.steps:
            lines.append(f"  {'ok  ' if s['ok'] else 'FAIL'} {s['step']:<10} {s['seconds']:>6.1f} s  {s['detail']}")
        lines.append("")
        for c in self.checks:
            lines.append(f"  {'ok  ' if c['ok'] else 'FAIL'} {c['check']}: {c['detail']}")
        if self.files:
            lines.append("")
            for key, value in self.files.items():
                lines.append(f"  {key}: {value}")
        if self.error:
            lines += ["", f"  Error: {self.error}"]
        lines += ["", "RESULT: " + ("PASS" if self.ok else "FAIL")]
        return "\n".join(lines)


def _wait_for(condition: Callable[[], bool], timeout: float, interval: float = 0.25) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return condition()


def run_pipeline(
    title: str = "Demo Tape",
    year: str = "2003",
    scenes: int = 3,
    scene_seconds: int = 3,
    standard: str = "pal",
    aspect: str = "4:3",
    timeout: float = 600,
    log: Optional[Callable[[str], None]] = None,
) -> DemoReport:
    """
    Capture (simulated) → merge with date overlay → upscale → poster → Plex export,
    with the services the web interface uses. Expects prepare_demo_home() to have run.
    """
    from .config import Config
    from .media import has_filter, probe
    from .service import CaptureService, CoverService, PostprocessingService, highres_file

    say = log or (lambda message: print(message, flush=True))
    os.environ.update({
        "DV2PLEX_DEMO_SCENES": str(scenes),
        "DV2PLEX_DEMO_SCENE_SECONDS": str(scene_seconds),
        "DV2PLEX_DEMO_STANDARD": standard,
        "DV2PLEX_DEMO_ASPECT": aspect,
        "DV2PLEX_DEMO_REALTIME": "0",
    })
    report = DemoReport()
    config = Config()
    # The chain is driven step by step here, so each step can be timed
    config.set("capture.auto_postprocess", False)
    config.set("capture.auto_export", False)
    logs: List[str] = []

    def collect(message: str) -> None:
        logs.append(message)

    merged_jobs: List[Any] = []
    capture = CaptureService(config, log_callback=collect, merge_finished_callback=merged_jobs.append)
    post = PostprocessingService(config, log_callback=collect, merge_busy=capture.is_merging)
    covers = CoverService(config, log_callback=collect)
    project = config.get_dv_import_root() / f"{title} ({year})"

    try:
        # 1. Capture: the simulated camera plays the whole tape, then stops by itself
        started = time.time()
        ok, error = capture.start_capture(title, year, preview_callback=None, auto_rewind_play=True)
        if not ok:
            raise RuntimeError(f"capture did not start: {error}")
        finished = _wait_for(lambda: not capture.is_capturing(), timeout)
        clips = sorted((project / "LowRes" / "splits").glob("*.avi"))
        report.step("capture", started, finished and len(clips) == scenes, f"{len(clips)} DV clips")
        say(f"capture: {len(clips)} clips")

        # 2. Merge: queued by the capture engine when the tape ended
        started = time.time()
        merged = _wait_for(lambda: bool(merged_jobs), timeout)
        job = merged_jobs[0] if merged_jobs else None
        merged_file = Path(job.result_path) if job and job.result_path else None
        report.step("merge", started, bool(merged and job and job.status == "completed"), str(merged_file or ""))
        say(f"merge: {job.status if job else 'timed out'}")
        if not merged_file:
            raise RuntimeError("merge failed")

        # 3. Upscale
        started = time.time()
        done: List[tuple] = []
        post.process_movie(project, DEMO_PROFILE, finished_callback=lambda s, m: done.append((s, m)))
        _wait_for(lambda: bool(done), timeout)
        upscaled = highres_file(project)
        report.step("upscale", started, bool(done and done[0][0]), done[0][1] if done else "timed out")
        say(f"upscale: {done[0][1] if done else 'timed out'}")

        # 4. Poster
        started = time.time()
        ok, poster, message = covers.generate_poster(upscaled, title, year)
        report.step("poster", started, ok, message or "")
        say(f"poster: {message}")

        # 5. Export into the demo Plex library
        from .plex_export import PlexExporter

        started = time.time()
        target = PlexExporter(config.get_plex_movies_root(), log_callback=collect).export_movie(
            upscaled, title, year, overwrite=True
        )
        report.step("export", started, bool(target), str(target or ""))
        say(f"export: {target}")

        # Checks on the results
        ffmpeg = config.get_ffmpeg_path()
        merged_info = probe(merged_file, ffmpeg)
        final_info = probe(target, ffmpeg) if target else None
        expected = scenes * scene_seconds
        report.check(
            "merged film is H.264 4:2:0 with AAC",
            bool(merged_info and merged_info.codec == "h264" and merged_info.pix_fmt == "yuv420p"
                 and merged_info.audio_codec == "aac"),
            f"{merged_info.codec}/{merged_info.pix_fmt}/{merged_info.audio_codec}" if merged_info else "unreadable",
        )
        report.check(
            "merged film has every scene once",
            bool(merged_info and merged_info.duration and abs(merged_info.duration - expected) < 1.0),
            f"{merged_info.duration:.2f} s, expected {expected} s" if merged_info and merged_info.duration else "unreadable",
        )
        if has_filter(ffmpeg, "drawtext"):
            fell_back = any("without it" in line or "overlay is skipped" in line for line in logs)
            report.check("date overlay rendered", not fell_back, "drawtext available")
        else:
            report.check("date overlay skipped with a clear message",
                         any("no drawtext filter" in line for line in logs), "this ffmpeg has no drawtext")
        if final_info:
            dar = final_info.dar
            want = (4, 3) if aspect == "4:3" else (16, 9)
            report.check(
                "upscaled film keeps the tape's aspect with square pixels",
                final_info.sar == 1 and abs(float(dar) - want[0] / want[1]) < 0.01,
                f"{final_info.width}x{final_info.height}, SAR {final_info.sar}, DAR {float(dar):.3f}",
            )
            report.check(
                "upscaled film plays everywhere (H.264 4:2:0, AAC)",
                final_info.codec == "h264" and final_info.pix_fmt == "yuv420p" and final_info.audio_codec == "aac",
                f"{final_info.codec}/{final_info.pix_fmt}/{final_info.audio_codec}",
            )
        plex_dir = config.get_plex_movies_root() / f"{title} ({year})"
        report.check("Plex folder has film and poster",
                     (plex_dir / f"{title} ({year}).mp4").is_file() and (plex_dir / "poster.jpg").is_file(),
                     str(plex_dir))
        report.files = {
            "clips": str(project / "LowRes" / "splits"),
            "merged": str(merged_file),
            "upscaled": str(upscaled),
            "plex": str(plex_dir),
        }
        report.ok = all(s["ok"] for s in report.steps) and all(c["ok"] for c in report.checks)
    except Exception as e:
        report.error = str(e)
        report.ok = False
    finally:
        if not report.ok:
            report.files["log"] = _write_log(logs)
    return report


def _write_log(lines: List[str]) -> str:
    path = Path(tempfile.gettempdir()) / f"dv2plex-demo-{int(time.time())}.log"
    try:
        path.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        return ""
    return str(path)


def seed_demo_projects(log: Optional[Callable[[str], None]] = None) -> None:
    """
    Fills the demo workspace with a few tapes in different states, for screenshots:
    one exported to Plex with a poster, one upscaled, one merged and waiting.
    """
    say = log or (lambda message: print(message, flush=True))
    tapes = [
        ("Sommerurlaub Gardasee", "2003", "2003-08-02T10:12:00", "4:3", "exported"),
        ("Kindergeburtstag Lena", "2005", "2005-03-19T15:04:00", "16:9", "upscaled"),
        ("Hochzeit Anna und Tom", "1999", "1999-06-26T13:30:00", "4:3", "merged"),
    ]
    for title, year, start, aspect, state in tapes:
        os.environ["DV2PLEX_DEMO_START"] = start
        report = run_pipeline(title, year, scenes=3, scene_seconds=3, aspect=aspect, log=say) if state == "exported" else None
        if report is None:
            _seed_partial(title, year, aspect, state, say)
    os.environ.pop("DV2PLEX_DEMO_START", None)


def _seed_partial(title: str, year: str, aspect: str, state: str, say: Callable[[str], None]) -> None:
    from .config import Config
    from .service import CaptureService, PostprocessingService

    os.environ.update({"DV2PLEX_DEMO_SCENES": "3", "DV2PLEX_DEMO_SCENE_SECONDS": "3",
                       "DV2PLEX_DEMO_ASPECT": aspect, "DV2PLEX_DEMO_REALTIME": "0"})
    config = Config()
    config.set("capture.auto_postprocess", False)
    config.set("capture.auto_export", False)
    merged: list = []
    capture = CaptureService(config, log_callback=lambda m: None, merge_finished_callback=merged.append)
    ok, error = capture.start_capture(title, year)
    if not ok:
        say(f"{title}: {error}")
        return
    _wait_for(lambda: bool(merged), 300)
    say(f"{title}: merged")
    if state == "upscaled":
        done: list = []
        PostprocessingService(config, log_callback=lambda m: None).process_movie(
            config.get_dv_import_root() / f"{title} ({year})", DEMO_PROFILE, finished_callback=lambda s, m: done.append(s)
        )
        _wait_for(lambda: bool(done), 300)
        say(f"{title}: upscaled")
