import json
import shutil
import subprocess
from pathlib import Path

import pytest

import dv2plex.config as config_module
from dv2plex.config import Config, SHIPPED_LEGACY_SETTINGS_BLOB, git_blob_id

TRACKED_SETTINGS = Path(__file__).parent / "config" / "settings.json"


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    return tmp_path


def _write_legacy(config_dir: Path, data: dict) -> Path:
    legacy = config_dir / "settings.json"
    legacy.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return legacy


def test_git_blob_id_matches_git(tmp_path):
    sample = tmp_path / "sample.json"
    sample.write_bytes(b'{"a": 1}\n')
    expected = subprocess.run(
        ["git", "hash-object", str(sample)], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert git_blob_id(sample.read_bytes()) == expected


def test_shipped_blob_is_the_tracked_settings_file():
    assert git_blob_id(TRACKED_SETTINGS.read_bytes()) == SHIPPED_LEGACY_SETTINGS_BLOB


def test_fresh_install_writes_defaults_to_local_file(config_dir):
    config = Config()

    assert config.config_path == config_dir / "settings.local.json"
    assert config.config_path.is_file()
    assert not (config_dir / "settings.json").exists()
    assert config.get("paths.plex_movies_root") == str(Path.home() / "Plex" / "Movies")


def test_changed_legacy_settings_are_taken_over_once(config_dir):
    legacy = _write_legacy(config_dir, {"paths": {"plex_movies_root": "/srv/plex/movies"}})
    legacy_bytes = legacy.read_bytes()

    config = Config()

    assert config.get("paths.plex_movies_root") == "/srv/plex/movies"
    saved = json.loads((config_dir / "settings.local.json").read_text(encoding="utf-8"))
    assert saved["paths"]["plex_movies_root"] == "/srv/plex/movies"
    # The tracked file is left alone, so git pull can update or remove it.
    assert legacy.read_bytes() == legacy_bytes


def test_local_file_wins_over_legacy(config_dir):
    _write_legacy(config_dir, {"paths": {"plex_movies_root": "/old"}})
    (config_dir / "settings.local.json").write_text(
        json.dumps({"paths": {"plex_movies_root": "/new"}}), encoding="utf-8"
    )

    assert Config().get("paths.plex_movies_root") == "/new"


@pytest.mark.parametrize("line_ending", [b"\n", b"\r\n"])
def test_unchanged_tracked_file_is_not_taken_over(config_dir, line_ending):
    content = TRACKED_SETTINGS.read_bytes().replace(b"\n", line_ending)
    (config_dir / "settings.json").write_bytes(content)

    config = Config()

    # The tracked file only holds example values (E:\PlexMovies); the defaults apply.
    assert config.get("paths.plex_movies_root") == str(Path.home() / "Plex" / "Movies")


def test_takeover_keeps_values_when_local_file_cannot_be_written(config_dir, monkeypatch):
    _write_legacy(config_dir, {"paths": {"plex_movies_root": "/srv/plex/movies"}})

    def deny(self, config=None):
        raise PermissionError("read-only")

    monkeypatch.setattr(Config, "save_config", deny)

    assert Config().get("paths.plex_movies_root") == "/srv/plex/movies"


def test_explicit_config_path_ignores_legacy(config_dir, tmp_path):
    _write_legacy(config_dir, {"paths": {"plex_movies_root": "/old"}})
    own = tmp_path / "own.json"

    config = Config(str(own))

    assert config.legacy_config_path is None
    assert config.get("paths.plex_movies_root") == str(Path.home() / "Plex" / "Movies")


def test_auto_update_is_off_by_default(config_dir):
    assert Config().get("update.enabled") is False


def test_fresh_clone_does_not_inherit_auto_update_from_tracked_file(config_dir):
    # The tracked settings.json says "enabled": true; a fresh clone must not pick that up.
    (config_dir / "settings.json").write_bytes(TRACKED_SETTINGS.read_bytes())

    assert Config().get("update.enabled") is False


@pytest.mark.parametrize("enabled", [True, False])
def test_existing_installation_keeps_its_update_setting(config_dir, enabled):
    _write_legacy(config_dir, {"paths": {"plex_movies_root": "/srv"}, "update": {"enabled": enabled}})

    assert Config().get("update.enabled") is enabled
    assert Config().get("update.enabled") is enabled  # and after the move to settings.local.json
