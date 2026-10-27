"""
CLI entry point for DV2Plex.

Provides two main modes:
- Server (headless): run only the FastAPI/uvicorn web server (no desktop window)
- Desktop: open the web UI in a pywebview desktop window (optionally against an existing URL)
"""

from __future__ import annotations

import argparse
from typing import Optional, Sequence


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DV2Plex - MiniDV Digitalisierung")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--server",
        action="store_true",
        help="Startet nur den Webserver (headless, kein Desktop-Fenster).",
    )
    mode.add_argument(
        "--desktop",
        action="store_true",
        help="Startet die Desktop-Web-App (Default).",
    )

    # Backwards compatibility
    p.add_argument(
        "--no-gui",
        action="store_true",
        help="Alias für --server (deprecated).",
    )

    p.add_argument(
        "--host",
        default=None,
        help="Bind host of the web server (default: 127.0.0.1). Any other host makes every API request need the token.",
    )
    p.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port (Server-Modus Default: 5000, Desktop Default: 0=auto).",
    )

    p.add_argument(
        "--url",
        default=None,
        help="Desktop: Öffnet diese URL (ohne eigenen Server zu starten). Beispiel: http://127.0.0.1:5000",
    )
    p.add_argument(
        "--share",
        action="store_true",
        help="Desktop: bindet den lokalen Server auf 0.0.0.0 (für Zugriff aus dem LAN); Fenster öffnet weiterhin 127.0.0.1.",
    )
    p.add_argument(
        "--show-token",
        action="store_true",
        help="Print the API token (created on first use) and exit.",
    )
    return p


def _show_token() -> None:
    from dv2plex.access import load_or_create_token
    from dv2plex.config import Config

    print(load_or_create_token(Config()))


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _build_parser().parse_args(argv)

    if args.show_token:
        _show_token()
        return

    server_mode = bool(args.server or args.no_gui)

    if server_mode:
        host = args.host or "127.0.0.1"
        port = args.port if args.port and args.port > 0 else 5000

        import uvicorn
        from dv2plex.web_app import app, setup_access, setup_services

        setup_services()
        setup_access(host, port)
        uvicorn.run(app, host=host, port=port, log_level="info")
        return

    # Desktop (default)
    if args.url:
        from dv2plex.desktop_app import main as desktop_main

        desktop_main(url=args.url)
        return

    bind_host = args.host or ("0.0.0.0" if args.share else "127.0.0.1")
    port = args.port if args.port and args.port > 0 else None

    from dv2plex.desktop_app import main as desktop_main

    desktop_main(bind_host=bind_host, port=port)


