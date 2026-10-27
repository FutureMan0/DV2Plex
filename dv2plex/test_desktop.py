"""The packaged desktop app: its folders, bundled ffmpeg, one instance, release check, window fallback."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import dv2plex.config as config_module
from dv2plex import desktop_app, instance, release_check
from dv2plex.config import Config


@pytest.mark.parametrize("candidate,current,newer", [
    ("v2.1.0", "2.0.0", True),
    ("2.0.1", "2.0.0", True),
    ("v2.0.0", "2.0.0", False),
    ("v1.9.9", "2.0.0", False),
    ("v2.0.0", "2.0.0-rc.1", True),
    ("v2.0.0-rc.2", "2.0.0-rc.1", True),
    ("v2.0.0-rc.1", "2.0.0", False),
    ("nightly", "2.0.0", False),
])
def test_version_comparison(candidate, current, newer):
    assert release_check.is_newer(candidate, current) is newer


def test_release_check_reports_a_newer_release(monkeypatch):
    monkeypatch.setattr(release_check, "_cache", {"at": 0.0, "result": None})
    monkeypatch.setattr(release_check, "fetch_latest", lambda timeout=6.0: {
        "tag_name": "v9.0.0", "html_url": "https://github.com/FutureMan0/DV2Plex/releases/tag/v9.0.0", "body": "Notes"})

    result = release_check.check("2.0.0")

    assert result["newer"] is True and result["latest"] == "9.0.0"
    assert result["url"].endswith("v9.0.0") and result["error"] is None


def test_release_check_survives_being_offline(monkeypatch):
    monkeypatch.setattr(release_check, "_cache", {"at": 0.0, "result": None})

    def offline(timeout=6.0):
        raise OSError("no network")

    monkeypatch.setattr(release_check, "fetch_latest", offline)

    result = release_check.check("2.0.0")

    assert result["newer"] is False and "no network" in result["error"]


def test_frozen_app_keeps_its_data_in_the_user_folders(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("DV2PLEX_HOME", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))

    assert config_module._default_config_dir() == config_module.user_config_dir()
    assert tmp_path in config_module.user_config_dir().parents
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_module.user_config_dir())
    config = Config()
    assert Path(config.get("paths.dv_import_root")).parent == config_module.user_videos_dir()
    assert config.get("update.check_releases") is True
    assert config.get("ui.setup_done") is False  # a fresh install runs the assistant


def test_frozen_app_prefers_its_own_ffmpeg(monkeypatch, tmp_path):
    bundled = tmp_path / "ffmpeg"
    bundled.write_text("")
    monkeypatch.setattr(Config, "_bundled_ffmpeg_candidates", staticmethod(lambda: [bundled]))
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path / "config")
    config = Config()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert config.get_ffmpeg_path() == bundled


def test_second_start_finds_the_running_instance(tmp_path, monkeypatch):
    instance.claim(tmp_path, 5123)
    assert json.loads((tmp_path / "instance.json").read_text())["port"] == 5123

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"version": "2.0.0"}'

    monkeypatch.setattr(instance.urllib.request, "urlopen", lambda url, timeout=1.5: Answer())
    assert instance.running_instance(tmp_path) == 5123

    instance.release(tmp_path)
    assert not (tmp_path / "instance.json").exists()


def test_stale_instance_file_is_ignored(tmp_path):
    (tmp_path / "instance.json").write_text('{"port": 1, "pid": 1}')

    assert instance.running_instance(tmp_path, timeout=0.2) is None


def test_without_a_window_the_server_keeps_running(monkeypatch, tmp_path):
    """pywebview may fail in start(); the browser then needs a live server."""
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    server = SimpleNamespace(should_exit=False)
    joined = []
    thread = SimpleNamespace(join=lambda timeout=None: joined.append((server.should_exit, timeout)))
    opened = []
    monkeypatch.setattr(desktop_app, "_start_uvicorn_in_thread", lambda host, port, log_level: (server, thread, "tok"))
    monkeypatch.setattr(desktop_app, "_wait_for_port", lambda host, port, timeout_s: True)

    def no_gui(*args, **kwargs):
        raise RuntimeError("no GTK, no Qt")

    monkeypatch.setattr(desktop_app, "_open_window", no_gui)
    monkeypatch.setattr(desktop_app, "_fallback_open_in_browser", lambda url, err: opened.append(url))

    desktop_app.main(bind_host="127.0.0.1", port=5124)

    assert opened == ["http://127.0.0.1:5124/?token=tok"]
    assert joined and joined[0] == (False, None), "the server was stopped before the browser opened"
