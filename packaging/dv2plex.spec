# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build of the DV2Plex desktop app. Run it through packaging/build.py, which
prepares the icons and (optionally) ffmpeg and passes them in:

    DV2PLEX_ICON_DIR    folder with icon.png, icon.ico, icon.icns
    DV2PLEX_FFMPEG_DIR  folder with ffmpeg and ffprobe to bundle (optional)

The app contains the web interface, capture, merge, ffmpeg upscaling, the light poster and
the Plex export. Real-ESRGAN (PyTorch) and Stable Diffusion are left out; they are several
gigabytes and need a matching GPU stack, so they stay with the Python installation.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
ICONS = Path(os.environ.get("DV2PLEX_ICON_DIR", ROOT / "build" / "icons"))
FFMPEG_DIR = os.environ.get("DV2PLEX_FFMPEG_DIR", "")

sys.path.insert(0, str(ROOT))
from dv2plex import __version__  # noqa: E402


def keep(name: str) -> bool:
    return ".test_" not in name and not name.endswith("conftest") and ".bin." not in name


datas = [
    (str(ROOT / "dv2plex" / "web"), "dv2plex/web"),
    (str(ROOT / "dv2plex" / "resources"), "dv2plex/resources"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
if os.environ.get("DV2PLEX_LICENSES_FILE"):
    datas.append((os.environ["DV2PLEX_LICENSES_FILE"], "."))
binaries = []
if FFMPEG_DIR:
    for name in sorted(os.listdir(FFMPEG_DIR)):
        path = Path(FFMPEG_DIR) / name
        if not path.is_file():
            continue
        if name.split(".")[0] in ("ffmpeg", "ffprobe"):
            binaries.append((str(path), "dv2plex/bin/ffmpeg/bin"))
        else:  # licence, source note
            datas.append((str(path), "dv2plex/bin/ffmpeg"))

hiddenimports = (
    collect_submodules("dv2plex", filter=keep)
    + collect_submodules("uvicorn")
    + ["websockets", "wsproto", "h11", "anyio", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont", "PIL.ImageStat"]
)
if sys.platform == "win32":
    hiddenimports += ["webview.platforms.edgechromium", "webview.platforms.winforms", "clr"]
elif sys.platform == "darwin":
    hiddenimports += ["webview.platforms.cocoa"]
else:
    hiddenimports += ["webview.platforms.gtk", "webview.platforms.qt"]

excludes = [
    # Heavy optional parts of the Python installation
    "torch", "torchvision", "basicsr", "facexlib", "gfpgan", "cv2", "rembg", "onnxruntime",
    "diffusers", "transformers", "accelerate", "safetensors", "playwright", "sklearn", "numpy",
    # Not used
    "tkinter", "matplotlib", "IPython", "pytest", "_pytest", "mypy", "ruff",
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

icon = None
if sys.platform == "win32" and (ICONS / "icon.ico").is_file():
    icon = str(ICONS / "icon.ico")
elif sys.platform == "darwin" and (ICONS / "icon.icns").is_file():
    icon = str(ICONS / "icon.icns")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DV2Plex",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # a window app; logs go to the log file
    icon=icon,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DV2Plex")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="DV2Plex.app",
        icon=icon,
        bundle_identifier="io.github.futureman0.dv2plex",
        version=__version__,
        info_plist={
            "CFBundleName": "DV2Plex",
            "CFBundleDisplayName": "DV2Plex",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "MIT License, DV2Plex contributors",
        },
    )
