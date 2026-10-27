"""
End-to-end check of the settings move with real git repositories.

An installation is a clone that updates itself with `git pull`. Once upstream stops
tracking dv2plex/config/settings.json (step 2), the pull has to work whether the
installation changed that file or not, and its settings have to survive.
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import dv2plex.config as config_module
from dv2plex.config import Config
from dv2plex.update_manager import UpdateManager

SETTINGS = "dv2plex/config/settings.json"
TRACKED_SETTINGS = Path(__file__).parent / "config" / "settings.json"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _git_ok(cwd: Path, *args: str) -> None:
    result = _git(cwd, *args)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def repos(tmp_path):
    upstream = tmp_path / "upstream"
    (upstream / "dv2plex" / "config").mkdir(parents=True)
    (upstream / SETTINGS).write_bytes(TRACKED_SETTINGS.read_bytes())
    _git_ok(upstream, "init", "-q", "-b", "master")
    _git_ok(upstream, "config", "user.email", "test@example.invalid")
    _git_ok(upstream, "config", "user.name", "test")
    _git_ok(upstream, "add", SETTINGS)
    _git_ok(upstream, "commit", "-q", "-m", "settings tracked")

    instance = tmp_path / "instance"
    _git_ok(tmp_path, "clone", "-q", str(upstream), str(instance))
    return upstream, instance


def _stop_tracking_upstream(upstream: Path) -> None:
    """Step 2: upstream removes settings.json from the index."""
    _git_ok(upstream, "rm", "-q", "--cached", SETTINGS)
    _git_ok(upstream, "commit", "-q", "-m", "stop tracking settings.json")


def _start_installation(instance: Path, monkeypatch) -> UpdateManager:
    """Starts the new code once (moves the settings) and returns its updater."""
    monkeypatch.setattr(config_module, "CONFIG_DIR", instance / "dv2plex" / "config")
    manager = UpdateManager(instance, "master", "dv2plex", Config(), None)

    def run_without_sudo(cmd, timeout=60):
        if cmd[0] == "sudo":
            cmd = cmd[1:]
        if cmd[0] != "git":  # systemctl
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return subprocess.run(cmd, cwd=instance, capture_output=True, text=True, timeout=timeout)

    monkeypatch.setattr(manager, "_run_cmd", run_without_sudo)
    return manager


def test_changed_settings_survive_when_upstream_stops_tracking(repos, monkeypatch):
    upstream, instance = repos
    legacy = instance / SETTINGS
    data = json.loads(legacy.read_text(encoding="utf-8"))
    data["paths"]["plex_movies_root"] = "/srv/plex/movies"
    legacy.write_text(json.dumps(data, indent=2), encoding="utf-8")

    manager = _start_installation(instance, monkeypatch)
    _stop_tracking_upstream(upstream)

    result = manager._perform_update_sync()

    assert result["success"] is True, result
    assert not legacy.exists()
    assert Config().get("paths.plex_movies_root") == "/srv/plex/movies"


def test_plain_pull_fails_on_changed_settings(repos):
    """The trap the reset avoids: without it, the installation stops updating."""
    upstream, instance = repos
    (instance / SETTINGS).write_text("{}", encoding="utf-8")
    _stop_tracking_upstream(upstream)

    pull = _git(instance, "pull", "-q", "origin", "master")

    assert pull.returncode != 0
    assert "settings.json" in pull.stderr


def test_unchanged_settings_are_removed_by_pull(repos, monkeypatch):
    upstream, instance = repos

    manager = _start_installation(instance, monkeypatch)
    local = instance / "dv2plex" / "config" / "settings.local.json"
    assert local.is_file()
    _stop_tracking_upstream(upstream)

    result = manager._perform_update_sync()

    assert result["success"] is True, result
    assert not (instance / SETTINGS).exists()
    assert local.is_file()
    assert Config().get("paths.plex_movies_root") == str(Path.home() / "Plex" / "Movies")
