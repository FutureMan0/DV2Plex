from types import SimpleNamespace
from pathlib import Path

from dv2plex.update_manager import UpdateManager


class DummyConfig:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, key, default=None):
        parts = key.split(".")
        current = self.data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current


class DummyCaptureService:
    def __init__(self, capturing=False, merging=False):
        self._capturing = capturing
        self._merging = merging

    def is_capturing(self):
        return self._capturing

    def has_active_merge(self):
        return self._merging


def test_parse_ahead_behind(monkeypatch, tmp_path: Path):
    manager = UpdateManager(tmp_path, "master", "dv2plex", DummyConfig(), None)

    def fake_run_cmd(_cmd):
        return SimpleNamespace(returncode=0, stdout="1\t2\n", stderr="")

    monkeypatch.setattr(manager, "_run_cmd", fake_run_cmd)
    ahead, behind, error = manager._parse_ahead_behind()

    assert ahead == 1
    assert behind == 2
    assert error is None


def test_parse_ahead_behind_error(monkeypatch, tmp_path: Path):
    manager = UpdateManager(tmp_path, "master", "dv2plex", DummyConfig(), None)

    def fake_run_cmd(_cmd):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(manager, "_run_cmd", fake_run_cmd)
    ahead, behind, error = manager._parse_ahead_behind()

    assert ahead == 0
    assert behind == 0
    assert error == "boom"


def test_busy_reason_prefers_capture(tmp_path: Path):
    capture = DummyCaptureService(capturing=True, merging=False)
    manager = UpdateManager(tmp_path, "master", "dv2plex", DummyConfig(), capture)

    assert manager.busy_reason() == "Capture läuft"


def test_busy_reason_merge(tmp_path: Path):
    capture = DummyCaptureService(capturing=False, merging=True)
    manager = UpdateManager(tmp_path, "master", "dv2plex", DummyConfig(), capture)

    assert manager.busy_reason() == "Merge läuft"




class SettingsConfig(DummyConfig):
    """Config stand-in with the settings paths UpdateManager looks at."""

    def __init__(self, repo: Path, moved: bool = True):
        super().__init__()
        config_dir = repo / "dv2plex" / "config"
        config_dir.mkdir(parents=True)
        self.config_path = config_dir / "settings.local.json"
        self.legacy_config_path = config_dir / "settings.json"
        if moved:
            self.config_path.write_text("{}", encoding="utf-8")


# sudo -n: fail instead of waiting for a password; --ff-only: never create merge commits
PULL = ["sudo", "-n", "git", "pull", "--ff-only", "origin", "master"]


def _record_commands(manager, monkeypatch, diff_returncode):
    commands = []

    def fake_run_cmd(cmd, timeout=60):
        commands.append(cmd)
        returncode = diff_returncode if cmd[:2] == ["git", "diff"] else 0
        return SimpleNamespace(returncode=returncode, stdout="", stderr="")

    monkeypatch.setattr(manager, "_run_cmd", fake_run_cmd)
    return commands


def test_update_resets_changed_legacy_settings_before_pull(monkeypatch, tmp_path: Path):
    manager = UpdateManager(tmp_path, "master", "dv2plex", SettingsConfig(tmp_path), None)
    commands = _record_commands(manager, monkeypatch, diff_returncode=1)

    result = manager._perform_update_sync()

    assert result["success"] is True
    assert commands[0] == ["git", "diff", "--quiet", "HEAD", "--", "dv2plex/config/settings.json"]
    assert commands[1] == ["sudo", "-n", "git", "checkout", "HEAD", "--", "dv2plex/config/settings.json"]
    assert commands[2] == PULL


def test_update_leaves_unchanged_legacy_settings(monkeypatch, tmp_path: Path):
    manager = UpdateManager(tmp_path, "master", "dv2plex", SettingsConfig(tmp_path), None)
    commands = _record_commands(manager, monkeypatch, diff_returncode=0)

    manager._perform_update_sync()

    assert not any(cmd[:4] == ["sudo", "-n", "git", "checkout"] for cmd in commands)
    assert PULL in commands


def test_update_keeps_legacy_settings_until_they_are_moved(monkeypatch, tmp_path: Path):
    config = SettingsConfig(tmp_path, moved=False)
    manager = UpdateManager(tmp_path, "master", "dv2plex", config, None)
    commands = _record_commands(manager, monkeypatch, diff_returncode=1)

    manager._perform_update_sync()

    assert commands[0] == PULL
