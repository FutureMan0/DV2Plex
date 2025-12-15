"""
DV2Plex Desktop App (pywebview)

Startet die bestehende FastAPI Web-UI lokal (uvicorn) und zeigt sie in einem
eingebetteten Desktop-Fenster (pywebview) an.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Optional, Tuple

import uvicorn


def _fallback_open_in_browser(url: str, err: Exception) -> None:
    """Fallback wenn pywebview kein GUI-Backend (GTK/QT) laden kann."""
    import sys
    import webbrowser

    print(
        "DV2Plex: pywebview konnte kein GUI-Backend laden (GTK/QT fehlt). "
        f"Öffne stattdessen im Browser: {url}",
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


def _start_uvicorn_in_thread(host: str, port: int, log_level: str = "info") -> Tuple[uvicorn.Server, threading.Thread]:
    """
    Startet uvicorn in einem Background-Thread und gibt (server, thread) zurück.
    """
    from dv2plex import web_app as web

    # Services initialisieren, bevor der Server startet
    web.setup_services()

    config = uvicorn.Config(
        web.app,
        host=host,
        port=port,
        log_level=log_level,
        access_log=False,
    )
    server = uvicorn.Server(config)

    t = threading.Thread(target=server.run, name="dv2plex-uvicorn", daemon=True)
    t.start()
    return server, t


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
    - Andernfalls wird ein lokaler uvicorn-Server gestartet und in pywebview angezeigt.
    """
    # Modus 1: Nur URL öffnen (z.B. wenn der Webserver schon separat läuft)
    if url:
        try:
            import webview  # pywebview import-name
            webview.create_window(title, url, width=width, height=height)
            webview.start()
        except Exception as e:
            _fallback_open_in_browser(url, e)
        return

    # Modus 2: Lokalen Server starten und anzeigen
    if open_host is None:
        # Wenn wir auf 0.0.0.0 binden (für externen Zugriff), öffnen wir lokal über 127.0.0.1
        open_host = "127.0.0.1" if bind_host == "0.0.0.0" else bind_host

    if port is None:
        port = _pick_free_port(open_host)

    server, thread = _start_uvicorn_in_thread(host=bind_host, port=port, log_level=log_level)

    if not _wait_for_port(open_host, port, timeout_s=15.0):
        # Server konnte nicht starten -> beenden
        server.should_exit = True
        thread.join(timeout=2.0)
        raise RuntimeError(f"Webserver konnte nicht gestartet werden (http://{open_host}:{port})")

    local_url = f"http://{open_host}:{port}"
    try:
        import webview  # pywebview import-name
        webview.create_window(title, local_url, width=width, height=height)
        try:
            webview.start()
        finally:
            # pywebview ist geschlossen -> Server stoppen
            try:
                server.should_exit = True
            except Exception:
                pass
            thread.join(timeout=3.0)
    except Exception as e:
        # Fallback: Desktop-Wrapper nicht verfügbar -> Browser öffnen und Server laufen lassen
        _fallback_open_in_browser(local_url, e)
        try:
            thread.join()
        except KeyboardInterrupt:
            try:
                server.should_exit = True
            except Exception:
                pass
            thread.join(timeout=3.0)


