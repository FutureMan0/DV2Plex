# Building the desktop app

The desktop app is the normal DV2Plex (web interface in a window) packaged with
[PyInstaller](https://pyinstaller.org/), so people can install it without Python. Releases
build it on GitHub Actions for Windows, macOS and Linux (`.github/workflows/release.yml`);
this page is for building it yourself.

## What is in it, and what is not

In: the interface, capture (Linux, with dvgrab), merge with the date overlay, ffmpeg
upscaling (`ffmpeg_hd`, `ffmpeg_fast`), the light poster, the Plex export, the demo mode,
and an ffmpeg build with libx264 and drawtext.

Not in: Real-ESRGAN (PyTorch) and Stable Diffusion covers. They need several gigabytes and a
GPU stack that matches the machine. Use the Python installation for those
([README](../README.md#installation)).

## Build

```bash
python -m venv .venv-build
. .venv-build/bin/activate            # Windows: .venv-build\Scripts\activate
pip install -r requirements-build.txt
python packaging/build.py             # downloads ffmpeg for this platform
python packaging/build.py --ffmpeg none           # without ffmpeg; the app uses the one on PATH
python packaging/build.py --ffmpeg path/to/folder # your own ffmpeg and ffprobe
```

The result is in `dist/`:

| Platform | File | Notes |
| :-- | :-- | :-- |
| Windows | `DV2Plex-<version>-windows-x64-setup.exe`, `…-portable.zip` | Installer needs [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`iscc`); installs per user |
| macOS | `DV2Plex-<version>-macos-<arch>.zip` | Contains `DV2Plex.app` |
| Linux | `DV2Plex-<version>-linux-x86_64.tar.gz` | `install.sh` puts it into `~/.local/opt/dv2plex` and the menu |

`build.py` refuses an ffmpeg without `libx264` or `drawtext`. It prints the SHA-256 of every
download and every package.

## Platform notes

- **Windows** needs the Microsoft Edge WebView2 runtime for the window. Windows 11 has it;
  on Windows 10 it comes with Edge, or from
  [Microsoft](https://developer.microsoft.com/microsoft-edge/webview2/).
- **macOS:** the app is not signed. The first start needs a right-click on `DV2Plex.app`,
  then *Open*.
- **Linux:** the window needs WebKitGTK and PyGObject in the build environment
  (`sudo apt install python3-gi gir1.2-webkit2-4.1 libgirepository1.0-dev libcairo2-dev`,
  then `pip install "PyGObject<3.51" pycairo`). Without them the app opens the interface in
  the browser instead. Build on the oldest distribution you want to support (glibc).

## Where the app keeps its data

| | Settings and logs | Captures (default) |
| :-- | :-- | :-- |
| Windows | `%APPDATA%\DV2Plex` | `%USERPROFILE%\Videos\DV2Plex` |
| macOS | `~/Library/Application Support/DV2Plex` | `~/Movies/DV2Plex` |
| Linux | `~/.config/dv2plex` | `~/Videos/DV2Plex` |

`DV2PLEX_HOME` moves all of it into one folder (the demo uses that).

## Updates

The app does not update itself. With *Look for a new version once a day* switched on (the
default in the app), it asks `api.github.com` for the latest release and shows a link to it.
