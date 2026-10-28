"""
CLI entry point for DV2Plex.

Modes:
- Desktop (default): the web interface in a desktop window (pywebview), with its own
  local server, or against a server elsewhere (--url)
- Server (--server): only the web server, headless
- Demo (--demo): either of the above on a separate demo workspace with a simulated camera
- Demo run (--demo-run): the whole chain once, without a window, with a report
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from dv2plex import __version__


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dv2plex",
        description="DV2Plex: MiniDV tapes to a Plex library.",
    )

    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--server",
        action="store_true",
        help="Run only the web server (headless, no window).",
    )
    mode.add_argument(
        "--desktop",
        action="store_true",
        help="Open the desktop window (default).",
    )

    # Backwards compatibility
    p.add_argument(
        "--no-gui",
        action="store_true",
        help="Same as --server (deprecated).",
    )

    p.add_argument(
        "--host",
        default=None,
        help="Bind host of the web server (default: server.host from the settings, else 127.0.0.1). "
        "Any other host makes every API request need the token.",
    )
    p.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port (server default: 5000, desktop default: a free port).",
    )

    p.add_argument(
        "--url",
        default=None,
        help="Desktop: open this URL instead of starting a server, e.g. http://192.168.1.20:5000/?token=...",
    )
    p.add_argument(
        "--share",
        action="store_true",
        help="Desktop: also make the window's server reachable on the LAN (binds 0.0.0.0).",
    )
    p.add_argument(
        "--show-token",
        action="store_true",
        help="Print the API token (created on first use) and exit.",
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="Use a demo workspace with a simulated camera; your settings and folders stay untouched.",
    )
    p.add_argument(
        "--demo-run",
        action="store_true",
        help="Run capture, merge, upscale, poster and export once on the demo workspace and print a report.",
    )
    p.add_argument(
        "--demo-dir",
        default=None,
        help="Folder of the demo workspace (default: ~/DV2Plex-Demo).",
    )
    p.add_argument(
        "--seed-demo",
        action="store_true",
        help="Fill the demo workspace with sample tapes (for screenshots) and exit.",
    )
    p.add_argument("--version", action="version", version=f"DV2Plex {__version__}")
    return p


def _show_token() -> None:
    from dv2plex.access import load_or_create_token
    from dv2plex.config import Config

    print(load_or_create_token(Config()))


def _setup_logging() -> None:
    from dv2plex.config import Config
    from dv2plex.log_setup import setup_logging

    log_file = setup_logging(Config())
    if log_file:
        import logging

        logging.getLogger("dv2plex").info("DV2Plex %s, log file %s", __version__, log_file)


def _reattach_stdio() -> None:
    """
    The Windows app is a window app (console=False): PyInstaller then sets sys.stdin and
    sys.stderr to None, even when DV2Plex started it with pipes. As the simulated dvgrab it
    must read keys from stdin and report on stderr, so use the pipe handles it was given.
    """
    for name, fd, mode in (("stdin", 0, "r"), ("stdout", 1, "w"), ("stderr", 2, "w")):
        if getattr(sys, name) is None:
            try:
                setattr(sys, name, open(fd, mode, encoding="utf-8", errors="replace", closefd=False,
                                        buffering=1 if mode == "w" else -1))
            except OSError:
                pass  # no handle: stays None, fake_dvgrab copes without


def main(argv: Optional[Sequence[str]] = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)

    # The packaged app starts itself as the simulated dvgrab in the demo
    if argv[:1] == ["--fake-dvgrab"]:
        from dv2plex.fake_dvgrab import main as fake_main

        _reattach_stdio()
        sys.exit(fake_main(argv[1:]))

    args = _build_parser().parse_args(argv)

    if args.demo or args.demo_run or args.seed_demo:
        # Before anything reads the settings: switch to the demo workspace
        from dv2plex.demo import prepare_demo_home

        home = prepare_demo_home(Path(args.demo_dir) if args.demo_dir else None)
        print(f"DV2Plex demo workspace: {home}", file=sys.stderr)

    if args.show_token:
        _show_token()
        return

    if args.seed_demo:
        from dv2plex.demo import seed_demo_projects

        seed_demo_projects()
        return

    if args.demo_run:
        from dv2plex.demo import run_pipeline

        report = run_pipeline()
        print(report.text())
        sys.exit(0 if report.ok else 1)

    _setup_logging()
    server_mode = bool(args.server or args.no_gui)

    if server_mode:
        port = args.port if args.port and args.port > 0 else 5000

        import uvicorn
        from dv2plex.web_app import app, config, setup_access, setup_services

        host = args.host or str(config.get("server.host", "") or "").strip() or "127.0.0.1"
        setup_services(mode="server")
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
