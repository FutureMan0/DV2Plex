import json
import logging
import subprocess
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import dv2plex.config as config_module
from dv2plex import access, cli, desktop_app, web_app
from dv2plex.access import ALWAYS_PROTECTED_PATHS, TOKEN_ENV
from dv2plex.config import Config

PROTECTED_POSTS = ["/api/chown", "/api/update/run", "/api/fix-config-permissions"]


@pytest.fixture
def start_server(monkeypatch, tmp_path):
    """Runs setup_access() for a bind host against a fresh settings folder."""

    def no_commands(cmd, *args, **kwargs):
        # The sudo routes must never run a real command here, even if the token check broke.
        raise AssertionError(f"test tried to run {cmd!r}")

    monkeypatch.setattr(subprocess, "run", no_commands)
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(web_app, "config", Config())
    monkeypatch.setattr(web_app, "api_token", None)
    monkeypatch.setattr(web_app, "token_required_everywhere", False)
    monkeypatch.delenv(TOKEN_ENV, raising=False)

    def start(host, base_url="http://127.0.0.1:5000"):
        token = web_app.setup_access(host, 5000)
        return TestClient(web_app.app, base_url=base_url), token

    return start


# --- which requests need the token ------------------------------------------------------

@pytest.mark.parametrize("host,loopback", [
    ("127.0.0.1", True), ("localhost", True), ("::1", True),
    ("0.0.0.0", False), ("::", False), ("192.168.1.20", False),
])
def test_is_loopback(host, loopback):
    assert access.is_loopback(host) is loopback


def test_protected_routes_need_the_token_on_every_host():
    for path in ALWAYS_PROTECTED_PATHS:
        assert access.requires_token(path, token_everywhere=False)
    assert not access.requires_token("/api/status", token_everywhere=False)
    assert not access.requires_token("/ws", token_everywhere=False)


def test_network_bind_protects_api_and_websocket_but_not_the_page():
    assert access.requires_token("/api/status", token_everywhere=True)
    assert access.requires_token("/ws", token_everywhere=True)
    assert not access.requires_token("/", token_everywhere=True)


# --- token storage ----------------------------------------------------------------------

def test_token_is_created_once_and_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    monkeypatch.delenv(TOKEN_ENV, raising=False)

    first = access.load_or_create_token(Config())
    second = access.load_or_create_token(Config())

    assert len(first) >= 32
    assert first == second
    saved = json.loads((tmp_path / "settings.local.json").read_text(encoding="utf-8"))
    assert saved["server"]["api_token"] == first


def test_environment_token_wins_and_is_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setenv(TOKEN_ENV, "from-the-environment")

    assert access.load_or_create_token(Config()) == "from-the-environment"
    saved = json.loads((tmp_path / "settings.local.json").read_text(encoding="utf-8"))
    assert saved["server"]["api_token"] == ""


def test_token_is_redacted_from_uvicorn_log_lines():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/api/player/stream?path=a.mp4&token=s3cret", "1.1", 200), None,
    )

    access.RedactTokenFilter().filter(record)

    assert "s3cret" not in record.getMessage()
    assert "token=***" in record.getMessage()


# --- server on 127.0.0.1 ----------------------------------------------------------------

def test_local_server_leaves_ordinary_routes_open(start_server):
    client, _ = start_server("127.0.0.1")

    assert client.get("/api/status").status_code == 200
    assert client.get("/").status_code == 200


@pytest.mark.parametrize("path", PROTECTED_POSTS)
def test_local_server_refuses_sudo_routes_without_token(start_server, path, tmp_path):
    client, _ = start_server("127.0.0.1")

    assert client.post(path, json={"path": str(tmp_path / "missing")}).status_code == 401


def test_local_server_refuses_browse_without_or_with_wrong_token(start_server, tmp_path):
    client, _ = start_server("127.0.0.1")

    assert client.get("/api/browse", params={"path": str(tmp_path)}).status_code == 401
    assert client.get(
        "/api/browse", params={"path": str(tmp_path)}, headers={"X-DV2Plex-Token": "wrong"}
    ).status_code == 401


