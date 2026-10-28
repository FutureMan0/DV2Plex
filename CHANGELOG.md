# Changelog

All notable changes to DV2Plex. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/): a major version breaks
something you set up, a minor one adds features, a patch fixes.

## [2.0.0] - unreleased

Breaking for servers reached over the network: see [docs/MIGRATION.md](docs/MIGRATION.md).

### Security

- The server listens on `127.0.0.1` by default and has an API token. On any other address
  every API request needs the token.
- On `127.0.0.1` only this machine's host names are answered, and requests that change
  something must come from the DV2Plex page itself (Host and Origin checks). Other web pages
  could delete projects or change settings before.
- Export, merge, upscaling, frames and posters accept only files inside the import folder.
  The export used to copy any readable file into the library.
- Titles and file names reach the page as text only (they went through `innerHTML`).
- No test can run `sudo`, `systemctl`, `chown` or a real `dvgrab` any more.

### Fixed

- Real-ESRGAN works again: the vendored copy lacked `realesrgan/version.py`, broke with
  torchvision 0.17 and later, and crashed on every machine without CUDA.
- NTSC tapes produced H.264 4:2:2, which most players refuse; every output is 4:2:0 now.
- Upscaled films keep the tape's aspect with square pixels (4:3 tapes: 2880 × 2160 in the 4K
  profiles); Real-ESRGAN films showed 4:3 tapes as 5:4.
- Every `GET /api/status` started a merge thread that never ended.
- A stopped capture was finalized twice (two merges, two rewinds).
- On Windows and macOS (case-insensitive file names) every clip was merged twice.
- `capture.auto_postprocess`, `capture.timestamp_overlay` and `timestamp_duration` did
  nothing; they work as the settings page says.
- The date overlay failing silently on an ffmpeg without `drawtext`; the log says so now.
- The desktop window ran `sudo systemctl enable` on start.
- The updater failed as root in a user's checkout ("dubious ownership") and could wait for
  a sudo password forever.
- Slow work (frame extraction) blocked every other request and the live view.
- When no window could be opened, the server stopped before the browser fallback opened.
- The live preview showed 4:3 tapes as 5:4.
- In the desktop app the demo camera found no ffmpeg (it looked only on PATH), and on
  Windows its messages never reached DV2Plex; the demo recorded nothing.

### Changed

- New interface: same tabs, English by default and German selectable, light and dark,
  accessible (keyboard, labels, contrast, screen readers), usable on a phone.
- DV is deinterlaced (bwdif) before upscaling; a profile can switch it off with
  `"deinterlace": false`.
- `capture.py` and `web_app.py` became packages of small modules (`dv2plex/capture/`,
  `dv2plex/api/`); the behaviour is pinned by tests.
- Settings live in `dv2plex/config/settings.local.json` (taken over once from the old,
  tracked `settings.json`).
- Automatic updates are off by default; the updater uses `sudo -n` and `git pull --ff-only`.
- `requirements.txt` no longer pulls `ntfy`, `scikit-learn` or PyInstaller.

### Added

- Desktop app for Windows (installer), macOS and Linux, built on GitHub Actions; it looks
  for new releases on GitHub instead of using git.
- First-start assistant: language, folders, camera check.
- Demo mode without a camera (`--demo`, `--demo-run`), backed by a simulated dvgrab; the
  end-to-end tests and the CI use it.
- `ffmpeg_hd` profile (plain HD, any computer), a light poster without the heavy libraries,
  `/api/info`, `server.host`, `server.allowed_hosts`, a rotating log file.
- Tests for capture, merge, upscale, export, access and the interface texts; CI on Linux,
  Windows and macOS.

### Removed

- `download_manager.py` (unused) and the old PyInstaller scripts.

## [1.0.0]

The version before this changelog: Linux capture with dvgrab, merge, Real-ESRGAN and ffmpeg
upscaling, Stable Diffusion covers, posters, Plex export, web interface and pywebview window.

[2.0.0]: https://github.com/FutureMan0/DV2Plex/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/FutureMan0/DV2Plex/releases/tag/v1.0.0
