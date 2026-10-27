"""
Test setup.

- Config, and web_app on import, write settings files; they go to a temporary folder
  instead of dv2plex/config/.
- No test may run sudo, systemctl, chown or a real dvgrab: every subprocess goes through a
  guard that fails the test instead (a test once ran a real `sudo chown` on a Mac).
- The heavy cover and poster libraries are not needed; service.py imports them lazily.
"""

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import dv2plex.config as _config  # noqa: E402

_TEST_CONFIG_DIR = Path(tempfile.mkdtemp(prefix="dv2plex-test-config-"))
atexit.register(shutil.rmtree, _TEST_CONFIG_DIR, True)
_config.CONFIG_DIR = _TEST_CONFIG_DIR
os.environ.pop("DV2PLEX_HOME", None)

FORBIDDEN_PROGRAMS = {"sudo", "systemctl", "chown", "dvgrab", "shutdown", "reboot", "doas", "pkexec"}
_RealPopen = subprocess.Popen


def _program(args) -> str:
    if isinstance(args, (str, bytes)):
        text = args.decode() if isinstance(args, bytes) else args
        first = text.strip().split()[0] if text.strip() else ""
    else:
        args = list(args)
        first = str(args[0]) if args else ""
    return os.path.basename(first).lower().removesuffix(".exe")


class GuardedPopen(_RealPopen):
    """Popen that refuses commands with system-wide effects."""

    def __init__(self, args, *pargs, **kwargs):
        program = _program(args)
        if program in FORBIDDEN_PROGRAMS:
            raise AssertionError(f"test tried to run {program!r}: {args!r}")
        if not isinstance(args, (str, bytes)):
            listed = [str(a) for a in args]
            if program == "git" and "push" in listed:
                raise AssertionError(f"test tried to push: {args!r}")
        super().__init__(args, *pargs, **kwargs)


@pytest.fixture(autouse=True)
def no_system_commands(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)
    yield


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end run with ffmpeg and the simulated camera")
    if sys.platform == "win32":
        # Windows consoles default to a legacy code page; the tests print UTF-8
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
