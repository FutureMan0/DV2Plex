"""
The capture engine against the simulated dvgrab: start, live preview, stop, the merge
that follows, the rewind block and the camera controls. These pin the behaviour down
before the engine is split into modules.
"""

import shutil
import sys
import time
from pathlib import Path

import pytest

from dv2plex.capture import CaptureEngine
from dv2plex.conftest import ffmpeg_available
from dv2plex.demo import fake_dvgrab_command

pytestmark = pytest.mark.skipif(not ffmpeg_available(), reason="needs ffmpeg and ffprobe on PATH")


def _wait(condition, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def tape(monkeypatch):
    def configure(scenes=2, seconds=2, realtime=False):
        monkeypatch.setenv("DV2PLEX_DEMO_SCENES", str(scenes))
        monkeypatch.setenv("DV2PLEX_DEMO_SCENE_SECONDS", str(seconds))
        monkeypatch.setenv("DV2PLEX_DEMO_REALTIME", "1" if realtime else "0")
        monkeypatch.setenv("DV2PLEX_DEMO_SPINUP", "1.5")
    return configure


@pytest.fixture
def engine():
    logs, states, merged = [], [], []
    created = []

    def make(**kwargs):
        e = CaptureEngine(
            Path(shutil.which("ffmpeg")),
            device_path="0",
            log_callback=logs.append,
            state_callback=states.append,
            dvgrab_cmd=kwargs.pop("dvgrab_cmd", fake_dvgrab_command()),
            use_sudo=False,
            merge_options=lambda: {"timestamp_overlay": False},
            merge_finished_callback=merged.append,
            rewind_seconds=kwargs.pop("rewind_seconds", 2),
            **kwargs,
        )
        e.logs, e.states, e.merged = logs, states, merged
        created.append(e)
        return e

    yield make
    for e in created:
        e._stop_all_processes()


def test_tape_end_merges_and_rewinds_by_itself(engine, tape, tmp_path):
    tape(scenes=2, seconds=2)
    e = engine()
    lowres = tmp_path / "Tape (2003)" / "LowRes"

    assert e.start_capture(lowres, title="Tape", year="2003")
    assert e.is_capturing
    assert _wait(lambda: not e.is_capturing)
    assert _wait(lambda: bool(e.merged))

    job = e.merged[0]
    assert job.status == "completed" and job.progress == 100
    assert (lowres / "movie_merged.mp4").is_file()
    assert len(list((lowres / "splits").glob("dvgrab-*.avi"))) == 2
    assert e.states.count("stopped") == 1
    status = e.get_merge_queue_status()
    assert status["jobs"][-1]["status"] == "completed" and status["pending_count"] == 0
    # After the tape the camera rewinds; new captures wait for it
    assert e.is_rewind_block_active()
    assert not e.start_capture(tmp_path / "Other (2003)" / "LowRes", title="Other", year="2003")
    assert _wait(lambda: not e.is_rewind_block_active(), 10)


@pytest.mark.skipif(sys.platform == "win32", reason="the simulated dvgrab cannot catch terminate() on Windows")
def test_live_preview_and_stop(engine, tape, tmp_path):
    tape(scenes=8, seconds=2, realtime=True)
    e = engine()
    frames = []
    lowres = tmp_path / "Live (2004)" / "LowRes"

    assert e.start_capture(lowres, preview_callback=frames.append, preview_fps=10, title="Live", year="2004")
    assert _wait(lambda: len(frames) >= 3, 30), "no preview frames"
    assert e.stop_capture()

    assert not e.is_capturing
    assert all(f[:2] == b"\xff\xd8" for f in frames[:3])  # JPEG
    assert _wait(lambda: bool(e.merged))
    assert e.merged[0].status == "completed"
    clips = list((lowres / "splits").glob("dvgrab-*.avi"))
    assert 1 <= len(clips) < 8, "stopped before the tape ended"
    # The monitor thread used to finalize a manual stop a second time
    assert e.states.count("stopped") == 1
    assert len(e.merge_jobs) == 1


def test_camera_controls_reach_the_interactive_dvgrab(engine, tape):
    tape()
    e = engine()

    assert e.rewind() is True
    assert e.play() is True
    assert e.pause() is True
    assert e.interactive_dvgrab_process is not None and e.interactive_dvgrab_process.poll() is None


def test_missing_dvgrab_is_reported(engine, tmp_path):
    e = engine(dvgrab_cmd=[str(tmp_path / "no-such-dvgrab")])

    assert e.start_capture(tmp_path / "X (2003)" / "LowRes", title="X", year="2003") is False
    assert e.last_dvgrab_error
    assert not e.is_capturing
