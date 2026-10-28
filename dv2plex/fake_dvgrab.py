"""
A stand-in for dvgrab, for the demo and the tests: no camera, no FireWire, no root.

It understands the dvgrab calls DV2Plex makes and answers like a camera with a tape in it:

    fake_dvgrab --list                                   lists one camera
    fake_dvgrab [-card N] -i                             camera control on stdin (a, p, k, Esc)
    fake_dvgrab [-card N] [-rewind] -autosplit -t -f dv1 <dir>/dvgrab.avi
                                                         "records" the tape: one DV clip per
                                                         scene, named after its recording time

The clips are real DV (made by ffmpeg from test patterns and a tone), so everything after
the capture (preview, merge, date overlay, upscaling, poster, export) runs unchanged.
Ctrl+C (SIGINT) ends the recording like with dvgrab; the clip being written is finished.

Environment (all optional):
    DV2PLEX_DEMO_SCENES          number of scenes on the tape (3)
    DV2PLEX_DEMO_SCENE_SECONDS   length of each scene in seconds (4)
    DV2PLEX_DEMO_STANDARD        pal or ntsc (pal)
    DV2PLEX_DEMO_ASPECT          4:3 or 16:9 (4:3)
    DV2PLEX_DEMO_REALTIME        1 = take as long as the tape plays, 0 = as fast as possible (1)
    DV2PLEX_DEMO_START           recording time of the first scene (2003-06-14T15:30:00)
    DV2PLEX_FFMPEG               ffmpeg to use (default: the one DV2Plex itself would use)
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

# Cheap test patterns, one per scene, so the scenes look different in the film
SOURCES = [
    "testsrc2=size={size}:rate={rate}",
    "smptebars=size={size}:rate={rate}",
    "life=size={size}:rate={rate}:mold=10:ratio=0.2:death_color=#2b6cb0:life_color=#f0a63a",
    "rgbtestsrc=size={size}:rate={rate}",
    "cellauto=size={size}:rate={rate}:rule=110",
]
TONES = [440, 523, 659, 784, 880]

_stop_requested = False


def _on_signal(signum, frame):  # noqa: ARG001
    global _stop_requested
    _stop_requested = True


def _say(message: str) -> None:
    """dvgrab reports on stderr; DV2Plex reads it from there."""
    if sys.stderr is None:  # a windowed app started without a console
        return
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


def _ffmpeg() -> str:
    # In the desktop app ffmpeg is bundled and usually not on PATH
    from dv2plex.config import find_ffmpeg

    return os.environ.get("DV2PLEX_FFMPEG") or str(find_ffmpeg())


def _record(prefix: Path, rewind: bool) -> int:
    scenes = _env_int("DV2PLEX_DEMO_SCENES", 3)
    seconds = _env_int("DV2PLEX_DEMO_SCENE_SECONDS", 4)
    ntsc = os.environ.get("DV2PLEX_DEMO_STANDARD", "pal").lower() == "ntsc"
    aspect = os.environ.get("DV2PLEX_DEMO_ASPECT", "4:3")
    realtime = os.environ.get("DV2PLEX_DEMO_REALTIME", "1") != "0"
    try:
        start = datetime.fromisoformat(os.environ.get("DV2PLEX_DEMO_START", "2003-06-14T15:30:00"))
    except ValueError:
        start = datetime(2003, 6, 14, 15, 30, 0)

    size, rate, target = ("720x480", "30000/1001", "ntsc-dv") if ntsc else ("720x576", "25", "pal-dv")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    stem = prefix.stem  # "dvgrab" for dvgrab.avi

    if rewind:
        _say("Rewinding tape...")
    # Like a camera spinning up: DV2Plex treats a dvgrab that ends within a second as failed
    time.sleep(float(os.environ.get("DV2PLEX_DEMO_SPINUP", "1.5")))
    _say("Capture Started")

    for index in range(scenes):
        if _stop_requested:
            break
        recorded = start + timedelta(minutes=17 * index, seconds=11 * index)
        name = f"{stem}-{recorded:%Y.%m.%d_%H-%M-%S}{prefix.suffix or '.avi'}"
        target_file = prefix.parent / name
        source = SOURCES[index % len(SOURCES)].format(size=size, rate=rate)
        cmd: List[str] = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y"]
        if realtime:
            cmd.append("-re")
        cmd += [
            "-f", "lavfi", "-i", source,
            "-f", "lavfi", "-i", f"sine=frequency={TONES[index % len(TONES)]}:sample_rate=48000",
            "-t", str(seconds),
            "-target", target, "-aspect", aspect,
            str(target_file),
        ]
        _say(f'"{target_file.name}": capturing scene {index + 1} of {scenes}')
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        while process.poll() is None:
            if _stop_requested:
                # Like dvgrab on Ctrl+C: finish the file being written, then stop
                try:
                    process.stdin.write(b"q")
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                break
            time.sleep(0.1)
        error = process.stderr.read().decode("utf-8", "replace").strip() if process.stderr else ""
        if process.returncode not in (0, 255) and not _stop_requested:
            _say(f"Error: ffmpeg could not write the scene: {error[-400:]}")
            return 1
        _say(f'"{target_file.name}": {seconds} seconds')

    _say("Capture Stopped")
    return 0


def _interactive() -> int:
    _say("Going interactive. Press '?' for help.")
    stdin = sys.stdin.buffer
    while not _stop_requested:
        char = stdin.read(1)
        if not char or char == b"\x1b":
            break
        state = {b"a": "Rewinding", b"p": "Playing", b"k": "Paused", b"z": "Fast forwarding"}.get(char)
        if state:
            _say(f"Camera: {state}")
    _say("Leaving interactive mode")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_signal)

    if "--list" in args:
        print("1: DV2Plex demo camera (simulated), card 0")
        return 0
    if "-i" in args or "--interactive" in args:
        return _interactive()

    positional = []
    skip = False
    for index, arg in enumerate(args):
        if skip:
            skip = False
            continue
        if arg in ("-card", "-f", "--card", "--format", "-size", "-frames"):
            skip = True
            continue
        if not arg.startswith("-"):
            positional.append(arg)
    if not positional:
        _say("Usage: fake_dvgrab [-card N] [-rewind] -autosplit -t -f dv1 <prefix>.avi")
        return 2
    return _record(Path(positional[-1]), rewind="-rewind" in args)


if __name__ == "__main__":
    sys.exit(main())