@pytest.mark.parametrize("path", ["/api/browse/", "/api/%62rowse"])
def test_path_variants_do_not_bypass_the_token(start_server, tmp_path, path):
    client, _ = start_server("127.0.0.1")

    response = client.get(f"{path}?path={tmp_path}", follow_redirects=True)

    assert response.status_code == 401


def test_token_opens_protected_routes(start_server, tmp_path):
    client, token = start_server("127.0.0.1")
    (tmp_path / "Filme").mkdir()

    by_header = client.get("/api/browse", params={"path": str(tmp_path)}, headers={"X-DV2Plex-Token": token})
    by_bearer = client.get("/api/browse", params={"path": str(tmp_path)}, headers={"Authorization": f"Bearer {token}"})
    by_query = client.get("/api/browse", params={"path": str(tmp_path), "token": token})

    assert by_header.status_code == by_bearer.status_code == by_query.status_code == 200
    assert "Filme" in [entry["name"] for entry in by_header.json()["entries"]]
    # Past the token check; fails later because no update manager runs in the test.
    update = client.post("/api/update/run", headers={"X-DV2Plex-Token": token})
    assert update.status_code == 500


def test_local_websocket_needs_no_token(start_server):
    client, _ = start_server("127.0.0.1")

    with client.websocket_connect("ws://127.0.0.1:5000/ws") as ws:
        assert ws.receive_json()["type"] == "status"


# --- server on 0.0.0.0 ------------------------------------------------------------------

def test_network_server_needs_token_for_every_api_route(start_server):
    client, token = start_server("0.0.0.0")

    assert client.get("/api/status").status_code == 401
    assert client.get("/api/settings").status_code == 401
    assert client.get("/api/status", headers={"X-DV2Plex-Token": token}).status_code == 200
    # The page itself loads, so it can ask for the token.
    assert client.get("/").status_code == 200


def test_network_websocket_needs_token(start_server):
    client, token = start_server("0.0.0.0")

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://127.0.0.1:5000/ws") as ws:
            ws.receive_json()

    with client.websocket_connect(f"ws://127.0.0.1:5000/ws?token={token}") as ws:
        assert ws.receive_json()["type"] == "status"


def test_settings_api_does_not_return_the_token(start_server):
    client, token = start_server("127.0.0.1")

    response = client.get("/api/settings")

    assert response.status_code == 200
    assert token not in response.text
    assert response.json()["update_enabled"] is False


# --- command line -----------------------------------------------------------------------

@pytest.fixture
def no_server(monkeypatch):
    """Replaces uvicorn and the service setup; records where the server would listen."""
    import uvicorn

    calls = {}
    monkeypatch.setattr(web_app, "setup_services", lambda **kw: calls.setdefault("services", kw))
    monkeypatch.setattr(cli, "_setup_logging", lambda: None)
    monkeypatch.setattr(web_app, "setup_access", lambda host, port=None: calls.setdefault("access", (host, port)))
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port, **kw: calls.setdefault("run", (host, port)))
    monkeypatch.setattr(desktop_app, "main", lambda **kw: calls.setdefault("desktop", kw))
    return calls


@pytest.mark.parametrize("argv,expected", [
    (["--server"], ("127.0.0.1", 5000)),
    (["--no-gui"], ("127.0.0.1", 5000)),
    (["--server", "--host", "0.0.0.0", "--port", "8080"], ("0.0.0.0", 8080)),
])
def test_server_mode_bind_host(no_server, argv, expected):
    cli.main(argv)

    assert no_server["run"] == expected
    assert no_server["access"] == expected


@pytest.mark.parametrize("argv,bind_host", [
    ([], "127.0.0.1"),
    (["--share"], "0.0.0.0"),
    (["--host", "192.168.1.20"], "192.168.1.20"),
])
def test_desktop_mode_bind_host(no_server, argv, bind_host):
    cli.main(argv)

    assert no_server["desktop"]["bind_host"] == bind_host


def test_show_token_prints_the_saved_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    monkeypatch.delenv(TOKEN_ENV, raising=False)

    cli.main(["--show-token"])
    first = capsys.readouterr().out.strip()
    cli.main(["--show-token"])
    second = capsys.readouterr().out.strip()

    assert first and first == second
    assert Config().get("server.api_token") == first


