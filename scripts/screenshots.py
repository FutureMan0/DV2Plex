#!/usr/bin/env python3
"""
Screenshots of the interface with demo data, for the README and for reviewing UI changes.

    python scripts/screenshots.py                  # seeds a demo workspace, writes docs/screenshots/
    python scripts/screenshots.py --out /tmp/shots --lang de

Needs ffmpeg, Pillow and Playwright with Chromium (pip install playwright Pillow;
python -m playwright install chromium). The demo workspace is a temporary folder unless
--demo-dir is given; your real settings are not touched.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABS = ["capture", "postprocess", "cover", "movie", "queue", "player", "logs", "settings"]


def free_port() -> int:
    # Chromium refuses some ports (5060, 5061, 6000 …); let the system pick one
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except OSError:
            time.sleep(0.3)
    raise SystemExit(f"Server did not answer at {url}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    parser.add_argument("--demo-dir", default=None)
    parser.add_argument("--lang", default="en", choices=["en", "de"])
    parser.add_argument("--no-seed", action="store_true", help="use the demo workspace as it is")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    demo_dir = Path(args.demo_dir) if args.demo_dir else Path(tempfile.mkdtemp(prefix="dv2plex-shots-"))
    env = dict(os.environ, PYTHONPATH=str(ROOT))

    if not args.no_seed and not (demo_dir / "DV_Import").exists():
        print(f"Seeding demo tapes into {demo_dir} …")
        subprocess.run([sys.executable, "-m", "dv2plex", "--seed-demo", "--demo-dir", str(demo_dir)], check=True, env=env, cwd=ROOT)

    port = free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "dv2plex", "--demo", "--server", "--port", str(port), "--demo-dir", str(demo_dir)],
        env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}/"
        wait_for(base + "api/status")
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            shots = [
                ("desktop", {"width": 1280, "height": 900}, "light", 1),
                ("desktop", {"width": 1280, "height": 900}, "dark", 1),
                ("mobile", {"width": 390, "height": 844}, "light", 2),
            ]
            for label, viewport, scheme, scale in shots:
                page = browser.new_page(viewport=viewport, device_scale_factor=scale, color_scheme=scheme)
                page.add_init_script(f"try {{ localStorage.setItem('dv2plex_language', '{args.lang}'); }} catch (e) {{}}")
                page.goto(base, wait_until="networkidle")
                # A sticky bar lands mid-page in a full-page capture
                page.add_style_tag(content=".savebar { position: static !important; }")
                page.evaluate(f"window.dv2plex.setLanguage('{args.lang}')")
                for index, tab in enumerate(TABS, start=1):
                    if label == "mobile" and tab not in ("capture", "movie", "player", "settings"):
                        continue
                    page.evaluate(f"window.dv2plex.activateTab('{tab}')")
                    page.wait_for_timeout(900)
                    name = f"{label}-{scheme}-{index}-{tab}.png" if label == "desktop" else f"mobile-{index}-{tab}.png"
                    page.screenshot(path=str(out / name), full_page=label == "desktop")
                if label == "desktop" and scheme == "light":
                    page.evaluate("window.dv2plex.openWizard()")
                    page.wait_for_timeout(600)
                    page.screenshot(path=str(out / "desktop-light-wizard.png"))
                page.close()
            browser.close()
        print(f"Screenshots in {out}")
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
