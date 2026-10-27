"""The web API: services, paths it accepts, validation, threads."""

import asyncio
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import dv2plex.config as config_module
from dv2plex import web_app
from dv2plex.access import TOKEN_ENV
from dv2plex.capture import CaptureEngine, default_use_sudo, interrupt_process
from dv2plex.config import Config
from dv2plex.update_manager import UpdateManager


@pytest.fixture
def api(monkeypatch, tmp_path):
    """A loopback server with real services on a temporary import and Plex folder."""
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    config = Config()
    config.set("paths.dv_import_root", str(tmp_path / "DV_Import"))
    config.set("paths.plex_movies_root", str(tmp_path / "Plex"))
    monkeypatch.setattr(web_app, "config", config)
    web_app.setup_services(mode="desktop")
    web_app.setup_access("127.0.0.1", 5000)
    (tmp_path / "DV_Import").mkdir()
    return TestClient(web_app.app, base_url="http://127.0.0.1:5000"), tmp_path


def test_status_requests_do_not_start_threads(api):
    client, _ = api
    client.get("/api/status")
    before = threading.active_count()

    for _ in range(30):
        assert client.get("/api/status").status_code == 200

    # Every status request used to start a merge worker thread that never ended
    assert threading.active_count() <= before + 1


@pytest.mark.parametrize("route,body", [
    ("/api/movie/export", {"video_path": "{outside}"}),
    ("/api/postprocess/process", {"movie_dir": "{outside_dir}", "profile_name": "ffmpeg_fast"}),
    ("/api/movie/merge", {"video_paths": ["{outside}", "{outside}"], "title": "x", "year": "2003"}),
    ("/api/cover/extract", {"video_path": "{outside}"}),
    ("/api/poster/generate", {"video_path": "{outside}", "title": "x"}),
    ("/api/cover/generate", {"frame_path": "{outside}", "title": "x"}),
])
def test_routes_refuse_files_outside_the_import_folder(api, route, body):
    client, tmp_path = api
    secret = tmp_path / "secret.mp4"
    secret.write_bytes(b"not for the web")
    filled = {
        key: (value.replace("{outside}", str(secret)).replace("{outside_dir}", str(tmp_path))
              if isinstance(value, str) else [v.replace("{outside}", str(secret)) for v in value]
              if isinstance(value, list) else value)
        for key, value in body.items()
    }

    response = client.post(route, json=filled)

    assert response.status_code == 400, response.text
    assert not (tmp_path / "Plex").exists()


def test_rename_cannot_leave_the_import_folder(api):
    client, tmp_path = api
    project = tmp_path / "DV_Import" / "Urlaub (2003)"
    (project / "LowRes").mkdir(parents=True)

    response = client.post("/api/player/rename", json={
        "project_path": str(project), "new_title": "../../escaped", "new_year": "2003"})

    assert response.status_code == 200, response.text
    assert not (tmp_path / "escaped (2003)").exists()
    assert (tmp_path / "DV_Import" / "escaped (2003)").is_dir()


def test_rename_refuses_a_bad_year(api):
    client, tmp_path = api
    project = tmp_path / "DV_Import" / "Urlaub (2003)"
    (project / "LowRes").mkdir(parents=True)

    response = client.post("/api/player/rename", json={"project_path": str(project), "new_title": "U", "new_year": "03"})

    assert response.status_code == 400
    assert project.is_dir()


def test_capture_refuses_a_bad_year_before_touching_anything(api):
    client, tmp_path = api

    response = client.post("/api/capture/start", json={"title": "Urlaub", "year": "03"})

    assert response.status_code == 400
    assert "four digits" in response.json()["detail"]
    assert list((tmp_path / "DV_Import").iterdir()) == []


def test_settings_are_validated(api):
    client, _ = api

    assert client.post("/api/settings", json={"update_interval_minutes": "soon"}).status_code == 422
    assert client.post("/api/settings", json={"update_interval_minutes": 1}).status_code == 400
    assert client.post("/api/settings", json={"default_profile": "nope"}).status_code == 400
    assert client.post("/api/settings", json={"dv_import_root": "  "}).status_code == 400
    ok = client.post("/api/settings", json={"timestamp_overlay": False, "ui_language": "de"})
    assert ok.status_code == 200
    assert web_app.config.get("capture.timestamp_overlay") is False
    assert client.get("/api/settings").json()["ui_language"] == "de"


