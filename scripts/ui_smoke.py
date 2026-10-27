#!/usr/bin/env python3
"""
Drives the interface in a real browser against the demo camera, the way a person would:

1. enters title and year, starts the recording (the simulated tape plays in real time)
2. waits for live preview frames, stops the recording
3. waits for the merge in the merge queue, the automatic upscaling and the Plex export
4. finds the film in the Plex export list and plays it in the video player
5. checks the keyboard (tab list with arrow keys), the German texts and the validation

    python scripts/ui_smoke.py [--headed] [--shots DIR]

Needs ffmpeg, Pillow and Playwright with Chromium. Uses a temporary demo workspace.
Prints one line per check and exits with 1 if one fails.
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
results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"{'ok  ' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--shots", default=None, help="save screenshots of the steps here")
    args = parser.parse_args()
    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    demo = Path(tempfile.mkdtemp(prefix="dv2plex-ui-"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, PYTHONPATH=str(ROOT), DV2PLEX_DEMO_SCENES="5", DV2PLEX_DEMO_SCENE_SECONDS="3",
               DV2PLEX_DEMO_REALTIME="1")
    server = subprocess.Popen(
        [sys.executable, "-m", "dv2plex", "--demo", "--server", "--port", str(port), "--demo-dir", str(demo)],
        env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}/"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "api/status", timeout=2)
                break
            except OSError:
                time.sleep(0.3)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not args.headed)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.add_init_script("try { localStorage.setItem('dv2plex_language', 'en'); } catch (e) {}")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="networkidle")

            page.wait_for_function("document.querySelector('#chip-connection').dataset.state === 'ok'", timeout=10000)
            check("live connection", True)

            # Validation: a two-digit year is refused before anything starts
            page.fill("#capture-title", "Konfirmation Max")
            page.fill("#capture-year", "04")
            page.click("#capture-start-btn")
            check("year validation", page.get_attribute("#capture-year", "aria-invalid") == "true"
                  and page.is_visible("#capture-year-error"))

            page.fill("#capture-year", "2004")
            page.click("#capture-start-btn")
            page.wait_for_selector("#capture-rec:not([hidden])", timeout=15000)
            check("recording starts", True)
            page.wait_for_selector("#preview-img:not([hidden])", timeout=30000)
            src = page.get_attribute("#preview-img", "src") or ""
            check("live preview frame", src.startswith("data:image/jpeg;base64,"), f"{len(src)} bytes")
            page.wait_for_timeout(1500)
            if shots:
                page.screenshot(path=str(shots / "ui-recording.png"))
            elapsed = page.text_content("#capture-elapsed")
            check("recording time runs", elapsed not in ("--:--:--", "00:00:00"), elapsed)

            page.click("#capture-stop-btn")
            page.wait_for_selector("#capture-rec", state="hidden", timeout=30000)
            check("stop", True, page.text_content("#capture-status"))

            # Merge, automatic upscaling and export (the demo switches those on)
            page.click("#tab-queue")
            page.wait_for_selector("#queue-list .badge.ok, #queue-current .badge.busy", timeout=60000)
            if shots:
                page.screenshot(path=str(shots / "ui-queue.png"))
            page.wait_for_selector("#queue-list .badge.ok", timeout=120000)
            check("merge done in the queue", True)

            page.click("#tab-movie")
            plex_film = demo / "PlexMovies" / "Konfirmation Max (2004)" / "Konfirmation Max (2004).mp4"
            deadline = time.time() + 180
            while time.time() < deadline and not plex_film.exists():
                time.sleep(1)
            check("film arrives in the Plex folder by itself", plex_film.exists(), str(plex_film))
            page.click("#movie-refresh")
            page.wait_for_selector("#movie-list .badge.ok", timeout=15000)
            check("export list shows it in Plex", "Konfirmation Max (2004)" in page.text_content("#movie-list"))

            page.click("#tab-player")
            page.wait_for_selector(".file-chip", timeout=15000)
            chips = page.locator(".file-chip")
            chips.last.click()
            page.wait_for_function("!document.querySelector('#player-video').hidden && document.querySelector('#player-video').readyState >= 1",
                                   timeout=20000)
            duration = page.evaluate("document.querySelector('#player-video').duration")
            check("video player plays the upscaled film", duration and duration > 1, f"{duration:.1f} s")

            # Keyboard: arrow keys move between tabs
            page.focus("#tab-player")
            page.keyboard.press("ArrowRight")
            focused = page.evaluate("document.activeElement.id")
            check("arrow keys move through the tabs", focused == "tab-logs", focused)
            page.wait_for_selector("#system-logs li", timeout=10000)
            check("log shows entries", page.locator("#system-logs li").count() > 5)

            # German
            page.evaluate("window.dv2plex.setLanguage('de')")
            check("German texts", page.text_content("#tab-capture") .strip() == "Digitalisieren"
                  and page.get_attribute("html", "lang") == "de")

            check("no script errors", not errors, "; ".join(errors)[:300])
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    print("RESULT:", "PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
