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
