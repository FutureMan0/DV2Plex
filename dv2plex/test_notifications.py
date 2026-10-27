import urllib.request
from pathlib import Path

import pytest

import dv2plex.config as config_module
from dv2plex.capture import CaptureEngine
from dv2plex.config import Config
from dv2plex.notifications import send_ntfy
from dv2plex.service import CaptureService, PostprocessingService


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    return Config()


@pytest.fixture
def posted(monkeypatch):
    """Records every request that would go out over the network."""
    requests = []

    def fake_urlopen(request, timeout=None):
        requests.append(request)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return requests


def test_ntfy_is_off_by_default(config, posted):
    assert config.get("notifications.ntfy_topic") == ""
    assert send_ntfy(config, "Merge abgeschlossen: Urlaub (1998)", lambda msg: None) is False
    assert posted == []


def test_ntfy_posts_to_configured_topic(config, posted):
    config.set("notifications.ntfy_topic", "my-secret-topic")

    assert send_ntfy(config, "Merge abgeschlossen: Urlaub (1998)", lambda msg: None) is True

    assert len(posted) == 1
    assert posted[0].full_url == "https://ntfy.sh/my-secret-topic"
    assert posted[0].get_method() == "POST"
    assert posted[0].data == "Merge abgeschlossen: Urlaub (1998)".encode("utf-8")


def test_ntfy_uses_own_server_and_quotes_topic(config, posted):
    config.set("notifications.ntfy_server", "https://ntfy.example.org/")
    config.set("notifications.ntfy_topic", "dv 2/plex")

    send_ntfy(config, "x", lambda msg: None)

    assert posted[0].full_url == "https://ntfy.example.org/dv%202%2Fplex"


def test_ntfy_failure_is_logged_not_raised(config, monkeypatch):
    config.set("notifications.ntfy_topic", "topic")

    def broken_urlopen(request, timeout=None):
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", broken_urlopen)
    logs = []

    assert send_ntfy(config, "x", logs.append) is False
    assert "offline" in logs[0]


def test_capture_completion_is_logged_and_handed_to_notifier():
    logs, notified = [], []
    engine = CaptureEngine(Path("ffmpeg"), log_callback=logs.append, notify_callback=notified.append)

    engine._notify_completion("Aufnahme beendet: Urlaub (1998)")

    assert "Aufnahme beendet: Urlaub (1998)" in logs
    assert notified == ["Aufnahme beendet: Urlaub (1998)"]


def test_capture_and_upscale_notifications_respect_the_setting(config, posted):
    capture = CaptureService(config, log_callback=lambda msg: None)
    postprocessing = PostprocessingService(config, log_callback=lambda msg: None)

    capture._notify("Merge abgeschlossen: Urlaub (1998)")
    postprocessing._notify_ntfy("Upscaling erfolgreich: Urlaub (1998)")
    assert posted == []

    config.set("notifications.ntfy_topic", "topic")
    capture._notify("Merge abgeschlossen: Urlaub (1998)")
    postprocessing._notify_ntfy("Upscaling erfolgreich: Urlaub (1998)")
    assert [r.full_url for r in posted] == ["https://ntfy.sh/topic", "https://ntfy.sh/topic"]