def test_desktop_window_opens_with_the_token(monkeypatch):
    opened = {}
    server = SimpleNamespace(should_exit=False)
    thread = SimpleNamespace(join=lambda timeout=None: None)
    monkeypatch.setattr(desktop_app, "_start_uvicorn_in_thread", lambda host, port, log_level: (server, thread, "tok-123"))
    monkeypatch.setattr(desktop_app, "_wait_for_port", lambda host, port, timeout_s: True)
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(
        create_window=lambda title, url, **kw: opened.setdefault("url", url),
        start=lambda: None,
    ))

    desktop_app.main(bind_host="127.0.0.1", port=5123)

    assert opened["url"] == "http://127.0.0.1:5123/?token=tok-123"


# --- other web pages (DNS rebinding, cross-site requests) -------------------------------

@pytest.mark.parametrize("host", ["127.0.0.1:5000", "localhost:5000", "[::1]:5000", "127.0.0.1", "LOCALHOST:5000"])
def test_local_server_answers_to_its_own_names(host):
    assert access.host_allowed(host, loopback_only=True)


@pytest.mark.parametrize("host", ["evil.example:5000", "192.168.1.20:5000", "", "127.0.0.1.evil.example"])
def test_local_server_refuses_other_host_names(host):
    assert not access.host_allowed(host, loopback_only=True)


def test_extra_host_names_can_be_allowed():
    assert access.host_allowed("dv2plex.lan:5000", loopback_only=True, extra_hosts=["dv2plex.lan"])
    assert access.host_allowed("anything:5000", loopback_only=False)


@pytest.mark.parametrize("origin,host,allowed", [
    (None, "127.0.0.1:5000", True),
    ("http://127.0.0.1:5000", "127.0.0.1:5000", True),
    ("https://dv.example.org", "dv.example.org", True),
    ("http://evil.example", "127.0.0.1:5000", False),
    ("http://127.0.0.1:6000", "127.0.0.1:5000", False),
    ("null", "127.0.0.1:5000", False),
    ("file://", "127.0.0.1:5000", False),
])
def test_origin_has_to_match_the_host(origin, host, allowed):
    assert access.origin_allowed(origin, host) is allowed


def test_dns_rebinding_host_is_refused(start_server):
    client, _ = start_server("127.0.0.1", base_url="http://rebind.evil.example:5000")

    assert client.get("/api/status").status_code == 421
    assert client.get("/").status_code == 421


def test_cross_site_post_is_refused_even_on_open_routes(start_server, tmp_path):
    client, _ = start_server("127.0.0.1")

    refused = client.post("/api/project/delete", json={"paths": [str(tmp_path)]},
                          headers={"Origin": "http://evil.example"})
    settings = client.post("/api/settings", json={"auto_export": True}, headers={"Origin": "http://evil.example"})

    assert refused.status_code == 403
    assert settings.status_code == 403
    assert web_app.config.get("capture.auto_export") is False


def test_same_page_post_and_scripts_without_origin_pass(start_server):
    client, _ = start_server("127.0.0.1")

    same_page = client.post("/api/settings", json={"auto_export": False}, headers={"Origin": "http://127.0.0.1:5000"})
    script = client.post("/api/settings", json={"auto_export": False})

    assert same_page.status_code == 200
    assert script.status_code == 200


def test_cross_site_websocket_is_refused(start_server):
    client, _ = start_server("127.0.0.1")

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://127.0.0.1:5000/ws", headers={"Origin": "http://evil.example"}) as ws:
            ws.receive_json()
    with client.websocket_connect("ws://127.0.0.1:5000/ws", headers={"Origin": "http://127.0.0.1:5000"}) as ws:
        assert ws.receive_json()["type"] == "status"


def test_server_mode_reads_the_host_setting(no_server, monkeypatch):
    monkeypatch.setitem(web_app.config.config["server"], "host", "0.0.0.0")

    cli.main(["--server"])

    assert no_server["run"] == ("0.0.0.0", 5000)
    assert no_server["services"] == {"mode": "server"}