def test_info_reports_capabilities(api):
    client, _ = api

    info = client.get("/api/info").json()

    assert info["version"]
    assert info["mode"] == "desktop"
    assert {"ffmpeg", "capture", "upscaling", "poster", "paths"} <= set(info)
    assert any(p["name"] == "ffmpeg_fast" and p["available"] for p in info["upscaling"]["profiles"])


def test_postprocess_list_offers_unmerged_clips(api):
    client, tmp_path = api
    splits = tmp_path / "DV_Import" / "Abgebrochen (2004)" / "LowRes" / "splits"
    splits.mkdir(parents=True)
    (splits / "dvgrab-2004.01.01_10-00-00.avi").write_bytes(b"dv")

    movies = client.get("/api/postprocess/list").json()["movies"]

    assert [m["display"] for m in movies] == ["Abgebrochen (2004)"]
    assert movies[0]["needs_merge"] is True


def test_desktop_start_does_not_touch_systemd(api, monkeypatch):
    calls = []
    monkeypatch.setattr(web_app.update_manager, "_ensure_service_enabled", lambda: calls.append(1) or {"success": True})
    web_app.config.set("update.enabled", True)

    asyncio.run(web_app.on_startup())

    assert calls == []
    if web_app.update_task:
        web_app.update_task.cancel()


# --- capture engine ---------------------------------------------------------------------

def test_sudo_only_on_linux_for_non_root(monkeypatch):
    engine = CaptureEngine(Path("ffmpeg"), dvgrab_cmd=["dvgrab"], use_sudo=False)
    assert engine._sudo_prefix() == []
    engine.use_sudo = True
    assert engine._sudo_prefix() == ["sudo", "-n"]
    if not sys.platform.startswith("linux"):
        assert default_use_sudo() is False


def test_interrupt_process_stops_a_child_on_every_platform():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])

    interrupt_process(child, timeout=5)

    assert child.poll() is not None


def test_update_manager_trusts_its_own_checkout(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""))
    manager = UpdateManager(tmp_path, "master", "dv2plex", Config(), None)

    manager._run_cmd(["sudo", "-n", "git", "pull", "--ff-only", "origin", "master"])
    manager._run_cmd(["git", "fetch", "origin", "master"])

    assert seen[0][:5] == ["sudo", "-n", "git", "-c", f"safe.directory={tmp_path.resolve()}"]
    assert seen[1][:3] == ["git", "-c", f"safe.directory={tmp_path.resolve()}"]


def test_update_status_explains_a_missing_checkout(tmp_path):
    manager = UpdateManager(tmp_path, "master", "dv2plex", Config(), None)

    status = manager._refresh_status_sync()

    assert status.ok is False
    assert "releases" in status.error


def test_slow_work_does_not_block_other_requests(api, monkeypatch):
    """Frame extraction runs ffmpeg for seconds; the page must keep getting status meanwhile."""
    import time as _time

    import httpx

    client, tmp_path = api
    video = tmp_path / "DV_Import" / "Film (2003)" / "HighRes" / "Film (2003)_4k.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")

    def slow_extract(path, count=4):
        _time.sleep(1.5)
        return False, [], "nothing"

    monkeypatch.setattr(web_app.cover_service, "extract_frames", slow_extract)

    async def scenario():
        transport = httpx.ASGITransport(app=web_app.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:5000") as http:
            started = _time.perf_counter()
            slow = asyncio.create_task(http.post("/api/cover/extract", json={"video_path": str(video)}))
            await asyncio.sleep(0.2)
            status = await http.get("/api/status")
            waited = _time.perf_counter() - started  # since the slow request began
            await slow
            return status.status_code, waited

    code, waited = asyncio.run(scenario())

    assert code == 200
    assert waited < 1.0, f"/api/status waited {waited:.2f} s for the frame extraction"
