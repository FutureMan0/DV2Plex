#!/usr/bin/env python3
"""
Builds the DV2Plex desktop app for the platform it runs on.

    python packaging/build.py                 # with a downloaded ffmpeg (needs internet)
    python packaging/build.py --ffmpeg none   # without; the app uses the ffmpeg on PATH
    python packaging/build.py --ffmpeg /path/to/folder-with-ffmpeg-and-ffprobe

Needs: pip install -r requirements-build.txt (PyInstaller, pywebview, FastAPI, uvicorn,
Pillow). Windows also needs Inno Setup 6 (iscc) for the installer.

Output in dist/:
    Windows  DV2Plex-<version>-windows-x64-setup.exe and a portable .zip
    macOS    DV2Plex-<version>-macos-<arch>.zip (DV2Plex.app)
    Linux    DV2Plex-<version>-linux-x86_64.tar.gz (folder, install.sh, .desktop entry)

The builds are not signed. The ffmpeg that is bundled is a GPL build; its licence and
source are noted in THIRD_PARTY_NOTICES.md and copied next to it.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"

# Where a GPL ffmpeg with libx264 and drawtext comes from, per platform
FFMPEG_SOURCES = {
    "win32": [
        "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-7.1.1-essentials_build.zip",
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n7.1-latest-win64-gpl-7.1.zip",
    ],
    "darwin-arm64": [
        "https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffmpeg.zip",
        "https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffprobe.zip",
    ],
    "darwin-x86_64": [
        "https://ffmpeg.martin-riedl.de/redirect/latest/macos/amd64/release/ffmpeg.zip",
        "https://ffmpeg.martin-riedl.de/redirect/latest/macos/amd64/release/ffprobe.zip",
    ],
    "linux": ["https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"],
}


def version() -> str:
    namespace: dict = {}
    exec((ROOT / "dv2plex" / "__init__.py").read_text(encoding="utf-8"), namespace)
    return namespace["__version__"]


def run(cmd, **kwargs) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kwargs)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ------------------------------------------------------------------ icons

def make_icons() -> Path:
    from PIL import Image

    out = BUILD / "icons"
    out.mkdir(parents=True, exist_ok=True)
    source = Image.open(ROOT / "packaging" / "icon.png").convert("RGBA")
    source.save(out / "icon.png")
    source.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    if sys.platform == "darwin":
        iconset = out / "icon.iconset"
        iconset.mkdir(exist_ok=True)
        for size in (16, 32, 128, 256, 512):
            source.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
            source.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
        run(["iconutil", "-c", "icns", str(iconset), "-o", str(out / "icon.icns")])
    return out


# ------------------------------------------------------------------ ffmpeg

def _platform_key() -> str:
    if sys.platform == "win32":
        return "win32"
    if sys.platform == "darwin":
        return "darwin-arm64" if platform.machine() == "arm64" else "darwin-x86_64"
    return "linux"


def _download(url: str) -> bytes:
    print(f"Downloading {url}", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "DV2Plex-build"})
    with urllib.request.urlopen(request, timeout=300) as response:
        data = response.read()
    print(f"  {len(data) / 1e6:.1f} MB, sha256 {hashlib.sha256(data).hexdigest()}", flush=True)
    return data


def _extract_binaries(data: bytes, url: str, out: Path) -> None:
    wanted = {"ffmpeg", "ffprobe", "ffmpeg.exe", "ffprobe.exe"}
    licences = {"LICENSE", "LICENSE.txt", "COPYING.GPLv3", "GPLv3.txt", "readme.txt"}
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.namelist():
                name = Path(member).name
                if name in wanted or name in licences:
                    target = out / ("LICENSE.txt" if name in licences and name != "readme.txt" else name)
                    target.write_bytes(archive.read(member))
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as archive:
            for member in archive.getmembers():
                name = Path(member.name).name
                if member.isfile() and (name in wanted or name in ("GPLv3.txt", "readme.txt")):
                    extracted = archive.extractfile(member)
                    if extracted:
                        target = out / ("LICENSE.txt" if name == "GPLv3.txt" else name)
                        target.write_bytes(extracted.read())
    for name in wanted:
        path = out / name
        if path.exists():
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def fetch_ffmpeg() -> Path:
    out = BUILD / "ffmpeg"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    key = _platform_key()
    urls = FFMPEG_SOURCES[key]
    if key == "win32":
        # Two alternative sources; the first that downloads wins
        for url in urls:
            try:
                _extract_binaries(_download(url), url, out)
                (out / "SOURCE.txt").write_text(f"Downloaded from {url}\n", encoding="utf-8")
                break
            except Exception as e:
                print(f"  failed: {e}", flush=True)
    else:
        for url in urls:
            _extract_binaries(_download(url), url, out)
        (out / "SOURCE.txt").write_text("Downloaded from:\n" + "\n".join(urls) + "\n", encoding="utf-8")
    return out


def check_ffmpeg(folder: Path) -> None:
    """The bundled ffmpeg must encode H.264 and draw text; otherwise the app would be crippled."""
    exe = folder / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if not exe.exists() or not (folder / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")).exists():
        raise SystemExit(f"ffmpeg or ffprobe missing in {folder}")
    encoders = subprocess.run([str(exe), "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    filters = subprocess.run([str(exe), "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    missing = [n for n, ok in (("libx264", "libx264" in encoders), ("drawtext", " drawtext " in filters)) if not ok]
    if missing:
        raise SystemExit(f"The ffmpeg in {folder} lacks {', '.join(missing)}")
    first = subprocess.run([str(exe), "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    print(f"Bundling {first}", flush=True)


# ------------------------------------------------------------------ packages

def package(ver: str) -> list:
    made = []
    if sys.platform == "win32":
        folder = DIST / "DV2Plex"
        portable = DIST / f"DV2Plex-{ver}-windows-x64-portable.zip"
        shutil.make_archive(str(portable.with_suffix("")), "zip", DIST, "DV2Plex")
        made.append(portable)
        iscc = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
        if Path(iscc).exists():
            run([iscc, f"/DMyAppVersion={ver}", str(ROOT / "packaging" / "windows" / "dv2plex.iss")])
            made.append(DIST / f"DV2Plex-{ver}-windows-x64-setup.exe")
        else:
            print("Inno Setup not found; only the portable zip was made.")
        assert folder.exists()
    elif sys.platform == "darwin":
        arch = "arm64" if platform.machine() == "arm64" else "x86_64"
        target = DIST / f"DV2Plex-{ver}-macos-{arch}.zip"
        run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(DIST / "DV2Plex.app"), str(target)])
        made.append(target)
    else:
        staging = BUILD / "linux-package" / f"DV2Plex-{ver}"
        shutil.rmtree(staging.parent, ignore_errors=True)
        shutil.copytree(DIST / "DV2Plex", staging / "DV2Plex", symlinks=True)
        for name in ("install.sh", "dv2plex.desktop"):
            shutil.copy2(ROOT / "packaging" / "linux" / name, staging / name)
        shutil.copy2(BUILD / "icons" / "icon.png", staging / "dv2plex.png")
        shutil.copy2(ROOT / "LICENSE", staging / "LICENSE")
        shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", staging / "THIRD_PARTY_NOTICES.md")
        (staging / "install.sh").chmod(0o755)
        target = DIST / f"DV2Plex-{ver}-linux-x86_64.tar.gz"
        with tarfile.open(target, "w:gz") as archive:
            archive.add(staging, arcname=staging.name)
        made.append(target)
    return made


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ffmpeg", default="auto", help="auto (download), none, or a folder with ffmpeg and ffprobe")
    args = parser.parse_args()

    ver = version()
    print(f"Building DV2Plex {ver} for {_platform_key()}", flush=True)
    icons = make_icons()
    env = dict(os.environ, DV2PLEX_ICON_DIR=str(icons))

    if args.ffmpeg != "none":
        folder = fetch_ffmpeg() if args.ffmpeg == "auto" else Path(args.ffmpeg)
        check_ffmpeg(folder)
        shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", folder / "NOTICE-DV2Plex.md")
        env["DV2PLEX_FFMPEG_DIR"] = str(folder)

    shutil.rmtree(DIST, ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(DIST),
         "--workpath", str(BUILD / "pyinstaller"), str(ROOT / "packaging" / "dv2plex.spec")], env=env, cwd=ROOT)

    for path in package(ver):
        print(f"{path.name}: {path.stat().st_size / 1e6:.1f} MB, sha256 {sha256(path)}")


if __name__ == "__main__":
    main()
