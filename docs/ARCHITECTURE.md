# How DV2Plex is built

A Python program with a web interface. The same server runs headless on a Linux box with a
FireWire card, or behind a desktop window (pywebview) on the computer in front of you.

## Layout

```
dv2plex/
├── cli.py              command line: desktop window, --server, --url, --demo, --demo-run
├── desktop_app.py      pywebview window around the local server; browser fallback
├── web_app.py          FastAPI app, shared state, access rules, WebSocket broadcast
├── api/                the HTTP routes
│   ├── capture.py      start/stop, camera control, status, merge queue, live preview
│   ├── library.py      upscaling list, Plex export, video player, merging films, deleting
│   ├── covers.py       frames, Stable Diffusion covers, posters
│   ├── system.py       settings, info, updates (git and GitHub Releases), logs, folder browser
│   └── live.py         the WebSocket
├── access.py           API token, Host and Origin checks
├── service.py          the services the routes call (capture, postprocessing, export, covers)
├── capture/            dvgrab capture
│   ├── engine.py       one capture: start, monitor, stop, finalize once
│   ├── dvgrab.py       device detection, command lines, sudo, the two dvgrab processes
│   ├── preview.py      live preview from the clips being written
│   ├── merge_queue.py  merges captured tapes one after another
│   └── processes.py    stopping and reading child processes on every platform
├── merge.py            joins the clips of a tape (date overlay), joins finished films
├── upscale.py          Real-ESRGAN or ffmpeg upscaling, aspect, deinterlacing, progress
├── media.py            ffprobe, output geometry, running ffmpeg with progress
├── plex_export.py      copies films and posters into the library under Title (Year)
├── naming.py           folder-safe titles, years
├── simple_poster.py    a poster from one frame, title and year (Pillow)
├── poster_generation.py, cover_generation.py   the full poster and Stable Diffusion covers (optional libraries)
├── frame_extraction.py frames for covers
├── notifications.py    ntfy push messages (off unless a topic is set)
├── update_manager.py   git updates of a server installation
├── release_check.py    the desktop app's look at GitHub Releases
├── instance.py         one running instance per settings folder
├── config.py           settings: defaults, settings.local.json, folders of the packaged app
├── log_setup.py        console and rotating log file, token masked
├── demo.py, fake_dvgrab.py   demo mode and the simulated camera
├── web/                the interface: index.html, index.css, index.js, i18n.json
└── bin/realesrgan/     Real-ESRGAN, vendored and patched (see THIRD_PARTY_NOTICES.md)
packaging/              desktop app: PyInstaller spec, build script, installer scripts, icon
scripts/                screenshots, browser smoke test, changelog section for releases
```

## One tape, from camera to Plex

1. **Capture** (`capture/engine.py`): `dvgrab -autosplit -t` writes one DV clip per scene into
   `DV_Import/<Title (Year)>/LowRes/splits/`, named after its recording time. The preview
   pipeline plays each finished clip through ffmpeg as JPEG frames to the WebSocket.
2. **Finalize** when the tape ends or the user stops: the camera rewinds (a second,
   interactive dvgrab), new captures wait for it, the clips go into the merge queue.
3. **Merge** (`capture/merge_queue.py` → `merge.py`): sorted by recording time, joined with the
   concat demuxer, H.264/AAC, the recording date drawn at the start of each scene →
   `LowRes/movie_merged.mp4`.
4. **Upscale** (`service.PostprocessingService` → `upscale.py`), started from the Upscaling tab or
   automatically (`capture.auto_postprocess`) → `HighRes/<Title (Year)>_4k.mp4`.
5. **Poster** (`service.CoverService`) → `HighRes/poster.jpg`.
6. **Export** (`plex_export.py`) → `<Plex library>/<Title (Year)>/<Title (Year)>.mp4` and
   `poster.jpg`, copied under a temporary name and renamed at the end.

Long work runs in worker threads (merge queue, postprocessing queue, poster queue); the
routes that touch the disk run in FastAPI's thread pool, so the event loop and the
WebSocket never wait for ffmpeg.

## Settings

`config.Config` merges `dv2plex/config/settings.local.json` over the defaults in `config.py`.
`DV2PLEX_HOME` moves settings, logs and the default folders into one folder (the demo uses
it); the packaged app uses the user's config and video folders. The settings page writes
through `POST /api/settings`, which validates the values.

## Tests

`dv2plex/test_*.py`, run with `pytest`. The end-to-end tests (`test_e2e_demo.py`,
`test_capture_engine.py`) use the simulated dvgrab and real ffmpeg; `conftest.py` makes every
subprocess fail that would run `sudo`, `systemctl`, `chown` or a real `dvgrab`.
`scripts/ui_smoke.py` drives the interface in Chromium.
