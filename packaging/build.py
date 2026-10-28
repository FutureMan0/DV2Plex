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
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"

# Where a GPL ffmpeg with libx264 and drawtext comes from, per platform. Each entry is one
# alternative (a list of archives that together hold ffmpeg and ffprobe); the first one that
# downloads and passes check_ffmpeg() is bundled. "btbn:<platform>" is looked up in the latest
# BtbN release, because its file names carry the ffmpeg version and change with every release.
FFMPEG_SOURCES = {
    "win32": [
        ["btbn:win64"],
        ["https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"],
    ],
    "darwin-arm64": [[
        "https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffmpeg.zip",
        "https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffprobe.zip",
    ]],
    "darwin-x86_64": [[
        "https://ffmpeg.martin-riedl.de/redirect/latest/macos/amd64/release/ffmpeg.zip",
        "https://ffmpeg.martin-riedl.de/redirect/latest/macos/amd64/release/ffprobe.zip",
    ]],
    "linux": [
        ["btbn:linux64"],
        ["https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"],
    ],
}
BTBN_RELEASE = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"


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


def _download(url: str, headers: dict | None = None, attempts: int = 4) -> bytes:
    """Downloads with retries: the mirrors drop connections now and then (IncompleteRead)."""
    print(f"Downloading {url}", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "DV2Plex-build", **(headers or {})})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                data = response.read()
            break
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == attempts:
                raise
            print(f"  attempt {attempt}: {e}", flush=True)
        except Exception as e:  # IncompleteRead, timeouts, connection resets
            if attempt == attempts:
                raise
            print(f"  attempt {attempt}: {e!r}", flush=True)
        time.sleep(5 * attempt)
    print(f"  {len(data) / 1e6:.1f} MB, sha256 {hashlib.sha256(data).hexdigest()}", flush=True)
    return data


def _btbn_url(platform_name: str) -> str:
    """The GPL build of the newest ffmpeg release branch for win64 or linux64 in BtbN's latest release."""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
    release = json.loads(_download(BTBN_RELEASE, headers))
    pattern = re.compile(rf"^ffmpeg-n(\d+)\.(\d+)-latest-{platform_name}-gpl-\d+\.\d+\.(zip|tar\.xz)$")
    found = []
    for asset in release.get("assets", []):
        match = pattern.match(asset["name"])
        if match:
            found.append(((int(match.group(1)), int(match.group(2))), asset["browser_download_url"]))
    if not found:
        raise RuntimeError(f"no {platform_name} GPL build in {BTBN_RELEASE}")
    return max(found)[1]


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
                if member.isfile() and (name in wanted or name in licences):
                    extracted = archive.extractfile(member)
                    if extracted:
                        target = out / ("LICENSE.txt" if name in licences and name != "readme.txt" else name)
                        target.write_bytes(extracted.read())
    for name in wanted:
        path = out / name
        if path.exists():
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def fetch_ffmpeg() -> Path:
    """Downloads ffmpeg and ffprobe; the first source that passes check_ffmpeg() is kept."""
    out = BUILD / "ffmpeg"
    problems = []
    for alternative in FFMPEG_SOURCES[_platform_key()]:
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        try:
            urls = [_btbn_url(u.split(":", 1)[1]) if u.startswith("btbn:") else u for u in alternative]
            for url in urls:
                _extract_binaries(_download(url), url, out)
            check_ffmpeg(out)
        except (Exception, SystemExit) as e:
            print(f"  not usable: {e}", flush=True)
            problems.append(f"{alternative[0]}: {e}")
            continue
        (out / "SOURCE.txt").write_text("Downloaded from:\n" + "\n".join(urls) + "\n", encoding="utf-8")
        return out
    raise SystemExit("No usable ffmpeg:\n  " + "\n  ".join(problems))


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
    check_demo_camera(exe)
    first = subprocess.run([str(exe), "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    print(f"Bundling {first}", flush=True)


def check_demo_camera(exe: Path) -> None:
    """Runs what the demo camera runs (dv2plex/fake_dvgrab.py): every test pattern to PAL DV.

    The release check of the packaged app depends on it; a build that cannot do it fails here,
    with ffmpeg's own message, instead of later as "capture: 0 clips".
    """
    sys.path.insert(0, str(ROOT))
    from dv2plex.fake_dvgrab import SOURCES

    with tempfile.TemporaryDirectory() as tmp:
        for index, pattern in enumerate(SOURCES):
            target = Path(tmp) / f"scene{index}.avi"
            result = subprocess.run([
                str(exe), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", pattern.format(size="720x576", rate="25"),
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-t", "0.4", "-target", "pal-dv", "-aspect", "4:3", str(target),
            ], capture_output=True, text=True)
            if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
                raise SystemExit(f"The ffmpeg in {exe.parent} cannot record the demo tape "
                                 f"({pattern.split('=')[0]}): {result.stderr.strip()[-400:]}")


# ------------------------------------------------------------------ licences

BUILD_ONLY = {"dv2plex", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "macholib", "pefile", "pip", "setuptools",
              "wheel", "packaging", "pywin32-ctypes"}


def write_package_licences() -> Path:
    """Name, version and licence of every Python package in the build environment."""
    from importlib import metadata

    rows = []
    for dist in metadata.distributions():
        name = dist.metadata.get("Name") or "?"
        if name.lower() in BUILD_ONLY:
            continue
        licence = (dist.metadata.get("License-Expression") or "").strip()
        if not licence:
            classifiers = [c.split("::")[-1].strip() for c in dist.metadata.get_all("Classifier") or []
                           if c.startswith("License ::")]
            licence = ", ".join(classifiers) or (dist.metadata.get("License") or "").strip().splitlines()[0:1]
            licence = licence if isinstance(licence, str) else (licence[0] if licence else "see the package")
        rows.append((name, dist.version, licence[:80]))
    out = BUILD / "licenses" / "THIRD_PARTY_LICENSES.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Python packages inside this build of DV2Plex, with their licences.",
        "DV2Plex itself: MIT. More (ffmpeg, Real-ESRGAN, models): THIRD_PARTY_NOTICES.md.",
        "",
    ] + [f"{n} {v}: {lic}" for n, v, lic in sorted(rows, key=lambda r: r[0].lower())]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


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
    env = dict(os.environ, DV2PLEX_ICON_DIR=str(icons), DV2PLEX_LICENSES_FILE=str(write_package_licences()))

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
