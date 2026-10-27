"""
DV2Plex Desktop App (pywebview)

Startet die bestehende FastAPI Web-UI lokal (uvicorn) und zeigt sie in einem
eingebetteten Desktop-Fenster (pywebview) an. Without a GUI backend (no WebView2,
WebKitGTK or Qt) the interface opens in the browser instead and the server keeps running.
"""

from __future__ import annotations

import logging
import socket
import sys
import threading
import time
from typing import Optional, Tuple
from urllib.parse import quote

import uvicorn

logger = logging.getLogger(__name__)


def _fallback_open_in_browser(url: str, err: Exception) -> None:
    """Fallback wenn pywebview kein GUI-Backend laden kann."""
    import webbrowser

    print(
        "DV2Plex: no window could be opened (pywebview found no WebView2, WebKitGTK or Qt). "
        "Opening the browser instead; close this program with Ctrl+C.",
        file=sys.stderr,
    )
    print(f"Details: {err}", file=sys.stderr)
    webbrowser.open(url)


def _pick_free_port(host: str = "127.0.0.1") -> int:
    """Findet einen freien TCP-Port auf dem angegebenen Host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def _wait_for_port(host: str, port: int, timeout_s: float = 10.0) -> bool:
    """Wartet bis ein TCP-Port erreichbar ist."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _start_uvicorn_in_thread(host: str, port: int, log_level: str = "info") -> Tuple[uvicorn.Server, threading.Thread, str]:
    """Startet uvicorn in einem Background-Thread und gibt (server, thread, api_token) zurück."""
    from dv2plex import web_app as web

    web.setup_services(mode="desktop")
    token = web.setup_access(host, port)

    config = uvicorn.Config(
        web.app,
        host=host,
        port=port,
        log_level=log_level,
        access_log=False,
        # The packaged app has no console; uvicorn's own logging setup would expect one
        log_config=None if getattr(sys, "frozen", False) else uvicorn.config.LOGGING_CONFIG,
    )
    server = uvicorn.Server(config)

    t = threading.Thread(target=server.run, name="dv2plex-uvicorn", daemon=True)
    t.start()
    return server, t, token


def _window_size(default: Tuple[int, int]) -> Tuple[int, int]:
    try:
        from dv2plex.config import Config

        config = Config()
        return int(config.get("ui.window_width", default[0])), int(config.get("ui.window_height", default[1]))
    except Exception:
        return default


def _open_window(title: str, url: str, width: int, height: int, on_closed=None) -> None:
    import webview  # pywebview import-name

    try:
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    except Exception:
        pass
    window = webview.create_window(title, url, width=width, height=height, min_size=(760, 560))
    if on_closed is not None:
        try:
            # Quitting with Cmd+Q ends the process without returning from start()
            window.events.closed += on_closed
        except Exception:
            pass
    webview.start()


def main(
    url: Optional[str] = None,
    bind_host: str = "127.0.0.1",
    open_host: Optional[str] = None,
    port: Optional[int] = None,
    title: str = "DV2Plex",
    width: int = 1280,
    height: int = 800,
    log_level: str = "info",
) -> None:
    """
    Startet DV2Plex als Desktop-Web-App.

    - Wenn `url` gesetzt ist, wird **kein** lokaler Server gestartet, sondern nur die URL geöffnet.
    - Läuft schon ein DV2Plex mit denselben Einstellungen, öffnet sich ein Fenster darauf.
    - Andernfalls wird ein lokaler uvicorn-Server gestartet und in pywebview angezeigt.
    """
    width, height = _window_size((width, height))

    # Modus 1: Nur URL öffnen (z.B. wenn der Webserver schon separat läuft)
    if url:
        try:
            _open_window(title, url, width, height)
        except Exception as e:
            _fallback_open_in_browser(url, e)
        return

    from dv2plex import config as config_module
    from dv2plex import instance

    config_dir = config_module.CONFIG_DIR
    running = instance.running_instance(config_dir) if bind_host in ("127.0.0.1", "0.0.0.0") else None
    if running and port is None:
        from dv2plex.access import load_or_create_token

        token = load_or_create_token(config_module.Config())
        logger.info("DV2Plex already runs on port %s; opening a window on it.", running)
        existing = f"http://127.0.0.1:{running}/?token={quote(token, safe='')}"
        try:
            _open_window(title, existing, width, height)
        except Exception as e:
            _fallback_open_in_browser(existing, e)
        return

    # Modus 2: Lokalen Server starten und anzeigen
    if open_host is None:
        # Wenn wir auf 0.0.0.0 binden (für externen Zugriff), öffnen wir lokal über 127.0.0.1
        open_host = "127.0.0.1" if bind_host == "0.0.0.0" else bind_host

    if port is None:
        port = _pick_free_port(open_host)

    server, thread, token = _start_uvicorn_in_thread(host=bind_host, port=port, log_level=log_level)

    if not _wait_for_port(open_host, port, timeout_s=15.0):
        server.should_exit = True
        thread.join(timeout=2.0)
        raise RuntimeError(f"Webserver konnte nicht gestartet werden (http://{open_host}:{port})")
    instance.claim(config_dir, port)

    # The page keeps the token from the URL and sends it with every API request
    local_url = f"http://{open_host}:{port}/?token={quote(token, safe='')}"
    try:
        window_error: Optional[Exception] = None
        try:
            _open_window(title, local_url, width, height, on_closed=lambda: instance.release(config_dir))
        except Exception as e:
            window_error = e
        if window_error is None:
            # Fenster geschlossen -> Server stoppen
            server.should_exit = True
            thread.join(timeout=3.0)
            return
        # No window possible: the browser shows the interface and the server keeps running.
        # (It used to stop the server first when pywebview failed in start().)
        _fallback_open_in_browser(local_url, window_error)
        try:
            thread.join()
        except KeyboardInterrupt:
            server.should_exit = True
            thread.join(timeout=3.0)
    finally:
        instance.release(config_dir)
