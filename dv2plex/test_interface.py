"""The web interface: every text exists in English and German, and the page is served whole."""

import json
import re
from pathlib import Path

from dv2plex import web_app

WEB = Path(__file__).parent / "web"
TEXTS = json.loads((WEB / "i18n.json").read_text(encoding="utf-8"))


def _keys_used():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "index.js").read_text(encoding="utf-8")
    keys = set(re.findall(r'data-i18n(?:-placeholder|-aria-label|-alt)?="([^"]+)"', html))
    keys |= set(re.findall(r"\bt\('([a-z_]+\.[a-z0-9_.]+)'", js))
    # Keys built at run time
    keys |= {f"capture.sent_{a}" for a in ("rewind", "play", "pause")}
    keys |= {f"job.{s}" for s in ("pending", "running", "completed", "failed")}
    keys |= {f"facts.mode_{m}" for m in ("server", "desktop")}
    return keys


def test_both_languages_have_the_same_texts():
    assert set(TEXTS["en"]) == set(TEXTS["de"]), sorted(set(TEXTS["en"]) ^ set(TEXTS["de"]))


def test_every_text_the_interface_uses_exists():
    missing = sorted(k for k in _keys_used() if k not in TEXTS["en"])
    assert not missing, missing


def test_placeholders_match_between_languages():
    for key, english in TEXTS["en"].items():
        assert set(re.findall(r"\{(\w+)\}", english)) == set(re.findall(r"\{(\w+)\}", TEXTS["de"][key])), key


def test_page_is_served_with_texts_inline(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import dv2plex.config as config_module
    from dv2plex.config import Config

    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(web_app, "config", Config())
    web_app.setup_access("127.0.0.1", 5000)
    page = TestClient(web_app.app, base_url="http://127.0.0.1:5000").get("/").text

    assert '<script id="i18n" type="application/json">' in page
    assert "user-scalable=no" not in page
    assert "fonts.googleapis.com" not in page  # works offline, sends nothing to Google
    assert "innerHTML" not in (WEB / "index.js").read_text(encoding="utf-8")
