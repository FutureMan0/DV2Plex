"""
End to end without a camera: the simulated dvgrab records a tape, then the real code
merges, upscales, makes a poster and exports to a Plex folder.

Needs ffmpeg and ffprobe on PATH (CI installs them). Takes some seconds per run.
"""

import time

import pytest
from fastapi.testclient import TestClient

import dv2plex.config as config_module
from dv2plex.conftest import ffmpeg_available
from dv2plex.demo import prepare_demo_home, run_pipeline
from dv2plex.media import probe

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not ffmpeg_available(), reason="needs ffmpeg and ffprobe on PATH"),
]

DEMO_ENV = ("DV2PLEX_HOME", "DV2PLEX_DEMO_SCENES", "DV2PLEX_DEMO_SCENE_SECONDS", "DV2PLEX_DEMO_STANDARD",
            "DV2PLEX_DEMO_ASPECT", "DV2PLEX_DEMO_REALTIME", "DV2PLEX_DEMO_START")


@pytest.fixture
def demo_home(tmp_path, monkeypatch):
    """A demo workspace; settings and environment are restored afterwards."""
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_module.CONFIG_DIR)
    for name in DEMO_ENV:
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    return prepare_demo_home(tmp_path / "demo")


@pytest.mark.parametrize("standard,aspect", [("pal", "4:3"), ("ntsc", "16:9")])
def test_tape_to_plex_library(demo_home, standard, aspect):
    report = run_pipeline("Demo Tape", "2003", scenes=3, scene_seconds=2, standard=standard, aspect=aspect, timeout=300)

    print(report.text())
    assert report.ok, report.text()
    plex = demo_home / "PlexMovies" / "Demo Tape (2003)"
    assert (plex / "Demo Tape (2003).mp4").is_file()
    assert (plex / "poster.jpg").is_file()


def _wait(condition, timeout=240):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.3)
    return False


def test_capture_to_plex_through_the_web_api(demo_home, monkeypatch):
    """What the browser does: start a capture; merge, upscale and export follow by themselves."""
    from dv2plex import web_app
    from dv2plex.config import Config

    monkeypatch.setenv("DV2PLEX_DEMO_REALTIME", "0")
    monkeypatch.setenv("DV2PLEX_DEMO_SCENES", "2")
    monkeypatch.setenv("DV2PLEX_DEMO_SCENE_SECONDS", "2")
    monkeypatch.setattr(web_app, "config", Config())
    web_app.setup_services(mode="desktop")
    web_app.setup_access("127.0.0.1", 5000)
    client = TestClient(web_app.app, base_url="http://127.0.0.1:5000")

    info = client.get("/api/info").json()
    assert info["demo"] is True and info["capture"]["supported"] is True
    started = client.post("/api/capture/start", json={"title": "Urlaub: Rom", "year": "2004"})
    assert started.status_code == 200, started.text

    project = demo_home / "DV_Import" / "Urlaub - Rom (2004)"
    plex_film = demo_home / "PlexMovies" / "Urlaub - Rom (2004)" / "Urlaub - Rom (2004).mp4"
    assert _wait(lambda: not client.get("/api/status").json()["capture_running"]), "capture did not end"
    assert _wait(lambda: plex_film.is_file()), "the film did not arrive in the Plex folder"

    queue = client.get("/api/merge/queue").json()
    assert queue["jobs"][-1]["status"] == "completed"
    film = probe(plex_film)
    assert film.codec == "h264" and film.pix_fmt == "yuv420p" and film.sar == 1
    assert (project / "HighRes" / "Urlaub - Rom (2004)_4k.mp4").is_file()

    # Poster through the API, then it shows up for the project
    upscaled = project / "HighRes" / "Urlaub - Rom (2004)_4k.mp4"
    assert client.post("/api/poster/generate", json={"video_path": str(upscaled), "title": "Urlaub - Rom", "year": "2004"}).status_code == 200
    assert _wait(lambda: (project / "HighRes" / "poster.jpg").is_file(), 120)
    projects = client.get("/api/player/projects").json()["projects"]
    assert projects[0]["has_poster"] is True
    stream = client.get("/api/player/stream", params={"path": str(upscaled)})
    assert stream.status_code == 200 and len(stream.content) > 10_000
